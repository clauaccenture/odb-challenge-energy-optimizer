"""Standalone local input for the desalination demo (no AWS calls).

Market prices are either uploaded by the user or explicitly synthetic. The
industrial configuration always comes from config/config_desaladora.yaml.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd

from industry_tariffs import RUTA_CONFIG, config
from src.desaladora import build_desaladora

# Perfil de mercado completamente inventado: reproducible, NO REData/OMIE.
ILLUSTRATIVE_SPOT_EUR_MWH = [
    43, 39, 31, 24, 22, 25, 39, 58, 75, 87, 82, 74,
    61, 45, 32, 27, 41, 76, 99, 104, 92, 70, 53, 47,
]
# Periodo totalmente transcurrido a fecha 18/11/2026: 79 días, sin datos futuros.
DEFAULT_DATE = "2026-09-01"
DEMO_DAYS = 79


def example_prices(day: str = DEFAULT_DATE, days: int = DEMO_DAYS) -> pd.DataFrame:
    """Precios ficticios para varios días completos; sin aleatoriedad ni AWS.

    El perfil cambia por día (desplazamiento horario, nivel y diferencia
    laborable/fin de semana) para mostrar optimizaciones independientes.
    Se respeta el cambio de horario de octubre: ese día tiene 25 horas.
    """
    if not 1 <= days <= 366:
        raise ValueError("El número de días sintéticos debe estar entre 1 y 366.")
    if pd.Timestamp(day).date() + pd.Timedelta(days=days - 1) > pd.Timestamp("2026-11-18").date():
        raise ValueError("La demo sintética no debe incluir fechas posteriores al 18/11/2026.")
    frames = []
    for index in range(days):
        current = pd.Timestamp(day).date() + pd.Timedelta(days=index)
        start = pd.Timestamp(current, tz="Europe/Madrid")
        finish = pd.Timestamp(current + pd.Timedelta(days=1), tz="Europe/Madrid")
        hours = pd.date_range(start, finish, freq="h", inclusive="left")
        # El día 25/10/2026 tiene 25 horas en Madrid; conservar todas las marcas UTC.
        offset = (index * 3) % 24
        variation = (index % 5 - 2) * 4
        weekend_adjustment = -8 if current.weekday() >= 5 else 0
        values = [
            float(ILLUSTRATIVE_SPOT_EUR_MWH[(h + offset) % 24] + variation + weekend_adjustment)
            for h in hours.tz_convert("Europe/Madrid").hour
        ]
        frames.append(pd.DataFrame({
            "datetime_utc": hours.tz_convert("UTC"),
            "precio_eur_mwh": values,
        }))
    return pd.concat(frames, ignore_index=True)


def csv_prices(content: bytes) -> pd.DataFrame:
    """CSV with datetime_utc (timezone/UTC) and precio_eur_mwh (EUR/MWh)."""
    rows = pd.read_csv(BytesIO(content))
    required = {"datetime_utc", "precio_eur_mwh"}
    if not required.issubset(rows.columns):
        raise ValueError("El CSV necesita columnas datetime_utc y precio_eur_mwh.")
    if rows.empty:
        raise ValueError("El CSV está vacío.")
    rows = rows[["datetime_utc", "precio_eur_mwh"]].copy()
    rows["datetime_utc"] = pd.to_datetime(rows["datetime_utc"], utc=True, errors="raise")
    rows["precio_eur_mwh"] = pd.to_numeric(rows["precio_eur_mwh"], errors="raise")
    if rows.isna().any().any():
        raise ValueError("El CSV contiene horas o precios vacíos.")
    if rows["datetime_utc"].duplicated().any():
        raise ValueError("El CSV contiene horas duplicadas.")
    return rows.sort_values("datetime_utc").reset_index(drop=True)


def calculate_local(prices: pd.DataFrame):
    cfg = config()
    plan, summary, monthly = build_desaladora(prices, cfg)
    for name in ("baseline", "optimizado"):
        summary[f"coste_{name}_total_eur"] = summary[f"coste_energia_flexible_{name}_eur"]
    summary["ahorro_eur"] = summary["ahorro_energia_eur"]
    summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].where(
        summary["coste_baseline_total_eur"] > 0
    ) * 100
    meta = {
        "config_yaml": Path(RUTA_CONFIG).read_text(encoding="utf-8"),
        "tarifa": {"anio": cfg["tarifa"]["anio_regulatorio"],
                   "peajes_eur_mwh": cfg["tarifas_reguladas"]["6.2TD"]["anios"][2026]["peajes_energia_eur_mwh"],
                   "cargos_eur_mwh": cfg["tarifas_reguladas"]["6.2TD"]["anios"][2026]["cargos_energia_eur_mwh"]},
        "horas_silver_fuera_vigencia_tarifa": 0,
    }
    monthly = monthly.rename(columns={
        "mes": "month",
        "dias_optimos": "days",
        "ahorro_energia_eur": "saving_eur",
    })
    return meta, plan, summary, monthly
