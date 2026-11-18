"""Fase 1: la Gold de la desaladora sale IDENTICA con base.yaml + industria que con el YAML antiguo.

No necesita datos reales ni AWS: usa precios sinteticos (con negativos y cambio de hora).
"""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config_loader import cargar_config  # noqa: E402
from src.config_loader_compuesto import cargar_escenario, yaml_resuelto  # noqa: E402
from src.desaladora import build_desaladora, validar_config  # noqa: E402
from src.tarifas_6_2td import _cargar_tarifa  # noqa: E402

CONFIG_ANTIGUA = ROOT / "config" / "config_desaladora.yaml"
# Diferencias decididas: datos nuevos que el YAML antiguo no tenia o metadatos.
NO_COMPARAR = ("fuentes_demo", "caso.sector", "carga_flexible.candidatas")
# Claves de fuentes_demo que lee app/desaladora_view.py (si falta una, la app falla).
FUENTES_APP = ("formula", "historico_gdo", "referencia_f_6_1td", "condiciones_6_2td", "peajes", "cargos")


def _gold():
    spec = importlib.util.spec_from_file_location("gold_redata", ROOT / "notebooks" / "03_gold_redata.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def aplanar(nodo, prefijo=""):
    out = {}
    for clave, valor in nodo.items():
        ruta = f"{prefijo}.{clave}" if prefijo else str(clave)
        if isinstance(valor, dict) and valor:
            out.update(aplanar(valor, ruta))
        else:
            out[ruta] = valor
    return out


def silver_sintetico() -> pd.DataFrame:
    """Dias completos en hora local: enero (festivos 1 y 6) y la semana del cambio de hora."""
    rng = np.random.default_rng(42)
    tramos = [("2026-01-01", "2026-01-15"), ("2026-03-26", "2026-04-02")]
    filas = []
    for inicio, fin in tramos:
        horas = pd.date_range(pd.Timestamp(inicio, tz="Europe/Madrid"),
                              pd.Timestamp(fin, tz="Europe/Madrid"), freq="h", inclusive="left")
        precios = rng.normal(60, 45, len(horas)).round(2)  # incluye precios negativos
        filas.append(pd.DataFrame({"datetime_utc": horas.tz_convert("UTC"), "precio_eur_mwh": precios}))
    silver = pd.concat(filas, ignore_index=True)
    assert (silver["precio_eur_mwh"] < 0).any()
    return silver


@pytest.fixture(scope="module")
def configs():
    antigua, _ = cargar_config(CONFIG_ANTIGUA)
    gold = _gold()
    nueva, tipos, texto, extra = gold.preparar_config(None, "desaladora")
    return antigua, nueva, tipos, texto, extra


def test_yaml_resuelto_equivale_al_antiguo(tmp_path, configs):
    texto = configs[3]
    ruta = tmp_path / "resuelto.yaml"
    ruta.write_text(texto, encoding="utf-8")
    antiguo = aplanar(cargar_config(CONFIG_ANTIGUA)[0])
    resuelto = aplanar(cargar_config(ruta)[0])
    relevante = lambda r: not r.startswith(NO_COMPARAR)  # noqa: E731
    faltan = sorted(r for r in antiguo if relevante(r) and r not in resuelto)
    distintos = sorted(r for r in antiguo if relevante(r) and r in resuelto and antiguo[r] != resuelto[r])
    # Claves nuevas (p. ej. caso.sector) se permiten: el codigo antiguo simplemente no las lee.
    assert not (faltan or distintos), f"faltan={faltan} distintos={distintos}"
    assert _cargar_tarifa(ruta) == _cargar_tarifa(CONFIG_ANTIGUA)


def test_yaml_resuelto_cumple_lo_que_lee_la_app(configs):
    cfg = yaml.safe_load(configs[3])
    assert cfg["version_config"] == 2
    assert set(FUENTES_APP) <= set(cfg["fuentes_demo"])
    assert cfg["tarifa"]["anio_regulatorio"]["value"] == 2026
    assert cfg["carga_flexible"]["energia_diaria_mwh"]["value"] == 30
    assert cfg["planta"]["volumen_m3_dia"]["value"] == 50000
    assert all("value" in nodo for nodo in cfg["operacion_demo"]["potencia_contratada_mw"].values())
    assert list(cfg["tarifas_reguladas"]) == ["6.2TD"] and "calendario_tarifario" not in cfg


def test_la_config_nueva_pasa_la_validacion_del_backend(configs):
    validar_config(configs[1])


def test_gold_desaladora_identica_con_config_antigua_y_nueva(configs):
    antigua, nueva = configs[0], configs[1]
    silver = silver_sintetico()
    for tabla_antigua, tabla_nueva in zip(build_desaladora(silver, antigua), build_desaladora(silver, nueva)):
        pd.testing.assert_frame_equal(tabla_antigua, tabla_nueva, check_exact=True)
    plan = build_desaladora(silver, nueva)[0]
    assert {date(2026, 3, 29)} <= set(plan["fecha_local"])  # dia de 23 horas incluido
    assert len(plan[plan["fecha_local"] == date(2026, 3, 29)]) == 23


def test_metadata_extra_es_json_y_trazable(configs):
    _, _, tipos, _, extra = configs
    json.dumps(extra, ensure_ascii=False, allow_nan=False)
    assert extra["industria"] == "desaladora"
    assert extra["apto_para_resultado_real"] is False and extra["advertencias"]
    assert not any(k.startswith(("tarifas_reguladas.6.3TD", "calendario_tarifario")) for k in tipos)
    assert extra["trazabilidad"]["planta.volumen_m3_dia"]["origen"] == "industria"


def test_siderurgia_se_bloquea_hasta_tener_multitarifa():
    with pytest.raises(ValueError, match="no coincide"):
        _gold().preparar_config(None, "siderurgia")


def test_modo_antiguo_no_cambia(configs):
    gold = _gold()
    cfg, tipos, texto, extra = gold.preparar_config(CONFIG_ANTIGUA, None)
    assert cfg == configs[0]
    assert texto == CONFIG_ANTIGUA.read_bytes().decode("utf-8")
    assert extra == {"config_origen": str(CONFIG_ANTIGUA)}


def test_ejecucion_local_completa_identica(tmp_path, monkeypatch):
    """Ejecuta ejecutar_desaladora --no-s3 en los dos modos y compara los Parquet."""
    pytest.importorskip("pyarrow")
    gold = _gold()
    silver = silver_sintetico()
    valores = [{"value": float(p), "datetime": t.tz_convert("Europe/Madrid").isoformat(timespec="milliseconds")}
               for t, p in zip(silver["datetime_utc"], silver["precio_eur_mwh"])]
    ruta_silver = tmp_path / "precios_horarios.json"
    ruta_silver.write_text(json.dumps({"included": [{"attributes": {
        "title": gold.SPOT_TITLE, "values": valores}}]}), encoding="utf-8")
    monkeypatch.setattr(gold, "SILVER", ruta_silver)
    salidas = {}
    for nombre, args in (("antiguo", (CONFIG_ANTIGUA, None)), ("nuevo", (None, "desaladora"))):
        destino = tmp_path / nombre
        monkeypatch.setattr(gold, "OUT_DIR_DESALADORA", destino)
        gold.ejecutar_desaladora(*gold.preparar_config(*args), False)
        salidas[nombre] = destino
    for fichero in ("programacion_horaria.parquet", "resumen_diario.parquet", "resumen_mensual.parquet"):
        pd.testing.assert_frame_equal(pd.read_parquet(salidas["antiguo"] / fichero),
                                      pd.read_parquet(salidas["nuevo"] / fichero), check_exact=True)
    meta = json.loads((salidas["nuevo"] / "metadata.json").read_text(encoding="utf-8"))
    assert meta["industria"] == "desaladora" and meta["advertencias"]
    assert yaml.safe_load(meta["config_yaml"])["version_config"] == 2
