"""02 - Calidad: capa raw (bronze) -> capa processed (silver).

Entrada : data/raw/redata/precios_*.json  (REData, cuartohorario, tal cual de la API)
Salida  : un JSON con la estructura de bronze, pero:
            - de una hora (media de los 4 cuartos de hora), no de 15 min
            - solo con el precio: se descartan id, type, color, description,
              percentage, magnitude, composite... y la serie PVPC

Orden de la limpieza:
    1. aplana la serie "Precio mercado spot" y pasa las fechas a UTC
    2. elimina precios nulos
    3. elimina cuartos de hora duplicados (se queda con el ultimo leido)
    4. trunca a 0 los precios negativos (ANTES de hacer la media)
    5. media de los 4 cuartos de cada hora

Guarda:
    data/processed/precios_horarios.json   (precio por hora)
    data/processed/calidad_precios.json    (informe corto)
y, si S3_BUCKET esta definido, los sube a s3://<bucket>/processed/.

Uso (desde la raiz del repo):
    python notebooks/02_calidad.py
    python notebooks/02_calidad.py --no-s3
"""
import argparse
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BUCKET = os.getenv("S3_BUCKET")
RAW_DIR = Path("data/raw/redata")
OUT_DIR = Path("data/processed")
SPOT_TITLE = "Precio mercado spot"
TZ_LOCAL = "Europe/Madrid"


def load_spot(raw_dir: Path) -> pd.DataFrame:
    """Aplana todos los JSON raw en una tabla (datetime_utc, price)."""
    rows = []
    files = sorted(raw_dir.glob("precios_*.json"))
    if not files:
        raise FileNotFoundError(f"No hay JSON en {raw_dir}. Ejecuta antes 01_ingesta_redata.py")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        spot = next(
            (s for s in payload.get("included", [])
             if s["attributes"]["title"] == SPOT_TITLE),
            None,
        )
        if spot is None:
            print(f"  AVISO: {path.name} no contiene la serie '{SPOT_TITLE}'")
            continue
        for v in spot["attributes"]["values"]:
            rows.append({"datetime_raw": v["datetime"], "price": v["value"]})
    df = pd.DataFrame(rows)
    # el texto lleva el desfase (+01:00 / +02:00): utc=True lo normaliza a UTC
    df["datetime_utc"] = pd.to_datetime(df["datetime_raw"], utc=True)
    return df.drop(columns="datetime_raw")


def hours_per_day(hourly: pd.DataFrame) -> dict:
    """Cuantas horas tiene cada dia local: 24 normal, 23 (primavera) o 25 (otono)."""
    local_day = hourly["hour_utc"].dt.tz_convert(TZ_LOCAL).dt.date
    per_day = hourly.groupby(local_day).size()
    return {
        "days_total": int(len(per_day)),
        "days_with_23_hours": [str(d) for d, n in per_day.items() if n == 23],
        "days_with_24_hours": int((per_day == 24).sum()),
        "days_with_25_hours": [str(d) for d, n in per_day.items() if n == 25],
        # dias con otro numero de horas (datos incompletos, p. ej. el ultimo dia)
        "days_with_other_hours": {str(d): int(n) for d, n in per_day.items() if n not in (23, 24, 25)},
    }


def clean_and_aggregate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Nulos, duplicados, negativos -> 0 y media horaria. Devuelve (horas, informe)."""
    report = {"rows_read": int(len(df))}

    report["null_prices_found"] = int(df["price"].isna().sum())
    rows_before = len(df)
    df = df.dropna(subset=["price"])
    report["null_prices_removed"] = rows_before - len(df)  # filas eliminadas por nulo

    # los trozos mensuales pueden solaparse: nos quedamos con el ultimo leido
    dup = df.duplicated(subset="datetime_utc", keep="last")
    report["duplicate_quarters_removed"] = int(dup.sum())
    df = df[~dup].sort_values("datetime_utc")

    # negativos -> 0 en cada cuarto de hora, ANTES de promediar
    report["negative_prices_replaced_by_0"] = int((df["price"] < 0).sum())
    df = df.assign(price=df["price"].clip(lower=0))

    # hora UTC a la que pertenece cada cuarto (los desfases son horas enteras)
    df = df.assign(hour_utc=df["datetime_utc"].dt.floor("h"))
    hourly = (
        df.groupby("hour_utc")
        .agg(price=("price", "mean"), n_quarters=("price", "size"))
        .reset_index()
    )
    report["hours_output"] = int(len(hourly))
    report.update(hours_per_day(hourly))
    return hourly, report


def to_bronze_like(hourly: pd.DataFrame) -> dict:
    """Mismo esquema que bronze, solo con titulo y valores (value, datetime)."""
    values = [
        {
            "value": round(float(p), 4),
            # hora local con su desfase, como en bronze (distingue las dos 02:00 de otono)
            "datetime": t.tz_convert(TZ_LOCAL).isoformat(timespec="milliseconds"),
        }
        for t, p in zip(hourly["hour_utc"], hourly["price"])
    ]
    return {"included": [{"attributes": {"title": SPOT_TITLE, "values": values}}]}


def upload_s3(path: Path) -> None:
    import boto3  # acceso por rol IAM de la EC2, sin claves en el codigo

    key = f"processed/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-s3", action="store_true", help="solo local")
    args = ap.parse_args()

    print("Leyendo JSON raw...")
    quarters = load_spot(RAW_DIR)
    hourly, report = clean_and_aggregate(quarters)

    incompletas = int((hourly["n_quarters"] != 4).sum())
    if incompletas:
        print(f"  AVISO: {incompletas} horas no tienen 4 cuartos de hora")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data_path = OUT_DIR / "precios_horarios.json"
    rep_path = OUT_DIR / "calidad_precios.json"
    data_path.write_text(json.dumps(to_bronze_like(hourly), ensure_ascii=False), encoding="utf-8")
    rep_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Guardado {data_path}")
    if BUCKET and not args.no_s3:
        upload_s3(data_path)
        upload_s3(rep_path)


if __name__ == "__main__":
    main()