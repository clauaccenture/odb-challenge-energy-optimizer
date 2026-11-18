"""Tests del loader compuesto: base.yaml + industrias/<industria>.yaml."""
import copy
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config_loader_compuesto import (  # noqa: E402
    ConfigError,
    cargar_config_compuesta,
    cargar_escenario,
    deep_merge,
    derivados,
)

CONFIG_DIR = ROOT / "config"
TARIFA_62 = ("tarifas_reguladas", "6.2TD", "anios", 2026)


# ----------------------------------------------------------------- utilidades
@pytest.fixture
def config_tmp(tmp_path):
    """Copia editable de config/ (base + industrias) en una carpeta temporal."""
    destino = tmp_path / "config"
    (destino / "industrias").mkdir(parents=True)
    (destino / "base.yaml").write_text((CONFIG_DIR / "base.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    for f in (CONFIG_DIR / "industrias").glob("*.yaml"):
        (destino / "industrias" / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return destino


def editar(config_dir, fichero, cambio):
    ruta = config_dir / fichero
    raw = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    cambio(raw)
    ruta.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def poner(raw, ruta, valor):
    nodo = raw
    for k in ruta[:-1]:
        nodo = nodo.setdefault(k, {})
    if isinstance(nodo.get(ruta[-1]), dict) and "value" in nodo[ruta[-1]]:
        nodo[ruta[-1]]["value"] = valor
    else:
        nodo[ruta[-1]] = {"value": valor, "source_type": "hypothesis"}


def nodo(raw, ruta):
    for k in ruta:
        raw = raw[k]
    return raw


# ----------------------------------------------------------------- casos reales
@pytest.mark.parametrize("industria,consumo,gwh,fraccion,metodo", [
    ("desaladora", 150, 54.75, 0.20, "volumen_x_consumo_especifico"),
    ("siderurgia", 100, 36.5, 0.30, "directo"),
])
def test_derivados_por_industria(industria, consumo, gwh, fraccion, metodo):
    d = cargar_escenario(industria, CONFIG_DIR).derivados
    assert d["consumo_estimado_mwh_dia"] == pytest.approx(consumo)
    assert d["consumo_estimado_gwh_ano"] == pytest.approx(gwh)
    assert d["fraccion_flexible"] == pytest.approx(fraccion)
    assert d["horas_minimas_s1"] == 5
    assert d["metodo_consumo"] == metodo
    assert d["tipo_optimizador_sugerido"] == "greedy"
    assert d["requiere_programacion_lineal"] is False


def test_herencia_y_override():
    des, _ = cargar_config_compuesta("desaladora", CONFIG_DIR)
    sid, _ = cargar_config_compuesta("siderurgia", CONFIG_DIR)
    assert des["mercado"]["zona_horaria"] == sid["mercado"]["zona_horaria"] == "Europe/Madrid"  # base
    assert (des["tarifa"]["acceso"], sid["tarifa"]["acceso"]) == ("6.2TD", "6.3TD")          # industria
    assert des["carga_flexible"]["energia_diaria_mwh"] == sid["carga_flexible"]["energia_diaria_mwh"] == 30
    assert des["version_config"] == sid["version_config"] == 2


def test_catalogo_de_tarifas_compartido():
    """Las tarifas viven en base: ambas industrias ven el mismo catalogo y cada una elige la suya."""
    des, _ = cargar_config_compuesta("desaladora", CONFIG_DIR)
    sid, _ = cargar_config_compuesta("siderurgia", CONFIG_DIR)
    assert set(des["tarifas_reguladas"]) == set(sid["tarifas_reguladas"]) == {"6.2TD", "6.3TD"}
    assert des["tarifas_reguladas"] == sid["tarifas_reguladas"]


def test_deposito_solo_en_desaladora():
    des, _ = cargar_config_compuesta("desaladora", CONFIG_DIR)
    sid, _ = cargar_config_compuesta("siderurgia", CONFIG_DIR)
    assert "deposito_agua_mwh_equivalente" in des["optimizacion_s1"]
    assert des["optimizacion_s1"]["deposito_agua_mwh_equivalente"] is None
    assert "deposito_agua_mwh_equivalente" not in sid["optimizacion_s1"]


def test_calendario_unico_se_copia_en_cada_tarifa():
    e = cargar_escenario("siderurgia", CONFIG_DIR)
    for acceso in ("6.2TD", "6.3TD"):
        assert e.valores["tarifas_reguladas"][acceso]["calendario"] == e.valores["calendario_tarifario"]
        assert e.trazabilidad[f"tarifas_reguladas.{acceso}.calendario.horas_punta"]["origen"] == "base (calendario_tarifario)"


def test_calendario_propio_de_la_tarifa_tiene_prioridad(config_tmp):
    def con_calendario(raw):
        raw.setdefault("tarifas_reguladas", {}).setdefault("6.3TD", {})["calendario"] = {
            "p6_antes_de_hora": {"value": 7, "source_type": "hypothesis"},
            "horas_punta": {"value": [10, 11], "source_type": "hypothesis"},
            "periodos_por_mes": {"value": {m: ["P1", "P2"] for m in range(1, 13)}, "source_type": "hypothesis"},
        }
    editar(config_tmp, "industrias/siderurgia.yaml", con_calendario)
    v = cargar_escenario("siderurgia", config_tmp).valores["tarifas_reguladas"]
    assert v["6.3TD"]["calendario"]["horas_punta"] == [10, 11]
    assert v["6.2TD"]["calendario"]["horas_punta"] == [9, 10, 11, 12, 13, 18, 19, 20, 21]


def test_festivos_son_fechas_y_anios_enteros():
    v, _ = cargar_config_compuesta("desaladora", CONFIG_DIR)
    anios = v["tarifas_reguladas"]["6.2TD"]["anios"]
    assert list(anios) == [2026]
    assert all(type(d) is date for d in anios[2026]["festivos_nacionales"])


def test_por_defecto_no_depende_del_directorio_actual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cargar_escenario("desaladora").derivados["consumo_estimado_mwh_dia"] == 150


# ----------------------------------------------------------------- trazabilidad y avisos
def test_trazabilidad_conserva_nota_fuente_y_origen():
    t = cargar_escenario("siderurgia", CONFIG_DIR).trazabilidad
    assert t["mercado.zona_horaria"]["origen"] == "base"
    assert t["planta.consumo_diario_mwh"]["origen"] == "industria"
    assert "NO el consumo real" in t["planta.consumo_diario_mwh"]["nota"]
    peajes = t["tarifas_reguladas.6.3TD.anios.2026.peajes_energia_eur_mwh"]
    assert peajes["fuente"] == "peajes" and peajes["url"].startswith("https://www.boe.es")
    assert t["caso.ubicacion"]["url"].startswith("https://prtr-es.miteco.gob.es")
    sobrescrito = t["operacion_demo.perfil_no_flexible"]
    assert sobrescrito["origen"] == "industria (sobrescribe base)"
    assert sobrescrito["valor_base"] == "uniforme_energia_diaria"


def test_advertencias_marcan_hipotesis_criticas():
    sid = cargar_escenario("siderurgia", CONFIG_DIR)
    texto = " | ".join(sid.advertencias)
    assert "tarifa.acceso es derived" in texto
    assert "6.3TD.anios.2026.cargos_energia_eur_mwh es hypothesis" in texto
    assert "perdidas reguladas de 6.3TD desconocidas" in texto
    assert "potencia contratada desconocida" in texto
    assert sid.apto_para_resultado_real is False
    des = " | ".join(cargar_escenario("desaladora", CONFIG_DIR).advertencias)
    assert "perdidas reguladas" not in des and "potencia contratada" not in des
    assert "cargos_energia_eur_mwh" not in des  # 6.2TD documentado


# ----------------------------------------------------------------- deep merge
def test_deep_merge_conserva_anidados_y_no_muta():
    base = {"a": {"b": 1, "c": 2}, "x": 3}
    assert deep_merge(base, {"a": {"b": 9}}) == {"a": {"b": 9, "c": 2}, "x": 3}
    assert base == {"a": {"b": 1, "c": 2}, "x": 3}


def test_deep_merge_hoja_completa_y_conflicto_de_forma():
    base = {"x": {"value": 1, "source_type": "documented", "nota": "base"}}
    assert deep_merge(base, {"x": {"value": 2, "source_type": "hypothesis"}})["x"] == {
        "value": 2, "source_type": "hypothesis"}
    with pytest.raises(ConfigError, match="forma"):
        deep_merge(base, {"x": {"y": {"value": 1, "source_type": "hypothesis"}}})


# ----------------------------------------------------------------- errores que deben detectarse
CASOS_INVALIDOS = [
    # (fichero, ruta, valor, texto esperado en el error)
    ("industrias/siderurgia.yaml", ("carga_flexible", "energia_diaria_mhw"), 40, "clave desconocida"),
    ("industrias/siderurgia.yaml", ("optimizacion_s1", "deposito_agua_mwh_equivalnte"), None, "clave desconocida"),
    ("base.yaml", ("carga_flexible", "energia_diaria_mwh"), True, "numero"),
    ("industrias/desaladora.yaml", ("planta", "dias_operacion_ano"), "trescientos", "entero"),
    ("base.yaml", ("baseline_s0", "hora_inicio"), [8], "entero"),
    ("base.yaml", ("baseline_s0", "hora_fin"), 25, "<= 24"),
    ("industrias/desaladora.yaml", ("planta", "volumen_m3_dia"), -5, "> 0"),
    ("industrias/desaladora.yaml", ("tarifa", "anio_regulatorio"), True, "entero"),
    ("industrias/desaladora.yaml", ("tarifa", "anio_regulatorio"), 2027, "2027"),
    ("industrias/desaladora.yaml", ("tarifa", "acceso"), 62, "texto"),
    ("industrias/desaladora.yaml", ("tarifa", "acceso"), "6.9TD", "uno de"),
    ("industrias/desaladora.yaml", ("tarifa", "acceso"), "6.1TD", "catalogo"),
    ("industrias/siderurgia.yaml", ("caso", "nombre"), {"a": 1}, "texto"),
    ("base.yaml", ("contrato", "perdidas_fraccion"), 1.5, "< 1"),
    ("base.yaml", ("contrato", "sc_eur_mwh"), float("nan"), "finito"),
    ("base.yaml", ("mercado", "fecha_inicio"), "2025-12-31", "fecha"),
    ("base.yaml", ("mercado", "politica_negativos"), "truncar", "uno de"),
    ("base.yaml", ("componentes", "iva"), "no", "true/false"),
    ("industrias/siderurgia.yaml", ("planta", "consumo_diario_mwh"), 20, "mayor que el consumo"),
    ("base.yaml", ("carga_flexible", "energia_diaria_mwh"), 40, "Baseline"),
    ("base.yaml", ("baseline_s0", "mwh_hora"), 8, "supera el limite"),
    ("base.yaml", ("optimizacion_s1", "min_horas_encendido"), 0, ">= 1"),
    ("base.yaml", ("calendario_tarifario", "horas_punta"), [25], "0-23"),
]


@pytest.mark.parametrize("fichero,ruta,valor,mensaje", CASOS_INVALIDOS,
                         ids=[".".join(map(str, c[1])) + f"={c[2]!r}" for c in CASOS_INVALIDOS])
def test_configuracion_invalida_falla_al_cargar(config_tmp, fichero, ruta, valor, mensaje):
    editar(config_tmp, fichero, lambda raw: poner(raw, ruta, valor))
    industria = "siderurgia" if "siderurgia" in fichero else "desaladora"
    with pytest.raises(ConfigError, match=mensaje):
        cargar_escenario(industria, config_tmp)


@pytest.mark.parametrize("fichero,cambio,mensaje", [
    ("base.yaml", lambda r: nodo(r, TARIFA_62)["peajes_energia_eur_mwh"]["value"].pop("P6"), "exactamente"),
    ("base.yaml", lambda r: nodo(r, TARIFA_62)["cargos_energia_eur_mwh"]["value"].update(P7=1.0), "exactamente"),
    ("base.yaml", lambda r: nodo(r, TARIFA_62)["peajes_energia_eur_mwh"]["value"].update(P1=-1.0), ">= 0"),
    ("base.yaml", lambda r: nodo(r, TARIFA_62)["festivos_nacionales"]["value"].append(date(2025, 12, 25)), "otro año"),
    ("base.yaml", lambda r: nodo(r, TARIFA_62)["festivos_nacionales"].update(value=["2026-01-01"]), "fecha"),
    ("base.yaml", lambda r: nodo(r, TARIFA_62[:3]).update({"2025": nodo(r, TARIFA_62)}), "entero"),
    ("base.yaml", lambda r: r.pop("calendario_tarifario"), "calendario_tarifario"),
    ("industrias/desaladora.yaml", lambda r: r["planta"]["conexion_kv"].update(unidad="kV"), "no permitidas"),
    ("industrias/desaladora.yaml", lambda r: r["planta"]["conexion_kv"].update(source_type="oficial"), "source_type"),
    ("industrias/desaladora.yaml", lambda r: r["planta"]["conexion_kv"].update(fuente="no_existe"), "fuentes_demo"),
    ("industrias/desaladora.yaml", lambda r: r.pop("contrato"), "explicitamente"),
    ("industrias/desaladora.yaml", lambda r: r["contrato"].pop("modelo"), "bloque vacio"),
    ("industrias/desaladora.yaml", lambda r: r["planta"].pop("conexion_kv"), "explicitamente"),
    ("industrias/desaladora.yaml", lambda r: r["tarifa"].pop("segmento_cargos"), "explicitamente"),
    ("industrias/desaladora.yaml", lambda r: r["contrato"]["modelo"].update(value="otra_comercializadora"), "otro contrato"),
    ("industrias/desaladora.yaml", lambda r: r["planta"].pop("volumen_m3_dia"), "necesita consumo_diario_mwh"),
])
def test_errores_de_estructura(config_tmp, fichero, cambio, mensaje):
    editar(config_tmp, fichero, cambio)
    with pytest.raises(ConfigError, match=mensaje):
        cargar_escenario("desaladora", config_tmp)


def test_inviable_si_no_cabe_en_24_horas(config_tmp):
    editar(config_tmp, "base.yaml", lambda r: poner(r, ("carga_flexible", "limite_mwh_hora"), 1))
    with pytest.raises(ConfigError, match="Inviable"):
        cargar_escenario("desaladora", config_tmp)


def test_otro_contrato_completo_se_acepta(config_tmp):
    def contrato_propio(raw):
        base = yaml.safe_load((config_tmp / "base.yaml").read_text(encoding="utf-8"))["contrato"]
        base["modelo"]["value"] = "indexado_generico"
        base["sc_eur_mwh"]["value"] = 12.0
        raw["contrato"] = base
    editar(config_tmp, "industrias/siderurgia.yaml", contrato_propio)
    v = cargar_escenario("siderurgia", config_tmp).valores
    assert v["contrato"]["modelo"] == "indexado_generico" and v["contrato"]["sc_eur_mwh"] == 12.0


@pytest.mark.parametrize("nombre", ["../base", "Desaladora", "desaladora.yaml", "", "no_existe"])
def test_identificador_de_industria_seguro(nombre):
    with pytest.raises(ConfigError):
        cargar_escenario(nombre, CONFIG_DIR)


# ----------------------------------------------------------------- derivados()
@pytest.mark.parametrize("restricciones,tipo", [
    ({"rampa_max_mwh_hora": 3}, "LP"),
    ({"deposito_agua_mwh_equivalente": 10}, "LP"),
    ({"min_horas_encendido": 3}, "MILP"),
    ({"rampa_max_mwh_hora": 3, "coste_arranque_eur": 100}, "MILP"),
])
def test_tipo_de_optimizador(restricciones, tipo):
    cfg = copy.deepcopy(cargar_config_compuesta("desaladora", CONFIG_DIR)[0])
    cfg["optimizacion_s1"].update(restricciones)
    d = derivados(cfg)
    assert d["requiere_programacion_lineal"] is True
    assert d["tipo_optimizador_sugerido"] == tipo
    assert d["restricciones_operativas_activas"] == [k for k in (
        "rampa_max_mwh_hora", "min_horas_encendido", "coste_arranque_eur",
        "deposito_agua_mwh_equivalente") if k in restricciones]


def test_derivados_funciona_sin_deposito():
    cfg, _ = cargar_config_compuesta("siderurgia", CONFIG_DIR)
    assert derivados(cfg)["restricciones_operativas_activas"] == []


def test_derivados_valida_aunque_se_llame_sin_loader():
    cfg = copy.deepcopy(cargar_config_compuesta("siderurgia", CONFIG_DIR)[0])
    cfg["planta"]["consumo_diario_mwh"] = 0
    with pytest.raises(ValueError):
        derivados(cfg)
    cfg["planta"]["consumo_diario_mwh"] = 100
    cfg["baseline_s0"]["mwh_hora"] = 3.0
    with pytest.raises(ValueError, match="Baseline"):
        derivados(cfg)


def test_horas_minimas_sin_errores_de_coma_flotante():
    cfg = copy.deepcopy(cargar_config_compuesta("desaladora", CONFIG_DIR)[0])
    cfg["carga_flexible"].update(energia_diaria_mwh=0.3, limite_mwh_hora=0.1)
    cfg["baseline_s0"].update(mwh_hora=0.025)
    assert derivados(cfg)["horas_minimas_s1"] == 3
