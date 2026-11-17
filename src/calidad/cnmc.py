from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingesta.cnmc import CnmcResourceConfig


def classify_raw_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_file": str(path),
        "status": "unreadable",
        "record_count": 0,
        "captured_at_utc": None,
        "error": None,
        "payload": None,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error"] = str(exc)
        return result
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        result["status"] = "malformed"
        result["error"] = "Falta records como lista"
        return result
    result.update({
        "status": "valid" if payload["records"] else "empty",
        "record_count": len(payload["records"]),
        "captured_at_utc": payload.get("captured_at_utc"),
        "payload": payload,
    })
    return result


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace(" ", "")
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_records(
    payload: dict[str, Any],
    resource: CnmcResourceConfig,
    start: date | str,
    end: date | str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    start_date = pd.Timestamp(start).date()
    end_date = pd.Timestamp(end).date()
    rows: list[dict[str, Any]] = []
    invalid_dates = 0
    invalid_prices = 0
    outside_window = 0
    filtered_by_product = 0
    for record in payload.get("records", []):
        if not isinstance(record, dict):
            continue
        negotiation = pd.to_datetime(record.get(resource.date_field), errors="coerce")
        if pd.isna(negotiation):
            invalid_dates += 1
            continue
        negotiation_date = negotiation.date()
        if not start_date <= negotiation_date <= end_date:
            outside_window += 1
            continue
        price = _to_number(record.get(resource.price_field))
        if price is None:
            invalid_prices += 1
        product = record.get(resource.product_field) if resource.product_field else None
        if resource.product_value and product != resource.product_value:
            filtered_by_product += 1
            continue
        rows.append({
            "fecha_negociacion": negotiation_date,
            "fecha_entrega": record.get("fecha_de_entrega"),
            "fecha_publicacion": record.get("fecha_de_publicacion"),
            "producto": product,
            "precio_eur_mwh": price,
            "source_resource": resource.name,
            "captured_at_utc": payload.get("captured_at_utc"),
        })
    values = pd.DataFrame(rows)
    if not values.empty:
        values["fecha_negociacion"] = pd.to_datetime(values["fecha_negociacion"]).dt.date
        values = values.sort_values(["fecha_negociacion", "captured_at_utc"]).reset_index(drop=True)
    report = {
        "input_records": len(payload.get("records", [])),
        "output_records": len(values),
        "invalid_dates": invalid_dates,
        "invalid_prices": invalid_prices,
        "outside_window": outside_window,
        "filtered_by_product": filtered_by_product,
    }
    return values, report


def deduplicate_records(values: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if values.empty:
        return values.copy(), 0
    key_columns = ["fecha_negociacion", "producto", "source_resource"]
    duplicate_mask = values.duplicated(subset=key_columns, keep="last")
    deduplicated = values.loc[~duplicate_mask].reset_index(drop=True)
    return deduplicated, int(duplicate_mask.sum())


def add_age_days(values: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    values = values.copy()
    negotiation = pd.to_datetime(values["fecha_negociacion"], errors="coerce")
    as_of_date = pd.Timestamp(as_of).date()
    values["edad_precio_gas_dias"] = (
        pd.Timestamp(as_of_date) - negotiation.dt.normalize()
    ).dt.days
    return values
