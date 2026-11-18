"""Tarifa de acceso (6.2TD, 6.3TD...) construida desde la configuracion, no desde un fichero fijo.

FASE 2 (siderurgia). Hoy NO lo usa nadie: src/tarifas_6_2td.py sigue siendo la fuente del calculo.
Reproduce exactamente su logica (P1-P6, festivos, calendario) para poder sustituirlo despues
sin cambiar resultados (ver src/tests/test_tarifa_regulada.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

PERIODOS = ("P1", "P2", "P3", "P4", "P5", "P6")
ZONA_PENINSULA = ZoneInfo("Europe/Madrid")


@dataclass(frozen=True)
class TarifaRegulada:
    acceso: str
    anio: int
    peajes_eur_mwh: dict
    cargos_eur_mwh: dict
    festivos: frozenset
    p6_antes_de_hora: int
    horas_punta: frozenset
    periodos_por_mes: dict  # mes -> (periodo punta, periodo llano)

    @classmethod
    def desde_config(cls, cfg: dict) -> "TarifaRegulada":
        """cfg = valores ya cargados (config_loader o config_loader_compuesto)."""
        acceso = cfg["tarifa"]["acceso"]
        anio = cfg["tarifa"]["anio_regulatorio"]
        bloque = cfg["tarifas_reguladas"].get(acceso)
        if bloque is None:
            raise ValueError(f"No hay datos regulados de {acceso} en la configuracion")
        datos = bloque["anios"].get(anio)
        if datos is None:
            raise ValueError(f"No hay peajes y cargos de {acceso} para {anio}")
        for clave in ("peajes_energia_eur_mwh", "cargos_energia_eur_mwh"):
            if tuple(datos[clave]) != PERIODOS:
                raise ValueError(f"{clave} de {acceso} {anio} debe tener exactamente {PERIODOS}")
        cal = bloque["calendario"]
        return cls(
            acceso=acceso,
            anio=anio,
            peajes_eur_mwh=dict(datos["peajes_energia_eur_mwh"]),
            cargos_eur_mwh=dict(datos["cargos_energia_eur_mwh"]),
            festivos=frozenset(datos["festivos_nacionales"]),
            p6_antes_de_hora=cal["p6_antes_de_hora"],
            horas_punta=frozenset(cal["horas_punta"]),
            periodos_por_mes={int(m): tuple(p) for m, p in cal["periodos_por_mes"].items()},
        )

    def es_dia_tipo_d(self, dia: date) -> bool:
        if dia.year != self.anio:
            raise ValueError(f"{dia} fuera del año regulatorio {self.anio} de {self.acceso}")
        return dia.weekday() >= 5 or dia in self.festivos

    def periodo(self, dia: date, hora_local: int) -> str:
        if not 0 <= hora_local <= 23:
            raise ValueError(f"Hora local fuera de rango: {hora_local}")
        if self.es_dia_tipo_d(dia) or hora_local < self.p6_antes_de_hora:
            return "P6"
        punta, llano = self.periodos_por_mes[dia.month]
        return punta if hora_local in self.horas_punta else llano

    def termino_regulado_eur_mwh(self, periodo: str) -> float:
        return self.peajes_eur_mwh[periodo] + self.cargos_eur_mwh[periodo]
