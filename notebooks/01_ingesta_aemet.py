"""
01 - Ingesta AEMET: climatologías diarias -> capa raw.

Descarga los datos climatológicos diarios desde AEMET OpenData,
guarda el JSON original en local y, si S3_BUCKET está definido,
lo sube a S3.

Ejemplos:

    # Ejecutar solo en local
    python notebooks/02_ingesta_aemet.py \
        --start 2025-01-01 \
        --end 2025-01-05 \
        --no-s3

    # Ejecutar y subir a S3
    python notebooks/02_ingesta_aemet.py \
        --start 2025-01-01 \
        --end 2025-01-05
"""

import os
import json
import argparse

from datetime import date, datetime, timezone
from pathlib import Path

import requests
import boto3
from dotenv import load_dotenv


#Configuración inicial
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


#Descarga datos AEMET
def fetch(start: date, end: date):
    """
    Descarga los datos climatológicos de AEMET.

    AEMET devuelve primero una respuesta con una URL en el campo
    'datos'. Después se hace una segunda petición a esa URL para
    obtener los registros meteorológicos.
    """

    if not API_KEY:
        raise ValueError(
            "No se ha encontrado AEMET_API_KEY en el archivo .env"
        )

    url = BASE_URL.format(
        start=start,
        end=end
    )

    headers = {
        "api_key": API_KEY,
        "accept": "application/json"
    }

    print(f"Solicitando datos AEMET: {start} -> {end}")

    # Primera petición
    response = requests.get(
        url,
        headers=headers,
        timeout=60
    )

    response.raise_for_status()

    respuesta = response.json()

    # Comprobar que AEMET ha proporcionado la URL de datos
    if "datos" not in respuesta:
        raise RuntimeError(
            f"AEMET no ha devuelto la URL de datos: {respuesta}"
        )

    url_datos = respuesta["datos"]

    # Segunda petición: datos meteorológicos reales
    response_datos = requests.get(
        url_datos,
        timeout=60
    )

    response_datos.raise_for_status()

    datos = response_datos.json()

    return datos


#Guardado local de los datos raw
def save_local(datos, start: date, end: date) -> Path:
    """
    Guarda la respuesta original de AEMET en la capa raw local.
    """

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    archivo = RAW_DIR / f"aemet_{start}_{end}.json"

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
        f"Datos guardados correctamente en: {archivo}"
    )

    print(
        f"Número de registros descargados: {len(datos)}"
    )

    return archivo


#Registro de la procedencia de cada descarga (manifest)
def save_manifest(
    archivo: Path,
    start: date,
    end: date,
    records: int
) -> Path:
    """
    Registra información sobre la procedencia de cada descarga.
    """

    manifest_path = RAW_DIR / "manifest.jsonl"

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
        f"Manifest actualizado en: {manifest_path}"
    )

    return manifest_path


#Subida de los datos raw a S3
def upload_s3(path):
    key = f"raw/aemet/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")


def main():

    parser = argparse.ArgumentParser(
        description="Ingesta de datos de AEMET OpenData"
    )

    parser.add_argument(
        "--start",
        required=True,
        type=date.fromisoformat,
        help="Fecha inicial en formato YYYY-MM-DD"
    )

    parser.add_argument(
        "--end",
        required=True,
        type=date.fromisoformat,
        help="Fecha final en formato YYYY-MM-DD"
    )

    parser.add_argument(
        "--no-s3",
        action="store_true",
        help="Guardar únicamente en local"
    )

    args = parser.parse_args()

    # Validación sencilla
    if args.end < args.start:
        raise ValueError(
            "--end no puede ser anterior a --start"
        )

    # 1. Descargar AEMET
    datos = fetch(
        args.start,
        args.end
    )

    # 2. Guardar raw local
    archivo = save_local(
        datos,
        args.start,
        args.end
    )

    # 3. Actualizar manifest
    save_manifest(
        archivo,
        args.start,
        args.end,
        len(datos)
    )

    # 4. Subir a S3
    if not args.no_s3:
        upload_s3(archivo)
    else:
        print(
            "Subida a S3 desactivada (--no-s3)."
        )


if __name__ == "__main__":
    main()