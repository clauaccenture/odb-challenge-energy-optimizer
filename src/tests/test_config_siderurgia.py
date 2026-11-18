import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # src/tests/ -> raiz del repo
sys.path.insert(0, str(ROOT))

from src.config_loader import SOURCE_TYPES, cargar_config, derivados  # noqa: E402

CFG_PATH = ROOT / "config" / "config_siderurgia.yaml"


@pytest.fixture(scope="module")
def cargado():
    assert CFG_PATH.exists(), f"No existe {CFG_PATH}"
    return cargar_config(CFG_PATH)


def test_siderurgia_carga_y_source_types_validos(cargado):
    cfg, tipos = cargado
    assert tipos
    assert set(tipos.values()) <= SOURCE_TYPES
    assert cfg["caso"]["sector"] == "siderurgia"
    assert cfg["planta"]["consumo_diario_mwh"] == 100
    assert cfg["planta"]["conexion_kv"] == 132


def test_siderurgia_usa_consumo_diario_directo(cargado):
    cfg, _ = cargado
    d = derivados(cfg)

    assert d["consumo_estimado_mwh_dia"] == 100
    assert d["consumo_estimado_gwh_ano"] == pytest.approx(36.5)
    assert d["fraccion_flexible"] == pytest.approx(0.30)
    assert d["horas_minimas_s1"] == 5
    assert d["requiere_programacion_lineal"] is False
    assert d["restricciones_operativas_activas"] == []


def test_siderurgia_baseline_suma_30_mwh(cargado):
    cfg, _ = cargado
    base = cfg["baseline_s0"]
    energia = base["mwh_hora"] * (base["hora_fin"] - base["hora_inicio"])

    assert energia == pytest.approx(30.0)
    assert energia == cfg["carga_flexible"]["energia_diaria_mwh"]


def test_siderurgia_selecciona_6_3td_2026(cargado):
    cfg, _ = cargado

    assert cfg["tarifa"]["acceso"] == "6.3TD"
    assert cfg["tarifa"]["anio_regulatorio"] == 2026
    datos = cfg["tarifas_reguladas"]["6.3TD"]["anios"][2026]
    assert set(datos["peajes_energia_eur_mwh"]) == {"P1", "P2", "P3", "P4", "P5", "P6"}
    assert set(datos["cargos_energia_eur_mwh"]) == {"P1", "P2", "P3", "P4", "P5", "P6"}


def test_siderurgia_conserva_precios_negativos(cargado):
    cfg, _ = cargado
    assert cfg["mercado"]["politica_negativos"] == "sin_truncar"


def test_siderurgia_restriccion_activa_exige_programacion_lineal(cargado):
    cfg = copy.deepcopy(cargado[0])
    cfg["optimizacion_s1"]["min_horas_encendido"] = 3

    d = derivados(cfg)

    assert d["requiere_programacion_lineal"] is True
    assert d["restricciones_operativas_activas"] == ["min_horas_encendido"]


def test_siderurgia_baseline_incoherente_falla(cargado):
    cfg = copy.deepcopy(cargado[0])
    cfg["baseline_s0"]["mwh_hora"] = 3.0

    with pytest.raises(ValueError, match="Baseline"):
        derivados(cfg)
