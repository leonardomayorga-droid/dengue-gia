"""Tablas analíticas (zona oro): canal endémico, rezago clima-casos, señal climática actual
e Índice de Priorización departamental."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
from gia.utils import log


def spearman(x, y) -> float:
    """Correlación de Spearman = Pearson sobre rangos (empates con rango promedio).
    Equivale a method="spearman" de pandas, pero sin depender de scipy."""
    return float(pd.Series(x).rank().corr(pd.Series(y).rank()))


def _casos_semana(fact: pd.DataFrame, nivel: str) -> pd.DataFrame:
    g = fact.groupby([nivel, "id_semana"], as_index=False)["casos"].sum()
    g["anio"] = g.id_semana // 100
    g["semana"] = g.id_semana % 100
    return g


# ---------------------------------------------------------------------------
# Canal endémico (método de cuartiles sobre años de referencia)
# ---------------------------------------------------------------------------
def canal_endemico(fact: pd.DataFrame, dim_t: pd.DataFrame) -> pd.DataFrame:
    presentes = sorted(set(fact.id_semana // 100))
    ref = [a for a in presentes if a != C.ANIO_ANALISIS and a not in C.ANIOS_EXCLUIDOS_CANAL]
    if len(ref) < 2:
        log.warning("Canal endémico OMITIDO: se necesitan al menos 2 años de referencia y hay %s (%s). "
                    "Descargue SIVIGILA de años anteriores (ideal 2019 y 2022-2024).", len(ref), ref)
        return pd.DataFrame(columns=["id_semana", "cod_dpto", "canal_q1", "canal_mediana", "canal_q3", "ambito"])
    log.info("Canal endémico: años de referencia %s", ref)
    f = fact.copy()
    f["nacional"] = "00"
    salidas = []
    for nivel, ambito in [("cod_dpto", "Departamental"), ("nacional", "Nacional")]:
        g = _casos_semana(f, nivel)
        g = g[g.anio.isin(ref)]
        # completar semanas sin casos con 0 (sin esto la mediana se sobreestima)
        claves = pd.MultiIndex.from_product([g[nivel].unique(), ref, range(1, 53)],
                                            names=[nivel, "anio", "semana"])
        g = g.set_index([nivel, "anio", "semana"])["casos"].reindex(claves, fill_value=0).reset_index()
        q = (g.groupby([nivel, "semana"])["casos"]
               .quantile([0.25, 0.5, 0.75]).unstack().reset_index()
               .rename(columns={0.25: "canal_q1", 0.5: "canal_mediana", 0.75: "canal_q3"}))
        q["ambito"] = ambito
        q = q.rename(columns={nivel: "cod_dpto"})
        if ambito == "Nacional":
            q["cod_dpto"] = None
        salidas.append(q)
    canal = pd.concat(salidas, ignore_index=True)
    # se replica para cada año del calendario, de modo que se relacione con dim_tiempo
    t = dim_t[["id_semana", "semana"]].copy()
    t.loc[t.semana == 53, "semana"] = 52
    canal = t.merge(canal, on="semana").drop(columns="semana")
    return canal.round(1)


# ---------------------------------------------------------------------------
# Rezago: ¿cuántas semanas después de la lluvia/calor suben los casos?
# ---------------------------------------------------------------------------
def _serie_mpio(mpio, cl, orden, casos, anios):
    s = (orden.merge(cl, on="id_semana", how="inner")
              .merge(casos[casos.cod_mpio == mpio], on=["id_semana", "cod_mpio"], how="left")
              .sort_values("t"))
    s["casos"] = s["casos"].fillna(0)
    s["anio"] = s.id_semana // 100
    return s[s.anio.isin(anios)].copy()


def rezago_clima(fact: pd.DataFrame, clima_w: pd.DataFrame, dim_t: pd.DataFrame, max_rezago=12):
    """Asociación clima -> casos con rezago de 0 a 12 semanas, por municipio.

    Se usan ANOMALÍAS DENTRO DE CADA AÑO (valor semanal menos el promedio de ese municipio en
    ese año), tanto del clima como de log(casos + 1). Sin este paso, la correlación queda dominada
    por la diferencia entre años (p. ej. 2024, año cálido y epidémico) y sale igual en todos los
    rezagos: no dice nada sobre el momento. La relación entre años se mide aparte (clima_anual).
    """
    orden = dim_t[["id_semana"]].sort_values("id_semana").reset_index(drop=True)
    orden["t"] = orden.index
    casos = _casos_semana(fact, "cod_mpio")[["cod_mpio", "id_semana", "casos"]]
    ultima = fact[fact.casos > 0].id_semana.max()
    orden = orden[orden.id_semana <= ultima]
    anios = sorted(set(fact.id_semana // 100) & set(C.ANIOS_CLIMA))
    filas, mejores = [], []
    for mpio, cl in clima_w.groupby("cod_mpio"):
        s = _serie_mpio(mpio, cl, orden, casos, anios)
        if len(s) < 52 or s.casos.sum() < 50:
            continue
        s["y"] = np.log1p(s.casos)
        s["y_anom"] = s.y - s.groupby("anio").y.transform("mean")
        for var in ["precip_mm", "temp_media_c", "humedad_pct"]:
            if var not in s:
                continue
            x = s[var] - s.groupby("anio")[var].transform("mean")
            best = (None, -2)
            for k in range(0, max_rezago + 1):
                xa = x.shift(k)
                ok = xa.notna() & s.y_anom.notna()
                if ok.sum() < 40 or xa[ok].std() == 0:
                    continue
                r = spearman(xa[ok], s.y_anom[ok])
                filas.append({"cod_mpio": mpio, "variable": var, "rezago_semanas": k, "correlacion": r})
                if r > best[1]:
                    best = (k, r)
            mejores.append({"cod_mpio": mpio, "variable": var, "mejor_rezago": best[0], "corr_max": best[1]})
    det = pd.DataFrame(filas)
    if det.empty:
        log.warning("Rezago: sin municipios con datos suficientes")
        return det, pd.DataFrame(mejores)
    resumen = (det.groupby(["variable", "rezago_semanas"])["correlacion"]
                  .agg(corr_mediana="median", corr_p25=lambda v: v.quantile(.25),
                       corr_p75=lambda v: v.quantile(.75), pct_municipios_positivos=lambda v: 100 * (v > 0).mean(),
                       n_municipios="size")
                  .reset_index().round(3))
    for var, g in resumen.groupby("variable"):
        b = g.loc[g.corr_mediana.idxmax()]
        log.info("Rezago %s: máximo a %s semanas (rho mediana %.2f; positivo en %.0f %% de municipios)",
                 var, int(b.rezago_semanas), b.corr_mediana, b.pct_municipios_positivos)
    return resumen, pd.DataFrame(mejores).round(3)


def clima_anual(fact: pd.DataFrame, clima_w: pd.DataFrame) -> pd.DataFrame:
    """Relación ENTRE AÑOS: anomalía de temperatura y lluvia de cada año frente a casos,
    en los municipios con clima. Responde '¿los años más cálidos tienen más dengue?'."""
    c = clima_w.copy()
    c["anio"] = c.id_semana // 100
    anios = sorted(set(fact.id_semana // 100) & set(C.ANIOS_CLIMA))
    c = c[c.anio.isin(anios)]
    a = c.groupby(["cod_mpio", "anio"]).agg(temp_media_c=("temp_media_c", "mean"),
                                            precip_mm=("precip_mm", "sum")).reset_index()
    f = fact[fact.cod_mpio.isin(a.cod_mpio.unique())].copy()
    f["anio"] = f.id_semana // 100
    a = a.merge(f.groupby(["cod_mpio", "anio"]).casos.sum().reset_index(), on=["cod_mpio", "anio"], how="left")
    a["casos"] = a.casos.fillna(0)
    a["anom_temp_c"] = a.temp_media_c - a.groupby("cod_mpio").temp_media_c.transform("mean")
    a["anom_precip_pct"] = 100 * (a.precip_mm / a.groupby("cod_mpio").precip_mm.transform("mean") - 1)
    a["anom_log_casos"] = np.log1p(a.casos) - a.groupby("cod_mpio").casos.transform(lambda v: np.log1p(v).mean())
    r = spearman(a.anom_temp_c, a.anom_log_casos)
    pos = a.groupby("cod_mpio").apply(lambda g: g.anom_temp_c.corr(g.anom_log_casos) > 0, include_groups=False).mean()
    log.info("Clima entre años: rho(anomalía de temperatura, casos) = %.2f; positiva en %.0f %% de municipios",
             r, 100 * pos)
    nal = (a.groupby("anio").agg(anom_temp_c=("anom_temp_c", "mean"), anom_precip_pct=("anom_precip_pct", "mean"),
                                 casos=("casos", "sum"), municipios=("cod_mpio", "nunique"))
             .reset_index().round(2))
    nal["rho_temp_casos"] = round(r, 3)
    nal["pct_municipios_positivos"] = round(100 * pos, 1)
    return nal


# ---------------------------------------------------------------------------
# Señal climática actual (tiempo real): anomalías recientes y pronosticadas
# ---------------------------------------------------------------------------
def senal_climatica(clima_w: pd.DataFrame, pron: pd.DataFrame, semanas_recientes=8) -> pd.DataFrame:
    c = clima_w.copy()
    c["anio"], c["semana"] = c.id_semana // 100, c.id_semana % 100
    ult = c.id_semana.max()
    anio_ult = ult // 100
    hist = c[c.anio < anio_ult].groupby(["cod_mpio", "semana"]).agg(
        precip_hist=("precip_mm", "mean"), temp_hist=("temp_media_c", "mean")).reset_index()

    recientes = sorted(c.id_semana.unique())[-semanas_recientes:]
    r = c[c.id_semana.isin(recientes)].merge(hist, on=["cod_mpio", "semana"], how="left")
    r = r.groupby("cod_mpio").agg(precip_reciente=("precip_mm", "sum"), precip_normal=("precip_hist", "sum"),
                                  temp_reciente=("temp_media_c", "mean"), temp_normal=("temp_hist", "mean"))

    p = pron.copy()
    p["semana"] = p["semana"].clip(upper=52)
    pw = p.groupby(["cod_mpio", "semana"]).agg(precip=("precip_mm", "sum"), temp=("temp_media_c", "mean"),
                                                dias=("precip_mm", "size")).reset_index()
    pw = pw.merge(hist, on=["cod_mpio", "semana"], how="left")
    pw["precip_hist_prop"] = pw.precip_hist * pw.dias / 7
    q = pw.groupby("cod_mpio").agg(precip_pron=("precip", "sum"), precip_pron_normal=("precip_hist_prop", "sum"),
                                   temp_pron=("temp", "mean"), temp_pron_normal=("temp_hist", "mean"))
    s = r.join(q, how="outer").reset_index()
    s["anom_precip_reciente_pct"] = 100 * (s.precip_reciente / s.precip_normal - 1)
    s["anom_precip_pron_pct"] = 100 * (s.precip_pron / s.precip_pron_normal - 1)
    s["anom_temp_pron_c"] = s.temp_pron - s.temp_pron_normal

    def z(v):
        return (v - v.mean()) / v.std(ddof=0) if v.std(ddof=0) else v * 0

    s["anom_temp_reciente_c"] = s.temp_reciente - s.temp_normal
    # Pesos según los hallazgos: la temperatura explica las diferencias entre años y la lluvia
    # anticipa la onda de casos con 3 a 6 semanas de rezago (por eso pesa la lluvia reciente).
    s["senal_clima"] = (0.35 * z(s.anom_temp_reciente_c.fillna(0))
                        + 0.35 * z(s.anom_precip_reciente_pct.fillna(0))
                        + 0.15 * z(s.anom_temp_pron_c.fillna(0))
                        + 0.15 * z(s.anom_precip_pron_pct.fillna(0)))
    s["fecha_corte"] = pron["fecha_extraccion"].iloc[0] if len(pron) else None
    return s.replace([np.inf, -np.inf], np.nan).round(2)


# ---------------------------------------------------------------------------
# Índice de Priorización departamental (IP, 0-100)
# ---------------------------------------------------------------------------
def indice_priorizacion(fact: pd.DataFrame, pob: pd.DataFrame, dim_d: pd.DataFrame,
                        senal: pd.DataFrame, dim_m: pd.DataFrame) -> pd.DataFrame:
    a = C.ANIO_ANALISIS
    f = fact[fact.id_semana // 100 == a]
    d = f.groupby("cod_dpto").agg(casos=("casos", "sum"), fallecidos=("fallecidos", "sum"),
                                  hospitalizados=("hospitalizados", "sum")).reset_index()
    graves = f[f.cod_eve == 220].groupby("cod_dpto")["casos"].sum().rename("casos_graves")
    d = d.merge(graves, on="cod_dpto", how="left").fillna({"casos_graves": 0})
    d = d.merge(pob[pob.anio == a][["cod_dpto", "poblacion"]], on="cod_dpto", how="left")
    d["incidencia_100k"] = d.casos / d.poblacion * 1e5
    d["pct_grave"] = 100 * d.casos_graves / d.casos
    d["letalidad_pct"] = 100 * d.fallecidos / d.casos
    # Letalidad suavizada (Bayes empírico): con pocos casos, 2 o 3 muertes disparan la tasa.
    # Se acerca cada departamento a la letalidad nacional en proporción a su tamaño:
    # (muertes + K * tasa_nacional) / (casos + K), con K = 1.000 casos.
    k_suav = 1000
    tasa_nal = d.fallecidos.sum() / d.casos.sum()
    d["letalidad_suav_pct"] = 100 * (d.fallecidos + k_suav * tasa_nal) / (d.casos + k_suav)

    sem = sorted(f.id_semana.unique())
    ult4, prev4 = sem[-4:], sem[-8:-4]
    u = f[f.id_semana.isin(ult4)].groupby("cod_dpto")["casos"].sum()
    p = f[f.id_semana.isin(prev4)].groupby("cod_dpto")["casos"].sum()
    # Tendencia suavizada: se suman 20 casos a ambos periodos para que departamentos pequeños
    # (p. ej. de 6 a 13 casos = +117 %) no dominen el componente.
    u, p = d.cod_dpto.map(u).fillna(0), d.cod_dpto.map(p).fillna(0)
    d["casos_ult4"], d["casos_prev4"] = u, p
    d["tendencia_4s_pct"] = 100 * ((u + 20) / (p + 20) - 1)

    if senal is not None and len(senal):
        sm = senal.merge(dim_m[["cod_mpio", "cod_dpto"]], on="cod_mpio")
        peso = f.groupby("cod_mpio")["casos"].sum()
        sm["w"] = sm.cod_mpio.map(peso).fillna(1)
        sd = sm.groupby("cod_dpto").apply(lambda g: np.average(g.senal_clima.fillna(0), weights=g.w),
                                          include_groups=False)
        d["senal_clima"] = d.cod_dpto.map(sd)
    else:
        d["senal_clima"] = np.nan

    def minmax(v):
        v = v.astype(float)
        lo, hi = v.quantile(.05), v.quantile(.95)
        v = v.clip(lo, hi)
        return ((v - lo) / (hi - lo)).fillna(0) if hi > lo else v * 0

    comp = {"incidencia": "incidencia_100k", "carga": "casos", "pct_grave": "pct_grave", "letalidad": "letalidad_suav_pct",
            "tendencia_4s": "tendencia_4s_pct", "senal_clima": "senal_clima"}
    d["ip"] = 0.0
    for k, col in comp.items():
        d[f"n_{k}"] = minmax(d[col].fillna(d[col].median() if d[col].notna().any() else 0))
        d["ip"] += C.PESOS_IP[k] * d[f"n_{k}"]
    d["ip"] = (100 * d.ip).round(1)
    d = d[d.casos >= 30]                       # evita que departamentos con muy pocos casos distorsionen
    d["ranking"] = d.ip.rank(ascending=False, method="min").astype(int)
    d["prioridad"] = pd.qcut(d.ip.rank(method="first"), 3, labels=["Baja", "Media", "Alta"]).astype(str)
    d["anio"] = a
    d = d.merge(dim_d[["cod_dpto", "departamento", "region"]], on="cod_dpto", how="left")
    return d.sort_values("ranking").round(2)
