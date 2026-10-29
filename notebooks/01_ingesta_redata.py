"""01 - Ingesta REData: precio del mercado diario -> capa raw (bronze).
 
Descarga el JSON tal cual lo devuelve la API, UN FICHERO POR DIA, y lo guarda
en data/raw/redata/ y, solo con --s3 y S3_BUCKET definido, en
s3://<bucket>/raw/redata/. No se modifica nada del JSON original.
 
Para el proyecto: 2025-10-01 -> 2026-09-30 = 365 ficheros
(precios_2025-10-01_2025-10-01.json ... precios_2026-09-30_2026-09-30.json).
 
Es reanudable: si un dia ya existe en data/raw/redata/ no se vuelve a descargar
Usa --force para descargar de nuevo.
Si un dia falla tras los reintentos, se anota y se continua con el resto; al final
se listan los dias fallidos y el script termina con error para poder relanzarlo.
Una respuesta válida sin precios spot se informa como ausencia de novedades,
sin guardar un raw vacío ni hacer fallar la ejecución.
 
Uso (desde la raiz del repo):
    python notebooks/01_ingesta_redata.py --start 2026-03-10 --end 2026-03-10 --preview --no-s3
    python notebooks/01_ingesta_redata.py --start 2025-10-01 --end 2026-09-30
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
 
import requests
from dotenv import load_dotenv
 
load_dotenv()
 
BASE_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
BUCKET = os.getenv("S3_BUCKET")
PROJECT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_DIR / "data" / "raw" / "redata"
SPOT_TITLE = "Precio mercado spot"  # la serie que nos interesa (id 600)
VALORES_ESPERADOS = (92, 96, 100)  # cuartos de hora: dia de 23 h, normal (24 h) y de 25 h
 
 
def day_chunks(start: date, end: date):
    """Un trozo por dia: (dia, dia) para cada dia de [start, end]."""
    cur = start
    while cur <= end:
        yield cur, cur
        cur += timedelta(days=1)
 
 
def raw_path(start: date, end: date) -> Path:
    return RAW_DIR / f"precios_{start}_{end}.json"
 
 
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
 
 
def spot_values(payload: dict) -> list | None:
    """Valores de la serie 'Precio mercado spot', o None si no esta en la respuesta."""
    if not isinstance(payload, dict) or not isinstance(payload.get("included"), list):
        raise ValueError("Respuesta REData no válida: falta la lista 'included'.")
    spot = next(
        (s for s in payload.get("included", []) if s["attributes"]["title"] == SPOT_TITLE),
        None,
    )
    if spot is None:
        return None
    values = spot["attributes"]["values"]
    if not isinstance(values, list):
        raise ValueError("Respuesta REData no válida: 'values' debe ser una lista.")
    return values
 
 
def save_local(payload: dict, start: date, end: date) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = raw_path(start, end)
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
    values = spot_values(payload) or []
    per_day = Counter(v["datetime"][:10] for v in values)
    print(f"  serie '{SPOT_TITLE}': {len(values)} valores")
    for day, n in sorted(per_day.items()):
        print(f"    {day}: {n} valores")
    if values:
        print(f"  primer valor: {values[0]}")
 
 
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument("--preview", action="store_true")
    storage = ap.add_mutually_exclusive_group()
    storage.add_argument("--no-s3", dest="no_s3", action="store_true", help="solo local (por defecto)")
    storage.add_argument("--s3", dest="no_s3", action="store_false", help="subir tambien a S3 (requiere S3_BUCKET)")
    ap.set_defaults(no_s3=True)
    ap.add_argument("--force", action="store_true", help="descargar aunque el dia ya exista")
    args = ap.parse_args()
    if args.end < args.start:
        ap.error("--end no puede ser anterior a --start.")
    if not args.no_s3 and not BUCKET:
        ap.error("--s3 requiere S3_BUCKET.")
 
    subir = bool(BUCKET) and not args.no_s3
    descargados, omitidos, fallidos, avisos = 0, 0, [], []
    sin_datos = []
 
    for s, e in day_chunks(args.start, args.end):
        path = raw_path(s, e)
 
        if path.exists() and not args.force:
            print(f"{s}: ya existe, se omite")
            omitidos += 1
            if subir:
                upload_s3(path)  # por si no se llego a subir en una ejecucion anterior
            continue
 
        print(f"Descargando {s}")
        try:
            payload = fetch(s, e)
        except RuntimeError as exc:
            print(f"  ERROR: {exc}")
            fallidos.append(str(s))
            continue
 
        values = spot_values(payload)
        if not values:
            print(f"  REDATA SIN DATOS PUBLICADOS para {s}: no hay precios spot nuevos que ingestar.")
            sin_datos.append(str(s))
            continue
        if len(values) not in VALORES_ESPERADOS:
            print(f"  AVISO: {len(values)} valores (esperados {VALORES_ESPERADOS})")
            avisos.append(f"{s}: {len(values)} valores")
 
        path = save_local(payload, s, e)
        descargados += 1
        print(f"  guardado en {path}")
        if args.preview:
            preview(payload)
        if subir:
            upload_s3(path)
        time.sleep(1)  # cortesia con la API
 
    total = (args.end - args.start).days + 1
    print(f"\nResumen: {total} dias | descargados: {descargados} | "
          f"ya existian: {omitidos} | sin datos publicados: {len(sin_datos)} | fallidos: {len(fallidos)}")
    if avisos:
        print("Dias con un numero de valores inesperado:")
        for a in avisos:
            print(f"  {a}")
    if fallidos:
        print("Dias fallidos (vuelve a lanzar el mismo comando para reintentarlos):")
        print("  " + ", ".join(fallidos))
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
 