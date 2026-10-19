"""Orquestador del pipeline ETL + analítica.

Uso:
    python run_pipeline.py              # descarga APIs (o usa caché) y reconstruye todo
    python run_pipeline.py --offline    # solo cachés locales (sin internet)
    python run_pipeline.py --sin-eda    # omite las figuras del análisis exploratorio
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# La consola de Windows usa cp1252: se fuerza UTF-8 para que tildes y símbolos no rompan el log
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import pandas as pd

import config as C
from gia import analytics as A
from gia import extract as E
from gia import transform as T
from gia.text_mining import procesar_boletines
from gia.utils import log


def main(offline: bool = False, eda: bool = True):
    t0 = time.time()
    for p in (C.CLEAN, C.MODEL, C.OUTPUTS):
        p.mkdir(parents=True, exist_ok=True)

    log.info("== 1. EXTRACCIÓN ==")
    siv_raw = E.extraer_sivigila()
    div_raw = E.extraer_divipola(offline)
    pob_raw = E.extraer_poblacion()

    log.info("== 2. LIMPIEZA Y TRANSFORMACIÓN ==")
    siv = T.limpiar_sivigila(siv_raw)
    anios = sorted(int(a) for a in siv.ano.unique())
    C.ANIO_ANALISIS = int(siv.loc[siv.cod_eve.isin(C.EVENTOS_CASOS), "ano"].max())
    log.info("Años con datos SIVIGILA: %s · año de análisis: %s", anios, C.ANIO_ANALISIS)
    for eve in C.EVENTOS:
        faltan = sorted(set(anios) - {int(a) for a in siv.loc[siv.cod_eve == eve, "ano"]})
        if faltan:
            log.warning("Evento %s (%s) sin archivo para los años %s", eve, C.EVENTOS[eve], faltan)
    siv.drop(columns=["archivo_origen"]).astype(str).to_parquet(C.CLEAN / "sivigila_limpio.parquet", index=False)
    fact = T.agregar_sivigila(siv)
    dim_m, dim_d = T.dimensiones_geograficas(div_raw)
    pob = T.limpiar_poblacion(pob_raw)
    dim_t = T.dim_tiempo()
    dim_e = pd.DataFrame([{"cod_eve": k, "evento": v} for k, v in C.EVENTOS.items()])

    # Municipios con más casos recientes -> ubicaciones para clima
    recientes = fact[fact.id_semana // 100 >= C.ANIO_ANALISIS - 2]
    top = recientes.groupby("cod_mpio")["casos"].sum().nlargest(C.TOP_MUNICIPIOS_CLIMA).index
    ubic = dim_m[dim_m.cod_mpio.isin(top)].dropna(subset=["latitud", "longitud"])[["cod_mpio", "latitud", "longitud"]]
    cobertura = recientes[recientes.cod_mpio.isin(ubic.cod_mpio)].casos.sum() / recientes.casos.sum()
    log.info("Clima para %s municipios (%.1f %% de los casos de los últimos 3 años)", len(ubic), 100 * cobertura)

    clima_w = T.clima_semanal(E.extraer_clima_historico(ubic, offline))
    pron = T.pronostico_diario(E.extraer_pronostico(ubic, offline))
    pron = pron[pron.cod_mpio.isin(ubic.cod_mpio)]
    boletin = procesar_boletines(dim_d)

    log.info("== 3. ANALÍTICA ==")
    canal = A.canal_endemico(fact, dim_t)
    rezago, rezago_mpio = A.rezago_clima(fact, clima_w, dim_t)
    clima_anio = A.clima_anual(fact, clima_w)
    senal = A.senal_climatica(clima_w, pron)
    prior = A.indice_priorizacion(fact, pob, dim_d, senal, dim_m)

    dim_m = T.completar_dim_municipio(dim_m, dim_d, fact)
    dim_m["con_clima"] = dim_m.cod_mpio.isin(ubic.cod_mpio).astype(int)

    # Validación de reconciliación: lo agregado debe sumar lo limpio
    assert fact.casos.sum() == int(siv.es_caso.sum()), "La agregación no reconcilia con los microdatos limpios"
    assert fact.fallecidos.sum() == int(siv.fallecido.sum()), "Las muertes agregadas no reconcilian"
    assert set(fact.cod_dpto) <= set(dim_d.cod_dpto), "Hay departamentos sin dimensión"

    log.info("== 4. CARGA (modelo estrella) ==")
    from gia.model import guardar_modelo
    calidad = pd.DataFrame(T.CALIDAD)
    guardar_modelo({
        "dim_tiempo": dim_t, "dim_departamento": dim_d, "dim_municipio": dim_m, "dim_evento": dim_e,
        "fact_dengue": fact, "fact_poblacion": pob, "fact_clima_semana": clima_w,
        "fact_pronostico": pron, "fact_canal_endemico": canal, "fact_senal_clima": senal,
        "dep_priorizacion": prior, "rezago_clima": rezago, "rezago_municipio": rezago_mpio, "clima_anual": clima_anio,
        "fact_boletin_menciones": boletin, "calidad_datos": calidad,
    })
    calidad.to_csv(C.OUTPUTS / "bitacora_calidad.csv", index=False, encoding="utf-8")

    if eda:
        log.info("== 5. ANÁLISIS EXPLORATORIO ==")
        from gia.eda import ejecutar_eda
        hallazgos = ejecutar_eda()
        (C.OUTPUTS / "hallazgos.json").write_text(json.dumps(hallazgos, ensure_ascii=False, indent=2, default=str),
                                                  encoding="utf-8")
    log.info("Pipeline completo en %.0f s", time.time() - t0)


if __name__ == "__main__":
    from gia.utils import LimiteAPI

    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--sin-eda", action="store_true")
    a = ap.parse_args()
    try:
        main(offline=a.offline, eda=not a.sin_eda)
    except LimiteAPI as exc:
        log.error(str(exc))
        sys.exit(2)
