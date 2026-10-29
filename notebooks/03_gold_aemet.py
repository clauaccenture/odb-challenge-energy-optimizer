"""03 - Gold: resumen diario de temperaturas a nivel nacional (AEMET).

Entrada : data/processed/aemet/aemet_diario.json  (silver: una fila por estacion y dia)
Salida  : una tabla en formato Parquet en data/outputs/
            gold_temperatura_diaria.parquet   una fila por dia
          y, solo con --s3 y S3_BUCKET definido, se sube a s3://<bucket>/outputs/aemet/.
          Tipos: fecha es una fecha (date), las temperaturas son decimales (float) y las
          horas son texto "HH:MM". Los datos que faltan son nulos, nunca 0.

Para cada dia, la tabla guarda justo lo que enseña el front end:
    fecha
    tmed                                media nacional de la tmed (ver nota 1)
    tmin, localidad_tmin,
      provincia_tmin, hora_tmin         la tmin mas baja de TODAS las estaciones del pais,
                                        con su localidad, su provincia y su hora
    tmax, localidad_tmax,
      provincia_tmax, hora_tmax         lo mismo para la tmax mas alta

Esta tabla no se cruza con los precios de REData: el front end consulta cada fuente
por separado.
Si el informe Silver confirma una ingesta sin datos publicados ni histórico,
Gold conserva el contrato de columnas con cero filas y emite un aviso explícito.

Notas:
  1. tmed nacional = media de las medias provinciales: primero se promedian las estaciones de
     cada provincia y despues las provincias entre si. Asi una provincia con muchas estaciones
     (p. ej. Santa Cruz de Tenerife) no pesa mas que una con pocas.
  2. tmin/tmax son valores reales de una estacion, y la hora es la de esa misma medicion.
  3. Para no enseñar horas vacias, el extremo se elige entre las estaciones que tienen
     temperatura Y hora valida. Si la estacion mas extrema del pais no tiene hora, se usa la
     siguiente que si la tenga (el script avisa de cuantos dias pasa).
  4. En caso de empate en el extremo se elige la primera por provincia y localidad en orden
     alfabetico (resultado reproducible).
  5. La hora se guarda tal como viene de AEMET, sin convertir de zona horaria.

Uso (desde la raiz del repo):
    python notebooks/03_gold_aemet.py
    python notebooks/03_gold_aemet.py --no-s3
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BUCKET = os.getenv("S3_BUCKET")
PROJECT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
SILVER = DATA_DIR / "processed" / "aemet" / "aemet_diario.json"
OUT_DIR = DATA_DIR / "outputs" / "aemet"
OUT_NAME = "gold_temperatura_diaria.parquet"
DECIMALS = 1  # decimales con los que se enseña la temperatura

COLUMNAS = [
    "fecha", "tmed",
    "tmin", "localidad_tmin", "provincia_tmin", "hora_tmin",
    "tmax", "localidad_tmax", "provincia_tmax", "hora_tmax",
]


def load_silver(path: Path) -> pd.DataFrame:
    """Lee el JSON silver (una fila por estacion y dia) con las temperaturas como numeros."""
    records = json.loads(path.read_text(encoding="utf-8"))
    if records == []:
        return pd.DataFrame(columns=[
            "fecha", "provincia", "localidad", "tmax", "tmin", "tmed", "hora_tmax", "hora_tmin",
        ])
    df = pd.DataFrame(records)
    for col in ["tmax", "tmin", "tmed"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def extremo(g: pd.DataFrame, col: str, hora_col: str, mas_alta: bool) -> dict:
    """Estacion con la temperatura mas alta/baja del dia: valor, localidad, provincia y hora.

    Se prefieren las estaciones con hora valida. 'saltada' indica que la estacion mas extrema
    del pais no tenia hora y se ha usado la siguiente. Si ese dia ninguna estacion tiene dato,
    todo es None.
    """
    vacio = {"valor": None, "localidad": None, "provincia": None, "hora": None, "saltada": False}
    d = g.dropna(subset=[col])
    if d.empty:
        return vacio
    d = d.sort_values([col, "provincia", "localidad"], ascending=[not mas_alta, True, True])
    absoluta = d.iloc[0]  # la mas extrema, tenga o no hora
    con_hora = d.dropna(subset=[hora_col])
    f = con_hora.iloc[0] if not con_hora.empty else absoluta
    return {
        "valor": round(float(f[col]), DECIMALS),
        "localidad": None if pd.isna(f["localidad"]) else f["localidad"],
        "provincia": f["provincia"],
        "hora": None if pd.isna(f[hora_col]) else f[hora_col],
        "saltada": f.name != absoluta.name,
    }


def tmed_nacional(g: pd.DataFrame):
    """Media de las medias provinciales (cada provincia pesa igual)."""
    m = g.groupby("provincia")["tmed"].mean().mean()
    return None if pd.isna(m) else round(float(m), DECIMALS)


def build_gold(silver: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    """Una fila por fecha. Devuelve (tabla, provincias_con_dato_por_dia, dias_con_extremo_saltado)."""
    rows, n_prov, saltados = [], {}, {"tmin": [], "tmax": []}
    for fecha, g in silver.groupby("fecha", sort=True):
        mn = extremo(g, "tmin", "hora_tmin", mas_alta=False)
        mx = extremo(g, "tmax", "hora_tmax", mas_alta=True)
        if mn["saltada"]:
            saltados["tmin"].append(str(fecha))
        if mx["saltada"]:
            saltados["tmax"].append(str(fecha))
        rows.append(
            {
                "fecha": fecha,
                "tmed": tmed_nacional(g),
                "tmin": mn["valor"],
                "localidad_tmin": mn["localidad"],
                "provincia_tmin": mn["provincia"],
                "hora_tmin": mn["hora"],
                "tmax": mx["valor"],
                "localidad_tmax": mx["localidad"],
                "provincia_tmax": mx["provincia"],
                "hora_tmax": mx["hora"],
            }
        )
        n_prov[str(fecha)] = int(g["provincia"].nunique())

    gold = pd.DataFrame(rows, columns=COLUMNAS)
    # tipos explicitos: fecha como date, temperaturas float, el resto texto (None -> nulo)
    gold["fecha"] = pd.to_datetime(gold["fecha"]).dt.date
    for col in ["tmed", "tmin", "tmax"]:
        gold[col] = gold[col].astype("float64")
    return gold, n_prov, saltados


def upload_s3(path: Path) -> None:
    import boto3  # acceso por rol IAM de la EC2, sin claves en el codigo

    key = f"outputs/aemet/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")


def main() -> None:
    ap = argparse.ArgumentParser()
    storage = ap.add_mutually_exclusive_group()
    storage.add_argument("--no-s3", dest="no_s3", action="store_true", help="solo local (por defecto)")
    storage.add_argument("--s3", dest="no_s3", action="store_false", help="subir tambien a S3 (requiere S3_BUCKET)")
    ap.set_defaults(no_s3=True)
    args = ap.parse_args()
    if not args.no_s3 and not BUCKET:
        ap.error("--s3 requiere S3_BUCKET.")

    if not SILVER.exists():
        raise FileNotFoundError(f"No existe {SILVER}. Ejecuta antes 02_calidad_aemet.py")
    gold, n_prov, saltados = build_gold(load_silver(SILVER))

    report_path = SILVER.parent / "calidad_aemet.json"
    if not report_path.exists():
        raise FileNotFoundError(f"No existe {report_path}. Ejecuta antes 02_calidad_aemet.py")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if gold.empty:
        if not (report.get("scope") == "last_ingestion" and report.get("ingested_files") == []
                and report.get("rows_read") == 0 and report.get("rows_output") == 0):
            raise ValueError("Silver AEMET vacío sin una ingesta completada sin datos publicados.")
        print("AEMET SIN DATOS: se genera Gold vacío. Los resultados energéticos siguen disponibles.")
    if report.get("scope") == "last_ingestion":
        dates = report["ingested_dates"]
        if not isinstance(dates, list) or any(not isinstance(day, str) for day in dates):
            raise ValueError("Fechas de última ingesta no válidas en el informe de calidad.")
        warning_dates = set(dates)
        print(f"Avisos Gold AEMET de la última ingesta: {len(warning_dates)} días.")
    else:
        warning_dates = set(n_prov)
        print("Avisos Gold AEMET del histórico completo.")

    # avisos (no se guardan en la tabla)
    max_prov = max(n_prov.values(), default=0)
    incompletos = [f for f, n in n_prov.items() if f in warning_dates and n < max_prov]
    if incompletos:
        print(f"  AVISO: {len(incompletos)} dias con menos de {max_prov} provincias: {incompletos}")
    for var, dias in saltados.items():
        dias = [day for day in dias if day in warning_dates]
        if dias:
            print(f"  AVISO: {len(dias)} dias en los que la {var} mas extrema no tenia hora y se uso "
                  f"la siguiente estacion con hora: {dias}")
    scoped = gold.loc[gold["fecha"].astype(str).isin(warning_dates)]
    sin_hora = int((scoped["hora_tmin"].isna() | scoped["hora_tmax"].isna()).sum())
    if sin_hora:
        print(f"  AVISO: {sin_hora} dias sin hora de tmin o de tmax (nulo en la tabla)")
    missing = sorted(warning_dates - set(n_prov))
    if missing:
        print(f"  AVISO: días ingestados sin temperaturas válidas en Gold: {missing}")
    if not warning_dates:
        print("GOLD AEMET SIN NOVEDADES: sin días nuevos que evaluar.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / OUT_NAME
    gold.to_parquet(out_path, index=False)

    print(f"Dias: {len(gold)} | {gold['fecha'].min()} -> {gold['fecha'].max()}")
    print(f"Guardado {out_path}")
    if BUCKET and not args.no_s3:
        upload_s3(out_path)


if __name__ == "__main__":
    main()