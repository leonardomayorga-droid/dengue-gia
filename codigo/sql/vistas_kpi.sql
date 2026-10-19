-- =============================================================================
-- Capa SQL del modelo (SQLite): índices y vistas de KPI
-- Global Insights Analytics · Caso Salud · Dengue Colombia
-- Se ejecuta automáticamente al final del pipeline (gia/model.py).
-- =============================================================================

CREATE INDEX IF NOT EXISTS ix_fd_semana ON fact_dengue(id_semana);
CREATE INDEX IF NOT EXISTS ix_fd_mpio   ON fact_dengue(cod_mpio);
CREATE INDEX IF NOT EXISTS ix_fd_dpto   ON fact_dengue(cod_dpto);
CREATE INDEX IF NOT EXISTS ix_fc_mpio   ON fact_clima_semana(cod_mpio, id_semana);

-- KPI anuales por departamento: casos, incidencia, % grave, letalidad
DROP VIEW IF EXISTS v_kpi_departamento_anio;
CREATE VIEW v_kpi_departamento_anio AS
SELECT  f.cod_dpto,
        d.departamento,
        d.region,
        f.id_semana / 100                                        AS anio,
        SUM(f.casos)                                             AS casos,
        SUM(CASE WHEN f.cod_eve = 220 THEN f.casos ELSE 0 END)   AS casos_graves,
        SUM(f.hospitalizados)                                    AS hospitalizados,
        SUM(f.fallecidos)                                        AS fallecidos,
        p.poblacion,
        ROUND(SUM(f.casos) * 100000.0 / p.poblacion, 1)          AS incidencia_100k,
        ROUND(100.0 * SUM(CASE WHEN f.cod_eve = 220 THEN f.casos ELSE 0 END) / SUM(f.casos), 2) AS pct_grave,
        ROUND(100.0 * SUM(f.fallecidos) / SUM(f.casos), 3)       AS letalidad_pct
FROM    fact_dengue f
JOIN    dim_departamento d ON d.cod_dpto = f.cod_dpto
LEFT JOIN fact_poblacion p ON p.cod_dpto = f.cod_dpto AND p.anio = f.id_semana / 100
GROUP BY f.cod_dpto, d.departamento, d.region, f.id_semana / 100, p.poblacion;

-- Serie semanal nacional frente al canal endémico
DROP VIEW IF EXISTS v_canal_nacional;
CREATE VIEW v_canal_nacional AS
SELECT  c.id_semana,
        c.canal_q1, c.canal_mediana, c.canal_q3,
        COALESCE(s.casos, 0) AS casos_observados,
        CASE WHEN COALESCE(s.casos,0) > c.canal_q3      THEN 'Epidemia'
             WHEN COALESCE(s.casos,0) > c.canal_mediana THEN 'Alerta'
             WHEN COALESCE(s.casos,0) > c.canal_q1      THEN 'Seguridad'
             ELSE 'Éxito' END AS zona
FROM    fact_canal_endemico c
LEFT JOIN (SELECT id_semana, SUM(casos) AS casos FROM fact_dengue GROUP BY id_semana) s
       ON s.id_semana = c.id_semana
WHERE   c.ambito = 'Nacional';

-- Top municipios por casos en cada año
DROP VIEW IF EXISTS v_top_municipios;
CREATE VIEW v_top_municipios AS
SELECT  *
FROM (
    SELECT  f.id_semana / 100 AS anio, m.cod_mpio, m.municipio, m.departamento,
            SUM(f.casos) AS casos,
            RANK() OVER (PARTITION BY f.id_semana / 100 ORDER BY SUM(f.casos) DESC) AS posicion
    FROM    fact_dengue f JOIN dim_municipio m ON m.cod_mpio = f.cod_mpio
    GROUP BY f.id_semana / 100, m.cod_mpio, m.municipio, m.departamento
) WHERE posicion <= 20;

-- Clima semanal y casos (base del análisis de rezago)
DROP VIEW IF EXISTS v_clima_casos;
CREATE VIEW v_clima_casos AS
SELECT  c.cod_mpio, c.id_semana, c.temp_media_c, c.precip_mm, c.dias_lluvia,
        COALESCE(SUM(f.casos), 0) AS casos
FROM    fact_clima_semana c
LEFT JOIN fact_dengue f ON f.cod_mpio = c.cod_mpio AND f.id_semana = c.id_semana
GROUP BY c.cod_mpio, c.id_semana, c.temp_media_c, c.precip_mm, c.dias_lluvia;
