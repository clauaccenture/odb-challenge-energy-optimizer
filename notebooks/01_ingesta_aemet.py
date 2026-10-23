"""
01 - Ingesta AEMET: climatologías diarias -> capa raw.

Descarga los datos climatológicos diarios desde AEMET OpenData.

AEMET permite como máximo 15 días por petición, por lo que este
script divide automáticamente el rango solicitado en bloques
de máximo 15 días.

Los datos se guardan sin transformar en:
    data/raw/aemet/

Si S3_BUCKET está definido y no se utiliza --no-s3,
también se suben a:
    s3://<bucket>/raw/aemet/

Ejemplo local:
    python notebooks/01_ingesta_aemet.py \
        --start 2025-01-01 \
        --end 2025-12-31 \
        --no-s3

Ejemplo con S3:
    python notebooks/01_ingesta_aemet.py \
        --start 2025-01-01 \
        --end 2025-12-31

Actualización diaria desde el histórico raw local:
    python notebooks/01_ingesta_aemet.py --daily --end 2026-10-22
"""

import os
import json
import argparse

from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests
import boto3
from dotenv import load_dotenv


# --------------------------------------------------
# CONFIGURACIÓN INICIAL
# --------------------------------------------------

load_dotenv()

API_KEY = os.getenv("AEMET_API_KEY")
BUCKET = os.getenv("S3_BUCKET")

RAW_DIR = Path("data/raw/aemet")

BASE_URL = (
    "https://opendata.aemet.es/opendata/api/"
    "valores/climatologicos/diarios/datos/"
    "fechaini/{start}T00:00:00UTC/"
    "fechafin/{end}T23:59:59UTC/"
    "todasestaciones"
)


# --------------------------------------------------
# DIVIDIR PERIODO EN BLOQUES DE 15 DÍAS
# --------------------------------------------------

def chunks_15_days(start: date, end: date):
    """
    Divide el periodo solicitado en bloques
    de máximo 15 días.
    """

    current = start

    while current <= end:

        # +14 porque contando el día inicial
        # tenemos un máximo de 15 días
        chunk_end = min(
            current + timedelta(days=14),
            end
        )

        yield current, chunk_end

        # El siguiente bloque empieza
        # al día siguiente
        current = chunk_end + timedelta(days=1)


# --------------------------------------------------
# DESCARGA DE DATOS AEMET
# --------------------------------------------------

class NoDataAvailable(RuntimeError):
    """La API confirma que no hay datos para el periodo solicitado."""


def validate_records(datos, start: date, end: date) -> None:
    if not isinstance(datos, list) or not datos:
        raise ValueError("AEMET debe devolver una lista no vacía de registros.")
    for row in datos:
        if not isinstance(row, dict) or not isinstance(row.get("fecha"), str):
            raise ValueError("AEMET ha devuelto un registro sin fecha válida.")
        record_date = date.fromisoformat(row["fecha"])
        if not start <= record_date <= end:
            raise ValueError(f"AEMET ha devuelto una fecha fuera del rango: {record_date}")


def fetch(start: date, end: date):
    """
    Descarga los datos climatológicos de AEMET
    para un bloque de fechas.

    AEMET devuelve primero una respuesta con una URL
    en el campo 'datos'.

    Después se realiza una segunda petición a esa URL
    para obtener los registros meteorológicos reales.
    """

    if not API_KEY:
        raise ValueError(
            "No se ha encontrado AEMET_API_KEY "
            "en el archivo .env"
        )

    url = BASE_URL.format(
        start=start,
        end=end
    )

    headers = {
        "api_key": API_KEY,
        "accept": "application/json"
    }

    print(
        f"Solicitando datos AEMET: "
        f"{start} -> {end}"
    )

    # Primera petición
    response = requests.get(
        url,
        headers=headers,
        timeout=60
    )

    if response.status_code == 404:
        raise NoDataAvailable(f"AEMET sin datos para {start} -> {end}")
    response.raise_for_status()

    respuesta = response.json()
    if not isinstance(respuesta, dict):
        raise ValueError("Respuesta de control AEMET no válida.")
    if respuesta.get("estado") == 404:
        raise NoDataAvailable(f"AEMET sin datos para {start} -> {end}")
    if respuesta.get("estado", 200) != 200:
        raise RuntimeError(f"Estado AEMET inesperado: {respuesta.get('estado')}")

    # Comprobar que AEMET devuelve
    # correctamente la URL de descarga
    if "datos" not in respuesta:
        raise RuntimeError(
            "AEMET no ha devuelto la URL "
            f"de datos: {respuesta}"
        )

    url_datos = respuesta["datos"]

    # Segunda petición para obtener
    # los registros meteorológicos reales
    response_datos = requests.get(
        url_datos,
        timeout=60
    )

    response_datos.raise_for_status()

    datos = response_datos.json()
    if datos == []:
        raise NoDataAvailable(f"AEMET sin registros para {start} -> {end}")
    validate_records(datos, start, end)

    return datos


# --------------------------------------------------
# GUARDADO LOCAL RAW
# --------------------------------------------------

def save_local(
    datos,
    start: date,
    end: date
) -> Path:
    """
    Guarda la respuesta original de AEMET
    en la capa raw local.
    """

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    archivo = RAW_DIR / (
        f"aemet_{start}_{end}.json"
    )

    with open(
        archivo,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            datos,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Datos guardados correctamente en: "
        f"{archivo}"
    )

    print(
        f"Número de registros descargados: "
        f"{len(datos)}"
    )

    return archivo


# --------------------------------------------------
# MANIFEST
# --------------------------------------------------

def save_manifest(
    archivo: Path,
    start: date,
    end: date,
    records: int
) -> Path:
    """
    Registra información sobre la procedencia
    y cobertura de cada descarga.
    """

    manifest_path = (
        RAW_DIR / "manifest.jsonl"
    )

    manifest = {
        "file": archivo.name,
        "source": "AEMET OpenData",
        "start": str(start),
        "end": str(end),
        "downloaded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "records": records
    }

    with open(
        manifest_path,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                manifest,
                ensure_ascii=False
            )
            + "\n"
        )

    print(
        f"Manifest actualizado en: "
        f"{manifest_path}"
    )

    return manifest_path


# --------------------------------------------------
# SUBIDA A S3
# --------------------------------------------------

def upload_s3(
    path: Path
) -> None:
    """
    Sube el archivo raw a S3.

    En EC2, boto3 puede utilizar el IAM Role
    asociado a la instancia.
    """

    if not BUCKET:
        raise ValueError(
            "S3_BUCKET no está definido "
            "en el archivo .env"
        )

    key = (
        f"raw/aemet/{path.name}"
    )

    boto3.client(
        "s3"
    ).upload_file(
        str(path),
        BUCKET,
        key
    )

    print(
        f"Subido a "
        f"s3://{BUCKET}/{key}"
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def save_ingestion_scope(status: str, files: list[str]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "last_ingestion.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "status": status,
        "files": files,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    temporary.replace(path)


def ingest_daily(target: date, no_s3: bool) -> None:
    save_ingestion_scope("running", [])
    latest = None
    latest_path = None
    for path in sorted(RAW_DIR.glob("aemet_*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        validate_records(records, date.min, date.max)
        eligible = [date.fromisoformat(row["fecha"]) for row in records
                    if date.fromisoformat(row["fecha"]) <= target]
        if eligible and (latest is None or max(eligible) > latest):
            latest = max(eligible)
            latest_path = path

    if latest is None or latest_path is None:
        raise ValueError("No hay histórico AEMET local hasta la fecha objetivo. "
                         "Ejecuta primero una carga con --start y --end.")
    if not no_s3 and not BUCKET:
        raise ValueError("S3_BUCKET no está definido.")

    print(f"Fecha objetivo AEMET: {target} | última fecha raw local: {latest}")
    # Recupera una subida fallida tras guardar el último raw en una ejecución anterior.
    if not no_s3:
        upload_s3(latest_path)

    pending = []
    current = target
    while current > latest:
        try:
            records = fetch(current, current)
        except NoDataAvailable as error:
            print(f"SIN DATOS PUBLICADOS: {error}")
        else:
            validate_records(records, current, current)
            pending.append((current, records))
        current -= timedelta(days=1)

    # Publicar de antiguo a reciente permite recuperar la última subida si falla S3.
    for day, records in reversed(pending):
        path = save_local(records, day, day)
        save_manifest(path, day, day, len(records))
        if not no_s3:
            upload_s3(path)

    save_ingestion_scope("completed", [
        f"aemet_{day}_{day}.json" for day, _ in reversed(pending)
    ])
    if pending:
        print(f"AEMET: {len(pending)} días nuevos guardados. "
              f"Última fecha disponible: {pending[0][0]}")
    else:
        print(f"AEMET SIN NOVEDADES. Se conserva la fecha {latest}.")


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Ingesta de datos de "
            "AEMET OpenData"
        )
    )

    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        help=(
            "Fecha inicial en formato "
            "YYYY-MM-DD"
        )
    )

    parser.add_argument(
        "--end",
        required=True,
        type=date.fromisoformat,
        help=(
            "Fecha final en formato "
            "YYYY-MM-DD"
        )
    )

    parser.add_argument(
        "--daily",
        action="store_true",
        help="Buscar días publicados desde --end hacia atrás hasta el histórico raw local."
    )

    parser.add_argument(
        "--no-s3",
        action="store_true",
        help=(
            "Guardar únicamente en local"
        )
    )

    args = parser.parse_args()

    if args.daily:
        if args.start is not None:
            parser.error("--daily no admite --start.")
        ingest_daily(args.end, args.no_s3)
        return
    if args.start is None:
        parser.error("--start es obligatorio salvo con --daily.")

    # Comprobar rango
    if args.end < args.start:
        raise ValueError(
            "--end no puede ser "
            "anterior a --start"
        )

    total_bloques = 0
    total_registros = 0
    ingested_files = []
    save_ingestion_scope("running", [])

    # Dividir automáticamente
    # el periodo en bloques de 15 días
    for chunk_start, chunk_end in chunks_15_days(
        args.start,
        args.end
    ):

        print("\n" + "=" * 60)

        print(
            f"Bloque AEMET: "
            f"{chunk_start} -> {chunk_end}"
        )

        print("=" * 60)

        # 1. Descargar bloque
        datos = fetch(
            chunk_start,
            chunk_end
        )

        # 2. Guardar raw local
        archivo = save_local(
            datos,
            chunk_start,
            chunk_end
        )

        # 3. Actualizar manifest
        save_manifest(
            archivo,
            chunk_start,
            chunk_end,
            len(datos)
        )

        # 4. Subir a S3 si corresponde
        if not args.no_s3:

            upload_s3(
                archivo
            )

        else:

            print(
                "Subida a S3 desactivada "
                "(--no-s3)."
            )

        total_bloques += 1
        total_registros += len(datos)
        ingested_files.append(archivo.name)

    save_ingestion_scope("completed", ingested_files)
    # Resumen
    print("\n" + "=" * 60)
    print("INGESTA AEMET FINALIZADA")
    print("=" * 60)

    print(
        f"Bloques descargados: "
        f"{total_bloques}"
    )

    print(
        f"Registros descargados: "
        f"{total_registros}"
    )

    print(
        f"Directorio raw: "
        f"{RAW_DIR}"
    )


if __name__ == "__main__":
    main()