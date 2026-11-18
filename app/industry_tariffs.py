"""Hourly Som Energia indexed price for any 6.xTD access tariff, reusing the desalination model."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import cargar_config  # noqa: E402
from src.desaladora import build_desaladora, precios_indexados  # noqa: E402
from src.tarifas_6_2td import FESTIVOS_NACIONALES, PERIODOS, RUTA_CONFIG  # noqa: E402

VOLTAGES = {"6.1TD": "1–30 kV", "6.2TD": "30–72,5 kV", "6.3TD": "72,5–145 kV", "6.4TD": "≥ 145 kV"}


def config() -> dict:
    """Current YAML values; re-read whenever the file changes on disk."""
    return _config(RUTA_CONFIG.stat().st_mtime_ns)


@lru_cache(maxsize=1)
def _config(_mtime: int) -> dict:
    cfg = cargar_config(RUTA_CONFIG)[0]
    # S0 moves the same daily flexible energy as S1, spread evenly over its window.
    base = cfg["baseline_s0"]
    hours = base["hora_fin"] - base["hora_inicio"]
    if hours > 0:
        base["mwh_hora"] = cfg["carga_flexible"]["energia_diaria_mwh"] / hours
    return cfg


def regulated_terms(tariff: str, year: int) -> dict[str, float] | None:
    """Energy toll + charge per period, EUR/MWh, or None if that tariff/year is not in the config."""
    data = config().get("tarifas_reguladas", {}).get(tariff, {}).get("anios", {}).get(year)
    if not data:
        return None
    return {p: data["peajes_energia_eur_mwh"][p] + data["cargos_energia_eur_mwh"][p] for p in PERIODOS}


def has_calendar(day: date) -> bool:
    return day.year in FESTIVOS_NACIONALES


def is_p6_day(day: date) -> bool:
    return day.weekday() >= 5 or day in FESTIVOS_NACIONALES.get(day.year, frozenset())


def indexed_prices(rows: pd.DataFrame, tariff: str) -> pd.DataFrame:
    """Som formula from src.desaladora (6.2TD), with the energy toll and charge of `tariff` instead.

    Returns period, market, supply (system costs, losses, margin and 1.5 % factor), regulated and total,
    all in EUR/MWh, aligned with `rows`.
    """
    years = set(rows["datetime_local"].dt.year)
    terms = {year: regulated_terms(tariff, year) for year in years}
    missing = sorted(year for year, value in terms.items() if value is None)
    if missing:
        raise ValueError(f"No hay peajes y cargos {tariff} cargados para {missing}.")
    som = precios_indexados(rows[["datetime_local", "precio_eur_mwh"]].reset_index(drop=True), config())
    regulated_62 = som["peaje_energia_eur_mwh"] + som["cargo_energia_eur_mwh"]
    regulated = pd.Series([terms[t.year][p] for t, p in zip(som["datetime_local"], som["periodo_tarifario"])])
    market = som["precio_eur_mwh"].astype(float)
    supply = som["precio_indexado_eur_mwh"] - regulated_62 - market
    return pd.DataFrame({
        "periodo": som["periodo_tarifario"].to_numpy(),
        "mercado": market.to_numpy(),
        "suministro": supply.to_numpy(),
        "regulado": regulated.to_numpy(),
        "total": (market + supply + regulated).to_numpy(),
    })


def recompute_case(published_plan: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Case 4 recomputed with the current YAML over the spot prices of the published run.

    Returns plan, daily summary and monthly summary with the same columns the dashboard reads.
    """
    silver = published_plan[["datetime_utc", "precio_eur_mwh"]].drop_duplicates("datetime_utc")
    plan, summary, monthly = build_desaladora(silver, config())
    for scenario in ("baseline", "optimizado"):
        summary[f"coste_{scenario}_total_eur"] = summary[f"coste_energia_flexible_{scenario}_eur"]
    summary["ahorro_eur"] = summary["ahorro_energia_eur"]
    summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].where(
        summary["coste_baseline_total_eur"] > 0
    ) * 100
    monthly = monthly.rename(columns={"mes": "month", "ahorro_energia_eur": "saving_eur", "dias_optimos": "days"})
    monthly["ahorro_estimado_anual_eur"] = float(summary["ahorro_eur"].sum())
    return plan, summary, monthly
