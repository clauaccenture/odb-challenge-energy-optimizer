"""01 - Ingesta REData: precio del mercado diario -> capa raw (bronze).

Descarga el JSON tal cual lo devuelve la API, por trozos mensuales, y lo guarda
en data/raw/redata/ (cache local) y, si S3_BUCKET esta definido, en
s3://<bucket>/raw/redata/. No se modifica nada del JSON original.

Uso (desde la raiz del repo):
    python notebooks/01_ingesta_redata.py --start 2026-03-10 --end 2026-03-10 --preview --no-s3
    python notebooks/01_ingesta_redata.py --start 2025-10-01 --end 2026-09-30
"""
import argparse
import json
import os
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
BUCKET = os.getenv("S3_BUCKET")
RAW_DIR = Path("data/raw/redata")
SPOT_TITLE = "Precio mercado spot"  # la serie que nos interesa (id 600)


def month_chunks(start: date, end: date):
    """Parte [start, end] en trozos que no cruzan de mes."""
    cur = start
    while cur <= end:
        next_month = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(end, next_month - timedelta(days=1))
        cur = next_month


def fetch(start: date, end: date, retries: int = 4) -> dict:
    params = {
        "start_date": f"{start}T00:00",
        "end_date": f"{end}T23:59",
        "time_trunc": "hour",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  intento {attempt + 1}/{retries} fallido ({exc}); reintento en {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"No se pudo descargar {start}..{end}")


def save_local(payload: dict, start: date, end: date) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"precios_{start}_{end}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    # registro de procedencia (fuente, URL y fecha de descarga) para el README
    meta = {
        "file": path.name,
        "source": "Red Electrica - REData",
        "url": BASE_URL,
        "start": str(start),
        "end": str(end),
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with open(RAW_DIR / "manifest.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(meta) + "\n")
    return path


def upload_s3(path: Path) -> None:
    import boto3  # acceso por rol IAM de la EC2, sin claves en el codigo

    key = f"raw/redata/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")


def preview(payload: dict) -> None:
    """Comprobacion rapida: cuantos valores hay por dia (96 = cuartohorario)."""
    spot = next(
        s for s in payload["included"] if s["attributes"]["title"] == SPOT_TITLE
    )
    values = spot["attributes"]["values"]
    per_day = Counter(v["datetime"][:10] for v in values)
    print(f"  serie '{SPOT_TITLE}': {len(values)} valores")
    for day, n in sorted(per_day.items()):
        print(f"    {day}: {n} valores")
    print(f"  primer valor: {values[0]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--no-s3", action="store_true", help="solo cache local")
    args = ap.parse_args()

    for s, e in month_chunks(args.start, args.end):
        print(f"Descargando {s} -> {e}")
        payload = fetch(s, e)
        path = save_local(payload, s, e)
        print(f"  guardado en {path}")
        if args.preview:
            preview(payload)
        if BUCKET and not args.no_s3:
            upload_s3(path)
        time.sleep(1)  # cortesia con la API


if __name__ == "__main__":
    main()
