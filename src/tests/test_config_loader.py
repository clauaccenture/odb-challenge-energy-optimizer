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
 
 
def test_perdidas_reguladas_por_periodo(cargado):
    p = cargado[0]["tarifas_reguladas"]["6.2TD"]["perdidas_reguladas_fraccion"]
    assert tuple(p) == PERIODOS and all(0 < v < 0.1 for v in p.values())


@pytest.mark.parametrize("ruta,valor", [
    (("contrato", "perdidas_fraccion"), -0.01),
    (("contrato", "sc_eur_mwh"), float("nan")),
    (("carga_flexible", "limite_mwh_hora"), 0),
    (("baseline_s0", "hora_fin"), 25),
    (("mercado", "fecha_inicio"), "2025-12-31"),
    (("componentes", "iva"), True),
    (("optimizacion_s1", "rampa_max_mwh_hora"), 3),
    (("operacion_demo", "potencia_contratada_mw", "p2"), 1),
])
def test_caso_rechaza_parametros_invalidos_o_no_soportados(cargado, ruta, valor):
    import copy
    from src.desaladora import validar_config

    cfg = copy.deepcopy(cargado[0])
    nodo = cfg
    for clave in ruta[:-1]:
        nodo = nodo[clave]
    nodo[ruta[-1]] = valor
    with pytest.raises(ValueError):
        validar_config(cfg)
