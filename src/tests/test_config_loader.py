import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # src/tests/ -> raiz del repo
sys.path.insert(0, str(ROOT))
from src.config_loader import SOURCE_TYPES, cargar_config, derivados  # noqa: E402
from src.tarifas_6_2td import (  # noqa: E402
    ANIO_TARIFAS,
    CARGOS_ENERGIA_EUR_MWH,
    FESTIVOS_NACIONALES,
    PEAJES_ENERGIA_EUR_MWH,
    PERIODOS,
)

CFG_PATH = ROOT / "config" / "config_desaladora.yaml"


@pytest.fixture(scope="module")
def cargado():
    return cargar_config(CFG_PATH)


def test_todos_los_parametros_tienen_source_type_valido(cargado):
    _, tipos = cargado
    assert tipos and set(tipos.values()) <= SOURCE_TYPES


def test_parametros_del_caso(cargado):
    cfg, _ = cargado
    assert cfg["carga_flexible"]["energia_diaria_mwh"] == 30
    assert cfg["carga_flexible"]["limite_mwh_hora"] == 7
    assert cfg["baseline_s0"]["mwh_hora"] == 2.5
    assert (cfg["baseline_s0"]["hora_inicio"], cfg["baseline_s0"]["hora_fin"]) == (8, 20)


def test_derivados_caso_desaladora(cargado):
    d = derivados(cargado[0])
    assert d["consumo_estimado_mwh_dia"] == 150
    assert d["consumo_estimado_gwh_ano"] == pytest.approx(54.75)
    assert d["fraccion_flexible"] == pytest.approx(0.2)
    assert d["horas_minimas_s1"] == 5
    assert d["requiere_programacion_lineal"] is False


def test_el_modulo_de_tarifas_lee_el_bloque_elegido(cargado):
    cfg, _ = cargado
    acceso, anio = cfg["tarifa"]["acceso"], cfg["tarifa"]["anio_regulatorio"]
    assert acceso == "6.2TD"
    assert ANIO_TARIFAS == anio
    datos = cfg["tarifas_reguladas"][acceso]["anios"][anio]
    assert tuple(datos["peajes_energia_eur_mwh"]) == PERIODOS
    assert tuple(datos["cargos_energia_eur_mwh"]) == PERIODOS
    assert PEAJES_ENERGIA_EUR_MWH == datos["peajes_energia_eur_mwh"]
    assert CARGOS_ENERGIA_EUR_MWH == datos["cargos_energia_eur_mwh"]


def test_el_calendario_cubre_el_año_elegido(cargado):
    cfg, _ = cargado
    anio = cfg["tarifa"]["anio_regulatorio"]
    assert anio in FESTIVOS_NACIONALES
    assert {p for pares in cfg["tarifas_reguladas"]["6.2TD"]["calendario"]["periodos_por_mes"].values()
            for p in pares} <= set(PERIODOS)


def test_anio_sin_bloque_de_datos_falla(tmp_path):
    import yaml
    from src.tarifas_6_2td import _cargar_tarifa
    raw = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
    raw["tarifa"]["anio_regulatorio"]["value"] = 2025  # no hay bloque 2025
    ruta = tmp_path / "otro.yaml"
    ruta.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="2025"):
        _cargar_tarifa(ruta)


def test_politica_de_negativos_igual_que_gold(cargado):
    assert cargado[0]["mercado"]["politica_negativos"] == "sin_truncar"


def test_baseline_distinto_de_carga_da_error(cargado):
    import copy
    cfg = copy.deepcopy(cargado[0])
    cfg["baseline_s0"]["mwh_hora"] = 3.0
    with pytest.raises(ValueError):
        derivados(cfg)


def test_restriccion_operativa_activa_exige_programacion_lineal(cargado):
    import copy
    cfg = copy.deepcopy(cargado[0])
    cfg["optimizacion_s1"]["rampa_max_mwh_hora"] = 3
    d = derivados(cfg)
    assert d["requiere_programacion_lineal"] is True
    assert d["restricciones_operativas_activas"] == ["rampa_max_mwh_hora"]


# ---- bloque contrato (modelo de precio Som Energia) ----
TERMINOS_FORMULA = (
    "factor_global", "pagos_capacidad_eur_mwh", "sobrecostes_eur_mwh", "desvios_eur_mwh",
    "factor_desvio", "garantias_origen_eur_mwh", "posom_eur_mwh", "fondo_eficiencia_eur_mwh",
    "margen_f_eur_mwh",
)


def test_contrato_valores_permitidos(cargado):
    c = cargado[0]["contrato"]
    assert c["modelo_precio"] in {"som_indexada_6_2td", "spot_mas_regulado"}
    assert c["fase_modelo"] in {1, 2, 3}
    assert c["liquidacion_precio_negativo"] in {"sin_suelo", "suelo_cero"}


def test_contrato_define_todos_los_terminos_de_la_formula(cargado):
    f = cargado[0]["contrato"]["formula"]
    assert set(TERMINOS_FORMULA) <= set(f)
    assert f["factor_global"] == 1.015


def test_fase_elegida_tiene_valores_para_sus_terminos(cargado):
    """No se puede subir fase_modelo sin haber rellenado los terminos que esa fase necesita."""
    cfg = cargado[0]
    c = cfg["contrato"]
    reg = cfg["tarifas_reguladas"]["6.2TD"]
    for fase, terminos in c["fases"].items():
        if fase > c["fase_modelo"]:
            continue
        for t in terminos:
            if t == "perdidas":
                assert tuple(reg["perdidas_reguladas_fraccion"]) == PERIODOS
            else:
                assert c["formula"][t] is not None, f"fase {c['fase_modelo']} exige un valor para {t}"


def test_terminos_de_fases_existen_en_la_formula(cargado):
    c = cargado[0]["contrato"]
    for terminos in c["fases"].values():
        for t in terminos:
            assert t == "perdidas" or t in c["formula"]


def test_perdidas_reguladas_por_periodo(cargado):
    p = cargado[0]["tarifas_reguladas"]["6.2TD"]["perdidas_reguladas_fraccion"]
    assert tuple(p) == PERIODOS and all(0 < v < 0.1 for v in p.values())


def test_terminos_estimados_con_rango_coherente():
    """Cada rango es [min, max] y el valor central (y los escenarios) caen dentro."""
    import yaml
    raw = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
    for nombre, t in raw["contrato"]["formula"].items():
        if not isinstance(t, dict) or "rango" not in t:
            continue
        lo, hi = t["rango"]
        assert lo <= t["value"] <= hi, f"{nombre}: value fuera de rango"
        for esc, v in t.get("escenarios", {}).items():
            assert lo <= v <= hi, f"{nombre}: escenario {esc} fuera de rango"