from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.calidad.base import deduplicate_records as deduplicate_common
from src.calidad.base import to_number


PRICE_COLUMN = "MIBGAS Daily Price [EUR/MWh]"


def read_raw_file(path: Path) -> pd.DataFrame:
    values = pd.read_csv(path, sep=";", skiprows=1, dtype=str, encoding="utf-8-sig")
    unnamed = [column for column in values.columns if str(column).startswith("Unnamed")]
    return values.drop(columns=unnamed, errors="ignore")


def _to_number(value: Any) -> float | None:
    return to_number(value)


def normalize_records(
    values: pd.DataFrame,
    start: date | str,
    end: date | str,
    product_code: str = "GDAES_D+1",
    place_of_delivery: str = "PVB",
    area: str = "ES",
) -> tuple[pd.DataFrame, dict[str, int]]:
    start_date = pd.Timestamp(start).date()
    end_date = pd.Timestamp(end).date()
    required = {
        "Trading day",
        "Product",
        "Place of delivery",
        "Area",
        "First Day Delivery",
        "Last Day Delivery",
        PRICE_COLUMN,
    }
    missing = required - set(values.columns)
    if missing:
        raise ValueError(f"Faltan columnas MIBGAS: {sorted(missing)}")

    delivery = pd.to_datetime(values["First Day Delivery"], dayfirst=True, errors="coerce")
    trading = pd.to_datetime(values["Trading day"], dayfirst=True, errors="coerce")
    invalid_dates = int(delivery.isna().sum())
    valid = values.loc[delivery.notna()].copy()
    valid["fecha_entrega"] = delivery.loc[delivery.notna()].dt.date
    valid["fecha_negociacion"] = trading.loc[delivery.notna()].dt.date
    outside = ~valid["fecha_entrega"].between(start_date, end_date)
    outside_window = int(outside.sum())
    valid = valid.loc[~outside].copy()
    product_mask = (
        (valid["Product"] == product_code)
        & (valid["Place of delivery"] == place_of_delivery)
        & (valid["Area"] == area)
    )
    filtered_by_product = int((~product_mask).sum())
    valid = valid.loc[product_mask].copy()
    valid["precio_eur_mwh"] = valid[PRICE_COLUMN].map(_to_number)
    invalid_prices = int(valid["precio_eur_mwh"].isna().sum())
    normalized = valid.rename(columns={"Product": "producto"})[
        ["fecha_negociacion", "fecha_entrega", "producto", "precio_eur_mwh"]
    ].reset_index(drop=True)
    report = {
        "input_records": len(values),
        "output_records": len(normalized),
        "invalid_dates": invalid_dates,
        "invalid_prices": invalid_prices,
        "outside_window": outside_window,
        "filtered_by_product": filtered_by_product,
    }
    return normalized, report


def deduplicate_records(values: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    return deduplicate_common(values, ["fecha_entrega", "producto"])
