"""Limpieza y transformación (zona plata) con bitácora de calidad de datos."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
from gia.utils import inicio_semana_epi, log, semana_epi

CALIDAD: list[dict] = []   # bitácora: fuente, regla, registros afectados


def _registrar(fuente: str, regla: str, antes: int, despues: int):
    CALIDAD.append({"fuente": fuente, "regla": regla, "registros_antes": antes,
                    "registros_despues": despues, "eliminados": antes - despues})
    if antes != despues:
        log.info("  [%s] %s: -%s", fuente, regla, f"{antes - despues:,}")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip().str.replace(",", ".", regex=False), errors="coerce")


def _buscar_col(df: pd.DataFrame, *opciones: str, requerido=True) -> str | None:
    for o in opciones:
        if o in df.columns:
            return o
    for o in opciones:  # coincidencia parcial (sin confundir 'dpto' con 'cod_dpto')
        for c in df.columns:
            if o in c and not (c.startswith("cod") and not o.startswith("cod")):
                return c
    if requerido:
        raise KeyError(f"No se encontró ninguna columna {opciones} en {list(df.columns)}")
    return None


def titulo(texto) -> str:
    """'ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA' -> 'Archipiélago de San Andrés, ...'."""
    menores = {"De", "Del", "La", "Las", "Los", "Y", "El"}
    pal = str(texto).strip().title().split()
    return " ".join(p.lower() if i and p in menores else p for i, p in enumerate(pal))


# ---------------------------------------------------------------------------
# SIVIGILA
# ---------------------------------------------------------------------------
GRUPOS_EDAD = [(0, 5, "0-4"), (5, 15, "5-14"), (15, 30, "15-29"), (30, 45, "30-44"),
               (45, 60, "45-59"), (60, 200, "60+")]
AREA = {1: "Cabecera municipal", 2: "Centro poblado", 3: "Rural disperso"}


def limpiar_sivigila(df: pd.DataFrame) -> pd.DataFrame:
    F = "SIVIGILA"
    df = df.copy()
    n0 = len(df)
    _registrar(F, "Registros cargados", n0, n0)

    # R1. Duplicidad de cargue: si un mismo (evento, año) viene en dos archivos se conserva el último
    df["ano"] = _num(df["ano"]).astype("Int64")
    df["cod_eve"] = _num(df["cod_eve"]).astype("Int64")
    pares = df.groupby(["cod_eve", "ano"])["archivo_origen"].nunique()
    for (eve, ano), n in pares[pares > 1].items():
        ultimo = sorted(df.loc[(df.cod_eve == eve) & (df.ano == ano), "archivo_origen"].unique())[-1]
        a = len(df)
        df = df[~((df.cod_eve == eve) & (df.ano == ano) & (df.archivo_origen != ultimo))]
        _registrar(F, f"R1 Archivo duplicado evento {eve} año {ano}", a, len(df))

    # R2. Evento y año dentro del alcance
    a = len(df)
    df = df[df.cod_eve.isin(list(C.EVENTOS)) & df.ano.isin(C.ANIOS)]
    _registrar(F, "R2 Evento/año fuera de alcance", a, len(df))

    # R3. Semana epidemiológica válida
    df["semana"] = _num(df["semana"]).astype("Int64")
    a = len(df)
    df = df[df.semana.between(1, 53)]
    _registrar(F, "R3 Semana epidemiológica inválida", a, len(df))

    # R4. Casos descartados (ajuste 6) o error de digitación (ajuste D)
    if "ajuste" in df.columns:
        a = len(df)
        df = df[~df["ajuste"].astype(str).str.strip().str.upper().isin(["6", "D"])]
        _registrar(F, "R4 Casos descartados / error de digitación", a, len(df))

    # R5. Ocurrencia en Colombia (código país 170)
    if "cod_pais_o" in df.columns:
        a = len(df)
        pais = _num(df["cod_pais_o"])
        df = df[pais.isna() | (pais == 170)]
        _registrar(F, "R5 Ocurrencia fuera de Colombia", a, len(df))

    # R6. Geografía de ocurrencia válida; código municipal DIVIPOLA de 5 dígitos
    dpto = _num(df["cod_dpto_o"])
    mun = _num(df["cod_mun_o"])
    a = len(df)
    ok = dpto.between(1, 99)
    df, dpto, mun = df[ok], dpto[ok], mun[ok]
    _registrar(F, "R6 Departamento de ocurrencia inválido", a, len(df))
    cod_mun = np.where(mun >= 1000, mun, dpto * 1000 + mun.fillna(0))   # algunos archivos traen 5 dígitos
    df["cod_dpto"] = dpto.astype(int).astype(str).str.zfill(2)
    df["cod_mpio"] = pd.Series(cod_mun, index=df.index).astype(int).astype(str).str.zfill(5)

    # Derivadas
    edad = _num(df.get("edad", pd.Series(index=df.index, dtype=float)))
    uni = _num(df.get("uni_med", pd.Series(1, index=df.index)))
    edad_anios = np.select([uni == 1, uni == 2, uni == 3], [edad, edad / 12, edad / 365], default=0)
    df["edad_anios"] = np.clip(edad_anios, 0, 110)
    df["grupo_edad"] = "ND"
    for lo, hi, et in GRUPOS_EDAD:
        df.loc[(df.edad_anios >= lo) & (df.edad_anios < hi), "grupo_edad"] = et
    sexo = df.get("sexo", pd.Series("", index=df.index)).astype(str).str.strip().str.upper().str[:1]
    df["sexo"] = np.where(sexo.isin(["M", "F"]), sexo, "ND")
    df["area_desc"] = _num(df.get("area", pd.Series(index=df.index))).map(AREA).fillna("No especificada")
    tip = _num(df.get("tip_cas", pd.Series(index=df.index)))
    aju = _num(df.get("ajuste", pd.Series(index=df.index)))
    df["confirmado"] = (tip.isin([3, 4, 5]) | aju.isin([3, 4, 5])).astype(int)
    df["hospitalizado"] = (_num(df.get("pac_hos", pd.Series(index=df.index))) == 1).astype(int)
    df["fallecido"] = (_num(df.get("con_fin", pd.Series(index=df.index))) == 2).astype(int)
    # Evento 580: el buscador SIVIGILA publica solo muertes por dengue ya confirmadas
    # (estado final "Confirmado por laboratorio" en el 100 % de los registros 2019-2025), con
    # condición final = 2. Cada registro cuenta como una muerte; si un archivo futuro trajera
    # registros sin condición final de muerte, se reportan como 'en estudio'.
    es580 = df.cod_eve == 580
    df.loc[es580, "fallecido"] = (_num(df.loc[es580, "con_fin"]) == 2).astype(int) if "con_fin" in df else 1
    df["fallecido_estudio"] = (es580 & (df.fallecido == 0)).astype(int)
    # Evitar doble conteo: algunos años (2019-2021, 2023) traen en 210/220 casos con condición
    # final = muerto que son las mismas muertes del evento 580. Si el año tiene archivo 580,
    # las muertes se toman solo de ahí.
    anios580 = set(df.loc[es580, "ano"])
    dup = (~es580) & df.ano.isin(anios580) & (df.fallecido == 1)
    if dup.any():
        CALIDAD.append({"fuente": F, "regla": "R7 Muertes en 210/220 ya contadas en el evento 580 (no se suman)",
                        "registros_antes": len(df), "registros_despues": len(df), "eliminados": 0,
                        "afectados": int(dup.sum())})
        log.info("  [%s] R7 muertes en 210/220 ya cubiertas por el evento 580: %s (no se suman)", F, int(dup.sum()))
    df.loc[dup, "fallecido"] = 0
    df["es_caso"] = (~es580).astype(int)
    df["id_semana"] = df.ano.astype(int) * 100 + df.semana.astype(int)
    _registrar(F, "Registros limpios", n0, len(df))
    return df


def agregar_sivigila(df: pd.DataFrame) -> pd.DataFrame:
    """De microdatos (una fila por caso) a hecho semanal: reduce el volumen y elimina el nivel individual."""
    dims = ["id_semana", "cod_mpio", "cod_dpto", "cod_eve", "sexo", "grupo_edad", "area_desc"]
    df = df.assign(confirmado_caso=df.confirmado * df.es_caso, hospitalizado_caso=df.hospitalizado * df.es_caso)
    f = (df.groupby(dims, observed=True)
           .agg(casos=("es_caso", "sum"), confirmados=("confirmado_caso", "sum"),
                hospitalizados=("hospitalizado_caso", "sum"),
                fallecidos=("fallecido", "sum"), fallecidos_en_estudio=("fallecido_estudio", "sum"))
           .reset_index())
    f["cod_eve"] = f["cod_eve"].astype(int)
    log.info("fact_dengue: %s filas (desde %s casos y %s muertes notificadas)", f"{len(f):,}",
             f"{int(df.es_caso.sum()):,}", f"{int((df.es_caso == 0).sum()):,}")
    return f


# ---------------------------------------------------------------------------
# DIVIPOLA -> dimensiones geográficas
# ---------------------------------------------------------------------------
def dimensiones_geograficas(div: pd.DataFrame):
    F = "DIVIPOLA"
    c_cd = _buscar_col(div, "cod_dpto", "codigo_departamento", "cod_depto")
    c_nd = _buscar_col(div, "dpto", "nom_dpto", "departamento")
    c_cm = _buscar_col(div, "cod_mpio", "codigo_municipio", "cod_mun")
    c_nm = _buscar_col(div, "nom_mpio", "municipio", "nombre_municipio")
    c_lat = _buscar_col(div, "latitud", "lat")
    c_lon = _buscar_col(div, "longitud", "lon")
    a = len(div)
    m = pd.DataFrame({
        "cod_mpio": _num(div[c_cm]).astype("Int64").astype(str).str.zfill(5),
        "municipio": div[c_nm].map(titulo),
        "cod_dpto": _num(div[c_cd]).astype("Int64").astype(str).str.zfill(2),
        "departamento_div": div[c_nd].astype(str).str.strip(),
        "latitud": _num(div[c_lat]), "longitud": _num(div[c_lon]),
    }).drop_duplicates("cod_mpio")
    _registrar(F, "Municipios únicos", a, len(m))
    # Coordenadas fuera de Colombia (errores de signo o escala)
    malas = ~(m.latitud.between(-5, 14) & m.longitud.between(-82, -66))
    m.loc[malas, ["latitud", "longitud"]] = np.nan
    CALIDAD.append({"fuente": F, "regla": "Coordenadas fuera de Colombia anuladas (se conserva el municipio)",
                    "registros_antes": len(m), "registros_despues": len(m), "eliminados": 0,
                    "afectados": int(malas.sum())})

    region = {c: r for r, lst in C.REGIONES.items() for c in lst}
    d = (m.groupby("cod_dpto")
           .agg(departamento=("departamento_div", "first"), n_municipios=("cod_mpio", "size"))
           .reset_index())
    d["departamento"] = d["departamento"].map(titulo)
    d.loc[d.cod_dpto == "11", "departamento"] = "Bogotá D.C."
    d["region"] = d.cod_dpto.map(region).fillna("Sin región")
    cap = m[m.cod_mpio.str.endswith("001")][["cod_dpto", "municipio"]].rename(columns={"municipio": "capital"})
    d = d.merge(cap, on="cod_dpto", how="left")
    m = m.drop(columns="departamento_div").merge(d[["cod_dpto", "departamento", "region"]], on="cod_dpto")
    m["es_capital"] = m.cod_mpio.str.endswith("001").astype(int)
    return m, d


def completar_dim_municipio(dim_m: pd.DataFrame, dim_d: pd.DataFrame, fact: pd.DataFrame) -> pd.DataFrame:
    """Integridad referencial: municipios del hecho que no existen en DIVIPOLA (p. ej. XX999)."""
    faltan = sorted(set(fact.cod_mpio) - set(dim_m.cod_mpio))
    if faltan:
        extra = pd.DataFrame({"cod_mpio": faltan, "municipio": "Municipio no especificado",
                              "cod_dpto": [c[:2] for c in faltan]})
        extra = extra.merge(dim_d[["cod_dpto", "departamento", "region"]], on="cod_dpto", how="left")
        extra["es_capital"] = 0
        dim_m = pd.concat([dim_m, extra], ignore_index=True)
        _registrar("Modelo", f"Municipios agregados a la dimensión por integridad ({len(faltan)})",
                   len(dim_m) - len(faltan), len(dim_m))
    return dim_m


# ---------------------------------------------------------------------------
# DANE
# ---------------------------------------------------------------------------
def limpiar_poblacion(df: pd.DataFrame) -> pd.DataFrame:
    F = "DANE"
    c_dp = _buscar_col(df, "dp")
    c_anio = _buscar_col(df, "ano", "anio", requerido=False)
    c_area = _buscar_col(df, "area_geografica", "area", requerido=False)
    if c_anio is None:  # formato ancho: un año por columna
        anios = [c for c in df.columns if str(c).isdigit()]
        df = df.melt(id_vars=[c for c in df.columns if c not in anios], value_vars=anios,
                     var_name="ano", value_name="poblacion")
        c_anio, c_pob = "ano", "poblacion"
    else:
        c_pob = _buscar_col(df, "poblacion", "total")
    a = len(df)
    if c_area:
        df = df[df[c_area].astype(str).str.strip().str.lower().str.startswith("total")]
        _registrar(F, "Filtro área geográfica = Total", a, len(df))
    p = pd.DataFrame({
        "cod_dpto": _num(df[c_dp]).astype("Int64").astype(str).str.zfill(2),
        "anio": _num(df[c_anio]).astype("Int64"),
        "poblacion": _num(df[c_pob].astype(str).str.replace(".", "", regex=False)),
    }).dropna()
    a = len(p)
    p = p[p.anio.isin(sorted(set(C.ANIOS) | set(C.ANIOS_CLIMA))) & (p.cod_dpto != "00")]
    _registrar(F, "Años fuera de alcance / total nacional", a, len(p))
    p["poblacion"] = p.poblacion.astype("int64")
    return p.groupby(["cod_dpto", "anio"], as_index=False)["poblacion"].sum()


# ---------------------------------------------------------------------------
# Clima
# ---------------------------------------------------------------------------
def _con_semana_epi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["time"]).dt.date
    se = df["fecha"].map(semana_epi)
    df["anio"] = se.str[0]
    df["semana"] = se.str[1]
    df["id_semana"] = df.anio * 100 + df.semana
    return df


def clima_semanal(df: pd.DataFrame) -> pd.DataFrame:
    F = "Open-Meteo"
    df = _con_semana_epi(df)
    a = len(df)
    df = df[df.anio >= min(C.ANIOS_CLIMA)]      # 1-2 ene. pueden caer en la última semana epi. del año previo
    _registrar(F, "Días de la semana epidemiológica del año anterior", a, len(df))
    a = len(df)
    df = df.dropna(subset=["temperature_2m_mean", "precipitation_sum"], how="all")
    _registrar(F, "Días sin dato", a, len(df))
    df["dia_lluvia"] = (df.precipitation_sum >= 1).astype(int)
    agg = {"temperature_2m_mean": "mean", "precipitation_sum": "sum", "dia_lluvia": "sum"}
    if "relative_humidity_2m_mean" in df:
        agg["relative_humidity_2m_mean"] = "mean"
    w = df.groupby(["id_semana", "cod_mpio"]).agg(agg).reset_index()
    return w.rename(columns={"temperature_2m_mean": "temp_media_c", "precipitation_sum": "precip_mm",
                             "relative_humidity_2m_mean": "humedad_pct", "dia_lluvia": "dias_lluvia"}).round(2)


def pronostico_diario(df: pd.DataFrame) -> pd.DataFrame:
    df = _con_semana_epi(df)
    return df.rename(columns={"temperature_2m_mean": "temp_media_c", "precipitation_sum": "precip_mm",
                              "relative_humidity_2m_mean": "humedad_pct"}).drop(columns="time")


# ---------------------------------------------------------------------------
# Tiempo
# ---------------------------------------------------------------------------
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def dim_tiempo() -> pd.DataFrame:
    filas = []
    for anio in sorted(set(C.ANIOS) | set(C.ANIOS_CLIMA)):
        n = 53 if semana_epi(inicio_semana_epi(anio, 53))[0] == anio else 52
        for s in range(1, n + 1):
            ini = inicio_semana_epi(anio, s)
            medio = ini + pd.Timedelta(days=3)
            filas.append({"id_semana": anio * 100 + s, "anio": anio, "semana": s,
                          "fecha_inicio": ini, "fecha_fin": ini + pd.Timedelta(days=6),
                          "mes_num": medio.month, "mes": MESES[medio.month - 1],
                          "trimestre": f"T{(medio.month - 1) // 3 + 1}",
                          "periodo_epi": f"PE{min((s - 1) // 4 + 1, 13):02d}",
                          "etiqueta": f"{anio}-S{s:02d}"})
    t = pd.DataFrame(filas).sort_values("id_semana").reset_index(drop=True)
    t["idx_semana"] = t.index + 1          # índice continuo: permite medidas con rezago en DAX
    return t
