from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


DEFAULT_FILE_PATTERN = re.compile(
    r"indicador_(?P<id>\d+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.json$"
)


def select_raw_files(raw_dir: Path, indicator_ids: set[int] | list[int]) -> list[Path]:
    selected_ids = {int(indicator_id) for indicator_id in indicator_ids}
    return sorted(
        path
        for path in (raw_dir / "indicadores").glob("*/indicador_*.json")
        if path.parent.name.isdigit() and int(path.parent.name) in selected_ids
    )


def metadata_text(indicator: dict[str, Any], key: str) -> str | None:
    items = indicator.get(key)
    if not isinstance(items, list):
        return None
    names = [
        item.get("name")
        for item in items
        if isinstance(item, dict) and item.get("name")
    ]
    return "; ".join(map(str, names)) or None


def classify_file(
    path: Path,
    project_root: Path,
    file_pattern: re.Pattern[str] = DEFAULT_FILE_PATTERN,
) -> dict[str, Any]:
    match = file_pattern.fullmatch(path.name)
    result: dict[str, Any] = {
        "source_file": str(path.relative_to(project_root)),
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "indicator_id": int(match.group("id")) if match else None,
        "requested_start": match.group("start") if match else None,
        "requested_end": match.group("end") if match else None,
        "status": "malformed",
        "value_count": 0,
        "indicator_name": None,
        "unit": None,
        "frequency": None,
        "payload": None,
        "error": None,
    }
    if not match:
        result["error"] = "Nombre de archivo no reconocido"
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["status"] = "unreadable"
        result["error"] = str(exc)
        return result
    indicator = payload.get("indicator") if isinstance(payload, dict) else None
    values = indicator.get("values") if isinstance(indicator, dict) else None
    if not isinstance(indicator, dict) or not isinstance(values, list):
        result["error"] = "Falta indicator.values como lista"
        return result
    result.update({
        "status": "empty" if not values else "valid",
        "value_count": len(values),
        "indicator_name": indicator.get("name"),
        "unit": metadata_text(indicator, "magnitud"),
        "frequency": metadata_text(indicator, "tiempo"),
        "payload": payload,
    })
    return result


def flatten_records(block_records: list[dict[str, Any]]) -> pd.DataFrame:
    value_rows: list[dict[str, Any]] = []
    for record in block_records:
        if record["status"] != "valid":
            continue
        indicator = record["payload"]["indicator"]
        for value in indicator["values"]:
            if not isinstance(value, dict):
                continue
            value_rows.append({
                "indicator_id": record["indicator_id"],
                "indicator_name": indicator.get("name"),
                "short_name": indicator.get("short_name"),
                "unit": record["unit"],
                "frequency": record["frequency"],
                "fecha_inicio": value.get("datetime_utc") or value.get("datetime"),
                "fecha_fin": value.get("datetime_end") or value.get("end_datetime"),
                "valor": value.get("value"),
                "geo_id": value.get("geo_id"),
                "geo_name": value.get("geo_name"),
                "requested_start": record["requested_start"],
                "requested_end": record["requested_end"],
                "source_file": record["source_file"],
            })
    values = pd.DataFrame(value_rows)
    if values.empty:
        raise ValueError("No se encontraron valores validos en los bloques raw.")
    return values


def normalize_values(
    values: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    local_timezone: str = "Europe/Madrid",
) -> tuple[pd.DataFrame, dict[str, int]]:
    values = values.copy()
    values["fecha_inicio"] = pd.to_datetime(values["fecha_inicio"], utc=True, errors="coerce")
    values["fecha_fin"] = pd.to_datetime(values["fecha_fin"], utc=True, errors="coerce")
    values["valor"] = pd.to_numeric(values["valor"], errors="coerce")
    values["indicator_id"] = pd.to_numeric(values["indicator_id"], errors="coerce").astype("Int64")
    values["geo_id"] = pd.to_numeric(values["geo_id"], errors="coerce").astype("Int64")
    values["datetime_local"] = values["fecha_inicio"].dt.tz_convert(local_timezone)
    values["fecha_inicio_fuera_ventana"] = (
        (values["fecha_inicio"] < start_date) | (values["fecha_inicio"] > end_date)
    )
    report = {
        "invalid_timestamps": int(values["fecha_inicio"].isna().sum()),
        "invalid_numeric_values": int(values["valor"].isna().sum()),
        "missing_geo_id": int(values["geo_id"].isna().sum()),
        "missing_fecha_fin": int(values["fecha_fin"].isna().sum()),
    }
    return values, report


def deduplicate_values(
    values: pd.DataFrame,
    key_columns: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    key_columns = list(key_columns or [
        "indicator_id", "fecha_inicio", "fecha_fin", "geo_id", "geo_name",
    ])
    duplicate_mask = values.duplicated(subset=key_columns, keep="last")
    duplicate_rows = values.loc[duplicate_mask, key_columns + ["source_file"]].copy()
    duplicates_removed = int(duplicate_mask.sum())
    values = values.loc[~duplicate_mask].copy()
    values = values.sort_values(
        ["indicator_id", "fecha_inicio", "geo_id"],
        na_position="last",
    ).reset_index(drop=True)
    return values, duplicate_rows, duplicates_removed
