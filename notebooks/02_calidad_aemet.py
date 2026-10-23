"""02 - Calidad: capa raw (bronze) -> capa processed (silver).

Entrada : data/raw/aemet/aemet_*.json  (AEMET OpenData, climatologias diarias, tal cual de la API)
Salida  : un JSON con una lista de registros, UNO POR ESTACION (localidad) Y DIA, con solo:
            fecha, indicativo, localidad, provincia, tmax, tmin, tmed, hora_tmax, hora_tmin

Silver NO agrega: conserva el dato de cada estacion. Las medias y los extremos nacionales
se calculan en gold.

Orden de la limpieza:
    1. aplana todos los JSON raw y se queda con las columnas necesarias
    2. fecha -> tipo date ; temperaturas "12,3" -> 12.3 (punto decimal) ;
       provincia en mayusculas y con un unico nombre (ver PROVINCIAS_EQUIV) ;
       localidad sin espacios sobrantes
    3. elimina filas sin estacion, fecha o provincia
    4. elimina duplicados (indicativo, fecha) (se queda con el ultimo leido)
    5. temperaturas fuera de rango fisico -> nulo
    6. elimina filas sin ninguna temperatura
    7. horas "HH:MM" normalizadas (lo que no sea una hora valida, p. ej. "Varias" -> nulo);
       si no hay temperatura, su hora tambien es nula

Los valores que no existen se quedan como nulo (null en el JSON), nunca como 0.

Guarda:
    data/processed/aemet/aemet_diario.json     (una fila por estacion y dia)
    data/processed/aemet/calidad_aemet.json    (informe corto)
y, si S3_BUCKET esta definido, los sube a s3://<bucket>/processed/aemet/.

Uso (desde la raiz del repo):
    python notebooks/02_calidad_aemet.py
    python notebooks/02_calidad_aemet.py --no-s3
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BUCKET = os.getenv("S3_BUCKET")
RAW_DIR = Path("data/raw/aemet")
OUT_DIR = Path("data/processed/aemet")

# columnas que se leen de bronze
RAW_COLS = ["fecha", "indicativo", "nombre", "provincia", "tmax", "tmin", "tmed", "horatmax", "horatmin"]
TEMP_COLS = ["tmax", "tmin", "tmed"]

# rango fisico razonable (min, max) en grados C para Espana; fuera -> nulo
RANGO_TEMP = (-50, 55)

# AEMET escribe algunas provincias de varias formas: se unifican a un solo nombre
PROVINCIAS_EQUIV = {
    "ILLES BALEARS": "BALEARES",
    "STA. CRUZ DE TENERIFE": "SANTA CRUZ DE TENERIFE",
}

OUT_COLS = ["fecha", "indicativo", "localidad", "provincia", "tmax", "tmin", "tmed", "hora_tmax", "hora_tmin"]


def to_num(s: pd.Series) -> pd.Series:
    """Texto con coma decimal -> float con punto (lo que no se pueda convertir, NaN)."""
    txt = s.astype("string").str.replace(",", ".", regex=False)
    return pd.to_numeric(txt, errors="coerce").astype("float64")


def normalizar_hora(s: pd.Series) -> pd.Series:
    """'9:05' -> '09:05'. 'Varias', vacios u horas invalidas -> nulo."""
    partes = s.astype("string").str.strip().str.extract(r"^(\d{1,2}):(\d{2})$")
    h = pd.to_numeric(partes[0], errors="coerce")
    m = pd.to_numeric(partes[1], errors="coerce")
    valida = (h <= 23) & (m <= 59)
    texto = h.astype("Int64").astype("string").str.zfill(2) + ":" + m.astype("Int64").astype("string").str.zfill(2)
    return texto.where(valida).astype(object)


def load_aemet(raw_dir: Path, filenames: list[str] | None = None) -> pd.DataFrame:
    """Aplana todos los JSON raw en una tabla con las columnas RAW_COLS."""
    frames = []
    files = (sorted(raw_dir.glob("aemet_*.json")) if filenames is None
             else [raw_dir / name for name in filenames])
    if not files:
        if filenames is not None:
            return pd.DataFrame(columns=RAW_COLS)
        raise FileNotFoundError(f"No hay JSON en {raw_dir}. Ejecuta antes 01_ingesta_aemet.py")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            print(f"  AVISO: {path.name} no contiene una lista de registros")
            continue
        frames.append(pd.DataFrame(payload))
    df = pd.concat(frames, ignore_index=True)
    # algunas columnas pueden no venir en ningun registro: las creamos vacias
    return df.reindex(columns=RAW_COLS)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Tipos, duplicados, rangos y filas vacias. Devuelve (tabla por estacion y dia, informe)."""
    report = {"rows_read": int(len(df))}
    df = df.copy()

    # 2. tipos: fecha como date, temperaturas como float con punto
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date
    df["provincia"] = df["provincia"].astype("string").str.strip().str.upper()
    df["provincia"] = df["provincia"].replace("", pd.NA)
    report["rows_with_province_name_unified"] = int(df["provincia"].isin(list(PROVINCIAS_EQUIV)).sum())
    df["provincia"] = df["provincia"].replace(PROVINCIAS_EQUIV)
    # localidad: quita espacios sobrantes (algunos nombres de AEMET traen espacios al final)
    df["localidad"] = (
        df["nombre"].astype("string").str.replace(r"\s+", " ", regex=True).str.strip().replace("", pd.NA)
    )
    for col in TEMP_COLS:
        df[col] = to_num(df[col])

    # 3. sin estacion, fecha o provincia no se puede identificar el dato
    rows_before = len(df)
    df = df.dropna(subset=["indicativo", "fecha", "provincia"])
    report["rows_without_station_date_or_province_removed"] = rows_before - len(df)

    # 4. los trozos descargados pueden solaparse: nos quedamos con el ultimo leido
    dup = df.duplicated(subset=["indicativo", "fecha"], keep="last")
    report["duplicate_rows_removed"] = int(dup.sum())
    df = df[~dup]

    # 5. temperaturas imposibles -> nulo (se conserva el resto de la fila)
    lo, hi = RANGO_TEMP
    out_of_range = {}
    for col in TEMP_COLS:
        bad = (df[col] < lo) | (df[col] > hi)
        out_of_range[col] = int(bad.sum())
        df.loc[bad, col] = np.nan
    report["out_of_range_set_to_null"] = out_of_range

    # 6. filas sin ninguna temperatura
    rows_before = len(df)
    df = df.dropna(subset=TEMP_COLS, how="all")
    report["rows_without_any_temperature_removed"] = rows_before - len(df)

    # coherencia tmin <= tmed <= tmax por estacion (solo informa, no modifica)
    incoherent = (df["tmin"] > df["tmed"]) | (df["tmed"] > df["tmax"]) | (df["tmin"] > df["tmax"])
    report["rows_with_incoherent_temperatures"] = int(incoherent.sum())

    # 7. horas normalizadas a 'HH:MM' (invalidas -> nulo); sin temperatura no hay hora
    df["hora_tmax"] = normalizar_hora(df["horatmax"])
    df["hora_tmin"] = normalizar_hora(df["horatmin"])
    report["hours_not_valid_or_missing"] = {
        "hora_tmax": int(df["hora_tmax"].isna().sum()),
        "hora_tmin": int(df["hora_tmin"].isna().sum()),
    }
    df.loc[df["tmax"].isna(), "hora_tmax"] = None
    df.loc[df["tmin"].isna(), "hora_tmin"] = None

    out = df[OUT_COLS].sort_values(["fecha", "provincia", "indicativo"]).reset_index(drop=True)

    # informe del resultado
    per_prov_day = out.groupby(["fecha", "provincia"]).size()
    report["rows_output"] = int(len(out))
    report["stations"] = int(out["indicativo"].nunique())
    report["provinces"] = int(out["provincia"].nunique())
    report["days"] = int(out["fecha"].nunique())
    report["date_min"] = str(out["fecha"].min()) if len(out) else None
    report["date_max"] = str(out["fecha"].max()) if len(out) else None
    report["stations_per_province_day"] = {
        "min": int(per_prov_day.min()) if len(per_prov_day) else None,
        "mean": round(float(per_prov_day.mean()), 2) if len(per_prov_day) else None,
        "max": int(per_prov_day.max()) if len(per_prov_day) else None,
    }
    report["null_values_per_column"] = {
        c: int(out[c].isna().sum()) for c in ["localidad", "tmax", "tmin", "tmed", "hora_tmax", "hora_tmin"]
    }
    return out, report


def latest_ingestion_files(raw_dir: Path) -> list[str] | None:
    path = raw_dir / "last_ingestion.json"
    if not path.exists():
        print("Sin registro de última ingesta: informe de calidad del histórico completo.")
        return None
    scope = json.loads(path.read_text(encoding="utf-8"))
    if scope.get("status") != "completed":
        raise ValueError("La última ingesta AEMET no ha finalizado correctamente.")
    files = scope.get("files")
    if not isinstance(files, list) or any(
        not isinstance(name, str) or Path(name).name != name
        or not name.startswith("aemet_") or not name.endswith(".json")
        for name in files
    ):
        raise ValueError("Lista de archivos de última ingesta AEMET no válida.")
    return files


def to_records(df: pd.DataFrame) -> list[dict]:
    """Lista de registros lista para json (fecha 'YYYY-MM-DD', NaN -> null)."""
    out = df.copy()
    out["fecha"] = out["fecha"].astype(str)
    out["provincia"] = out["provincia"].astype(str)
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")


def upload_s3(path: Path) -> None:
    import boto3  # acceso por rol IAM de la EC2, sin claves en el codigo

    key = f"processed/aemet/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-s3", action="store_true", help="solo local")
    args = ap.parse_args()

    print("Leyendo JSON raw...")
    filenames = latest_ingestion_files(RAW_DIR)
    raw = load_aemet(RAW_DIR)
    df, historical_report = clean(raw)
    if df.empty:
        raise ValueError("No hay temperaturas válidas para generar Silver AEMET.")
    ingested = raw if filenames is None else load_aemet(RAW_DIR, filenames)
    if filenames is None:
        report = historical_report
    else:
        _, report = clean(ingested)
    dates = sorted(pd.to_datetime(ingested["fecha"], errors="raise").dropna().dt.strftime("%Y-%m-%d").unique())
    report["scope"] = "historical" if filenames is None else "last_ingestion"
    report["ingested_files"] = filenames
    report["ingested_dates"] = dates

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data_path = OUT_DIR / "aemet_diario.json"
    rep_path = OUT_DIR / "calidad_aemet.json"
    data_path.write_text(json.dumps(to_records(df), ensure_ascii=False), encoding="utf-8")
    rep_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if filenames == []:
        print("CALIDAD AEMET SIN NOVEDADES: no se han ingestado registros nuevos.")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Silver histórico completo: {len(df)} registros. Guardado {data_path}")
    if BUCKET and not args.no_s3:
        upload_s3(data_path)
        upload_s3(rep_path)


if __name__ == "__main__":
    main()