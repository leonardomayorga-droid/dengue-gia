"""Fuente 6 (no estructurada): minería de texto del Boletín Epidemiológico Semanal (BES) del INS.

Para cada PDF:
  1. se extrae el texto y se aísla la sección de dengue (desde el título "Dengue / Metodología"
     hasta el título del siguiente evento),
  2. se divide en oraciones (punto, punto y coma, y la frase "Dentro de lo esperado", que en las
     tablas separa los territorios en situación normal de los que están en alerta),
  3. se cuentan, por departamento, las menciones en la sección y las menciones en oraciones con
     lenguaje de alerta (aumento, incremento, por encima de lo esperado, alerta, brote...).
El resultado es una señal cualitativa de la autoridad sanitaria que complementa los datos.
"""
from __future__ import annotations

import re

import pandas as pd

import config as C
from gia.utils import log, normalizar_nombre

PALABRAS_ALERTA = ["AUMENTO", "INCREMENTO", "POR ENCIMA", "ALERTA", "BROTE", "EPIDEMIA",
                   "MAYORES INCIDENCIAS", "SITUACION DE"]

# Alias habituales en los boletines -> código DANE
ALIAS = {
    "BOGOTA": "11", "VALLE": "76", "SAN ANDRES": "88", "NORTE DE SANTANDER": "54",
    "LA GUAJIRA": "44", "GUAJIRA": "44", "ARCHIPIELAGO DE SAN ANDRES": "88",
}


def _diccionario_departamentos(dim_dpto: pd.DataFrame) -> list[tuple[str, str]]:
    pares = {}
    for n, c in zip(dim_dpto["departamento"], dim_dpto["cod_dpto"]):
        nombre = normalizar_nombre(n)
        pares[nombre] = c
        pares[nombre.split(" PROVIDENCIA")[0].split(" D C")[0].strip()] = c
    pares.update(ALIAS)
    # nombres largos primero: evita que 'SANTANDER' capture 'NORTE DE SANTANDER'
    return sorted(((k, v) for k, v in pares.items() if len(k) > 3), key=lambda kv: -len(kv[0]))


def _seccion_dengue(texto: str) -> str:
    ini = re.search(r"\nDengue\s*\n\s*Metodolog", texto)
    if not ini:
        return ""
    resto = texto[ini.end():]
    fin = re.search(r"\n[A-ZÁÉÍÓÚ][\wáéíóúñ ,\-]{2,60}\s*\n\s*Metodolog", resto)
    return resto[: fin.start()] if fin else resto


def _oraciones(seccion: str) -> list[str]:
    s = re.sub(r"D\.\s?[TCE]\.", "D", seccion)          # 'Cartagena de Indias D. T.' no corta la oración
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?i)dentro de lo esperado", ". Dentro de lo esperado", s)
    return [normalizar_nombre(o) for o in re.split(r"[.;]\s+", s) if o.strip()]


def procesar_boletines(dim_dpto: pd.DataFrame) -> pd.DataFrame | None:
    pdfs = sorted(C.RAW_BOLETINES.glob("*.pdf"))
    if not pdfs:
        log.info("Boletines: no hay PDF en %s — fuente opcional omitida", C.RAW_BOLETINES)
        return None
    from pypdf import PdfReader

    nombres = _diccionario_departamentos(dim_dpto)
    filas = []
    for pdf in pdfs:
        texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(pdf).pages)
        nom = normalizar_nombre(pdf.stem)
        m_sem = re.search(r"SEMANA\D{0,3}(\d{1,2})", nom) or re.search(r"(?i)semana epidemiol[oó]gica\s+(\d{1,2})", texto)
        m_anio = re.search(r"(20\d{2})", pdf.stem) or re.search(r"(20\d{2})", texto)
        semana = int(m_sem.group(1)) if m_sem else None
        anio = int(m_anio.group(1)) if m_anio else None
        seccion = _seccion_dengue(texto)
        if not seccion:
            log.warning("  Boletín %s: no se encontró la sección de dengue", pdf.name)
            continue
        conteo: dict[str, list[int]] = {}
        for o in _oraciones(seccion):
            restante = f" {o} "
            alerta = any(p in o for p in PALABRAS_ALERTA)
            for nombre, cod in nombres:
                patron = f" {nombre} "
                n = restante.count(patron)
                if n:
                    restante = restante.replace(patron, " ")
                    c = conteo.setdefault(cod, [0, 0])
                    c[0] += n
                    c[1] += n if alerta else 0
        for cod, (tot, ale) in conteo.items():
            filas.append({"archivo": pdf.name, "anio": anio, "semana": semana,
                          "id_semana": anio * 100 + semana if anio and semana else None,
                          "cod_dpto": cod, "menciones_dengue": tot, "menciones_alerta": ale})
        log.info("  Boletín %-28s año=%s sem=%s · %s departamentos citados en la sección de dengue, "
                 "%s con lenguaje de alerta", pdf.name, anio, semana, len(conteo),
                 sum(1 for v in conteo.values() if v[1]))
    return pd.DataFrame(filas) if filas else None
