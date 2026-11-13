"""Read and validate the Gold Parquet tables stored in S3."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from io import BytesIO
import os

import boto3
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = os.getenv("S3_BUCKET", "energy-optimizer-grupo4")
# Same variable as notebooks 02/03; selects outputs/<prefix>/ (default outputs/redata).
S3_PREFIX = f"outputs/{os.getenv('REDATA_S3_PREFIX', 'redata').strip('/')}"
S3_REGION = "eu-north-1"
GOLD_S3_URI = f"s3://{S3_BUCKET}/{S3_PREFIX}/"
MONTHLY_FILENAME = "gold_plan_mensual.parquet"
HOURLY_FILENAME = "gold_programacion_horaria.parquet"
TEMPERATURE_PREFIX = "outputs/aemet"
TEMPERATURE_FILENAME = "gold_temperatura_diaria.parquet"
TEMPERATURE_S3_URI = f"s3://{S3_BUCKET}/{TEMPERATURE_PREFIX}/{TEMPERATURE_FILENAME}"
TEMPERATURE_COLUMNS = [
	"fecha", "tmed",
	"tmin", "localidad_tmin", "provincia_tmin", "hora_tmin",
	"tmax", "localidad_tmax", "provincia_tmax", "hora_tmax",
]
TIMEZONE = "Europe/Madrid"
# Contract of the case 4 scenario, not metadata supplied by the Parquet files.
ENERGY_TARGET_MWH = 30.0
HOURLY_LIMIT_MWH = 7.0
MONTHLY_NUMERIC = [
	"precio_spot_medio_mensual_eur_mwh", "ahorro_estimado_mensual_eur",
	"precio_spot_medio_anual_eur_mwh", "ahorro_estimado_anual_eur",
]
HOURLY_NUMERIC = [
	"precio_eur_mwh", "consumo_baseline_mwh", "consumo_optimizado_mwh",
	"coste_baseline_eur", "coste_optimizado_eur",
]
# 6.2TD energy tolls and charges published by Gold; empty (NaN) on days without a loaded tariff.
TARIFF_HOURLY_NUMERIC = [
	"peaje_energia_eur_mwh", "cargo_energia_eur_mwh",
	"coste_regulado_baseline_eur", "coste_regulado_optimizado_eur",
	"coste_total_baseline_eur", "coste_total_optimizado_eur",
]
TARIFF_PERIODS = {"P1", "P2", "P3", "P4", "P5", "P6"}


def read_table(filename: str, required: list[str], *, prefix: str = S3_PREFIX) -> pd.DataFrame:
	response = boto3.client("s3", region_name=S3_REGION).get_object(
		Bucket=S3_BUCKET,
		Key=f"{prefix}/{filename}",
	)
	with closing(response["Body"]) as body:
		table = pd.read_parquet(BytesIO(body.read()), engine="pyarrow")
	missing = set(required) - set(table.columns)
	if missing:
		raise ValueError(f"{filename}: faltan columnas: {', '.join(sorted(missing))}.")
	return table.loc[:, required].copy()


def numeric_columns(table: pd.DataFrame, columns: list[str], name: str) -> None:
	for column in columns:
		table[column] = pd.to_numeric(table[column], errors="raise")
		if not np.isfinite(table[column].to_numpy(dtype=float)).all():
			raise ValueError(f"{name}: {column} contiene valores vacíos o no finitos.")


def load_temperature_table() -> pd.DataFrame:
	"""Read national daily temperatures, preserving missing measurements as nulls."""
	table = read_table(TEMPERATURE_FILENAME, TEMPERATURE_COLUMNS, prefix=TEMPERATURE_PREFIX)
	table["fecha"] = pd.to_datetime(table["fecha"], format="%Y-%m-%d", errors="raise").dt.date
	if table["fecha"].isna().any() or table["fecha"].duplicated().any():
		raise ValueError(f"{TEMPERATURE_FILENAME}: fechas vacías o duplicadas.")
	for column in ("tmin", "tmax", "tmed"):
		table[column] = pd.to_numeric(table[column], errors="raise")
		if np.isinf(table[column].to_numpy(dtype=float, na_value=np.nan)).any():
			raise ValueError(f"{TEMPERATURE_FILENAME}: {column} contiene valores no finitos.")
	for column in ("hora_tmin", "hora_tmax"):
		hours = table[column].astype("string")
		if not hours.dropna().str.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d").all():
			raise ValueError(f"{TEMPERATURE_FILENAME}: {column} debe tener formato HH:MM.")
	return table.sort_values("fecha").reset_index(drop=True)


def load_gold_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
	"""Read the current monthly/hourly contract and aggregate already optimized hours."""
	monthly = read_table(MONTHLY_FILENAME, ["mes", *MONTHLY_NUMERIC])
	plan = read_table(HOURLY_FILENAME, ["fecha_local", "hora_local", *HOURLY_NUMERIC, "periodo_tarifario", *TARIFF_HOURLY_NUMERIC])
	if plan.empty or monthly.empty:
		raise ValueError("Las tablas Gold mensual y horaria deben contener resultados.")
	plan["fecha_local"] = pd.to_datetime(plan["fecha_local"], format="%Y-%m-%d", errors="raise").dt.date
	if plan["fecha_local"].isna().any():
		raise ValueError("Hay fechas locales vacías.")
	if not monthly["mes"].astype("string").str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])").fillna(False).all():
		raise ValueError("La tabla mensual debe contener meses con formato YYYY-MM.")
	if monthly["mes"].duplicated().any():
		raise ValueError("La tabla mensual contiene meses duplicados.")
	numeric_columns(monthly, MONTHLY_NUMERIC, MONTHLY_FILENAME)
	numeric_columns(plan, ["hora_local", *HOURLY_NUMERIC], HOURLY_FILENAME)
	for column in TARIFF_HOURLY_NUMERIC:
		plan[column] = pd.to_numeric(plan[column], errors="raise")
		if np.isinf(plan[column].to_numpy(dtype=float, na_value=np.nan)).any():
			raise ValueError(f"{HOURLY_FILENAME}: {column} contiene valores no finitos.")
	if not plan["hora_local"].between(0, 23).all() or not (plan["hora_local"] % 1 == 0).all():
		raise ValueError("hora_local debe ser un entero entre 0 y 23.")
	schedules = []
	for day, schedule in plan.groupby("fecha_local", sort=True):
		start = pd.Timestamp(day, tz=TIMEZONE)
		end = pd.Timestamp(day + pd.Timedelta(days=1), tz=TIMEZONE)
		expected = pd.date_range(start, end, freq="h", inclusive="left")
		# Gold guarantees chronological row order, including the two autumn 02:00s.
		if schedule["hora_local"].tolist() != expected.hour.tolist():
			raise ValueError(f"{day}: horas incompletas, duplicadas o fuera del orden cronológico de Gold.")
		schedule = schedule.copy()
		schedule["datetime_local"] = expected
		for scenario in ("baseline", "optimizado"):
			consumption = schedule[f"consumo_{scenario}_mwh"]
			if not consumption.between(0, HOURLY_LIMIT_MWH).all():
				raise ValueError(f"{day}: consumo {scenario} fuera del límite horario del caso 4.")
			if not np.isclose(consumption.sum(), ENERGY_TARGET_MWH, atol=1e-5, rtol=0):
				raise ValueError(f"{day}: energía diaria {scenario} distinta del objetivo del caso 4.")
			if not np.allclose(schedule["precio_eur_mwh"] * consumption, schedule[f"coste_{scenario}_eur"], atol=1e-4, rtol=0):
				raise ValueError(f"{day}: coste {scenario} distinto de precio por consumo.")
		validate_tariff_day(day, schedule)
		schedules.append(schedule)
	plan = pd.concat(schedules, ignore_index=True)
	summary = plan.groupby("fecha_local", as_index=False, sort=True).agg(
		horas_del_dia=("hora_local", "size"),
		consumo_baseline_total_mwh=("consumo_baseline_mwh", "sum"),
		consumo_optimizado_total_mwh=("consumo_optimizado_mwh", "sum"),
		coste_baseline_total_eur=("coste_baseline_eur", "sum"),
		coste_optimizado_total_eur=("coste_optimizado_eur", "sum"),
	)
	regulated = plan.groupby("fecha_local", sort=True)[
		["coste_regulado_baseline_eur", "coste_regulado_optimizado_eur"]
	].sum(min_count=1)
	summary["coste_regulado_baseline_total_eur"] = regulated["coste_regulado_baseline_eur"].to_numpy()
	summary["coste_regulado_optimizado_total_eur"] = regulated["coste_regulado_optimizado_eur"].to_numpy()
	summary["ahorro_eur"] = (summary["coste_baseline_total_eur"] - summary["coste_optimizado_total_eur"]).round(5)
	summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].replace(0, float("nan")) * 100
	summary["energia_flexible_objetivo_mwh"] = ENERGY_TARGET_MWH
	summary["limite_flexible_mwh_por_hora"] = HOURLY_LIMIT_MWH
	summary["estado_optimizacion"] = "optimo"
	summary["month"] = pd.to_datetime(summary["fecha_local"]).dt.strftime("%Y-%m")
	daily_totals = summary.groupby("month", sort=True).agg(
		saving_eur=("ahorro_eur", "sum"),
		days=("fecha_local", "count"),
	)
	monthly = monthly.rename(columns={"mes": "month", "ahorro_estimado_mensual_eur": "saving_eur"})
	monthly = monthly.sort_values("month").reset_index(drop=True)
	if monthly["month"].tolist() != daily_totals.index.tolist():
		raise ValueError("Los meses de Gold no coinciden con los días óptimos del resumen.")
	if not np.allclose(monthly["saving_eur"], daily_totals["saving_eur"], atol=1e-4, rtol=0):
		raise ValueError("El ahorro mensual no coincide con el resumen diario.")
	hourly_prices = plan.assign(month=plan["datetime_local"].dt.strftime("%Y-%m")).groupby("month")["precio_eur_mwh"].mean()
	if not np.allclose(monthly["precio_spot_medio_mensual_eur_mwh"], hourly_prices, atol=5.1e-5, rtol=0):
		raise ValueError("El precio medio mensual no coincide con la programación horaria.")
	for column in ("precio_spot_medio_anual_eur_mwh", "ahorro_estimado_anual_eur"):
		if monthly[column].nunique() != 1:
			raise ValueError(f"{column} debe repetirse con el mismo valor en todos los meses.")
	if not np.isclose(monthly["ahorro_estimado_anual_eur"].iloc[0], monthly["saving_eur"].sum(), atol=1e-4, rtol=0):
		raise ValueError("El ahorro anual de Gold no coincide con el total del período cargado.")
	if not np.isclose(monthly["precio_spot_medio_anual_eur_mwh"].iloc[0], plan["precio_eur_mwh"].mean(), atol=5.1e-5, rtol=0):
		raise ValueError("El precio medio anual no coincide con la programación horaria.")
	monthly["days"] = daily_totals["days"].to_numpy()
	return monthly, summary.drop(columns="month"), plan


def validate_tariff_day(day: date, schedule: pd.DataFrame) -> None:
	"""A day carries either no tariff at all or a complete and consistent 6.2TD breakdown."""
	present = schedule[TARIFF_HOURLY_NUMERIC].notna().all(axis=1)
	if not present.any():
		return
	if not present.all():
		raise ValueError(f"{day}: peajes y cargos 6.2TD incompletos.")
	if not schedule["periodo_tarifario"].isin(TARIFF_PERIODS).all():
		raise ValueError(f"{day}: periodo tarifario fuera de P1-P6.")
	regulated_price = schedule["peaje_energia_eur_mwh"] + schedule["cargo_energia_eur_mwh"]
	for scenario in ("baseline", "optimizado"):
		regulated = schedule[f"consumo_{scenario}_mwh"] * regulated_price
		if not np.allclose(regulated, schedule[f"coste_regulado_{scenario}_eur"], atol=1e-4, rtol=0):
			raise ValueError(f"{day}: coste regulado {scenario} distinto de consumo por peaje y cargo.")
		total = schedule[f"coste_{scenario}_eur"] + schedule[f"coste_regulado_{scenario}_eur"]
		if not np.allclose(total, schedule[f"coste_total_{scenario}_eur"], atol=1e-4, rtol=0):
			raise ValueError(f"{day}: coste total {scenario} distinto de mercado más regulado.")


def apply_tariff_scenario(
	monthly: pd.DataFrame, summary: pd.DataFrame, plan: pd.DataFrame,
	start: date | None = None, end: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
	"""Use all published tariff days, optionally filtered, with market + 6.2TD costs.

	Market-only costs are kept as coste_mercado_* so the UI can show the breakdown.
	"""
	summary = summary[
		summary["fecha_local"].map(
			lambda value: (start is None or start <= value) and (end is None or value <= end)
		)
		& summary["coste_regulado_baseline_total_eur"].notna()
	].copy()
	plan = plan[plan["fecha_local"].isin(set(summary["fecha_local"]))].copy()
	for scenario in ("baseline", "optimizado"):
		summary[f"coste_mercado_{scenario}_total_eur"] = summary[f"coste_{scenario}_total_eur"]
		summary[f"coste_{scenario}_total_eur"] = (
			summary[f"coste_{scenario}_total_eur"] + summary[f"coste_regulado_{scenario}_total_eur"]
		)
		plan[f"coste_mercado_{scenario}_eur"] = plan[f"coste_{scenario}_eur"]
		plan[f"coste_{scenario}_eur"] = plan[f"coste_total_{scenario}_eur"]
	summary["ahorro_eur"] = (summary["coste_baseline_total_eur"] - summary["coste_optimizado_total_eur"]).round(5)
	summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].replace(0, float("nan")) * 100
	month = pd.to_datetime(summary["fecha_local"]).dt.strftime("%Y-%m")
	totals = summary.groupby(month, sort=True).agg(saving_eur=("ahorro_eur", "sum"), days=("fecha_local", "count"))
	prices = plan.groupby(plan["datetime_local"].dt.strftime("%Y-%m"))["precio_eur_mwh"].mean()
	monthly = monthly[monthly["month"].isin(totals.index)].copy().set_index("month")
	monthly["saving_eur"] = totals["saving_eur"]
	monthly["days"] = totals["days"]
	monthly["precio_spot_medio_mensual_eur_mwh"] = prices.reindex(monthly.index)
	monthly["ahorro_estimado_anual_eur"] = float(totals["saving_eur"].sum())
	monthly["precio_spot_medio_anual_eur_mwh"] = float(plan["precio_eur_mwh"].mean()) if len(plan) else float("nan")
	return monthly.reset_index(), summary, plan
