"""Shared Spanish number formatting for the dashboard."""

import pandas as pd


def format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def format_eur(value: float) -> str:
    if pd.isna(value):
        return "Sin datos"
    return f"{format_number(value)} €"


def format_pct(value: float) -> str:
    if pd.isna(value):
        return "No aplica"
    return f"{value:.1f}".replace(".", ",") + " %"
