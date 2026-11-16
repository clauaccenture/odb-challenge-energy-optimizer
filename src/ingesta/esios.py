from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import requests


RequestGet = Callable[..., requests.Response]
Sleep = Callable[[float], None]


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


def get_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    retries: int = 4,
    timeout: int = 90,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            response = request_get(url, headers=headers, params=params, timeout=timeout)
            if response.status_code in (401, 403):
                raise PermissionError(
                    f"ESIOS rechazo la credencial o el acceso (HTTP {response.status_code})."
                )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("ESIOS devolvio una respuesta JSON que no es un objeto.")
            return payload
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Fallo la peticion a ESIOS: {url}") from exc
            wait = 2 ** attempt
            sleep(wait)
    raise RuntimeError(f"Fallo la peticion a ESIOS: {url}")


def save_raw(
    payload: dict[str, Any],
    path: Path,
    s3_key: str | None = None,
    upload_to_s3: bool = False,
    bucket: str | None = None,
    s3_client: Any = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if upload_to_s3 and s3_key:
        if not bucket:
            raise ValueError("Falta el bucket S3 para subir el archivo raw.")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        s3_client.upload_file(str(path), bucket, s3_key)
    return path


def date_chunks(start: date, end: date, size: int = 30):
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
        return "skipped", indicator_id, chunk_start, chunk_end, 0, None

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
