from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
    validate_positive_int,
)



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

    def __post_init__(self) -> None:
        validate_http_settings(
            self.base_url, self.retries, self.timeout, self.pause_seconds
        )
        validate_positive_int("page_size", self.page_size)
        if self.page_size > 10_000:
            raise ValueError("page_size no puede superar 10.000")


def get_json(
    url: str,
    params: dict[str, Any],
    retries: int = 4,
    timeout: int = 90,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    return request_json(
        url,
        params=params,
        retries=retries,
        timeout=timeout,
        source="CNMC",
        request_get=request_get,
        sleep=sleep,
    )


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
        raw_page = result["records"]
        page = [record for record in raw_page if isinstance(record, dict)]
        records.extend(page)
        total = result.get("total")
        offset += len(raw_page)
        if not raw_page or (isinstance(total, int) and offset >= total) or len(raw_page) < config.page_size:
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
    return save_json(payload, path)


def ingest_resource(
    resource: CnmcResourceConfig,
    config: CnmcIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> tuple[str, Path, int]:
    path = config.raw_dir / f"{resource.name}.json"
    if path.exists() and not config.force:
        payload = load_valid_json(path, required_list_key="records")
        if payload is not None:
            return "skipped", path, len(payload["records"])
    payload = fetch_resource(resource, config, request_get=request_get, sleep=sleep)
    save_raw(payload, path)
    return "downloaded", path, len(payload["records"])
