"""Lee config.yaml: cada parametro es {value, source_type, nota}.

cargar_config(path) -> (valores, tipos)
    valores : dict anidado solo con los valores
    tipos   : dict {"seccion.parametro": source_type}
derivados(valores) -> dict con lo que se calcula a partir del config (source_type = derived)
"""
from pathlib import Path

import yaml

SOURCE_TYPES = {"documented", "derived", "hypothesis"}


def _es_hoja(nodo) -> bool:
    return isinstance(nodo, dict) and "value" in nodo and "source_type" in nodo


def _recorrer(nodo, ruta, valores, tipos):
    for clave, hijo in nodo.items():
        r = f"{ruta}.{clave}" if ruta else clave
        if _es_hoja(hijo):
            if hijo["source_type"] not in SOURCE_TYPES:
                raise ValueError(f"{r}: source_type '{hijo['source_type']}' no valido {sorted(SOURCE_TYPES)}")
            valores[clave] = hijo["value"]
            tipos[r] = hijo["source_type"]
        elif isinstance(hijo, dict):
            valores[clave] = {}
            _recorrer(hijo, r, valores[clave], tipos)
        else:
            valores[clave] = hijo  # claves simples (p. ej. version_config)


def cargar_config(path: str | Path) -> tuple[dict, dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    valores, tipos = {}, {}
    _recorrer(raw, "", valores, tipos)
    return valores, tipos


def derivados(cfg: dict) -> dict:
    """Valores calculados (source_type = derived) y comprobaciones de coherencia."""
    consumo = cfg["planta"]["volumen_m3_dia"] * cfg["planta"]["consumo_especifico_kwh_m3"] / 1000  # MWh/dia
    carga = cfg["carga_flexible"]["energia_diaria_mwh"]
    limite = cfg["carga_flexible"]["limite_mwh_hora"]
    base = cfg["baseline_s0"]
    energia_baseline = base["mwh_hora"] * (base["hora_fin"] - base["hora_inicio"])
    if abs(energia_baseline - carga) > 1e-9:
        raise ValueError(f"Baseline ({energia_baseline} MWh) distinto de la carga flexible ({carga} MWh)")
    horas_min = -(-carga // limite)  # techo
    restr = cfg["optimizacion_s1"]
    operativas = [k for k in ("rampa_max_mwh_hora", "min_horas_encendido",
                              "coste_arranque_eur", "deposito_agua_mwh_equivalente")
                  if restr[k] is not None]
    return {
        "consumo_estimado_mwh_dia": consumo,                 # 150
        "consumo_estimado_gwh_ano": consumo * cfg["planta"]["dias_operacion_ano"] / 1000,  # 54,75
        "fraccion_flexible": carga / consumo,                # 0,20
        "horas_minimas_s1": int(horas_min),                  # 5
        "requiere_programacion_lineal": bool(operativas),
        "restricciones_operativas_activas": operativas,
    }