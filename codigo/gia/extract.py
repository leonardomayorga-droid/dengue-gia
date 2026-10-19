"""Extracción (zona bronce) de las cinco fuentes del proyecto.

Fuente 1  SIVIGILA (INS)            Hoja de cálculo  Excel de microdatos, eventos 210 y 220
Fuente 2  DIVIPOLA (datos.gov.co)   API pública      JSON Socrata con coordenadas de municipios
Fuente 3  Open-Meteo histórico      API pública      JSON clima diario 2022-hoy (semiestructurado)
Fuente 4  Open-Meteo pronóstico     Tiempo real      JSON pronóstico 16 días (se consulta en cada corrida)
Fuente 5  DANE proyecciones         Hoja de cálculo  PPED-AreaDep-2018-2050_VP.xlsx
Fuente 6  Boletín Epidemiológico    No estructurado  PDF (ver text_mining.py) — opcional
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pandas as pd

import config as C
from gia.utils import get_json, limpiar_valores_excel, log, normalizar_columnas

COLS_SIVIGILA = [
    "cod_eve", "fec_not", "semana", "ano", "edad", "uni_med", "sexo",
    "cod_pais_o", "cod_dpto_o", "cod_mun_o", "area", "tip_ss", "per_etn",
    "tip_cas", "ajuste", "pac_hos", "con_fin", "ini_sin",
]


# ---------------------------------------------------------------------------
# Fuente 1 — SIVIGILA
# ---------------------------------------------------------------------------
def extraer_sivigila() -> pd.DataFrame:
    archivos = sorted(
        p for p in C.RAW_SIVIGILA.iterdir()
        if p.suffix.lower() in {".xlsx", ".xls", ".csv"} and not p.name.startswith("~$")
    )
    if not archivos:
        raise FileNotFoundError(
            f"No hay archivos en {C.RAW_SIVIGILA}. Descárguelos del Buscador de microdatos INS "
            "(https://portalsivigila.ins.gov.co/Paginas/Buscador.aspx): eventos Dengue y Dengue grave."
        )
    partes = []
    cache_dir = C.CLEAN / "_cache_sivigila"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for p in archivos:
        # Leer un Excel de ~80 MB tarda 2-4 min: se guarda una copia Parquet por archivo y fecha
        cache = cache_dir / f"{p.stem}_{int(p.stat().st_mtime)}.parquet"
        if cache.exists():
            df = pd.read_parquet(cache)
        else:
            log.info("  Leyendo %s (puede tardar unos minutos la primera vez)...", p.name)
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p, sep=None, engine="python", encoding="latin-1", dtype=str)
            else:
                df = pd.read_excel(p, dtype=str)
            df = limpiar_valores_excel(normalizar_columnas(df))
            df = df[[c for c in COLS_SIVIGILA if c in df.columns]]
            df.astype("string").to_parquet(cache, index=False)
        faltan = {"cod_eve", "semana", "ano", "cod_dpto_o", "cod_mun_o"} - set(df.columns)
        if faltan:
            log.warning("  %s: faltan columnas clave %s — archivo omitido", p.name, faltan)
            continue
        df = df[[c for c in COLS_SIVIGILA if c in df.columns]]
        df["archivo_origen"] = p.name
        log.info("  SIVIGILA %-45s %8s filas", p.name, f"{len(df):,}")
        partes.append(df)
    df = pd.concat(partes, ignore_index=True)
    log.info("SIVIGILA total: %s registros individuales", f"{len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Fuente 2 — DIVIPOLA (API Socrata)
# ---------------------------------------------------------------------------
def extraer_divipola(offline: bool = False) -> pd.DataFrame:
    data = get_json(C.DIVIPOLA_API, {"$limit": 5000}, C.RAW_API / "divipola.json", offline)
    df = normalizar_columnas(pd.DataFrame(data))
    log.info("DIVIPOLA: %s municipios, columnas %s", len(df), list(df.columns))
    return df


# ---------------------------------------------------------------------------
# Fuente 5 — DANE proyecciones de población departamental
# ---------------------------------------------------------------------------
def extraer_poblacion() -> pd.DataFrame:
    archivos = [p for p in C.RAW_DANE.iterdir()
                if p.suffix.lower() in {".xlsx", ".xls"} and not p.name.startswith("~$")]
    if not archivos:
        raise FileNotFoundError(
            f"No hay Excel en {C.RAW_DANE}. Descargue PPED-AreaDep-2018-2050_VP.xlsx de "
            "https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/"
        )
    # El libro DANE trae hojas de índice y notas; los datos están en la hoja cuya fila de
    # encabezados contiene DP / DPNOM (en 2025: 'PobDepartamentalxÁrea'), tras varias filas de título.
    crudo, fila, hoja = None, None, None
    for nombre, h in pd.read_excel(archivos[0], header=None, dtype=str, sheet_name=None).items():
        for i in range(min(40, len(h))):
            vals = {str(v).strip().upper() for v in h.iloc[i].tolist()}
            if "DP" in vals and "DPNOM" in vals:
                crudo, fila, hoja = h, i, nombre
                break
        if crudo is not None:
            break
    if crudo is None:
        raise ValueError("No se encontró en ninguna hoja la fila de encabezados DP/DPNOM del Excel DANE")
    log.info("DANE: hoja '%s', encabezados en la fila %s", hoja, fila + 1)
    df = crudo.iloc[fila + 1:].copy()
    df.columns = crudo.iloc[fila].tolist()
    df = normalizar_columnas(df).dropna(how="all")
    log.info("DANE: %s filas, columnas %s", len(df), list(df.columns)[:8])
    return df


# ---------------------------------------------------------------------------
# Fuentes 3 y 4 — Open-Meteo (histórico y pronóstico)
# ---------------------------------------------------------------------------
def _como_lista(data):
    return data if isinstance(data, list) else [data]


def _diario_a_df(bloque: dict, cod_mpio: str) -> pd.DataFrame:
    d = pd.DataFrame(bloque["daily"])
    d.insert(0, "cod_mpio", cod_mpio)
    return d


def extraer_clima_historico(ubicaciones: pd.DataFrame, offline: bool = False) -> pd.DataFrame:
    """ubicaciones: columnas cod_mpio, latitud, longitud. Caché por municipio-año."""
    hoy = date.today()
    fin_archivo = hoy - timedelta(days=7)          # el archivo histórico tiene ~5 días de rezago
    marcos = []
    for anio in C.ANIOS_CLIMA:
        ini = date(anio, 1, 1)
        fin = min(date(anio, 12, 31), fin_archivo)
        if ini > fin:
            continue
        pendientes = []
        for u in ubicaciones.itertuples():
            cache = C.RAW_API / "clima_hist" / f"{u.cod_mpio}_{anio}.json"
            if cache.exists():
                marcos.append(_diario_a_df(json.loads(cache.read_text(encoding="utf-8")), u.cod_mpio))
            else:
                pendientes.append(u)
        if pendientes and offline:
            raise FileNotFoundError(f"Modo offline: faltan {len(pendientes)} cachés de clima {anio}")
        for i in range(0, len(pendientes), C.LOTE_UBICACIONES):
            lote = pendientes[i:i + C.LOTE_UBICACIONES]
            params = {
                "latitude": ",".join(f"{u.latitud:.4f}" for u in lote),
                "longitude": ",".join(f"{u.longitud:.4f}" for u in lote),
                "start_date": ini.isoformat(), "end_date": fin.isoformat(),
                "daily": ",".join(C.VARIABLES_CLIMA), "timezone": "America/Bogota",
            }
            tmp = C.RAW_API / "clima_hist" / f"_lote_{anio}_{i}.json"
            data = _como_lista(get_json(C.OPEN_METEO_ARCHIVE, params, tmp))
            tmp.unlink(missing_ok=True)
            for u, bloque in zip(lote, data):
                (C.RAW_API / "clima_hist" / f"{u.cod_mpio}_{anio}.json").write_text(
                    json.dumps(bloque), encoding="utf-8")
                marcos.append(_diario_a_df(bloque, u.cod_mpio))
            peso = len(lote) * max(1, ((fin - ini).days + 1) / 14)          # llamadas que cuenta la API
            pausa = max(C.PAUSA_SEGUNDOS, 60 * peso / C.LLAMADAS_POR_MINUTO)
            log.info("  Open-Meteo histórico %s: lote %s/%s (~%.0f llamadas; pausa %.0f s)", anio,
                     i // C.LOTE_UBICACIONES + 1, -(-len(pendientes) // C.LOTE_UBICACIONES), peso, pausa)
            time.sleep(pausa)
        n_cache = len(ubicaciones) - len(pendientes)
        if n_cache:
            log.info("  Open-Meteo histórico %s: %s municipios tomados de la caché", anio, n_cache)
    df = pd.concat(marcos, ignore_index=True)
    log.info("Clima histórico: %s registros diarios", f"{len(df):,}")
    return df


def extraer_pronostico(ubicaciones: pd.DataFrame, offline: bool = False) -> pd.DataFrame:
    """Instantánea en tiempo real: pronóstico de 16 días. Se guarda una caché por fecha de corrida."""
    carpeta = C.RAW_API / "pronostico"
    carpeta.mkdir(parents=True, exist_ok=True)
    if offline:
        archivos = sorted(carpeta.glob("pronostico_*.json"))
        if not archivos:
            raise FileNotFoundError("Modo offline sin pronóstico cacheado")
        cache = archivos[-1]
    else:
        cache = carpeta / f"pronostico_{date.today().isoformat()}.json"
    fecha_corte = cache.stem.replace("pronostico_", "")

    if cache.exists():
        bloques = json.loads(cache.read_text(encoding="utf-8"))
    else:
        bloques = {}
        ubic = list(ubicaciones.itertuples())
        for i in range(0, len(ubic), C.LOTE_UBICACIONES):
            lote = ubic[i:i + C.LOTE_UBICACIONES]
            params = {
                "latitude": ",".join(f"{u.latitud:.4f}" for u in lote),
                "longitude": ",".join(f"{u.longitud:.4f}" for u in lote),
                "daily": ",".join(C.VARIABLES_CLIMA), "timezone": "America/Bogota",
                "forecast_days": 16,
            }
            tmp = carpeta / f"_lote_{i}.json"
            data = _como_lista(get_json(C.OPEN_METEO_FORECAST, params, tmp))
            tmp.unlink(missing_ok=True)
            for u, bloque in zip(lote, data):
                bloques[u.cod_mpio] = bloque
            time.sleep(C.PAUSA_SEGUNDOS)
        cache.write_text(json.dumps(bloques), encoding="utf-8")
    df = pd.concat([_diario_a_df(b, cod) for cod, b in bloques.items()], ignore_index=True)
    df["fecha_extraccion"] = fecha_corte
    log.info("Pronóstico (tiempo real, corte %s): %s registros", fecha_corte, len(df))
    return df
