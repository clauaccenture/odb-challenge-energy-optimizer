"""Caso horario simulado: formula Som Energia con parametros trazables, no factura."""

from datetime import date
import math

import numpy as np
import pandas as pd

from src.config_loader import derivados
from src.tarifas_6_2td import (
    ANIO_TARIFAS,
    CARGOS_ENERGIA_EUR_MWH,
    PEAJES_ENERGIA_EUR_MWH,
    PERIODOS,
    periodo_6_2td,
)


def asignar_carga(
    dia: pd.DataFrame,
    energia_mwh: float,
    limites_mwh: pd.Series,
    precio_col: str,
    franja_inicio: int,
    franja_fin: int,
) -> pd.Series:
    """Llenado por precio marginal; valido solo sin restricciones intertemporales."""
    if limites_mwh.sum() + 1e-9 < energia_mwh:
        raise ValueError("Energia flexible infactible con los limites horarios disponibles.")
    en_franja = dia["datetime_local"].dt.hour.between(franja_inicio, franja_fin - 1)
    orden = dia.assign(fuera_franja=~en_franja).sort_values(
        [precio_col, "fuera_franja", "datetime_utc"]
    ).index
    asignado = pd.Series(0.0, index=dia.index)
    restante = energia_mwh
    for idx in orden:
        cantidad = min(limites_mwh.loc[idx], restante)
        asignado.loc[idx] = cantidad
        restante -= cantidad
        if restante <= 1e-9:
            break
    return asignado


def _numero(valor: object, nombre: str, minimo: float = 0) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"{nombre}: se esperaba un numero.")
    if not math.isfinite(valor) or valor < minimo:
        raise ValueError(f"{nombre}: debe ser finito y >= {minimo}.")
    return float(valor)


def validar_config(cfg: dict) -> None:
    """Rechaza configuraciones no soportadas, sin ignorar restricciones o impuestos."""
    if cfg["version_config"] != 2:
        raise ValueError("El caso desaladora necesita version_config: 2.")
    tarifa, mercado, contrato = cfg["tarifa"], cfg["mercado"], cfg["contrato"]
    if (tarifa["acceso"], tarifa["zona"], tarifa["anio_regulatorio"], tarifa["segmento_cargos"]) != (
        "6.2TD", "peninsula", ANIO_TARIFAS, 4
    ):
        raise ValueError("Solo se soporta 6.2TD Peninsula 2026, segmento de cargos 4.")
    tension = _numero(cfg["planta"]["conexion_kv"], "conexion_kv")
    if not 30 <= tension < 72.5:
        raise ValueError("La tension de acceso debe corresponder a 6.2TD.")
    inicio = (date.fromisoformat(mercado["fecha_inicio"])
              if mercado["fecha_inicio"] is not None else date(ANIO_TARIFAS, 1, 1))
    fin = (date.fromisoformat(mercado["fecha_fin"])
           if mercado["fecha_fin"] is not None else date(ANIO_TARIFAS, 12, 31))
    if not (inicio <= fin and inicio.year == fin.year == ANIO_TARIFAS):
        raise ValueError("La ventana debe estar ordenada y dentro de la vigencia 2026.")
    if (mercado["fuente"], mercado["serie"], mercado["zona_horaria"], mercado["politica_negativos"]) != (
        "REData", "Precio mercado spot", "Europe/Madrid", "sin_truncar"
    ):
        raise ValueError("Se requiere spot REData peninsular sin truncar, Europe/Madrid.")
    if (contrato["modelo"], contrato["resolucion"], contrato["liquidacion_negativos"],
        contrato["criterio_gdo"]) != (
        "som_energia_referencia_v1", "horaria_media_cuartohoraria",
        "sin_suelo_simulado", "historico_sin_impuestos"
    ):
        raise ValueError("Modelo contractual, resolucion o liquidacion no soportados.")
    esperados = {
        "spot": True, "peaje_energia": True, "cargo_energia": True, "perdidas": True,
        "iee": False, "iva": False, "potencia_y_excesos": False,
    }
    if cfg["componentes"] != esperados:
        raise ValueError("Solo se soporta termino de energia indexada, sin factura ni impuestos.")
    for clave in ("volumen_m3_dia", "consumo_especifico_kwh_m3", "dias_operacion_ano"):
        if _numero(cfg["planta"][clave], f"planta.{clave}") == 0:
            raise ValueError(f"planta.{clave}: debe ser positivo.")
    carga = cfg["carga_flexible"]
    for clave in ("energia_diaria_mwh", "limite_mwh_hora"):
        if _numero(carga[clave], f"carga_flexible.{clave}") == 0:
            raise ValueError(f"carga_flexible.{clave}: debe ser positivo.")
    base, opt = cfg["baseline_s0"], cfg["optimizacion_s1"]
    _numero(base["mwh_hora"], "baseline_s0.mwh_hora")
    for seccion, a, b in ((base, "hora_inicio", "hora_fin"),
                          (opt, "franja_preferente_inicio", "franja_preferente_fin")):
        if (type(seccion[a]) is not int or type(seccion[b]) is not int
                or not 0 <= seccion[a] < seccion[b] <= 24):
            raise ValueError(f"{a}/{b}: intervalo horario entero invalido.")
    if base["mwh_hora"] > carga["limite_mwh_hora"]:
        raise ValueError("El baseline supera el limite flexible horario.")
    d = derivados(cfg)
    if d["requiere_programacion_lineal"]:
        raise ValueError("Restricciones operativas activas no implementadas; no se ignoraran.")
    if d["consumo_estimado_mwh_dia"] < carga["energia_diaria_mwh"]:
        raise ValueError("La energia flexible supera el consumo total estimado.")
    for clave in ("factor_formula", "pc_eur_mwh", "sc_eur_mwh", "dsv_eur_mwh",
                  "posom_eur_mwh", "perdidas_fraccion", "fe_eur_mwh", "f_eur_mwh"):
        _numero(contrato[clave], f"contrato.{clave}")
    if contrato["factor_formula"] != 1.015 or contrato["perdidas_fraccion"] >= 1:
        raise ValueError("Factor de formula distinto de 1.015 o perdidas fuera de [0,1).")
    gdo = contrato["gdo_eur_mwh_por_trimestre"]
    if set(gdo) != {"t1", "t2", "t3", "t4"}:
        raise ValueError("Faltan trimestres GdO o hay trimestres desconocidos.")
    for clave, valor in gdo.items():
        _numero(valor, f"gdo.{clave}")
    operacion = cfg["operacion_demo"]
    if (operacion["perfil_no_flexible"] != "uniforme_energia_diaria"
            or operacion["flexibilidad_validada_en_planta"] is not False):
        raise ValueError("Solo se soporta perfil uniforme simulado sin validacion de planta.")
    potencias = operacion["potencia_contratada_mw"]
    if set(potencias) != {p.lower() for p in PERIODOS}:
        raise ValueError("La potencia debe definir exactamente P1-P6.")
    valores = [_numero(potencias[p.lower()], f"potencia.{p}") for p in PERIODOS]
    if valores != sorted(valores) or valores[0] == 0:
        raise ValueError("Se requieren potencias positivas y P1 <= P2 <= ... <= P6.")


def precios_indexados(dia: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Formula publica, aplicada a medias horarias y costes de adquisicion supuestos."""
    p = dia.copy()
    c = cfg["contrato"]
    p["periodo_tarifario"] = [
        periodo_6_2td(t.date(), t.hour) for t in p["datetime_local"]
    ]
    p["peaje_energia_eur_mwh"] = p["periodo_tarifario"].map(PEAJES_ENERGIA_EUR_MWH)
    p["cargo_energia_eur_mwh"] = p["periodo_tarifario"].map(CARGOS_ENERGIA_EUR_MWH)
    for nombre in ("pc", "sc", "dsv", "posom", "fe", "f"):
        p[f"{nombre}_eur_mwh"] = c[f"{nombre}_eur_mwh"]
    p["gdo_eur_mwh"] = [
        c["gdo_eur_mwh_por_trimestre"][f"t{(t.month - 1) // 3 + 1}"]
        for t in p["datetime_local"]
    ]
    adquisicion = p["precio_eur_mwh"] + p[
        ["pc_eur_mwh", "sc_eur_mwh", "dsv_eur_mwh", "gdo_eur_mwh", "posom_eur_mwh"]
    ].sum(axis=1)
    p["perdidas_fraccion"] = c["perdidas_fraccion"]
    p["factor_formula"] = c["factor_formula"]
    p["perdidas_eur_mwh"] = adquisicion * c["perdidas_fraccion"]
    p["adquisicion_con_perdidas_eur_mwh"] = adquisicion + p["perdidas_eur_mwh"]
    p["ajuste_formula_eur_mwh"] = (c["factor_formula"] - 1) * (
        p["adquisicion_con_perdidas_eur_mwh"] + p["fe_eur_mwh"] + p["f_eur_mwh"]
    )
    p["precio_indexado_eur_mwh"] = (
        c["factor_formula"] * (
            p["adquisicion_con_perdidas_eur_mwh"] + p["fe_eur_mwh"] + p["f_eur_mwh"]
        ) + p["peaje_energia_eur_mwh"] + p["cargo_energia_eur_mwh"]
    )
    return p


def build_desaladora(silver: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve horario, diario (incluye ausencias) y mensual; no accede a AWS."""
    validar_config(cfg)
    datos = silver.copy().reset_index(drop=True)
    datos["datetime_utc"] = pd.to_datetime(datos["datetime_utc"], utc=True, errors="raise")
    if datos["datetime_utc"].isna().any():
        raise ValueError("Timestamp UTC vacio en Silver.")
    datos["datetime_local"] = datos["datetime_utc"].dt.tz_convert("Europe/Madrid")
    datos["fecha_local"] = datos["datetime_local"].dt.date
    datos = datos[datos["datetime_local"].dt.year == ANIO_TARIFAS]
    if datos.empty:
        raise ValueError(f"No hay precios Silver dentro de la vigencia tarifaria {ANIO_TARIFAS}.")
    mercado = cfg["mercado"]
    inicio = (date.fromisoformat(mercado["fecha_inicio"])
              if mercado["fecha_inicio"] is not None else datos["fecha_local"].min())
    fin = (date.fromisoformat(mercado["fecha_fin"])
           if mercado["fecha_fin"] is not None else datos["fecha_local"].max())
    datos = datos[datos["fecha_local"].between(inicio, fin)].sort_values("datetime_utc")
    datos["precio_eur_mwh"] = pd.to_numeric(datos["precio_eur_mwh"], errors="raise")
    if not np.isfinite(datos["precio_eur_mwh"].to_numpy(dtype=float)).all():
        raise ValueError("Precio spot vacio o no finito en la ventana del caso.")
    if datos["datetime_utc"].duplicated().any():
        raise ValueError("Timestamp horario duplicado en Silver.")
    if datos.empty:
        raise ValueError("No hay precios Silver dentro de la ventana del caso desaladora.")
    carga, base, opt = cfg["carga_flexible"], cfg["baseline_s0"], cfg["optimizacion_s1"]
    energia = carga["energia_diaria_mwh"]
    no_flexible = derivados(cfg)["consumo_estimado_mwh_dia"] - energia
    grupos = {fecha: dia for fecha, dia in datos.groupby("fecha_local", sort=True)}
    planes, diarios = [], []
    for fecha_ts in pd.date_range(inicio, fin, freq="D"):
        fecha = fecha_ts.date()
        inicio_dia = pd.Timestamp(fecha, tz="Europe/Madrid")
        fin_dia = pd.Timestamp(fecha + pd.Timedelta(days=1), tz="Europe/Madrid")
        esperadas = pd.date_range(inicio_dia, fin_dia, freq="h", inclusive="left")
        dia = grupos.get(fecha)
        fila = {"fecha_local": fecha, "horas_esperadas": len(esperadas),
                "horas_disponibles": 0 if dia is None else len(dia)}
        if dia is None:
            diarios.append({**fila, "estado_optimizacion": "sin_datos"})
            continue
        if not pd.DatetimeIndex(dia["datetime_utc"]).equals(esperadas.tz_convert("UTC")):
            diarios.append({**fila, "estado_optimizacion": "dia_incompleto"})
            continue
        p = precios_indexados(dia, cfg)
        p["consumo_no_flexible_mwh"] = no_flexible / len(p)
        p["potencia_contratada_mw"] = p["periodo_tarifario"].str.lower().map(
            cfg["operacion_demo"]["potencia_contratada_mw"]
        )
        limites = (p["potencia_contratada_mw"] - p["consumo_no_flexible_mwh"]).clip(
            upper=carga["limite_mwh_hora"]
        )
        en_baseline = p["datetime_local"].dt.hour.between(base["hora_inicio"], base["hora_fin"] - 1)
        p["consumo_baseline_mwh"] = base["mwh_hora"] * en_baseline.astype(float)
        if (limites < 0).any() or (p["consumo_baseline_mwh"] > limites + 1e-9).any():
            raise ValueError(f"{fecha}: potencia contratada insuficiente para S0.")
        if not math.isclose(p["consumo_baseline_mwh"].sum(), energia, abs_tol=1e-9):
            raise ValueError(f"{fecha}: baseline no conserva energia; revisar cambio de hora.")
        p["consumo_optimizado_mwh"] = asignar_carga(
            p, energia, limites, "precio_indexado_eur_mwh",
            opt["franja_preferente_inicio"], opt["franja_preferente_fin"],
        )
        for escenario in ("baseline", "optimizado"):
            p[f"consumo_planta_{escenario}_mwh"] = (
                p["consumo_no_flexible_mwh"] + p[f"consumo_{escenario}_mwh"]
            )
            for alcance, consumo in (
                ("flexible", p[f"consumo_{escenario}_mwh"]),
                ("planta", p[f"consumo_planta_{escenario}_mwh"]),
            ):
                columna = f"coste_energia_{alcance}_{escenario}_eur"
                p[columna] = consumo * p["precio_indexado_eur_mwh"]
                fila[columna] = p[columna].sum()
        fila["ahorro_energia_eur"] = (
            fila["coste_energia_flexible_baseline_eur"] - fila["coste_energia_flexible_optimizado_eur"]
        )
        diarios.append({**fila, "estado_optimizacion": "optimo"})
        p["hora_local"] = p["datetime_local"].dt.hour
        planes.append(p)
    if not planes:
        raise ValueError("Ningun dia completo optimizable en la ventana del caso desaladora.")
    plan = pd.concat(planes, ignore_index=True)
    resumen = pd.DataFrame(diarios)
    meses = pd.to_datetime(resumen["fecha_local"]).dt.strftime("%Y-%m")
    costes = [c for c in resumen if c.startswith("coste_") or c == "ahorro_energia_eur"]
    mensual = resumen.groupby(meses)[costes].sum(min_count=1)
    mensual.index.name = "mes"
    mensual["dias_esperados"] = resumen.groupby(meses).size()
    mensual["dias_optimos"] = resumen["estado_optimizacion"].eq("optimo").groupby(meses).sum()
    mensual["dias_sin_programacion"] = mensual["dias_esperados"] - mensual["dias_optimos"]
    return plan, resumen, mensual.reset_index()
