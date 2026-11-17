from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import requests

from src.ingesta.base import RequestGet, Sleep, request_bytes, save_bytes


@dataclass(frozen=True)
class MibgasIngestionConfig:
    raw_dir: Path
    base_url: str
    language: str = "es"
    file_path_template: str = "/{language}/file-access/MIBGAS_Data_{year}.csv?path=AGNO_{year}/XLS"
    retries: int = 4
    timeout: int = 90
    pause_seconds: float = 1
    force: bool = False


def get_csv_bytes(
    year: int,
    config: MibgasIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> bytes:
    path = config.file_path_template.format(language=config.language, year=year)
    url = f"{config.base_url.rstrip('/')}{path}"
    return request_bytes(
        url,
        retries=config.retries,
        timeout=config.timeout,
        source="MIBGAS",
        request_get=request_get,
        sleep=sleep,
    )


def save_raw(content: bytes, path: Path) -> Path:
    return save_bytes(content, path)


def ingest_year(
    year: int,
    config: MibgasIngestionConfig,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> tuple[str, Path, int]:
    path = config.raw_dir / f"MIBGAS_Data_{year}.csv"
    if path.exists() and not config.force:
        return "skipped", path, path.read_bytes().count(b"\n")
    content = get_csv_bytes(year, config, request_get=request_get, sleep=sleep)
    save_raw(content, path)
    return "downloaded", path, content.count(b"\n")
