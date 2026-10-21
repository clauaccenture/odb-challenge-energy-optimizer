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

    response.raise_for_status()

    respuesta = response.json()

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

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Ingesta de datos de "
            "AEMET OpenData"
        )
    )

    parser.add_argument(
        "--start",
        required=True,
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
        "--no-s3",
        action="store_true",
        help=(
            "Guardar únicamente en local"
        )
    )

    args = parser.parse_args()

    # Comprobar rango
    if args.end < args.start:
        raise ValueError(
            "--end no puede ser "
            "anterior a --start"
        )

    total_bloques = 0
    total_registros = 0

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