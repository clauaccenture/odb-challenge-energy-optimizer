from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from src.ingesta.base import (
    RequestGet,
    Sleep,
    load_valid_json,
    request_json,
    save_json,
    validate_http_settings,
)



@dataclass(frozen=True)
class EsiosIngestionConfig:
    raw_dir: Path
    base_url: str
    headers: dict[str, str]
    locale: str = "es"
    retries: int = 4
    timeout: int = 90
    pause_seconds: float = 1
    upload_to_s3: bool = False
    bucket: str | None = None
    force: bool = False

    def __post_init__(self) -> None:
        validate_http_settings(
            self.base_url, self.retries, self.timeout, self.pause_seconds
        )
        if not isinstance(self.headers, dict):
            raise TypeError("headers debe ser un diccionario")
        if not isinstance(self.locale, str) or not self.locale.strip():
            raise ValueError("locale debe ser un texto no vacio")


def get_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    retries: int = 4,
    timeout: int = 90,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    return request_json(
        url,
        headers=headers,
        params=params,
        retries=retries,
        timeout=timeout,
        source="ESIOS",
        forbidden_statuses={401, 403},
        request_get=request_get,
        sleep=sleep,
    )


def save_raw(
    payload: dict[str, Any],
    path: Path,
    s3_key: str | None = None,
    upload_to_s3: bool = False,
    bucket: str | None = None,
    s3_client: Any = None,
) -> Path:
    save_json(payload, path)
    if upload_to_s3 and s3_key:
        if not bucket:
            raise ValueError("Falta el bucket S3 para subir el archivo raw.")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        s3_client.upload_file(str(path), bucket, s3_key)
    return path


def date_chunks(start: date, end: date, size: int = 30):
    if not isinstance(start, date) or not isinstance(end, date):
        raise TypeError("start y end deben ser fechas")
    if start > end:
        raise ValueError("start no puede ser posterior a end")
    if isinstance(size, bool) or not isinstance(size, int):
        raise TypeError("size debe ser un entero")
    if size < 1 or size > 365:
        raise ValueError("size debe estar entre 1 y 365 dias")
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=size - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def values_count(payload: dict[str, Any]) -> int:
    indicator = payload.get("indicator")
    if not isinstance(indicator, dict) or not isinstance(indicator.get("values"), list):
        raise ValueError(
            "Respuesta de indicador no valida: se esperaba indicator.values como lista."
        )
    return len(indicator["values"])


def download_one(
    task: tuple[int, date, date],
    config: EsiosIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
    s3_client: Any = None,
) -> tuple[str, int, date, date, int, str | None]:
    indicator_id, chunk_start, chunk_end = task
    filename = f"indicador_{indicator_id}_{chunk_start}_{chunk_end}.json"
    local_path = config.raw_dir / "indicadores" / str(indicator_id) / filename
    s3_key = f"raw/esios/indicadores/{indicator_id}/{filename}"

    if local_path.exists() and not config.force:
        payload = load_valid_json(local_path)
        if payload is not None:
            try:
                n_values = values_count(payload)
            except ValueError:
                n_values = 0
            if n_values > 0:
                return "skipped", indicator_id, chunk_start, chunk_end, n_values, None

    url = f"{config.base_url}/indicators/{indicator_id}"
    params = {
        "start_date": f"{chunk_start.isoformat()}T00:00:00Z",
        "end_date": f"{chunk_end.isoformat()}T23:59:59Z",
        "locale": config.locale,
    }
    try:
        payload = get_json(
            url,
            config.headers,
            params=params,
            retries=config.retries,
            timeout=config.timeout,
            request_get=request_get,
            sleep=sleep,
        )
        n_values = values_count(payload)
        save_raw(
            payload,
            local_path,
            s3_key,
            upload_to_s3=config.upload_to_s3,
            bucket=config.bucket,
            s3_client=s3_client,
        )
        sleep(config.pause_seconds)
        return "downloaded", indicator_id, chunk_start, chunk_end, n_values, None
    except (RuntimeError, PermissionError, ValueError) as exc:
        return "failed", indicator_id, chunk_start, chunk_end, 0, str(exc)
