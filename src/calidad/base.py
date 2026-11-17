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
) -> tuple[pd.DataFrame, int]:
    if values.empty:
        return values.copy(), 0
    duplicate_mask = values.duplicated(subset=list(key_columns), keep="last")
    deduplicated = values.loc[~duplicate_mask].reset_index(drop=True)
    return deduplicated, int(duplicate_mask.sum())
