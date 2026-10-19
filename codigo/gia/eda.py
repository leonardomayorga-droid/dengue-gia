"""Análisis exploratorio (EDA): estadísticos, figuras para el informe y hallazgos clave (hallazgos.json).

Paleta: instancia de referencia validada para daltonismo (azul #2a78d6 / naranja #eb6834),
rampa secuencial azul para magnitud y colores de estado solo para las zonas del canal endémico.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

import config as C  # noqa: E402
from gia.utils import log  # noqa: E402

AZUL, NARANJA = "#2a78d6", "#eb6834"
TXT, TXT2, GRID, FONDO = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
ESTADO = {"Éxito": "#0ca30c", "Seguridad": "#fab219", "Alerta": "#ec835a", "Epidemia": "#d03b3b"}
SECUENCIAL = LinearSegmentedColormap.from_list(
    "azul", ["#f0efec", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
ORDINAL = {"Baja": "#86b6ef", "Media": "#2a78d6", "Alta": "#104281"}

plt.rcParams.update({
    "figure.facecolor": FONDO, "axes.facecolor": FONDO, "savefig.facecolor": FONDO,
    "axes.edgecolor": GRID, "axes.labelcolor": TXT2, "xtick.color": TXT2, "ytick.color": TXT2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": .6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "font.size": 9.5, "axes.titlesize": 11.5, "axes.titleweight": "bold", "axes.titlecolor": TXT,
    "axes.titlelocation": "left", "legend.frameon": False, "figure.dpi": 150,
})


def _fmt(n):
    return f"{n:,.0f}".replace(",", ".")


def _guardar(fig, nombre):
    ruta = C.OUTPUTS / "eda" / nombre
    fig.tight_layout()
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta.name


def _leer(nombre):
    p = C.MODEL / "parquet" / f"{nombre}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def ejecutar_eda() -> dict:
    (C.OUTPUTS / "eda").mkdir(parents=True, exist_ok=True)
    f, t, d = _leer("fact_dengue"), _leer("dim_tiempo"), _leer("dim_departamento")
    pob, canal, rez = _leer("fact_poblacion"), _leer("fact_canal_endemico"), _leer("rezago_clima")
    prior, mun = _leer("dep_priorizacion"), _leer("dim_municipio")
    canual = _leer("clima_anual")
    a = C.ANIO_ANALISIS
    f["anio"] = f.id_semana // 100
    H: dict = {"anio_analisis": a, "figuras": []}

    # --- Estadísticos descriptivos ------------------------------------------------------
    anual = f.groupby("anio").agg(casos=("casos", "sum"), graves=("casos", lambda s: s[f.loc[s.index, "cod_eve"] == 220].sum()),
                                  fallecidos=("fallecidos", "sum"), hospitalizados=("hospitalizados", "sum"))
    pob_nal = pob.groupby("anio")["poblacion"].sum()
    anual["incidencia_100k"] = anual.casos / anual.index.map(pob_nal) * 1e5
    anual["letalidad_pct"] = 100 * anual.fallecidos / anual.casos
    anual["pct_grave"] = 100 * anual.graves / anual.casos
    anual["pct_hosp"] = 100 * anual.hospitalizados / anual.casos
    anual.round(3).to_csv(C.OUTPUTS / "eda" / "resumen_anual.csv")
    H["resumen_anual"] = anual.round(2).reset_index().to_dict("records")

    sm = f.groupby(["cod_mpio", "id_semana"])["casos"].sum()
    desc = sm.describe(percentiles=[.25, .5, .75, .9, .99]).round(2)
    desc["asimetria"] = round(float(sm.skew()), 2)
    desc.to_csv(C.OUTPUTS / "eda" / "descriptivos_casos_municipio_semana.csv")
    H["casos_municipio_semana"] = desc.to_dict()

    top_m = f[f.anio == a].groupby("cod_mpio")["casos"].sum().sort_values(ascending=False)
    H["concentracion_top10_municipios_pct"] = round(100 * top_m.head(10).sum() / top_m.sum(), 1)
    H["top10_municipios"] = (top_m.head(10).rename("casos").reset_index()
                             .merge(mun[["cod_mpio", "municipio", "departamento"]], on="cod_mpio")
                             .to_dict("records"))

    # --- Fig 1. Serie semanal nacional ----------------------------------------------------
    s = f.groupby("id_semana")["casos"].sum()
    s = s.reindex(t[t.anio.isin(C.ANIOS) & (t.id_semana <= s.index.max())].id_semana)
    s[(s.index % 100 < 53)] = s[(s.index % 100 < 53)].fillna(0)   # semana 53 sin publicar -> hueco
    fig, ax = plt.subplots(figsize=(9, 3.4))
    x = np.arange(len(s))
    ax.plot(x, s.values, color=AZUL, lw=2)
    ticks = [i for i, k in enumerate(s.index) if k % 100 == 1]
    ax.set_xticks(ticks, [str(s.index[i] // 100) for i in ticks])
    imax = int(np.nanargmax(s.values))
    ax.annotate(f"Pico: {_fmt(s.values[imax])} casos\n(semana {s.index[imax] % 100} de {s.index[imax] // 100})",
                (imax, s.values[imax]), xytext=(10, -5), textcoords="offset points", color=TXT, fontsize=8.5)
    ax.set_title("Casos semanales de dengue y dengue grave notificados en Colombia")
    ax.set_ylabel("Casos por semana epidemiológica")
    ax.yaxis.set_major_formatter(lambda v, _: _fmt(v))
    H["figuras"].append(_guardar(fig, "fig1_serie_nacional.png"))
    H["pico"] = {"id_semana": int(s.index[imax]), "casos": int(s.values[imax])}

    # --- Fig 2. Canal endémico nacional del año de análisis -------------------------------
    if canal.empty:
        log.warning("EDA: sin canal endémico (faltan años de referencia); se omite la figura 2")
        H["semanas_por_zona"] = "sin canal endémico: faltan años de referencia"
    else:
        cn = canal[(canal.ambito == "Nacional") & (canal.id_semana // 100 == a)].sort_values("id_semana")
        obs = f[f.anio == a].groupby("id_semana")["casos"].sum()
        cn = cn[cn.id_semana <= obs.index.max()]          # solo semanas con datos publicados
        obs = obs.reindex(cn.id_semana, fill_value=0)
        xs = (cn.id_semana % 100).values
        fig, ax = plt.subplots(figsize=(9, 3.6))
        techo = max(obs.max(), cn.canal_q3.max()) * 1.15
        capas = [(0, cn.canal_q1, "Éxito"), (cn.canal_q1, cn.canal_mediana, "Seguridad"),
                 (cn.canal_mediana, cn.canal_q3, "Alerta"), (cn.canal_q3, techo, "Epidemia")]
        for lo, hi, z in capas:
            ax.fill_between(xs, lo, hi, color=ESTADO[z], alpha=.32, lw=0, label=f"Zona de {z.lower()}")
        ax.plot(xs, obs.values, color=TXT, lw=2, label=f"Casos observados {a}")
        ax.set_xlim(1, xs.max()); ax.set_ylim(0, techo)
        ax.set_title(f"Canal endémico nacional {a} (cuartiles de años de referencia)")
        ax.set_xlabel("Semana epidemiológica"); ax.set_ylabel("Casos")
        ax.yaxis.set_major_formatter(lambda v, _: _fmt(v))
        ax.legend(loc="upper left", ncol=5, fontsize=8, bbox_to_anchor=(0, -0.18))
        H["figuras"].append(_guardar(fig, "fig2_canal_endemico.png"))
        zona = np.select([obs.values > cn.canal_q3.values, obs.values > cn.canal_mediana.values,
                          obs.values > cn.canal_q1.values], ["Epidemia", "Alerta", "Seguridad"], "Éxito")
        H["semanas_por_zona"] = pd.Series(zona).value_counts().to_dict()

    # --- Fig 3. Incidencia por departamento (top 15) -------------------------------------
    inc = (f[f.anio == a].groupby("cod_dpto")["casos"].sum().rename("casos").reset_index()
             .merge(pob[pob.anio == a], on="cod_dpto").merge(d[["cod_dpto", "departamento"]], on="cod_dpto"))
    inc["incidencia"] = inc.casos / inc.poblacion * 1e5
    # Incidencia nacional = todos los casos / toda la población (incluye departamentos sin casos)
    nal = inc.casos.sum() / pob[pob.anio == a].poblacion.sum() * 1e5
    top = inc.nlargest(15, "incidencia").sort_values("incidencia")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(top.departamento, top.incidencia, color=AZUL, height=.62)
    for y, v in enumerate(top.incidencia):
        ax.text(v, y, f" {v:,.0f}".replace(",", "."), va="center", color=TXT2, fontsize=8)
    ax.axvline(nal, color=TXT, lw=1, ls="--")
    ax.text(nal, len(top) - .4, f" Nacional: {nal:,.0f}".replace(",", "."), color=TXT, fontsize=8)
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Incidencia de dengue por 100.000 habitantes, {a} (15 departamentos más altos)")
    H["figuras"].append(_guardar(fig, "fig3_incidencia_departamentos.png"))
    H["incidencia_nacional_100k"] = round(nal, 1)
    H["top5_incidencia"] = inc.nlargest(5, "incidencia")[["departamento", "casos", "incidencia"]].round(1).to_dict("records")

    # --- Fig 4. Mapa de calor departamento x semana --------------------------------------
    hm = (f[f.anio == a].groupby(["cod_dpto", "id_semana"])["casos"].sum().reset_index()
            .merge(pob[pob.anio == a], on="cod_dpto"))
    hm["inc"] = hm.casos / hm.poblacion * 1e5
    hm = hm.merge(d[["cod_dpto", "departamento"]], on="cod_dpto")
    piv = hm.pivot_table(index="departamento", columns=hm.id_semana % 100, values="inc", fill_value=0)
    top_casos = hm.groupby("departamento")["casos"].sum().nlargest(15).index
    piv = piv.loc[[i for i in top_casos if i in piv.index]]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    im = ax.imshow(piv.values.astype(float), aspect="auto", cmap=SECUENCIAL, interpolation="nearest")
    ax.set_yticks(range(len(piv)), piv.index); ax.set_xticks(range(0, piv.shape[1], 4), piv.columns[::4])
    ax.grid(False); ax.set_xlabel("Semana epidemiológica")
    cb = fig.colorbar(im, ax=ax, fraction=.025, pad=.01); cb.set_label("Casos por 100.000 hab.", color=TXT2)
    cb.outline.set_visible(False)
    ax.set_title(f"Estacionalidad: incidencia semanal en los 15 departamentos con más casos, {a}")
    H["figuras"].append(_guardar(fig, "fig4_mapa_calor_semanal.png"))

    # --- Fig 5. Rezago clima -> casos (anomalías dentro de cada año) -------------------------
    if not rez.empty:
        fig, ax = plt.subplots(figsize=(8, 3.6))
        nombres = {"precip_mm": ("Precipitación", AZUL), "temp_media_c": ("Temperatura media", NARANJA)}
        for var, (lab, col) in nombres.items():
            r = rez[rez.variable == var].sort_values("rezago_semanas")
            if r.empty:
                continue
            ax.fill_between(r.rezago_semanas, r.corr_p25, r.corr_p75, color=col, alpha=.12, lw=0)
            ax.plot(r.rezago_semanas, r.corr_mediana, color=col, lw=2, marker="o", ms=4, label=lab)
            b = r.loc[r.corr_mediana.idxmax()]
            pct = float(b.get("pct_municipios_positivos", float("nan")))
            ax.annotate(f"{lab}: máx. {int(b.rezago_semanas)} sem., ρ={b.corr_mediana:.2f}\n"
                        f"(positiva en {pct:.0f} % de municipios)",
                        (b.rezago_semanas, b.corr_mediana), xytext=(0, 22 if var == "precip_mm" else -34),
                        textcoords="offset points", ha="center", color=TXT, fontsize=8,
                        arrowprops=dict(arrowstyle="-", color=TXT2, lw=.6))
            H[f"rezago_optimo_{var}"] = {"semanas": int(b.rezago_semanas), "rho_mediana": float(b.corr_mediana),
                                         "pct_municipios_positivos": pct, "n_municipios": int(b.n_municipios)}
        ax.axhline(0, color=TXT2, lw=.8)
        ax.set_xlabel("Semanas de rezago (clima antes de los casos)")
        ax.set_ylabel("Correlación de Spearman\n(mediana entre municipios)")
        ax.set_title("Dentro de cada año, la lluvia antecede los casos por 3-6 semanas (efecto débil)")
        ax.set_ylim(min(-0.2, rez.corr_p25.min() - .02), max(0.35, rez.corr_p75.max() + .05))
        ax.legend(loc="lower right", ncol=2)
        H["figuras"].append(_guardar(fig, "fig5_rezago_clima.png"))

    # --- Fig 8. Entre años: temperatura y tamaño de la epidemia -------------------------------
    if not canual.empty:
        ca = canual.sort_values("anio")
        lim = max(0.3, ca.anom_temp_c.abs().max())
        DIVERG = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#d03b3b"])
        colores = [DIVERG((v + lim) / (2 * lim)) for v in ca.anom_temp_c]
        fig, ax = plt.subplots(figsize=(8, 3.6))
        xs8 = np.arange(len(ca))
        ax.bar(xs8, ca.casos, color=colores, width=.6, edgecolor=GRID)
        ax.set_xticks(xs8, [str(int(v)) for v in ca.anio])
        for x, (cs, tv) in enumerate(zip(ca.casos, ca.anom_temp_c)):
            ax.text(x, cs, f"{_fmt(cs)} casos\n{tv:+.2f} °C", ha="center", va="bottom", fontsize=8.5, color=TXT)
        ax.set_ylim(0, ca.casos.max() * 1.25); ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(lambda v, _: _fmt(v))
        ax.set_ylabel(f"Casos ({int(ca.municipios.max())} municipios con clima)")
        ax.set_title("Los años más cálidos tienen más dengue")
        ax.text(0, -0.2, "Color: anomalía de temperatura media del año frente al promedio 2022-2025 "
                "(azul = más frío, rojo = más cálido).", transform=ax.transAxes, fontsize=8, color=TXT2)
        H["figuras"].append(_guardar(fig, "fig8_clima_anual.png"))
        H["clima_anual"] = ca.to_dict("records")
        H["rho_temp_casos_entre_anios"] = float(ca.rho_temp_casos.iloc[0])
        H["pct_municipios_temp_positiva"] = float(ca.pct_municipios_positivos.iloc[0])

    # --- Fig 6. Sexo y grupo de edad --------------------------------------------------------
    se = f[(f.anio == a) & f.sexo.isin(["F", "M"])].pivot_table(index="grupo_edad", columns="sexo",
                                                               values="casos", aggfunc="sum").fillna(0)
    orden = [g for g in ["0-4", "5-14", "15-29", "30-44", "45-59", "60+"] if g in se.index]
    se = se.loc[orden]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    w = .38
    xx = np.arange(len(se))
    for i, (sx, lab, col) in enumerate([("F", "Mujeres", AZUL), ("M", "Hombres", NARANJA)]):
        ax.bar(xx + (i - .5) * (w + .02), se[sx], width=w, color=col, label=lab)
    ax.set_xticks(xx, se.index); ax.set_xlabel("Grupo de edad (años)"); ax.grid(axis="x", visible=False)
    ax.yaxis.set_major_formatter(lambda v, _: _fmt(v))
    ax.set_title(f"Casos por grupo de edad y sexo, {a}"); ax.legend()
    H["figuras"].append(_guardar(fig, "fig6_edad_sexo.png"))
    H["grupo_edad_mas_casos"] = se.sum(axis=1).idxmax()
    H["pct_casos_menores_15"] = round(100 * se.loc[[g for g in ["0-4", "5-14"] if g in se.index]].values.sum() / se.values.sum(), 1)

    # --- Fig 7. Índice de priorización -------------------------------------------------------
    if not prior.empty:
        p = prior.nsmallest(15, "ranking").sort_values("ip")
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(p.departamento, p.ip, color=p.prioridad.map(ORDINAL), height=.62)
        for y, (v, pr) in enumerate(zip(p.ip, p.prioridad)):
            ax.text(v, y, f" {v:.0f} · {pr}", va="center", color=TXT2, fontsize=8)
        ax.set_xlim(0, 100); ax.grid(axis="y", visible=False)
        ax.set_xlabel("Índice de priorización (0-100)")
        ax.set_title(f"Departamentos priorizados para intervención, {a}")
        H["figuras"].append(_guardar(fig, "fig7_priorizacion.png"))
        H["top5_priorizacion"] = prior.nsmallest(5, "ranking")[
            [c for c in ["departamento", "ip", "casos", "incidencia_100k", "fallecidos", "letalidad_pct",
                         "letalidad_suav_pct", "tendencia_4s_pct", "senal_clima"] if c in prior]].round(2).to_dict("records")
        H["n_prioridad_alta"] = int((prior.prioridad == "Alta").sum())

    log.info("EDA: %s figuras en %s", len(H["figuras"]), C.OUTPUTS / "eda")
    return H
