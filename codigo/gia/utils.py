"""Utilidades comunes: logging, normalización de texto/columnas, semana epidemiológica, HTTP con caché."""
from __future__ import annotations

import json
import logging
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("gia")


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def quitar_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c))


def limpiar_valores_excel(df: pd.DataFrame) -> pd.DataFrame:
    """El buscador SIVIGILA exporta cada celda como fórmula de texto: ="2045", ="001".
    Se quita el envoltorio ="..." y los espacios de relleno."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            s = df[c].astype("string")
            df[c] = s.str.replace(r'^="(.*)"$', r"\1", regex=True).str.strip().replace("", pd.NA)
    return df


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """minúsculas, sin tildes, sin espacios: 'COD_DPTO_O' -> 'cod_dpto_o', 'AÑO' -> 'ano'."""
    nuevas = []
    for c in df.columns:
        c = quitar_tildes(str(c)).strip().lower().replace("ñ", "n")
        c = "".join(ch if ch.isalnum() else "_" for ch in c)
        while "__" in c:
            c = c.replace("__", "_")
        nuevas.append(c.strip("_"))
    df = df.copy()
    df.columns = nuevas
    return df


def normalizar_nombre(texto: str) -> str:
    """Para cruzar nombres de territorios: mayúsculas, sin tildes, sin signos."""
    t = quitar_tildes(texto).upper()
    t = "".join(ch if ch.isalnum() or ch == " " else " " for ch in t)
    return " ".join(t.split())


# ---------------------------------------------------------------------------
# Semana epidemiológica (calendario INS/MMWR: semanas de domingo a sábado;
# la semana 1 es la que contiene al menos 4 días de enero)
# ---------------------------------------------------------------------------
def inicio_anio_epi(anio: int) -> date:
    ene4 = date(anio, 1, 4)
    return ene4 - timedelta(days=(ene4.weekday() + 1) % 7)


def semana_epi(fecha: date) -> tuple[int, int]:
    anio = fecha.year
    if fecha < inicio_anio_epi(anio):
        anio -= 1
    elif fecha >= inicio_anio_epi(anio + 1):
        anio += 1
    semana = (fecha - inicio_anio_epi(anio)).days // 7 + 1
    return anio, semana


def inicio_semana_epi(anio: int, semana: int) -> date:
    return inicio_anio_epi(anio) + timedelta(weeks=semana - 1)


class LimiteAPI(RuntimeError):
    """La API pública agotó su cupo por hora o por día: reintentar no sirve, hay que esperar."""


# ---------------------------------------------------------------------------
# HTTP con caché local (zona bronce). Permite re-ejecutar sin internet (--offline)
# ---------------------------------------------------------------------------
def get_json(url: str, params: dict, cache_file: Path, offline: bool = False, reintentos: int = 6):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if offline or cache_file.exists():
        if not cache_file.exists():
            raise FileNotFoundError(f"Modo offline y no existe caché: {cache_file}")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    import requests  # importación diferida: no se necesita en modo offline

    espera = 2
    for intento in range(1, reintentos + 1):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 429:  # límite de uso de la API
                motivo = ""
                try:
                    motivo = r.json().get("reason", "")
                except ValueError:
                    pass
                m = motivo.lower()
                if "hour" in m or "daily" in m or "day" in m:
                    raise LimiteAPI(
                        f"La API alcanzó su límite {'por hora' if 'hour' in m else 'diario'} ({motivo}). "
                        "Lo descargado ya quedó en caché: vuelva a ejecutar 'python run_pipeline.py' "
                        f"{'en 1 hora' if 'hour' in m else 'mañana'} y el pipeline retomará donde quedó.")
                log.warning("Límite por minuto de la API (%s). Esperando 65 s...", motivo or "429")
                time.sleep(65)
                continue
            r.raise_for_status()
            data = r.json()
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except LimiteAPI:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Intento %s/%s falló (%s): %s", intento, reintentos, url, exc)
            if intento == reintentos:
                raise
            time.sleep(espera)
            espera *= 2
