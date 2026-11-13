"""Read a single published desaladora run in memory, never legacy or local data."""

from contextlib import closing
import hashlib
from io import BytesIO
import json
import re

import boto3
import numpy as np
import pandas as pd
import yaml

from data_loader import S3_BUCKET, S3_REGION, TIMEZONE, numeric_columns

PREFIX = "outputs/desaladora_som_energia"
DESALADORA_S3_URI = f"s3://{S3_BUCKET}/{PREFIX}/latest.json"
COMPONENTS = [
    "precio_eur_mwh", "pc_eur_mwh", "sc_eur_mwh", "dsv_eur_mwh",
    "gdo_eur_mwh", "posom_eur_mwh", "perdidas_eur_mwh",
    "fe_eur_mwh", "f_eur_mwh", "ajuste_formula_eur_mwh",
    "peaje_energia_eur_mwh", "cargo_energia_eur_mwh",
]
COSTS = [
    f"coste_energia_{scope}_{scenario}_eur"
    for scope in ("flexible", "planta") for scenario in ("baseline", "optimizado")
]
FILES = ("programacion_horaria.parquet", "resumen_diario.parquet", "resumen_mensual.parquet")


def load_desaladora_tables() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Resolve latest once and verify hashes, coverage and published cost totals."""
    client = boto3.client("s3", region_name=S3_REGION)

    def read(key: str) -> bytes:
        response = client.get_object(Bucket=S3_BUCKET, Key=key)
        with closing(response["Body"]) as body:
            return body.read()

    pointer = json.loads(read(f"{PREFIX}/latest.json"))
    if not isinstance(pointer, dict) or not isinstance(pointer.get("metadata_key"), str):
        raise ValueError("latest.json: falta metadata_key.")
    key = pointer["metadata_key"]
    if not re.fullmatch(rf"{PREFIX}/runs/[0-9a-f]{{32}}/metadata\.json", key):
        raise ValueError("latest.json: metadata_key no identifica una ejecucion versionada.")
    metadata = json.loads(read(key))
    if not isinstance(metadata, dict) or metadata.get("schema") != "desaladora_som_energia_v1":
        raise ValueError("Metadata del caso desaladora: schema no soportado.")
    if (metadata.get("es_simulacion") is not True
            or metadata.get("criterio_optimizacion") != "precio_indexado_eur_mwh"):
        raise ValueError("Metadata sin simulacion u optimizacion por precio indexado.")
    config_yaml = metadata["config_yaml"]
    if not isinstance(config_yaml, str):
        raise ValueError("Metadata: config_yaml debe ser texto.")
    if hashlib.sha256(config_yaml.encode("utf-8")).hexdigest() != metadata["config_sha256"]:
        raise ValueError("La huella de la configuracion YAML no coincide.")
    cfg = yaml.safe_load(config_yaml)
    if not isinstance(cfg, dict) or cfg.get("version_config") != 2:
        raise ValueError("Configuracion publicada no soportada.")
    tables = []
    for name in FILES:
        output_key = f"{key.rsplit('/', 1)[0]}/{name}"
        if metadata["outputs_s3"][name] != output_key:
            raise ValueError(f"{name}: no pertenece a la misma ejecucion.")
        content = read(output_key)
        if hashlib.sha256(content).hexdigest() != metadata["outputs_sha256"][name]:
            raise ValueError(f"{name}: la huella SHA256 no coincide.")
        tables.append(pd.read_parquet(BytesIO(content)))
    plan, summary, monthly = tables
    if any(table.empty for table in tables):
        raise ValueError("La ejecucion desaladora debe contener resultados.")
    for table in (plan, summary):
        table["fecha_local"] = pd.to_datetime(table["fecha_local"], errors="raise").dt.date
        if table["fecha_local"].isna().any():
            raise ValueError("Fecha local vacia en la ejecucion desaladora.")
    summary = summary.sort_values("fecha_local").reset_index(drop=True)
    expected_dates = pd.date_range(summary["fecha_local"].min(), summary["fecha_local"].max()).date.tolist()
    if summary["fecha_local"].tolist() != expected_dates:
        raise ValueError("El resumen diario debe registrar tambien los dias sin programacion.")
    if not summary["estado_optimizacion"].isin(["optimo", "sin_datos", "dia_incompleto"]).all():
        raise ValueError("Estado diario de optimizacion desconocido.")
    numeric_columns(plan, [
        *COMPONENTS, *COSTS, "precio_indexado_eur_mwh", "consumo_no_flexible_mwh",
        "consumo_baseline_mwh", "consumo_optimizado_mwh",
        "consumo_planta_baseline_mwh", "consumo_planta_optimizado_mwh",
        "potencia_contratada_mw",
    ], FILES[0])
    plan["datetime_local"] = pd.to_datetime(plan["datetime_utc"], utc=True, errors="raise").dt.tz_convert(TIMEZONE)
    if plan["datetime_local"].isna().any() or plan["datetime_local"].duplicated().any():
        raise ValueError("Timestamp horario vacio o duplicado.")
    if not plan["datetime_local"].dt.date.equals(plan["fecha_local"]):
        raise ValueError("Fecha local distinta del timestamp horario.")
    if not plan["periodo_tarifario"].isin(["P1", "P2", "P3", "P4", "P5", "P6"]).all():
        raise ValueError("Periodo tarifario desconocido.")
    if (metadata["tarifa"]["anio"] != cfg["tarifa"]["anio_regulatorio"]["value"]
            or not plan["datetime_local"].dt.year.eq(metadata["tarifa"]["anio"]).all()):
        raise ValueError("La programacion esta fuera de la vigencia tarifaria declarada.")
    if not np.allclose(plan[COMPONENTS].sum(axis=1), plan["precio_indexado_eur_mwh"], atol=1e-8, rtol=0):
        raise ValueError("El desglose no suma el precio indexado.")
    optimum = summary[summary["estado_optimizacion"] == "optimo"]
    if set(plan["fecha_local"]) != set(optimum["fecha_local"]):
        raise ValueError("La programacion y los dias optimos no coinciden.")
    energy = cfg["carga_flexible"]["energia_diaria_mwh"]["value"]
    limit = cfg["carga_flexible"]["limite_mwh_hora"]["value"]
    for day, schedule in plan.groupby("fecha_local", sort=True):
        start = pd.Timestamp(day, tz=TIMEZONE)
        end = pd.Timestamp(day + pd.Timedelta(days=1), tz=TIMEZONE)
        if schedule["datetime_local"].tolist() != pd.date_range(start, end, freq="h", inclusive="left").tolist():
            raise ValueError(f"{day}: programacion horaria incompleta o desordenada.")
        for scenario in ("baseline", "optimizado"):
            flexible = schedule[f"consumo_{scenario}_mwh"]
            plant = schedule[f"consumo_planta_{scenario}_mwh"]
            if (not flexible.between(0, limit).all()
                    or not np.isclose(flexible.sum(), energy, atol=1e-8, rtol=0)):
                raise ValueError(f"{day}: energia flexible invalida.")
            if ((schedule["consumo_no_flexible_mwh"] < 0).any()
                    or not np.allclose(plant, flexible + schedule["consumo_no_flexible_mwh"], atol=1e-8, rtol=0)
                    or (plant > schedule["potencia_contratada_mw"] + 1e-8).any()):
                raise ValueError(f"{day}: consumo de planta incoherente con potencia.")
            for scope, consumption in (("flexible", flexible), ("planta", plant)):
                if not np.allclose(
                    consumption * schedule["precio_indexado_eur_mwh"],
                    schedule[f"coste_energia_{scope}_{scenario}_eur"], atol=1e-7, rtol=0,
                ):
                    raise ValueError(f"{day}: coste de energia incoherente.")
    numeric_columns(optimum, [*COSTS, "ahorro_energia_eur"], FILES[1])
    totals = plan.groupby("fecha_local")[COSTS].sum()
    if not np.allclose(optimum[COSTS], totals.reindex(optimum["fecha_local"]), atol=1e-7, rtol=0):
        raise ValueError("Los costes diarios no coinciden con la programacion.")
    savings = optimum[COSTS[0]] - optimum[COSTS[1]]
    if not np.allclose(optimum["ahorro_energia_eur"], savings, atol=1e-7, rtol=0):
        raise ValueError("El ahorro diario no coincide con S0 menos S1.")
    monthly = monthly.sort_values("mes").reset_index(drop=True)
    expected_monthly = summary.groupby(pd.to_datetime(summary["fecha_local"]).dt.strftime("%Y-%m"))
    aggregated = expected_monthly[[*COSTS, "ahorro_energia_eur"]].sum(min_count=1)
    if (monthly["mes"].tolist() != aggregated.index.tolist()
            or not np.allclose(monthly[[*COSTS, "ahorro_energia_eur"]], aggregated, atol=1e-7, rtol=0, equal_nan=True)
            or not np.array_equal(monthly["dias_esperados"], expected_monthly.size())
            or not np.array_equal(monthly["dias_sin_programacion"], monthly["dias_esperados"] - monthly["dias_optimos"])
            or not np.array_equal(monthly["dias_optimos"], expected_monthly["estado_optimizacion"].agg(lambda s: s.eq("optimo").sum()))):
        raise ValueError("El resumen mensual no coincide con el diario.")
    if (metadata["dias_optimos"] != len(optimum) or metadata["dias_esperados"] != len(summary)
            or metadata["fecha_primera_programacion"] != str(plan["fecha_local"].min())
            or metadata["fecha_ultima_programacion"] != str(plan["fecha_local"].max())):
        raise ValueError("La cobertura declarada no coincide con las tablas.")
    # Adapt published results to the existing overview and trend view contract.
    for scenario in ("baseline", "optimizado"):
        summary[f"coste_{scenario}_total_eur"] = summary[f"coste_energia_flexible_{scenario}_eur"]
    summary["ahorro_eur"] = summary["ahorro_energia_eur"]
    summary["ahorro_pct"] = summary["ahorro_eur"] / summary["coste_baseline_total_eur"].where(
        summary["coste_baseline_total_eur"] > 0
    ) * 100
    monthly = monthly.rename(columns={"mes": "month", "ahorro_energia_eur": "saving_eur", "dias_optimos": "days"})
    monthly["ahorro_estimado_anual_eur"] = float(summary["ahorro_eur"].sum())
    return metadata, monthly, summary, plan
