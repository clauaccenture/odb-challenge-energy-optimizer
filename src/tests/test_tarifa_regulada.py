"""TarifaRegulada (fase 2) reproduce EXACTAMENTE src/tarifas_6_2td.py y sirve para 6.3TD."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.tarifas_6_2td as actual  # noqa: E402
from src.config_loader_compuesto import cargar_escenario  # noqa: E402
from src.tarifa_regulada import TarifaRegulada  # noqa: E402


def dias(anio):
    d = date(anio, 1, 1)
    while d.year == anio:
        yield d
        d += timedelta(days=1)


def test_6_2td_identica_al_modulo_actual_todas_las_horas():
    t = TarifaRegulada.desde_config(cargar_escenario("desaladora").valores)
    assert (t.acceso, t.anio) == ("6.2TD", actual.ANIO_TARIFAS)
    assert t.peajes_eur_mwh == actual.PEAJES_ENERGIA_EUR_MWH
    assert t.cargos_eur_mwh == actual.CARGOS_ENERGIA_EUR_MWH
    for dia in dias(t.anio):
        for hora in range(24):
            assert t.periodo(dia, hora) == actual.periodo_6_2td(dia, hora), (dia, hora)


def test_6_3td_usa_sus_propios_peajes_con_el_mismo_calendario():
    t62 = TarifaRegulada.desde_config(cargar_escenario("desaladora").valores)
    t63 = TarifaRegulada.desde_config(cargar_escenario("siderurgia").valores)
    assert t63.acceso == "6.3TD" and t63.peajes_eur_mwh["P1"] == pytest.approx(11.279)
    assert t63.peajes_eur_mwh != t62.peajes_eur_mwh
    assert t63.periodo(date(2026, 1, 15), 10) == t62.periodo(date(2026, 1, 15), 10) == "P1"
    assert t63.periodo(date(2026, 1, 17), 10) == "P6"  # sabado


def test_fuera_de_anio_falla():
    t = TarifaRegulada.desde_config(cargar_escenario("desaladora").valores)
    with pytest.raises(ValueError, match="fuera del año"):
        t.periodo(date(2025, 12, 31), 10)
