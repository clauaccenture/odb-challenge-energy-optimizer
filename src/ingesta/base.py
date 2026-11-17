from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import requests


RequestGet = Callable[..., requests.Response]
Sleep = Callable[[float], None]


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    retries: int = 4,
    timeout: int = 90,
    source: str = "fuente",
    forbidden_statuses: set[int] | None = None,
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    forbidden_statuses = forbidden_statuses or set()
    for attempt in range(retries):
        try:
            response = request_get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            if response.status_code in forbidden_statuses:
                raise PermissionError(
                    f"{source} rechazo la credencial o el acceso "
                    f"(HTTP {response.status_code})."
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(
                    f"{source} devolvio una respuesta JSON que no es un objeto."
                )
            return payload
        except PermissionError:
            raise
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Fallo la peticion a {source}: {url}") from exc
            sleep(2**attempt)
    raise RuntimeError(f"Fallo la peticion a {source}: {url}")


def request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    retries: int = 4,
    timeout: int = 90,
    source: str = "fuente",
    request_get: RequestGet = requests.get,
    sleep: Sleep = time.sleep,
) -> bytes:
    for attempt in range(retries):
        try:
            response = request_get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            if not response.content:
                raise ValueError(f"{source} devolvio un fichero vacio.")
            return response.content
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Fallo la peticion a {source}: {url}") from exc
            sleep(2**attempt)
    raise RuntimeError(f"Fallo la peticion a {source}: {url}")


def save_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def save_bytes(content: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
