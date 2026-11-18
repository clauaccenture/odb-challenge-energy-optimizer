"""Regresion: base.yaml + industria debe reproducir los YAML completos actuales.

Compara el sistema actual (config_loader.py + config/config_<industria>.yaml) con el
compuesto (config_loader_compuesto.py + base.yaml + industrias/<industria>.yaml).
Si algo falla, el mensaje dice exactamente que parametro difiere o falta.
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]  # src/tests/ -> raiz del repo
sys.path.insert(0, str(ROOT))

from src import config_loader as actual  # noqa: E402
from src import config_loader_compuesto as compuesto  # noqa: E402

CONFIG_DIR = ROOT / "config"
CASOS = [
    ("desaladora", CONFIG_DIR / "config_desaladora.yaml"),
    ("siderurgia", CONFIG_DIR / "config_siderurgia.yaml"),
]
IDS = [c[0] for c in CASOS]
IGNORAR = {"fuentes_demo"}  # metadatos: pueden diferir a proposito
# Diferencias DECIDIDAS (Jaime + Didac). Cualquier otra diferencia hace fallar el test.
EXCLUIDOS_A_PROPOSITO = {
    "siderurgia": {
        # Restriccion propia de desalacion: ya no se hereda en siderurgia.
        "optimizacion_s1.deposito_agua_mwh_equivalente",
    },
}


def aplanar(nodo, prefijo=""):
    out = {}
    for clave, valor in nodo.items():
        ruta = f"{prefijo}.{clave}" if prefijo else str(clave)
        if isinstance(valor, dict) and valor:
            out.update(aplanar(valor, ruta))
        else:
            out[ruta] = valor
    return out


def iguales(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == pytest.approx(b)
    return a == b


def relevante(ruta):
    return ruta.split(".")[0] not in IGNORAR


@pytest.fixture(params=CASOS, ids=IDS)
def ambos(request):
    industria, ruta_antigua = request.param
    if not ruta_antigua.exists():
        pytest.skip(f"No existe {ruta_antigua.name}")
    old, _ = actual.cargar_config(ruta_antigua)
    new, _ = compuesto.cargar_config_compuesta(industria, CONFIG_DIR)
    return industria, old, new


def test_derivados_identicos(ambos):
    industria, old, new = ambos
    d_old, d_new = actual.derivados(old), compuesto.derivados(new)
    diffs = [f"  {k}: actual={d_old[k]!r} | compuesto={d_new[k]!r}"
             for k in sorted(set(d_old) & set(d_new)) if not iguales(d_old[k], d_new[k])]
    assert not diffs, f"[{industria}] derivados distintos:\n" + "\n".join(diffs)


def test_valores_comunes_identicos(ambos):
    industria, old, new = ambos
    f_old, f_new = aplanar(old), aplanar(new)
    comunes = {r for r in set(f_old) & set(f_new) if relevante(r)}
    assert len(comunes) >= 40, f"Solo {len(comunes)} rutas comunes"
    diffs = [f"  {r}: actual={f_old[r]!r} | compuesto={f_new[r]!r}"
             for r in sorted(comunes) if not iguales(f_old[r], f_new[r])]
    assert not diffs, f"[{industria}] valores distintos:\n" + "\n".join(diffs)


def test_no_falta_ningun_parametro_del_yaml_actual(ambos):
    industria, old, new = ambos
    excluidos = EXCLUIDOS_A_PROPOSITO.get(industria, set())
    faltan = sorted(r for r in set(aplanar(old)) - set(aplanar(new))
                    if relevante(r) and r not in excluidos)
    assert not faltan, f"[{industria}] faltan en base+industria:\n" + "\n".join(f"  {r}" for r in faltan)


def test_las_exclusiones_siguen_siendo_necesarias(ambos):
    """Si una exclusion ya no hace falta, se borra: la lista no puede ocultar nada."""
    industria, old, new = ambos
    f_old, f_new = aplanar(old), aplanar(new)
    for r in EXCLUIDOS_A_PROPOSITO.get(industria, set()):
        assert r in f_old and r not in f_new, f"[{industria}] exclusion obsoleta: {r}"


def test_tarifas_6_2td_lee_igual_la_config_resuelta(ambos, tmp_path):
    """El modulo de tarifas real debe obtener los mismos peajes, cargos y calendario."""
    from src.tarifas_6_2td import _cargar_tarifa
    industria, old, new = ambos
    ruta = tmp_path / f"{industria}_resuelta.yaml"
    ruta.write_text(yaml.safe_dump(new, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert _cargar_tarifa(ruta) == _cargar_tarifa(dict(CASOS)[industria])


def test_validar_config_de_desaladora_acepta_la_config_resuelta():
    """La validacion propia del backend de la desaladora debe aceptar la config compuesta."""
    modulo = pytest.importorskip("src.desaladora")
    cfg, _ = compuesto.cargar_config_compuesta("desaladora", CONFIG_DIR)
    modulo.validar_config(cfg)
