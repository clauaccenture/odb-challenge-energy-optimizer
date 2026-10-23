"""
04 - Análisis descriptivo AEMET + REData

Objetivo:
Cruzar la temperatura media diaria de AEMET con el precio medio
diario de REData para estudiar descriptivamente su relación.

Este análisis NO implica causalidad: la temperatura va muy ligada a la
estación del año, y otras variables (renovables, gas, demanda...) también
mueven el precio.

Salida:
    data/outputs/aemet/analisis_temperatura_precio.parquet   (datos cruzados por día)
    data/outputs/aemet/grafico_temperatura_precio.png        (gráfico para el cliente, 300 dpi)
    data/outputs/aemet/grafico_temperatura_precio.svg        (mismo gráfico en vectorial)

Uso (desde la raíz del repo):
    python notebooks/04_analisis_temperatura_precio.py                     # todos los días disponibles
    python notebooks/04_analisis_temperatura_precio.py --start 2025-10-01 --end 2026-09-30
    python notebooks/04_analisis_temperatura_precio.py --start 2026-01-01  # desde una fecha en adelante
    python notebooks/04_analisis_temperatura_precio.py --show              # además abre la ventana

--start y --end son opcionales y se pueden usar por separado. Los dos extremos están incluidos.
"""

import argparse
from datetime import date
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# --------------------------------------------------
# RUTAS
# --------------------------------------------------

AEMET_PATH = Path("data/outputs/aemet/gold_temperatura_diaria.parquet")
REDATA_PATH = Path("data/outputs/redata/gold_programacion_horaria.parquet")
OUTPUT_PATH = Path("data/outputs/aemet/analisis_temperatura_precio.parquet")
FIGURE_PATH = Path("data/outputs/aemet/grafico_temperatura_precio.png")


# --------------------------------------------------
# PARÁMETROS DEL GRÁFICO
# --------------------------------------------------

ESTACION_POR_MES = {
    12: "Invierno", 1: "Invierno", 2: "Invierno",
    3: "Primavera", 4: "Primavera", 5: "Primavera",
    6: "Verano", 7: "Verano", 8: "Verano",
    9: "Otoño", 10: "Otoño", 11: "Otoño",
}
COLOR_ESTACION = {
    "Invierno": "#2b6cb0",
    "Primavera": "#00ff77",
    "Verano": "#ffd000",
    "Otoño": "#ff5100",
}

# Tramos de temperatura para el gráfico de barras y la tabla resumen
TRAMOS_BORDES = [float("-inf"), 10, 15, 20, 25, float("inf")]
TRAMOS_NOMBRES = ["< 10 °C", "10-15 °C", "15-20 °C", "20-25 °C", "> 25 °C"]

# Calidad y tamaño pensados para pegar el gráfico en una diapositiva
DPI = 300                   # resolución del PNG (150 = borrador, 300 = presentación)
FIGSIZE = (13, 6)           # pulgadas: casi el ancho de una diapositiva 16:9 (13,33)
FUENTE_BASE = 12            # tamaño de letra base (se ve bien proyectado)

ANCHO_TRAMO_TENDENCIA = 2   # °C por tramo para la línea de tendencia
MIN_DIAS_TRAMO = 5          # un tramo con menos días no se dibuja en la tendencia


# --------------------------------------------------
# CARGA
# --------------------------------------------------

def load_data():

    if not AEMET_PATH.exists():
        raise FileNotFoundError(f"No existe {AEMET_PATH}")

    if not REDATA_PATH.exists():
        raise FileNotFoundError(f"No existe {REDATA_PATH}")

    aemet = pd.read_parquet(AEMET_PATH)
    redata = pd.read_parquet(REDATA_PATH)

    return aemet, redata


# --------------------------------------------------
# PREPARAR AEMET
# --------------------------------------------------

def prepare_aemet(df):

    df = df.copy()

    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    return df[["fecha", "tmed", "tmin", "tmax"]]


# --------------------------------------------------
# PREPARAR REDATA
# --------------------------------------------------

def prepare_redata(df):

    df = df.copy()

    # En Gold REData la fecha se llama fecha_local
    df["fecha"] = pd.to_datetime(df["fecha_local"]).dt.date

    # Convertimos los precios horarios en precio medio diario
    diario = (
        df
        .groupby("fecha", as_index=False)
        .agg(
            precio_medio_eur_mwh=("precio_eur_mwh", "mean"),
            precio_min_eur_mwh=("precio_eur_mwh", "min"),
            precio_max_eur_mwh=("precio_eur_mwh", "max"),
        )
    )

    return diario


# --------------------------------------------------
# CRUCE
# --------------------------------------------------

def merge_sources(aemet, redata):

    combinado = pd.merge(redata, aemet, on="fecha", how="inner")

    # Columnas auxiliares para el análisis
    fecha = pd.to_datetime(combinado["fecha"])
    combinado["estacion"] = fecha.dt.month.map(ESTACION_POR_MES)
    combinado["tramo_temperatura"] = pd.cut(
        combinado["tmed"],
        bins=TRAMOS_BORDES,
        labels=TRAMOS_NOMBRES,
        right=False,
    )

    return combinado


# --------------------------------------------------
# FILTRO POR PERIODO
# --------------------------------------------------

def filter_period(df, start, end):
    """Se queda con los días entre start y end (ambos incluidos). Cualquiera puede ser None."""

    disponible_min, disponible_max = df["fecha"].min(), df["fecha"].max()

    if start is not None and start < disponible_min:
        print(f"AVISO: --start {start} es anterior al primer día cruzado ({disponible_min}).")
    if end is not None and end > disponible_max:
        print(f"AVISO: --end {end} es posterior al último día cruzado ({disponible_max}).")

    if start is not None:
        df = df[df["fecha"] >= start]
    if end is not None:
        df = df[df["fecha"] <= end]

    if df.empty:
        raise ValueError(
            f"No hay días en el periodo pedido. Días disponibles tras el cruce: "
            f"{disponible_min} -> {disponible_max}"
        )

    return df.reset_index(drop=True)


# --------------------------------------------------
# ANALISIS
# --------------------------------------------------

def resumen_por_tramo(df):
    """Precio medio, mediana y nº de días por tramo de temperatura."""
    return (
        df.groupby("tramo_temperatura", observed=False)["precio_medio_eur_mwh"]
        .agg(dias="size", precio_medio="mean", precio_mediana="median")
        .round(1)
    )


def analyze(df):

    pearson = df["tmed"].corr(df["precio_medio_eur_mwh"])

    print("\n" + "=" * 60)
    print("AEMET + REDATA")
    print("=" * 60)

    print(f"\nDías comparados: {len(df)}")

    print(f"\nCorrelación lineal (Pearson) temperatura vs precio: {pearson:.3f}")
    print(
        "  OJO: si la relación tiene forma de U (precios altos con frío y con calor),\n"
        "  la correlación lineal sale cercana a 0 aunque haya un patrón claro.\n"
        "  Por eso se enseña también el resumen por tramos."
    )

    resumen = resumen_por_tramo(df)
    print("\nPrecio de la electricidad por tramo de temperatura media diaria:")
    print(resumen.to_string())

    return pearson, resumen


# --------------------------------------------------
# GRÁFICO
# --------------------------------------------------

def plot_relationship(df, resumen):

    fechas = pd.to_datetime(df["fecha"])
    periodo = f"{fechas.min():%d/%m/%Y} - {fechas.max():%d/%m/%Y}"

    plt.rcParams.update({"font.size": FUENTE_BASE})

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=FIGSIZE, gridspec_kw={"width_ratios": [3, 2]}
    )

    # ---------- Panel izquierdo: un punto por día, coloreado por estación ----------
    for estacion, color in COLOR_ESTACION.items():
        d = df[df["estacion"] == estacion]
        if d.empty:
            continue  # con un periodo corto, esa estación no aparece
        ax1.scatter(
            d["tmed"], d["precio_medio_eur_mwh"],
            s=40, alpha=0.7, color=color, label=f"{estacion} ({len(d)} días)",
            edgecolors="none",
        )

    # Línea de tendencia: mediana del precio por tramos de 2 °C
    base = (df["tmed"] // ANCHO_TRAMO_TENDENCIA) * ANCHO_TRAMO_TENDENCIA
    tend = (
        df.assign(tramo=base)
        .groupby("tramo")["precio_medio_eur_mwh"]
        .agg(mediana="median", n="size")
    )
    tend = tend[tend["n"] >= MIN_DIAS_TRAMO]
    ax1.plot(
        tend.index + ANCHO_TRAMO_TENDENCIA / 2, tend["mediana"],
        color="black", linewidth=2.5,
        label=f"Mediana por tramos de {ANCHO_TRAMO_TENDENCIA} °C",
    )

    ax1.set_xlabel("Temperatura media diaria (°C)")
    ax1.set_ylabel("Precio medio diario (EUR/MWh)")
    ax1.set_title("Cada punto es un día", fontsize=FUENTE_BASE + 2, loc="left")
    # Hueco libre arriba para la leyenda: así nunca se superpone a los puntos
    ax1.set_ylim(top=ax1.get_ylim()[1] * 1.3)
    ax1.legend(loc="upper left", ncol=2, frameon=False, fontsize=FUENTE_BASE - 1)
    ax1.grid(alpha=0.25)

    # ---------- Panel derecho: precio medio por tramo de temperatura ----------
    resumen = resumen[resumen["dias"] > 0]  # sin tramos vacíos
    etiquetas = [
        f"{t}\n({int(n)} {'día' if n == 1 else 'días'})"
        for t, n in zip(resumen.index, resumen["dias"])
    ]
    barras = ax2.bar(
        etiquetas, resumen["precio_medio"],
        color="#4a5568", alpha=0.85,
    )
    for barra, valor in zip(barras, resumen["precio_medio"]):
        if pd.notna(valor):
            ax2.text(
                barra.get_x() + barra.get_width() / 2, valor + 1.5,
                f"{valor:.0f}", ha="center", va="bottom", fontsize=FUENTE_BASE,
            )
    ax2.set_ylabel("Precio medio (EUR/MWh)")
    ax2.set_title("Precio medio según la temperatura", fontsize=FUENTE_BASE + 2, loc="left")
    ax2.grid(axis="y", alpha=0.25)
    ax2.tick_params(axis="x", labelsize=FUENTE_BASE - 1)

    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle(
        f"Temperatura media diaria y precio de la electricidad ({periodo})",
        fontsize=FUENTE_BASE + 6, fontweight="bold", x=0.01, ha="left",
    )
    fig.text(
        0.01, 0.01,
        "Fuentes: AEMET (temperatura media nacional) y REData (precio spot medio diario). "
        "Relación descriptiva, no causal: la temperatura coincide con la estación del año.",
        fontsize=FUENTE_BASE - 2, color="#4a5568", ha="left",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))

    return fig


# --------------------------------------------------
# GUARDAR RESULTADOS
# --------------------------------------------------

def save_analysis(df):

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # tramo_temperatura es categórica: se guarda como texto
    out = df.assign(tramo_temperatura=df["tramo_temperatura"].astype("string"))
    out.to_parquet(OUTPUT_PATH, index=False)

    print(f"\nGuardado análisis en: {OUTPUT_PATH}")


def save_figure(fig, dpi):

    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # PNG en alta resolución (fondo blanco, sin márgenes sobrantes)
    fig.savefig(FIGURE_PATH, dpi=dpi, facecolor="white", bbox_inches="tight")

    # SVG: vectorial, se ve nítido a cualquier tamaño (PowerPoint y Google Slides lo aceptan)
    svg_path = FIGURE_PATH.with_suffix(".svg")
    fig.savefig(svg_path, bbox_inches="tight")

    print(f"Guardado gráfico en: {FIGURE_PATH} ({dpi} dpi) y {svg_path}")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, help="primer día del análisis (YYYY-MM-DD)")
    ap.add_argument("--end", type=date.fromisoformat, help="último día del análisis (YYYY-MM-DD)")
    ap.add_argument("--dpi", type=int, default=DPI, help=f"resolución del PNG (por defecto {DPI})")
    ap.add_argument("--show", action="store_true", help="abrir también la ventana del gráfico")
    args = ap.parse_args()

    if args.start and args.end and args.end < args.start:
        raise ValueError("--end no puede ser anterior a --start")

    aemet, redata = load_data()

    aemet = prepare_aemet(aemet)
    redata = prepare_redata(redata)

    combinado = merge_sources(aemet, redata)
    combinado = filter_period(combinado, args.start, args.end)

    print(f"Periodo analizado: {combinado['fecha'].min()} -> {combinado['fecha'].max()}")

    _, resumen = analyze(combinado)

    save_analysis(combinado)

    fig = plot_relationship(combinado, resumen)
    save_figure(fig, args.dpi)

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()