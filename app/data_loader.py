"""Read and validate the Gold Parquet tables stored in S3."""

from __future__ import annotations

from contextlib import closing
from io import BytesIO

import boto3
import numpy as np
import pandas as pd


S3_BUCKET = "energy-optimizer-grupo4"
S3_PREFIX = "outputs"
S3_REGION = "eu-north-1"
GOLD_S3_URI = f"s3://{S3_BUCKET}/{S3_PREFIX}/"
PLAN_FILENAME = "gold_plan_horario.parquet"
SUMMARY_FILENAME = "gold_resumen_diario.parquet"
TIMEZONE = "Europe/Madrid"
PLAN_NUMERIC = [
	"precio_eur_mwh", "consumo_baseline_mwh", "consumo_optimizado_mwh",
	"coste_baseline_eur", "coste_optimizado_eur",
]
SUMMARY_TOTALS = {
	"consumo_baseline_total_mwh": "consumo_baseline_mwh",
	"consumo_optimizado_total_mwh": "consumo_optimizado_mwh",
	"coste_baseline_total_eur": "coste_baseline_eur",
	"coste_optimizado_total_eur": "coste_optimizado_eur",
}


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


def load_gold_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
	"""Load matching hourly and daily results; timestamps come from local time."""
	plan = read_table(PLAN_FILENAME, ["datetime_local", "fecha_local", *PLAN_NUMERIC])
	summary = read_table(SUMMARY_FILENAME, [
		"fecha_local", "horas_del_dia", "energia_flexible_objetivo_mwh",
		"limite_flexible_mwh_por_hora", "politica_negativos", "estado_optimizacion",
		*SUMMARY_TOTALS, "ahorro_eur", "ahorro_pct",
	])
	if summary.empty:
		raise ValueError("El resumen diario no contiene fechas.")
	for table in (plan, summary):
		table["fecha_local"] = pd.to_datetime(table["fecha_local"], format="%Y-%m-%d", errors="raise").dt.date
		if table["fecha_local"].isna().any():
			raise ValueError("Hay fechas locales vacías.")
	if summary["fecha_local"].duplicated().any():
		raise ValueError("El resumen contiene fechas duplicadas.")
	if not summary["estado_optimizacion"].isin(["optimo", "dia_incompleto", "infactible"]).all():
		raise ValueError("El resumen contiene estados de optimización desconocidos.")
	numeric_columns(plan, PLAN_NUMERIC, PLAN_FILENAME)
	numeric_columns(summary, ["horas_del_dia", "energia_flexible_objetivo_mwh", "limite_flexible_mwh_por_hora"], SUMMARY_FILENAME)
	if not summary["horas_del_dia"].ge(0).all() or not (summary["horas_del_dia"] % 1 == 0).all():
		raise ValueError("El número de horas debe ser un entero no negativo.")
	if not summary[["energia_flexible_objetivo_mwh", "limite_flexible_mwh_por_hora"]].gt(0).all().all():
		raise ValueError("La energía objetivo y el límite horario deben ser positivos.")
	plan["datetime_local"] = pd.to_datetime(plan["datetime_local"], utc=True, errors="raise").dt.tz_convert(TIMEZONE)
	if plan["datetime_local"].isna().any() or plan["datetime_local"].duplicated().any():
		raise ValueError("El plan contiene horas vacías o duplicadas.")
	if not (plan["datetime_local"].dt.date == plan["fecha_local"]).all():
		raise ValueError("La fecha del plan no coincide con datetime_local en Europe/Madrid.")
	valid = summary[summary["estado_optimizacion"] == "optimo"].copy()
	numeric_columns(valid, [*SUMMARY_TOTALS, "ahorro_eur"], SUMMARY_FILENAME)
	if not plan["fecha_local"].isin(valid["fecha_local"]).all():
		raise ValueError("El plan incluye fechas sin un resumen óptimo correspondiente.")
	for daily in valid.itertuples(index=False):
		schedule = plan[plan["fecha_local"] == daily.fecha_local].sort_values("datetime_local")
		start = pd.Timestamp(daily.fecha_local, tz=TIMEZONE)
		end = pd.Timestamp(daily.fecha_local + pd.Timedelta(days=1), tz=TIMEZONE)
		expected = pd.date_range(start, end, freq="h", inclusive="left")
		if daily.horas_del_dia != len(expected) or schedule["datetime_local"].tolist() != expected.tolist():
			raise ValueError(f"{daily.fecha_local}: faltan horas o no coinciden con el día local completo.")
		for total_column, hourly_column in SUMMARY_TOTALS.items():
			if not np.isclose(schedule[hourly_column].sum(), getattr(daily, total_column), atol=1e-4, rtol=0):
				raise ValueError(f"{daily.fecha_local}: {total_column} no coincide entre las dos tablas.")
		for scenario in ("baseline", "optimizado"):
			consumption = schedule[f"consumo_{scenario}_mwh"]
			if not consumption.between(0, daily.limite_flexible_mwh_por_hora).all():
				raise ValueError(f"{daily.fecha_local}: consumo {scenario} fuera del límite horario.")
			if not np.isclose(consumption.sum(), daily.energia_flexible_objetivo_mwh, atol=1e-5, rtol=0):
				raise ValueError(f"{daily.fecha_local}: energía diaria {scenario} distinta del objetivo.")
			if not np.allclose(schedule["precio_eur_mwh"] * consumption, schedule[f"coste_{scenario}_eur"], atol=1e-4, rtol=0):
				raise ValueError(f"{daily.fecha_local}: coste {scenario} distinto de precio por consumo.")
		saving = daily.coste_baseline_total_eur - daily.coste_optimizado_total_eur
		if not np.isclose(saving, daily.ahorro_eur, atol=1e-4, rtol=0):
			raise ValueError(f"{daily.fecha_local}: ahorro distinto de coste S0 menos coste S1.")
	summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].replace(0, float("nan")) * 100
	return plan.sort_values("datetime_local").reset_index(drop=True), summary.sort_values("fecha_local").reset_index(drop=True)


def monthly_results(summary: pd.DataFrame) -> pd.DataFrame:
	valid = summary[summary["estado_optimizacion"] == "optimo"].copy()
	valid["month"] = pd.to_datetime(valid["fecha_local"]).dt.to_period("M").astype(str)
	return valid.groupby("month", as_index=False, sort=True).agg(
		cost_s0_eur=("coste_baseline_total_eur", "sum"),
		cost_s1_eur=("coste_optimizado_total_eur", "sum"),
		saving_eur=("ahorro_eur", "sum"),
		days=("fecha_local", "count"),
	)
