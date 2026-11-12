"""Peajes y cargos regulados del término de energía 6.2TD (Península).

Los datos (peajes, cargos, calendario P1-P6 y festivos) ya NO están en este fichero: viven en
config/config_desaladora.yaml, bloque ``tarifas_reguladas``. Este módulo solo los lee y mantiene
la misma interfaz de siempre (PEAJES_ENERGIA_EUR_MWH, CARGOS_ENERGIA_EUR_MWH, ANIO_TARIFAS,
periodo_6_2td, ...), de modo que 03_gold, la app y los tests no cambian.

La tarifa y el año los eligen ``tarifa.acceso`` y ``tarifa.anio_regulatorio`` del YAML.
Se puede apuntar a otro fichero con la variable de entorno ENERGY_CONFIG.

Fuentes (indicadas junto a cada dato en el YAML):
- Periodos horarios: Circular 3/2020 de la CNMC, art. 7.2 (BOE-A-2020-1066).
- Peajes de transporte y distribución 2026: Resolución CNMC de 18/12/2025,
  Anexo I (BOE-A-2025-26348).
- Cargos 2026: Orden TED/1524/2025, segmento 4 = 6.2TD (BOE-A-2025-26705).

Los importes se expresan en €/MWh (el BOE los publica en €/kWh) y no incluyen
IVA ni el Impuesto Especial sobre la Electricidad.
"""

import os
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from .config_loader import cargar_config

ZONA_PENINSULA = ZoneInfo("Europe/Madrid")
PERIODOS = ("P1", "P2", "P3", "P4", "P5", "P6")

RUTA_CONFIG = Path(os.getenv(
    "ENERGY_CONFIG",
    Path(__file__).resolve().parents[1] / "config" / "config_desaladora.yaml",
))


def _cargar_tarifa(ruta):
    """Lee del YAML los datos de la tarifa y el año elegidos."""
    cfg, _ = cargar_config(ruta)
    acceso = cfg["tarifa"]["acceso"]
    anio = cfg["tarifa"]["anio_regulatorio"]
    bloque = cfg.get("tarifas_reguladas", {}).get(acceso)
    if bloque is None:
        raise ValueError(f"No hay datos regulados de {acceso} en {ruta}")
    datos = bloque["anios"].get(anio)
    if datos is None:
        raise ValueError(f"No hay peajes y cargos de {acceso} para {anio} en {ruta}")
    for clave in ("peajes_energia_eur_mwh", "cargos_energia_eur_mwh"):
        if tuple(datos[clave]) != PERIODOS:
            raise ValueError(f"{clave} de {acceso} {anio} debe tener exactamente {PERIODOS}")
    return anio, bloque["calendario"], bloque["anios"], datos


ANIO_TARIFAS, _CALENDARIO, _ANIOS, _DATOS_ANIO = _cargar_tarifa(RUTA_CONFIG)

PEAJES_ENERGIA_EUR_MWH = dict(_DATOS_ANIO["peajes_energia_eur_mwh"])
CARGOS_ENERGIA_EUR_MWH = dict(_DATOS_ANIO["cargos_energia_eur_mwh"])

# Festivos nacionales de fecha fija y no sustituibles, más el 6 de enero, por año con calendario.
FESTIVOS_NACIONALES = {
    anio: frozenset(d["festivos_nacionales"])
    for anio, d in _ANIOS.items()
    if "festivos_nacionales" in d
}

# Temporada peninsular por mes -> (periodo en horas punta, periodo en horas llano).
_PERIODOS_POR_MES = {int(m): tuple(p) for m, p in _CALENDARIO["periodos_por_mes"].items()}
_HORAS_PUNTA = frozenset(_CALENDARIO["horas_punta"])
_P6_ANTES_DE_HORA = _CALENDARIO["p6_antes_de_hora"]


def es_dia_tipo_d(dia):
    """True si el día es sábado, domingo o festivo nacional (todo el día P6)."""
    if dia.year not in FESTIVOS_NACIONALES:
        raise ValueError(f"No hay calendario de festivos cargado para {dia.year}")
    return dia.weekday() >= 5 or dia in FESTIVOS_NACIONALES[dia.year]


def periodo_6_2td(dia, hora_local):
    """Periodo P1-P6 de una hora local peninsular (0-23) de un día dado."""
    if not 0 <= hora_local <= 23:
        raise ValueError(f"Hora local fuera de rango: {hora_local}")
    if es_dia_tipo_d(dia) or hora_local < _P6_ANTES_DE_HORA:
        return "P6"
    punta, llano = _PERIODOS_POR_MES[dia.month]
    return punta if hora_local in _HORAS_PUNTA else llano


def periodo_desde_datetime(momento):
    """Periodo P1-P6 de un datetime; si tiene zona horaria se pasa a hora peninsular."""
    if momento.tzinfo is not None:
        momento = momento.astimezone(ZONA_PENINSULA)
    return periodo_6_2td(momento.date(), momento.hour)


def termino_regulado_eur_mwh(periodo):
    """Peaje + cargo de energía del periodo, en €/MWh."""
    return PEAJES_ENERGIA_EUR_MWH[periodo] + CARGOS_ENERGIA_EUR_MWH[periodo]


def coste_horario_eur(energia_mwh, precio_mercado_eur_mwh, periodo):
    """Coste de una hora: energía x (precio de mercado sin truncar + peaje + cargo)."""
    return energia_mwh * (precio_mercado_eur_mwh + termino_regulado_eur_mwh(periodo))