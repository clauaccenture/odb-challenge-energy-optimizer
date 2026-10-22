"""
04 - Análisis descriptivo AEMET + REData

Objetivo:
Cruzar la temperatura media diaria de AEMET con el precio medio
diario de REData para estudiar descriptivamente su relación.

Este análisis NO implica causalidad: la temperatura va muy ligada a la
estación del año, y otras variables (renovables, gas, demanda...) también
mueven el precio.

Salida:
    data/outputs/analisis_temperatura_precio.parquet   (datos cruzados por día)
    data/outputs/grafico_temperatura_precio.png        (gráfico para el cliente)

Uso (desde la raíz del repo):
    python notebooks/04_analisis_aemet_redata.py
    python notebooks/04_analisis_aemet_redata.py --show   # además abre la ventana
"""

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# --------------------------------------------------
# RUTAS
# --------------------------------------------------

AEMET_PATH = Path("data/outputs/gold_temperatura_diaria.parquet")
REDATA_PATH = Path("data/outputs/gold_plan_horario.parquet")
OUTPUT_PATH = Path("data/outputs/analisis_temperatura_precio.parquet")
FIGURE_PATH = Path("data/outputs/grafico_temperatura_precio.png")


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
    "Primavera": "#1cb764",
    "Verano": "#e6f509",
    "Otoño": "#e30707",
}

# Tramos de temperatura para el gráfico de barras y la tabla resumen
TRAMOS_BORDES = [float("-inf"), 10, 15, 20, 25, float("inf")]
TRAMOS_NOMBRES = ["< 10 °C", "10-15 °C", "15-20 °C", "20-25 °C", "> 25 °C"]

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

    anio_min = pd.to_datetime(df["fecha"]).dt.year.min()
    anio_max = pd.to_datetime(df["fecha"]).dt.year.max()
    periodo = str(anio_min) if anio_min == anio_max else f"{anio_min}-{anio_max}"

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(14, 5.8), gridspec_kw={"width_ratios": [3, 2]}
    )

    # ---------- Panel izquierdo: un punto por día, coloreado por estación ----------
    for estacion, color in COLOR_ESTACION.items():
        d = df[df["estacion"] == estacion]
        ax1.scatter(
            d["tmed"], d["precio_medio_eur_mwh"],
            s=28, alpha=0.7, color=color, label=f"{estacion} ({len(d)} días)",
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
    ax1.set_title("Cada punto es un día", fontsize=11, loc="left")
    ax1.legend(frameon=False, fontsize=9)
    ax1.grid(alpha=0.25)

    # ---------- Panel derecho: precio medio por tramo de temperatura ----------
    etiquetas = [f"{t}\n({int(n)} días)" for t, n in zip(resumen.index, resumen["dias"])]
    barras = ax2.bar(
        etiquetas, resumen["precio_medio"],
        color="#4a5568", alpha=0.85,
    )
    for barra, valor in zip(barras, resumen["precio_medio"]):
        if pd.notna(valor):
            ax2.text(
                barra.get_x() + barra.get_width() / 2, valor + 1.5,
                f"{valor:.0f}", ha="center", va="bottom", fontsize=10,
            )
    ax2.set_ylabel("Precio medio (EUR/MWh)")
    ax2.set_title("Precio medio según la temperatura", fontsize=11, loc="left")
    ax2.grid(axis="y", alpha=0.25)
    ax2.tick_params(axis="x", labelsize=9)

    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle(
        f"Temperatura media diaria y precio de la electricidad ({periodo})",
        fontsize=14, fontweight="bold", x=0.01, ha="left",
    )
    fig.text(
        0.01, 0.01,
        "Fuentes: AEMET (temperatura media nacional) y REData (precio spot medio diario). "
        "Relación descriptiva, no causal: la temperatura coincide con la estación del año.",
        fontsize=8.5, color="#4a5568", ha="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))

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


def save_figure(fig):

    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_PATH, dpi=150)

    print(f"Guardado gráfico en: {FIGURE_PATH}")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="abrir también la ventana del gráfico")
    args = ap.parse_args()

    aemet, redata = load_data()

    aemet = prepare_aemet(aemet)
    redata = prepare_redata(redata)

    combinado = merge_sources(aemet, redata)

    _, resumen = analyze(combinado)

    save_analysis(combinado)

    fig = plot_relationship(combinado, resumen)
    save_figure(fig)

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()