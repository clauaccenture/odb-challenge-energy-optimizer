from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests


RequestGet = Callable[..., requests.Response]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class CnmcResourceConfig:
    name: str
    resource_id: str
    date_field: str
    price_field: str
    product_field: str | None = None
    product_value: str | None = None


@dataclass(frozen=True)
class CnmcIngestionConfig:
    raw_dir: Path
    base_url: str
    page_size: int = 1000
    retries: int = 4
    timeout: int = 90
    pause_seconds: float = 1
    force: bool = False


def get_json(
    url: str,
    params: dict[str, Any],
    retries: int = 4,
    timeout: int = 90,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            response = request_get(url, params=params, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("CNMC devolvio una respuesta JSON que no es un objeto.")
            return payload
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Fallo la peticion a CNMC: {url}") from exc
            sleep(2 ** attempt)
    raise RuntimeError(f"Fallo la peticion a CNMC: {url}")


def fetch_resource(
    resource: CnmcResourceConfig,
    config: CnmcIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = get_json(
            config.base_url,
            {
                "resource_id": resource.resource_id,
                "limit": config.page_size,
                "offset": offset,
            },
            retries=config.retries,
            timeout=config.timeout,
            request_get=request_get,
            sleep=sleep,
        )
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("records"), list):
            raise ValueError("La respuesta CNMC no contiene result.records como lista.")
        page = [record for record in result["records"] if isinstance(record, dict)]
        records.extend(page)
        total = result.get("total")
        offset += len(page)
        if not page or (isinstance(total, int) and offset >= total) or len(page) < config.page_size:
            break
        sleep(config.pause_seconds)
    return {
        "source": "cnmc",
        "resource": resource.name,
        "resource_id": resource.resource_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }


def save_raw(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ingest_resource(
    resource: CnmcResourceConfig,
    config: CnmcIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> tuple[str, Path, int]:
    path = config.raw_dir / f"{resource.name}.json"
    if path.exists() and not config.force:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return "skipped", path, len(payload.get("records", []))
    payload = fetch_resource(resource, config, request_get=request_get, sleep=sleep)
    save_raw(payload, path)
    return "downloaded", path, len(payload["records"])
