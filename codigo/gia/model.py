"""Carga (zona oro): modelo estrella en Parquet (para Power BI), CSV (portabilidad) y SQLite (capa SQL)."""
from __future__ import annotations

import sqlite3

import pandas as pd

import config as C
from gia.utils import log


def guardar_modelo(tablas: dict[str, pd.DataFrame]):
    C.MODEL.mkdir(parents=True, exist_ok=True)
    (C.MODEL / "parquet").mkdir(exist_ok=True)
    (C.MODEL / "csv").mkdir(exist_ok=True)
    if C.SQLITE_DB.exists():
        C.SQLITE_DB.unlink()
    con = sqlite3.connect(C.SQLITE_DB)
    for nombre, df in tablas.items():
        if df is None or df.empty:
            continue
        df = df.copy()
        for c in df.columns:  # fechas a ISO para SQLite/CSV
            if df[c].dtype == object and len(df) and hasattr(df[c].iloc[0], "isoformat"):
                df[c] = pd.to_datetime(df[c])
        df.to_parquet(C.MODEL / "parquet" / f"{nombre}.parquet", index=False)
        df.to_csv(C.MODEL / "csv" / f"{nombre}.csv", index=False, encoding="utf-8")
        df.to_sql(nombre, con, index=False)
        log.info("  %-24s %9s filas", nombre, f"{len(df):,}")
    # índices y vistas SQL de KPI
    sql = (C.ROOT / "sql" / "vistas_kpi.sql").read_text(encoding="utf-8")
    con.executescript(sql)
    con.commit()
    con.close()
    log.info("Modelo guardado en %s (Parquet, CSV y SQLite)", C.MODEL)
