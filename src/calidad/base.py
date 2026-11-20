from __future__ import annotations

from typing import Any, Sequence

import pandas as pd


def to_number(value: Any) -> float | None:
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


def deduplicate_records(
    values: pd.DataFrame,
    key_columns: Sequence[str],
    order_columns: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, int]:
    """Deduplicate after applying an explicit, deterministic source order."""
    if values.empty:
        return values.copy(), 0
    available_order_columns = [
        column for column in (order_columns or []) if column in values.columns
    ]
    if available_order_columns:
        values = values.sort_values(
            available_order_columns,
            kind="mergesort",
            na_position="last",
        )
    duplicate_mask = values.duplicated(subset=list(key_columns), keep="last")
    deduplicated = values.loc[~duplicate_mask].reset_index(drop=True)
    return deduplicated, int(duplicate_mask.sum())
