"""Read and validate the Gold Parquet tables stored in S3."""

from __future__ import annotations

from contextlib import closing
from io import BytesIO

import boto3
import numpy as np
import pandas as pd


S3_BUCKET = "energy-optimizer-grupo4"
S3_PREFIX = "outputs/redata"
S3_REGION = "eu-north-1"
GOLD_S3_URI = f"s3://{S3_BUCKET}/{S3_PREFIX}/"
MONTHLY_FILENAME = "gold_plan_mensual.parquet"
HOURLY_FILENAME = "gold_programacion_horaria.parquet"
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


def read_table(filename: str, required: list[str]) -> pd.DataFrame:
	response = boto3.client("s3", region_name=S3_REGION).get_object(
		Bucket=S3_BUCKET,
		Key=f"{S3_PREFIX}/{filename}",
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


def load_gold_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
	"""Read the current monthly/hourly contract and aggregate already optimized hours."""
	monthly = read_table(MONTHLY_FILENAME, ["mes", *MONTHLY_NUMERIC])
	plan = read_table(HOURLY_FILENAME, ["fecha_local", "hora_local", *HOURLY_NUMERIC])
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
		schedules.append(schedule)
	plan = pd.concat(schedules, ignore_index=True)
	summary = plan.groupby("fecha_local", as_index=False, sort=True).agg(
		horas_del_dia=("hora_local", "size"),
		consumo_baseline_total_mwh=("consumo_baseline_mwh", "sum"),
		consumo_optimizado_total_mwh=("consumo_optimizado_mwh", "sum"),
		coste_baseline_total_eur=("coste_baseline_eur", "sum"),
		coste_optimizado_total_eur=("coste_optimizado_eur", "sum"),
	)
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
