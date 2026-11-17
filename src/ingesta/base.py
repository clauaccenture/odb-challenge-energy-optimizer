from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import requests


RequestGet = Callable[..., requests.Response]
Sleep = Callable[[float], None]


def validate_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} debe ser un entero")
    if value <= 0:
        raise ValueError(f"{name} debe ser mayor que cero")


def validate_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} debe ser un entero")
    if value < 0:
        raise ValueError(f"{name} no puede ser negativo")


def validate_non_negative_number(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} debe ser un numero")
    if value < 0:
        raise ValueError(f"{name} no puede ser negativo")


def validate_http_settings(
    base_url: str,
    retries: int,
    timeout: int,
    pause_seconds: float,
) -> None:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url debe ser un texto no vacio")
    validate_positive_int("retries", retries)
    validate_positive_int("timeout", timeout)
    validate_non_negative_number("pause_seconds", pause_seconds)


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
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return path


def save_bytes(content: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return path


def load_valid_json(
    path: Path,
    required_list_key: str | None = None,
) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if required_list_key and not isinstance(payload.get(required_list_key), list):
        return None
    if required_list_key and not payload[required_list_key]:
        return None
    return payload


def is_valid_bytes_file(path: Path, required_markers: tuple[bytes, ...]) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    return all(marker in content for marker in required_markers)
