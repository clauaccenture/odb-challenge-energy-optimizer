"""01 - Ingesta ESIOS: catalogo e indicadores -> capa raw.

Uso desde la raiz del proyecto:

    python notebooks/01_ingesta_esios.py --catalog-only --no-s3
    python notebooks/01_ingesta_esios.py --no-s3
    python notebooks/01_ingesta_esios.py --force --start 2025-10-01 --end 2026-09-30

Las fechas e indicadores se leen de config/esios.yaml y config/modelo.yaml.
La descarga es reanudable: los bloques validos existentes se omiten.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.esios import load_esios_config
from src.ingesta.esios import (
    EsiosIngestionConfig,
    date_chunks,
    download_one,
    get_json,
    save_raw,
)
from src.project import find_project_root


BASE_URL = "https://api.esios.ree.es"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descarga indicadores de ESIOS.")
    parser.add_argument("--start", type=date.fromisoformat, help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--end", type=date.fromisoformat, help="Fecha final YYYY-MM-DD.")
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Actualiza el catalogo y calcula el plan sin descargar indicadores.",
    )
    parser.add_argument(
        "--no-s3",
        action="store_true",
        help="Guarda solo en local, aunque exista S3_BUCKET.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Vuelve a descargar bloques raw existentes.",
    )
    return parser.parse_args()


def as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def clean_description(value: str) -> tuple[str, str]:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = " ".join(html.unescape(text).split())
    for label in ("Publicación:", "Publicacion:"):
        description, separator, publication = text.partition(label)
        if separator:
            return description.strip(), publication.strip()
    return text.strip(), ""


def write_catalog_documents(
    project_root: Path,
    indicators: list[dict[str, Any]],
    downloaded_at: datetime,
    catalog_path: Path,
) -> Path:
    catalog_dir = project_root / "docs" / "fuentes" / "esios"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_csv = catalog_dir / "catalogo_indicadores_esios.csv"

    with catalog_csv.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["id", "name", "short_name", "description", "publication"],
        )
        writer.writeheader()
        for item in indicators:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            description, publication = clean_description(item.get("description", ""))
            writer.writerow(
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "short_name": item.get("short_name", ""),
                    "description": description,
                    "publication": publication,
                }
            )

    relative_catalog_path = catalog_path.relative_to(project_root)
    catalog_doc = catalog_dir / "catalogo_indicadores_esios.md"
    catalog_doc.write_text(
        "# Catalogo de indicadores ESIOS\n\n"
        f"Snapshot obtenido el {downloaded_at.date()} "
        f"({len(indicators)} indicadores).\n\n"
        "El [CSV completo](./catalogo_indicadores_esios.csv) incluye el ID, "
        "nombre, nombre corto, descripcion y publicacion indicada por ESIOS. "
        "La respuesta original del catalogo se conserva en "
        f"`{relative_catalog_path}`.\n",
        encoding="utf-8",
    )
    return catalog_csv


def load_catalog(
    project_root: Path,
    headers: dict[str, str],
    locale: str,
    retries: int,
    raw_dir: Path,
    upload_to_s3: bool,
    bucket: str | None,
) -> tuple[list[int], Path]:
    catalog_payload = get_json(
        f"{BASE_URL}/indicators",
        headers,
        params={"locale": locale},
        retries=retries,
    )
    indicators = catalog_payload.get("indicators")
    if not isinstance(indicators, list):
        raise ValueError("Respuesta del catalogo no valida: falta 'indicators'.")

    downloaded_at = datetime.now(timezone.utc)
    catalog_name = f"catalogo_indicadores_{downloaded_at:%Y%m%dT%H%M%SZ}.json"
    catalog_path = raw_dir / "catalogo" / catalog_name
    save_raw(
        catalog_payload,
        catalog_path,
        f"raw/esios/catalogo/{catalog_name}",
        upload_to_s3=upload_to_s3,
        bucket=bucket,
    )
    catalog_csv = write_catalog_documents(
        project_root, indicators, downloaded_at, catalog_path
    )

    catalog_ids = {
        int(item["id"])
        for item in indicators
        if isinstance(item, dict) and item.get("id") is not None
    }
    return sorted(catalog_ids), catalog_csv


def run() -> None:
    args = parse_args()
    project_root = find_project_root(PROJECT_ROOT)
    load_dotenv(project_root / ".env")

    config = load_esios_config(
        project_root / "config" / "esios.yaml",
        project_root / "config" / "modelo.yaml",
    )
    esios = config["esios"]
    ingestion = esios["ingestion"]
    model = config["model"]

    api_key = os.getenv("ESIOS_API_KEY")
    if not api_key:
        raise RuntimeError(f"Falta ESIOS_API_KEY en {project_root / '.env'}.")

    start = args.start or as_date(ingestion["start"])
    end = args.end or as_date(ingestion["end"])
    if end < start:
        raise ValueError("La fecha final debe ser igual o posterior a la inicial.")

    bucket = os.getenv("S3_BUCKET")
    upload_to_s3 = bool(bucket) and not args.no_s3
    raw_dir = project_root / "data" / "raw" / "esios"
    headers = {
        "Accept": "application/json; application/vnd.esios-api-v1+json",
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    selected_ids = [int(value) for value in esios["indicator_ids"]]
    catalog_ids, catalog_csv = load_catalog(
        project_root,
        headers,
        esios["locale"],
        ingestion["retries"],
        raw_dir,
        upload_to_s3,
        bucket,
    )
    unknown_ids = sorted(set(selected_ids) - set(catalog_ids))
    if unknown_ids:
        raise ValueError(f"IDs no encontrados en el catalogo ESIOS: {unknown_ids}")

    chunks = list(date_chunks(start, end, ingestion["chunk_days"]))
    tasks = [
        (indicator_id, chunk_start, chunk_end)
        for indicator_id in selected_ids
        for chunk_start, chunk_end in chunks
    ]
    print(f"Ventana de ingesta: {start} a {end}")
    print(f"Ventana objetivo: {model['target_start']} a {model['target_end']}")
    print(f"Indicadores seleccionados: {len(selected_ids)}")
    print(f"Peticiones estimadas: {len(tasks):,}")
    print(f"Catalogo CSV: {catalog_csv}")

    if args.catalog_only:
        return

    ingestion_config = EsiosIngestionConfig(
        raw_dir=raw_dir,
        base_url=BASE_URL,
        headers=headers,
        locale=esios["locale"],
        retries=ingestion["retries"],
        timeout=ingestion["timeout_seconds"],
        pause_seconds=ingestion["pause_seconds"],
        upload_to_s3=upload_to_s3,
        bucket=bucket,
        force=args.force or ingestion["force"],
    )
    downloaded = skipped = empty = 0
    failures: list[tuple[int, date, date, str | None]] = []
    with ThreadPoolExecutor(max_workers=ingestion["max_workers"]) as executor:
        futures = [
            executor.submit(download_one, task, ingestion_config) for task in tasks
        ]
        for future in as_completed(futures):
            status, indicator_id, chunk_start, chunk_end, n_values, error = future.result()
            if status == "skipped":
                skipped += 1
            elif status == "downloaded":
                downloaded += 1
                empty += int(n_values == 0)
                print(f"Indicador {indicator_id} | {chunk_start}..{chunk_end} | {n_values} valores")
            else:
                failures.append((indicator_id, chunk_start, chunk_end, error))
                print(f"ERROR indicador {indicator_id} | {chunk_start}..{chunk_end}: {error}")

    print(
        f"Resumen: descargados={downloaded}, ya existentes={skipped}, "
        f"bloques vacios={empty}, fallidos={len(failures)}"
    )
    if failures:
        failures_path = raw_dir / "fallos_ingesta.json"
        failures_path.write_text(
            json.dumps(
                [
                    {
                        "indicator_id": indicator_id,
                        "start": str(chunk_start),
                        "end": str(chunk_end),
                        "error": error,
                    }
                    for indicator_id, chunk_start, chunk_end, error in failures
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise RuntimeError(f"Hay bloques fallidos; detalle guardado en {failures_path}.")


if __name__ == "__main__":
    run()