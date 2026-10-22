"""03 - Gold: plan horario y resumen diario del caso 4 (Energy Optimizer).
 
Entrada : data/processed/redata/precios_horarios.json  (silver: precio spot por hora)
Salida  : dos tablas en formato Parquet en data/outputs/redata/
            gold_plan_horario.parquet     una fila por MES (12 filas) con: precio spot
                                          medio mensual, ahorro estimado mensual, precio
                                          spot medio anual y ahorro estimado anual
            gold_resumen_diario.parquet   una fila por dia local
          y, si S3_BUCKET esta definido, se suben a s3://<bucket>/outputs/redata/.
          Tipos de gold_resumen_diario: fecha_local es una fecha.
 
Para cada dia LOCAL (Europe/Madrid, con 23, 24 o 25 horas reales):
    - Baseline:   2,5 MWh por hora de 08:00 a 20:00 (sin incluir la hora que empieza
                  a las 20:00) -> 12 horas x 2,5 = 30 MWh
    - Optimizado: los mismos 30 MWh, con un maximo de 7 MWh por hora, ocupando
                  las horas de la mas barata a la mas cara en franjas de 7 MWh
                  (7 + 7 + 7 + 7 + 2). Optimo para este problema lineal sin mas
                  restricciones; no hace falta PuLP.
                  Desempate de precios iguales: 1) hora dentro de la franja
                  08:00-17:00, 2) la mas temprana.
    - Coste = precio_eur_mwh x consumo. Solo componente de mercado: sin peajes,
              cargos ni impuestos.
 
Los precios vienen de la API (via silver); los consumos son el escenario del reto.
 
Uso (desde la raiz del repo):
    python notebooks/03_gold_redata.py
    python notebooks/03_gold_redata.py --no-s3
"""
import argparse
import json
import os
from pathlib import Path
 
import pandas as pd
from dotenv import load_dotenv
 
load_dotenv()

BUCKET = os.getenv("S3_BUCKET")
SILVER = Path("data/processed/redata/precios_horarios.json")
OUT_DIR = Path("data/outputs/redata")
SPOT_TITLE = "Precio mercado spot"
TZ_LOCAL = "Europe/Madrid"
 
# Parametros del caso 4 (no vienen de la API)
ENERGIA_DIARIA_MWH = 30.0
LIMITE_MWH_HORA = 7.0
BASELINE_MWH_HORA = 2.5
BASELINE_HORA_INICIO = 8   # 08:00
BASELINE_HORA_FIN = 20     # hasta las 20:00, sin incluir la hora que empieza a las 20:00
# Franja preferente para desempatar precios iguales: de 08:00 a 17:00
# (horas que empiezan entre las 08:00 y las 16:00; la que empieza a las 17:00 no entra)
FRANJA_PREFERENTE_INICIO = 8
FRANJA_PREFERENTE_FIN = 17
POLITICA_NEGATIVOS = "cero_antes_media_horaria"  # aplicada ya en silver
HORAS_VALIDAS = (23, 24, 25)  # 24 normal; 23 en primavera; 25 en otono
 
 
def load_silver(path: Path) -> pd.DataFrame:
    """Lee el JSON silver y devuelve (datetime_utc, datetime_local, fecha_local, precio)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    serie = next(s for s in payload["included"] if s["attributes"]["title"] == SPOT_TITLE)
    df = pd.DataFrame(serie["attributes"]["values"]).rename(columns={"value": "precio_eur_mwh"})
    df["datetime_utc"] = pd.to_datetime(df["datetime"], utc=True)
    df["datetime_local"] = df["datetime_utc"].dt.tz_convert(TZ_LOCAL)
    df["fecha_local"] = df["datetime_local"].dt.date
    df = df.drop(columns="datetime").sort_values("datetime_utc").reset_index(drop=True)
    return df
 
 
def plan_dia(dia: pd.DataFrame) -> pd.DataFrame:
    """Baseline y asignacion optimizada (horas mas baratas primero) de un dia."""
    dia = dia.copy()
    en_baseline = dia["datetime_local"].dt.hour.between(BASELINE_HORA_INICIO, BASELINE_HORA_FIN - 1)
    dia["consumo_baseline_mwh"] = BASELINE_MWH_HORA * en_baseline.astype(float)
 
    # Orden de llenado, de la hora mas barata a la mas cara:
    #   1) precio mas bajo
    #   2) en empate de precio, primero la hora que cae en la franja 08:00-17:00
    #   3) si aun empatan, la mas temprana (resultado reproducible)
    en_franja = dia["datetime_local"].dt.hour.between(FRANJA_PREFERENTE_INICIO, FRANJA_PREFERENTE_FIN - 1)
    orden = (
        dia.assign(fuera_franja=~en_franja)
        .sort_values(["precio_eur_mwh", "fuera_franja", "datetime_utc"])
        .index
    )
 
    # Reparto en franjas de 7 MWh (7 + 7 + 7 + 7 + 2 con 30 MWh y limite de 7)
    asignado = pd.Series(0.0, index=dia.index)
    restante = ENERGIA_DIARIA_MWH
    for idx in orden:
        x = min(LIMITE_MWH_HORA, restante)
        asignado[idx] = x
        restante -= x
        if restante <= 0:
            break
    dia["consumo_optimizado_mwh"] = asignado
    return dia
 
 
def build_gold(silver: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    planes, resumenes = [], []
    for fecha, dia in silver.groupby("fecha_local", sort=True):
        n = len(dia)
        fila = {
            "fecha_local": fecha,
            "horas_del_dia": n,
            "energia_flexible_objetivo_mwh": ENERGIA_DIARIA_MWH,
            "limite_flexible_mwh_por_hora": LIMITE_MWH_HORA,
            "politica_negativos": POLITICA_NEGATIVOS,
        }
        if n not in HORAS_VALIDAS:
            # dia con datos incompletos: no se optimiza para no dar un ahorro engañoso
            fila["estado_optimizacion"] = "dia_incompleto"
            resumenes.append(fila)
            print(f"  AVISO: {fecha} tiene {n} horas (se esperaban 23, 24 o 25); se omite")
            continue
        if n * LIMITE_MWH_HORA < ENERGIA_DIARIA_MWH:
            fila["estado_optimizacion"] = "infactible"
            resumenes.append(fila)
            continue
 
        p = plan_dia(dia)
        p["coste_baseline_eur"] = (p["precio_eur_mwh"] * p["consumo_baseline_mwh"]).round(5)
        p["coste_optimizado_eur"] = (p["precio_eur_mwh"] * p["consumo_optimizado_mwh"]).round(5)
        planes.append(p)
 
        cb = round(p["coste_baseline_eur"].sum(), 5)
        co = round(p["coste_optimizado_eur"].sum(), 5)
        ahorro = round(cb - co, 5)
        fila.update({
            "estado_optimizacion": "optimo",
            "consumo_baseline_total_mwh": round(p["consumo_baseline_mwh"].sum(), 5),
            "consumo_optimizado_total_mwh": round(p["consumo_optimizado_mwh"].sum(), 5),
            "coste_baseline_total_eur": cb,
            "coste_optimizado_total_eur": co,
            "ahorro_eur": ahorro,
            "ahorro_pct": round(100 * ahorro / cb, 6) if cb else None,
        })
        resumenes.append(fila)
 
    if not planes:
        raise ValueError("Ningun dia se ha podido optimizar: revisa el silver (dias incompletos)")
    plan = pd.concat(planes, ignore_index=True)
    # datetime_utc se usa solo internamente (orden y desempate); no se incluye en la salida.
    # datetime_local (con su desfase) sigue siendo unico por fila.
    plan = plan[[
        "datetime_local", "fecha_local", "precio_eur_mwh",
        "consumo_baseline_mwh", "consumo_optimizado_mwh",
        "coste_baseline_eur", "coste_optimizado_eur",
    ]]
 
    resumen = pd.DataFrame(resumenes).reindex(columns=[
        "fecha_local", "horas_del_dia", "energia_flexible_objetivo_mwh",
        "limite_flexible_mwh_por_hora", "politica_negativos", "estado_optimizacion",
        "consumo_baseline_total_mwh", "consumo_optimizado_total_mwh",
        "coste_baseline_total_eur", "coste_optimizado_total_eur",
        "ahorro_eur", "ahorro_pct",
    ])
    return plan, resumen
 
 
def build_mensual(plan: pd.DataFrame, resumen: pd.DataFrame) -> pd.DataFrame:
    """Tabla mensual a partir del plan horario y del resumen diario (solo dias optimos).
 
    Una fila por mes. Los campos anuales se repiten en cada fila.
      precio_spot_medio_mensual_eur_mwh : media de los precios horarios del mes
      ahorro_estimado_mensual_eur       : suma del ahorro diario del mes
      precio_spot_medio_anual_eur_mwh   : media de los precios horarios del periodo
      ahorro_estimado_anual_eur         : suma del ahorro diario del periodo
    """
    p = plan.assign(mes=pd.to_datetime(plan["fecha_local"]).dt.strftime("%Y-%m"))
    ok = resumen[resumen["estado_optimizacion"] == "optimo"]
    r = ok.assign(mes=pd.to_datetime(ok["fecha_local"]).dt.strftime("%Y-%m"))
 
    mensual = pd.DataFrame({
        "precio_spot_medio_mensual_eur_mwh": p.groupby("mes")["precio_eur_mwh"].mean().round(4),
        "ahorro_estimado_mensual_eur": r.groupby("mes")["ahorro_eur"].sum().round(5),
    }).reset_index()
    mensual["precio_spot_medio_anual_eur_mwh"] = round(p["precio_eur_mwh"].mean(), 4)
    mensual["ahorro_estimado_anual_eur"] = round(r["ahorro_eur"].sum(), 5)
    return mensual
 
 
def upload_s3(path: Path) -> None:
    import boto3  # acceso por rol IAM de la EC2, sin claves en el codigo
 
    key = f"outputs/redata/{path.name}"
    boto3.client("s3").upload_file(str(path), BUCKET, key)
    print(f"  subido a s3://{BUCKET}/{key}")
 
 
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-s3", action="store_true", help="solo local")
    args = ap.parse_args()
 
    if not SILVER.exists():
        raise FileNotFoundError(f"No existe {SILVER}. Ejecuta antes 02_calidad_redata.py")
    plan, resumen = build_gold(load_silver(SILVER))
 
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = OUT_DIR / "gold_plan_horario.parquet"
    resumen_path = OUT_DIR / "gold_resumen_diario.parquet"
    mensual = build_mensual(plan, resumen)
    mensual.to_parquet(plan_path, index=False)  # gold_plan_horario: ahora tabla mensual
    resumen.to_parquet(resumen_path, index=False)
 
    ok = resumen[resumen["estado_optimizacion"] == "optimo"]
    print(f"Dias: {len(resumen)} (optimos: {len(ok)}) | horas en el plan: {len(plan)}")
    if len(ok):
        # % ponderado: ahorro total / coste baseline total (la media de los % diarios
        # se distorsiona con dias de precios casi 0, donde el % sale ~100 %)
        pct = 100 * ok["ahorro_eur"].sum() / ok["coste_baseline_total_eur"].sum()
        print(f"Ahorro total: {ok['ahorro_eur'].sum():.2f} EUR | ahorro ponderado: {pct:.2f} %")
    print(f"Guardado {plan_path} y {resumen_path}")
    if BUCKET and not args.no_s3:
        upload_s3(plan_path)
        upload_s3(resumen_path)
 
 
if __name__ == "__main__":
    main()
