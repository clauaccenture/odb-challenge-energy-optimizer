"""Peajes y cargos regulados del término de energía 6.2TD (Península, 2026).

Fuentes:
- Periodos horarios: Circular 3/2020 de la CNMC, art. 7.2 (BOE-A-2020-1066).
- Peajes de transporte y distribución 2026: Resolución CNMC de 18/12/2025,
  Anexo I (BOE-A-2025-26348).
- Cargos 2026: Orden TED/1524/2025, segmento 4 = 6.2TD (BOE-A-2025-26705).

Los importes se expresan en €/MWh (el BOE los publica en €/kWh) y no incluyen
IVA ni el Impuesto Especial sobre la Electricidad.
"""

from datetime import date
from zoneinfo import ZoneInfo

ZONA_PENINSULA = ZoneInfo("Europe/Madrid")
PERIODOS = ("P1", "P2", "P3", "P4", "P5", "P6")
# Año al que corresponden los peajes y cargos de este módulo.
ANIO_TARIFAS = 2026

PEAJES_ENERGIA_EUR_MWH = {
    "P1": 14.736,
    "P2": 7.202,
    "P3": 2.542,
    "P4": 1.254,
    "P5": 0.062,
    "P6": 0.020,
}

CARGOS_ENERGIA_EUR_MWH = {
    "P1": 9.144,
    "P2": 6.773,
    "P3": 3.658,
    "P4": 1.829,
    "P5": 1.172,
    "P6": 0.732,
}

# Festivos nacionales de fecha fija y no sustituibles, más el 6 de enero.
# Se excluye el Viernes Santo porque no tiene fecha fija.
FESTIVOS_NACIONALES = {
    2026: frozenset({
        date(2026, 1, 1),
        date(2026, 1, 6),
        date(2026, 5, 1),
        date(2026, 8, 15),
        date(2026, 10, 12),
        date(2026, 11, 1),
        date(2026, 12, 6),
        date(2026, 12, 8),
        date(2026, 12, 25),
    }),
}

# Temporada peninsular por mes -> (periodo en horas punta, periodo en horas llano).
_PERIODOS_POR_MES = {
    1: ("P1", "P2"), 2: ("P1", "P2"), 7: ("P1", "P2"), 12: ("P1", "P2"),
    3: ("P2", "P3"), 11: ("P2", "P3"),
    6: ("P3", "P4"), 8: ("P3", "P4"), 9: ("P3", "P4"),
    4: ("P4", "P5"), 5: ("P4", "P5"), 10: ("P4", "P5"),
}
_HORAS_PUNTA = frozenset(range(9, 14)) | frozenset(range(18, 22))


def es_dia_tipo_d(dia):
    """True si el día es sábado, domingo o festivo nacional (todo el día P6)."""
    if dia.year not in FESTIVOS_NACIONALES:
        raise ValueError(f"No hay calendario de festivos cargado para {dia.year}")
    return dia.weekday() >= 5 or dia in FESTIVOS_NACIONALES[dia.year]


def periodo_6_2td(dia, hora_local):
    """Periodo P1-P6 de una hora local peninsular (0-23) de un día dado."""
    if not 0 <= hora_local <= 23:
        raise ValueError(f"Hora local fuera de rango: {hora_local}")
    if es_dia_tipo_d(dia) or hora_local < 8:
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
