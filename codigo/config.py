"""Configuración central del pipeline — Global Insights Analytics · Caso Salud (Dengue Colombia)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Las variables de entorno permiten correr el pipeline sobre otra carpeta (p. ej. datos de prueba)
DATA = Path(os.environ.get("GIA_DATA", ROOT / "data"))
OUTPUTS = Path(os.environ.get("GIA_OUTPUTS", ROOT / "outputs"))

# ---------------------------------------------------------------------------
# Zonas del lago de datos (arquitectura medallón: bronce -> plata -> oro)
# ---------------------------------------------------------------------------
RAW = DATA / "raw"          # bronce: datos tal como llegan de la fuente
CLEAN = DATA / "clean"      # plata: datos limpios y tipados (Parquet)
MODEL = DATA / "model"      # oro: modelo estrella listo para Power BI (Parquet, CSV, SQLite)

RAW_SIVIGILA = RAW / "sivigila"      # Excel descargados del Buscador de microdatos INS
RAW_DANE = RAW / "dane"              # PPED-AreaDep-2018-2050_VP.xlsx
RAW_BOLETINES = RAW / "boletines"    # PDF del Boletín Epidemiológico Semanal (opcional)
RAW_API = RAW / "api"                # respuestas JSON cacheadas de las APIs

SQLITE_DB = MODEL / "gia_salud.db"

# ---------------------------------------------------------------------------
# Alcance
# ---------------------------------------------------------------------------
# Años de microdatos SIVIGILA. Los años previos al último sirven como referencia
# del canal endémico; el último año es el "año de análisis".
ANIOS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
ANIO_ANALISIS = ANIOS[-1]     # se recalcula en ejecución con el último año presente en los datos
# 2020-2021 tuvieron subnotificación por COVID-19; se excluyen del canal endémico.
ANIOS_EXCLUIDOS_CANAL = [2020, 2021]

# Códigos de evento INS
EVENTOS = {
    210: "Dengue",
    220: "Dengue grave",
    580: "Mortalidad por dengue",
}
# Los microdatos publicados de 210/220 traen condición final = 1 (vivo) en todos los registros:
# las muertes se notifican en el evento 580. Esos registros NO suman como casos (casos = 0);
# solo alimentan 'fallecidos' (confirmados) y 'fallecidos_en_estudio'.
EVENTOS_CASOS = [210, 220]

# Clima: municipios con más casos para los que se consulta Open-Meteo y años de clima.
# 40 municipios x ~4,8 años de clima diario pesan ~5.000 llamadas de Open-Meteo: cerca del cupo
# por hora del plan gratuito. Cada municipio-año queda en caché, así que una corrida
# interrumpida por el límite se retoma sin repetir lo ya descargado.
TOP_MUNICIPIOS_CLIMA = 40
ANIOS_CLIMA = [2022, 2023, 2024, 2025, 2026]
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
VARIABLES_CLIMA = ["temperature_2m_mean", "precipitation_sum", "relative_humidity_2m_mean"]
LOTE_UBICACIONES = 10        # ubicaciones por petición a Open-Meteo
PAUSA_SEGUNDOS = 1.5         # pausa mínima entre peticiones
# Open-Meteo gratuito: 600 llamadas/min, 5.000/hora, 10.000/día. Una "llamada" = 1 ubicación,
# hasta 14 días y hasta 10 variables; un lote de 10 municipios x 1 año pesa ~260 llamadas.
# Se reparte el consumo para no superar ~450 llamadas por minuto.
LLAMADAS_POR_MINUTO = 450

# DIVIPOLA (API Socrata de datos.gov.co)
DIVIPOLA_API = "https://www.datos.gov.co/resource/gdxc-w37w.json"

# Regiones naturales (agrupación analítica propia, por código DANE de departamento)
REGIONES = {
    "Caribe": ["08", "13", "20", "23", "44", "47", "70", "88"],
    "Andina": ["05", "11", "15", "17", "25", "41", "54", "63", "66", "68", "73"],
    "Pacífica": ["19", "27", "52", "76"],
    "Orinoquía": ["50", "81", "85", "99"],
    "Amazonía": ["18", "86", "91", "94", "95", "97"],
}

# Ponderaciones del Índice de Priorización (IP) — documentadas en el informe
# Se combinan incidencia (riesgo por habitante) y carga absoluta (casos), porque la incidencia
# sola sobredimensiona departamentos con poca población.
PESOS_IP = {
    "incidencia": 0.25,
    "carga": 0.15,
    "pct_grave": 0.15,
    "letalidad": 0.20,
    "tendencia_4s": 0.15,
    "senal_clima": 0.10,
}
