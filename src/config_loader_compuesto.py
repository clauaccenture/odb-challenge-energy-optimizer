"""Configuracion compuesta: config/base.yaml + config/industrias/<industria>.yaml.

Convive con src/config_loader.py (no lo sustituye) hasta que el equipo lo apruebe.

Reparto (acordado Jaime + Didac)
--------------------------------
base.yaml      -> valores por defecto del reto, restricciones comunes, mercado, componentes,
                  calendario P1-P6 unico, CATALOGO de tarifas reguladas (6.2TD, 6.3TD...)
                  y contrato de referencia (valores revisados por Claudia).
industria.yaml -> caso, planta, eleccion de tarifa, contrato.modelo y lo que se aparte de la base
                  (restricciones propias como el deposito de la desaladora, potencias, etc.).

API
---
cargar_escenario(industria, config_dir=None) -> ConfigCargada
    Carga, fusiona, VALIDA COMPLETAMENTE y calcula derivados. Si devuelve algo, la configuracion
    es coherente y esta lista para el optimizador. Incluye trazabilidad y advertencias.
cargar_config_compuesta(industria, config_dir=None) -> (valores, tipos)
    Mismo formato que config_loader.cargar_config (compatibilidad). Tambien valida todo.
yaml_resuelto(escenario) -> str
    YAML unico ya fusionado, con el mismo formato que config_desaladora.yaml (version_config 2).
    Es lo que se guarda en metadata.json para que la app y la auditoria vean la config usada.
derivados(valores) -> dict
    Mismo contrato que config_loader.derivados; valida coherencia antes de calcular.

Reglas
------
- Hoja = {value, source_type, nota?, fuente?}. Cualquier otra clave en una hoja es error.
- Solo se admiten claves conocidas (ESQUEMA): una errata da error, no hereda en silencio.
- Override de hoja: la industria sustituye la hoja completa; el valor base queda en la trazabilidad.
- Resolucion temporal horaria (intervalos de 1 h).
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

SOURCE_TYPES = frozenset({"documented", "derived", "hypothesis"})
CLAVES_HOJA = frozenset({"value", "source_type", "nota", "fuente"})
PERIODOS = ("P1", "P2", "P3", "P4", "P5", "P6")
TRIMESTRES = ("t1", "t2", "t3", "t4")
TARIFAS_ACCESO = frozenset({"6.1TD", "6.2TD", "6.3TD", "6.4TD"})
POLITICAS_NEGATIVOS = frozenset({"sin_truncar"})  # la unica que implementa 03_gold
CONFIG_DIR_POR_DEFECTO = Path(__file__).resolve().parents[1] / "config"
_ID_INDUSTRIA = re.compile(r"^[a-z0-9_]{1,64}$")
_TOL = 1e-6

# Lo que cada industria DEBE declarar (cabecera de base.yaml).
OBLIGATORIAS_EN_INDUSTRIA = (
    ("caso", "nombre"),
    ("caso", "sector"),
    ("caso", "etiqueta_resultado"),
    ("planta", "conexion_kv"),
    ("planta", "dias_operacion_ano"),
    ("tarifa", "acceso"),
    ("tarifa", "zona"),
    ("tarifa", "anio_regulatorio"),
    ("tarifa", "segmento_cargos"),
    ("contrato", "modelo"),
)
# Si la industria cambia contrato.modelo, debe definir todos estos terminos.
TERMINOS_CONTRATO = (
    "resolucion", "liquidacion_negativos", "factor_formula", "pc_eur_mwh", "sc_eur_mwh",
    "dsv_eur_mwh", "posom_eur_mwh", "perdidas_fraccion", "fe_eur_mwh", "f_eur_mwh",
    "gdo_eur_mwh_por_trimestre", "criterio_gdo",
)
# Parametros que, si no estan documentados, impiden presentar el resultado como real.
CRITICOS = (
    ("tarifa", "acceso"),
    ("carga_flexible", "energia_diaria_mwh"),
    ("carga_flexible", "limite_mwh_hora"),
    ("contrato", "sc_eur_mwh"),
    ("contrato", "f_eur_mwh"),
    ("contrato", "perdidas_fraccion"),
)
RESTRICCIONES_OPERATIVAS = (
    "rampa_max_mwh_hora", "min_horas_encendido", "coste_arranque_eur", "deposito_agua_mwh_equivalente",
)


class ConfigError(ValueError):
    """Error de configuracion (hereda de ValueError por compatibilidad con los tests)."""


def _ruta(path: tuple) -> str:
    return ".".join(str(p) for p in path)


# --------------------------------------------------------------------------- validadores
Validador = Callable[[Any], Optional[str]]


def _es_numero(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(minimo=None, minimo_excl=None, maximo=None, maximo_excl=None,
         entero=False, nulo=False) -> Validador:
    def validar(v):
        if v is None:
            return None if nulo else "no puede ser null"
        if entero and (isinstance(v, bool) or not isinstance(v, int)):
            return f"debe ser entero, no {type(v).__name__}"
        if not _es_numero(v):
            return f"debe ser numero finito, no {v!r}"
        if minimo is not None and v < minimo:
            return f"debe ser >= {minimo}"
        if minimo_excl is not None and v <= minimo_excl:
            return f"debe ser > {minimo_excl}"
        if maximo is not None and v > maximo:
            return f"debe ser <= {maximo}"
        if maximo_excl is not None and v >= maximo_excl:
            return f"debe ser < {maximo_excl}"
        return None
    return validar


def _texto(opciones=None, nulo=False) -> Validador:
    def validar(v):
        if v is None:
            return None if nulo else "no puede ser null"
        if not isinstance(v, str) or not v.strip():
            return "debe ser texto no vacio"
        if opciones is not None and v not in opciones:
            return f"debe ser uno de {sorted(opciones)}"
        return None
    return validar


def _booleano(v):
    return None if isinstance(v, bool) else "debe ser true/false"


def _fecha_o_nulo(v):
    if v is None:
        return None
    if isinstance(v, datetime) or not isinstance(v, date):
        return "debe ser una fecha AAAA-MM-DD sin comillas, o null"
    return None


def _lista_textos(v):
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        return "debe ser una lista de textos"
    return None


def _zona_horaria(v):
    if (err := _texto()(v)):
        return err
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        return f"zona horaria desconocida: {v!r}"
    return None


def _horas_punta(v):
    if not isinstance(v, list) or not v:
        return "debe ser una lista no vacia de horas"
    if any(isinstance(h, bool) or not isinstance(h, int) or not 0 <= h <= 23 for h in v):
        return "cada hora debe ser un entero 0-23"
    if len(set(v)) != len(v):
        return "hay horas repetidas"
    return None


def _periodos_por_mes(v):
    if not isinstance(v, dict) or set(v) != set(range(1, 13)) or any(isinstance(k, bool) for k in v):
        return "debe tener exactamente los meses 1-12 (enteros)"
    for mes, par in v.items():
        if not isinstance(par, list) or len(par) != 2 or any(p not in PERIODOS[:5] for p in par):
            return f"mes {mes}: debe ser [periodo_punta, periodo_llano] con valores P1-P5"
    return None


def _por_periodo(minimo=0.0, maximo_excl=None, nulo=False) -> Validador:
    def validar(v):
        if v is None:
            return None if nulo else "no puede ser null"
        if not isinstance(v, dict) or tuple(v) != PERIODOS:
            return f"debe tener exactamente {list(PERIODOS)} en ese orden"
        for p, x in v.items():
            if not _es_numero(x) or x < minimo or (maximo_excl is not None and x >= maximo_excl):
                limite = f"[{minimo}, {maximo_excl})" if maximo_excl is not None else f">= {minimo}"
                return f"{p}={x!r} debe ser numero {limite}"
        return None
    return validar


def _por_trimestre(minimo, maximo) -> Validador:
    def validar(v):
        if not isinstance(v, dict) or tuple(v) != TRIMESTRES:
            return f"debe tener exactamente {list(TRIMESTRES)} en ese orden"
        for t, x in v.items():
            if not _es_numero(x) or not minimo <= x <= maximo:
                return f"{t}={x!r} debe ser numero entre {minimo} y {maximo}"
        return None
    return validar


def _festivos(v):
    if not isinstance(v, list) or not v:
        return "debe ser una lista no vacia de fechas"
    if any(isinstance(d, datetime) or not isinstance(d, date) for d in v):
        return "cada festivo debe ser una fecha AAAA-MM-DD sin comillas"
    if len(set(v)) != len(v):
        return "hay festivos repetidos"
    return None


def _nulo(v):
    return None if v is None else "solo admite null en esta forma (usar p1..p6 para valores)"


# --------------------------------------------------------------------------- esquema
# ruta -> (validador, obligatoria_en_config_final)
_POS = _num(minimo_excl=0)
_NO_NEG = _num(minimo=0)
_CAL_P6 = _num(minimo=0, maximo=24, entero=True)


def _num_o_por_periodo(v):
    """Pc: un numero unico o un valor por periodo {P1..P6} (Claudia, BOE-A-2025-26705)."""
    return _por_periodo(0.0)(v) if isinstance(v, dict) else _NO_NEG(v)


ESQUEMA: dict[tuple, tuple[Validador, bool]] = {
    ("caso", "nombre"): (_texto(), True),
    ("caso", "sector"): (_texto(), True),
    ("caso", "cnae"): (_texto(), False),
    ("caso", "ubicacion"): (_texto(), False),
    ("caso", "proceso"): (_texto(), False),
    ("caso", "etiqueta_resultado"): (_texto(), True),
    ("planta", "volumen_m3_dia"): (_POS, False),
    ("planta", "consumo_especifico_kwh_m3"): (_POS, False),
    ("planta", "consumo_diario_mwh"): (_POS, False),
    ("planta", "conexion_kv"): (_POS, True),
    ("planta", "dias_operacion_ano"): (_num(minimo=1, maximo=366, entero=True), True),
    ("carga_flexible", "energia_diaria_mwh"): (_POS, True),
    ("carga_flexible", "limite_mwh_hora"): (_POS, True),
    ("carga_flexible", "candidatas"): (_lista_textos, False),
    ("baseline_s0", "mwh_hora"): (_POS, True),
    ("baseline_s0", "hora_inicio"): (_num(minimo=0, maximo=23, entero=True), True),
    ("baseline_s0", "hora_fin"): (_num(minimo=1, maximo=24, entero=True), True),
    ("optimizacion_s1", "franja_preferente_inicio"): (_num(minimo=0, maximo=23, entero=True), True),
    ("optimizacion_s1", "franja_preferente_fin"): (_num(minimo=1, maximo=24, entero=True), True),
    ("optimizacion_s1", "rampa_max_mwh_hora"): (_num(minimo_excl=0, nulo=True), True),
    ("optimizacion_s1", "min_horas_encendido"): (_num(minimo=1, entero=True, nulo=True), True),
    ("optimizacion_s1", "coste_arranque_eur"): (_num(minimo=0, nulo=True), True),
    # Propia de desalacion: solo la declara la industria que la tiene.
    ("optimizacion_s1", "deposito_agua_mwh_equivalente"): (_num(minimo=0, nulo=True), False),
    ("mercado", "fuente"): (_texto(), True),
    ("mercado", "serie"): (_texto(), True),
    ("mercado", "zona_horaria"): (_zona_horaria, True),
    ("mercado", "politica_negativos"): (_texto(POLITICAS_NEGATIVOS), True),
    ("mercado", "fecha_inicio"): (_fecha_o_nulo, True),
    ("mercado", "fecha_fin"): (_fecha_o_nulo, True),
    ("tarifa", "acceso"): (_texto(TARIFAS_ACCESO), True),
    ("tarifa", "zona"): (_texto(), True),
    ("tarifa", "anio_regulatorio"): (_num(minimo=2000, maximo=2100, entero=True), True),
    ("tarifa", "segmento_cargos"): (_num(minimo=1, maximo=6, entero=True), True),
    **{("componentes", c): (_booleano, True) for c in (
        "spot", "peaje_energia", "cargo_energia", "perdidas", "iee", "iva", "potencia_y_excesos")},
    ("calendario_tarifario", "p6_antes_de_hora"): (_CAL_P6, True),
    ("calendario_tarifario", "horas_punta"): (_horas_punta, True),
    ("calendario_tarifario", "periodos_por_mes"): (_periodos_por_mes, True),
    ("contrato", "modelo"): (_texto(), True),
    ("contrato", "resolucion"): (_texto(), True),
    ("contrato", "liquidacion_negativos"): (_texto(), True),
    ("contrato", "factor_formula"): (_POS, True),
    ("contrato", "pc_eur_mwh"): (_num_o_por_periodo, True),
    **{("contrato", c): (_NO_NEG, True) for c in (
        "sc_eur_mwh", "dsv_eur_mwh", "posom_eur_mwh", "fe_eur_mwh", "f_eur_mwh")},
    # Metadatos del contrato de Claudia (no intervienen en el calculo actual).
    ("contrato", "factor_desvio_som_por_trimestre"): (_por_trimestre(0, 1), False),
    ("contrato", "coste_omie_2026_eur_mwh"): (_NO_NEG, False),
    ("contrato", "coste_ree_os_2026_eur_mwh"): (_NO_NEG, False),
    ("contrato", "perdidas_fraccion"): (_num(minimo=0, maximo_excl=1), True),
    **{("contrato", "gdo_eur_mwh_por_trimestre", t): (_NO_NEG, True) for t in TRIMESTRES},
    ("contrato", "criterio_gdo"): (_texto(), True),
    ("operacion_demo", "perfil_no_flexible"): (_texto(), True),
    ("operacion_demo", "flexibilidad_validada_en_planta"): (_booleano, True),
    ("operacion_demo", "potencia_contratada_mw"): (_nulo, False),
    **{("operacion_demo", "potencia_contratada_mw", f"p{i}"): (_POS, False) for i in range(1, 7)},
    ("desconocido",): (_lista_textos, False),
}
# Bloques dinamicos de tarifas_reguladas.<acceso>...
ESQUEMA_TARIFA = {
    ("calendario", "p6_antes_de_hora"): _CAL_P6,
    ("calendario", "horas_punta"): _horas_punta,
    ("calendario", "periodos_por_mes"): _periodos_por_mes,
    ("perdidas_reguladas_fraccion",): _por_periodo(0.0, 1.0, nulo=True),
}
ESQUEMA_ANIO = {
    "peajes_energia_eur_mwh": _por_periodo(0.0),
    "cargos_energia_eur_mwh": _por_periodo(0.0),
    "festivos_nacionales": _festivos,
}


def _validador_de(path: tuple) -> Optional[Validador]:
    if path in ESQUEMA:
        return ESQUEMA[path][0]
    if len(path) >= 3 and path[0] == "tarifas_reguladas":
        if path[1] not in TARIFAS_ACCESO:
            return None
        resto = path[2:]
        if resto in ESQUEMA_TARIFA:
            return ESQUEMA_TARIFA[resto]
        if len(resto) == 3 and resto[0] == "anios" and resto[2] in ESQUEMA_ANIO:
            return ESQUEMA_ANIO[resto[2]]
    return None


# --------------------------------------------------------------------------- lectura y fusion
def _leer_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"No existe el YAML: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML mal formado: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: la raiz del YAML debe ser un diccionario")
    return raw


def _es_hoja(nodo: Any) -> bool:
    return isinstance(nodo, dict) and "value" in nodo


def deep_merge(base: dict, override: dict, _ruta_actual: tuple = ()) -> dict:
    """Fusion profunda sin mutar las entradas. Override gana.

    - Hoja vs hoja: la del override sustituye a la completa.
    - Dict vs dict: se fusionan recursivamente.
    - Hoja vs bloque (o al reves): error, el override cambia la forma del parametro.
    """
    resultado = deepcopy(base)
    for clave, valor in override.items():
        ruta = _ruta_actual + (clave,)
        if clave not in resultado:
            resultado[clave] = deepcopy(valor)
            continue
        actual = resultado[clave]
        bloque_a = isinstance(actual, dict) and not _es_hoja(actual)
        bloque_b = isinstance(valor, dict) and not _es_hoja(valor)
        if bloque_a and bloque_b:
            resultado[clave] = deep_merge(actual, valor, ruta)
        elif bloque_a != bloque_b:
            raise ConfigError(
                f"{_ruta(ruta)}: la industria cambia la forma del parametro "
                f"(hoja <-> bloque). Revisa la indentacion o el nombre de la clave."
            )
        else:
            resultado[clave] = deepcopy(valor)
    return resultado


def _hojas(nodo: dict, origen: str, ruta: tuple = ()) -> dict[tuple, dict]:
    """Devuelve {ruta: hoja} validando la ESTRUCTURA de cada hoja."""
    salida: dict[tuple, dict] = {}
    for clave, hijo in nodo.items():
        r = ruta + (clave,)
        if r == ("version_config",):
            if isinstance(hijo, bool) or not isinstance(hijo, int):
                raise ConfigError(f"{origen}: version_config debe ser entero")
            continue
        if r == ("fuentes_demo",):
            if not isinstance(hijo, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in hijo.items()):
                raise ConfigError(f"{origen}: fuentes_demo debe ser un diccionario clave: texto")
            continue
        if _es_hoja(hijo):
            extra = set(hijo) - CLAVES_HOJA
            if extra:
                raise ConfigError(f"{origen}: {_ruta(r)} tiene claves no permitidas en una hoja: {sorted(extra)}")
            st = hijo.get("source_type")
            if not isinstance(st, str) or st not in SOURCE_TYPES:
                raise ConfigError(f"{origen}: {_ruta(r)}: source_type {st!r} no valido; permitidos {sorted(SOURCE_TYPES)}")
            for meta in ("nota", "fuente"):
                if meta in hijo and (not isinstance(hijo[meta], str) or not hijo[meta].strip()):
                    raise ConfigError(f"{origen}: {_ruta(r)}: '{meta}' debe ser texto no vacio")
            salida[r] = hijo
        elif isinstance(hijo, dict):
            if not hijo:
                raise ConfigError(f"{origen}: {_ruta(r)} es un bloque vacio")
            if "source_type" in hijo:
                raise ConfigError(f"{origen}: {_ruta(r)} tiene source_type pero le falta 'value'")
            salida.update(_hojas(hijo, origen, r))
        else:
            raise ConfigError(
                f"{origen}: {_ruta(r)} = {hijo!r} no tiene formato {{value, source_type}}")
    return salida


def _a_valores(nodo: dict) -> dict:
    """Arbol de hojas -> arbol de valores (formato de config_loader.cargar_config)."""
    salida = {}
    for clave, hijo in nodo.items():
        if _es_hoja(hijo):
            salida[clave] = deepcopy(hijo["value"])
        elif isinstance(hijo, dict) and clave != "fuentes_demo":
            salida[clave] = _a_valores(hijo)
        else:
            salida[clave] = deepcopy(hijo)
    return salida


def _materializar_calendarios(raw: dict) -> set[str]:
    """Copia calendario_tarifario en cada tarifa que no declare uno propio.

    src/tarifas_6_2td.py lee tarifas_reguladas.<acceso>.calendario: se mantiene ese contrato
    sin duplicar el calendario en base.yaml. Devuelve las tarifas que lo han heredado.
    """
    tarifas = raw.get("tarifas_reguladas")
    if not isinstance(tarifas, dict) or not tarifas:
        raise ConfigError("Falta el catalogo tarifas_reguladas en base.yaml")
    heredan = set()
    for acceso, bloque in tarifas.items():
        if isinstance(bloque, dict) and "calendario" not in bloque:
            if "calendario_tarifario" not in raw:
                raise ConfigError(
                    f"tarifas_reguladas.{acceso} no tiene calendario y falta calendario_tarifario en base.yaml")
            bloque["calendario"] = deepcopy(raw["calendario_tarifario"])
            heredan.add(acceso)
    return heredan


# --------------------------------------------------------------------------- coherencia
def _consumo_diario(planta: dict) -> tuple[float, str]:
    directo = planta.get("consumo_diario_mwh")
    vol, esp = planta.get("volumen_m3_dia"), planta.get("consumo_especifico_kwh_m3")
    if directo is not None:
        if not _es_numero(directo) or directo <= 0:
            raise ConfigError("planta.consumo_diario_mwh debe ser un numero > 0")
        return float(directo), "directo"
    if vol is None or esp is None:
        raise ConfigError(
            "La planta necesita consumo_diario_mwh, o volumen_m3_dia + consumo_especifico_kwh_m3")
    if not (_es_numero(vol) and _es_numero(esp)) or vol <= 0 or esp <= 0:
        raise ConfigError("volumen_m3_dia y consumo_especifico_kwh_m3 deben ser numeros > 0")
    return vol * esp / 1000.0, "volumen_x_consumo_especifico"


def _validar_coherencia(cfg: dict) -> None:
    """Reglas entre parametros. Se ejecuta SIEMPRE al cargar y dentro de derivados()."""
    consumo, _ = _consumo_diario(cfg["planta"])
    flex = cfg["carga_flexible"]["energia_diaria_mwh"]
    limite = cfg["carga_flexible"]["limite_mwh_hora"]
    for nombre, v in (("energia_diaria_mwh", flex), ("limite_mwh_hora", limite)):
        if not _es_numero(v) or v <= 0:
            raise ConfigError(f"carga_flexible.{nombre} debe ser un numero > 0")
    if flex > consumo + _TOL:
        raise ConfigError(
            f"Carga flexible ({flex} MWh/dia) mayor que el consumo diario ({consumo} MWh/dia)")
    if limite * 24 < flex - _TOL:
        raise ConfigError(
            f"Inviable: {flex} MWh/dia no caben en 24 h con limite {limite} MWh/h")

    b = cfg["baseline_s0"]
    if b["hora_fin"] <= b["hora_inicio"]:
        raise ConfigError("Baseline: hora_fin debe ser mayor que hora_inicio (no cruza medianoche)")
    if b["mwh_hora"] > limite + _TOL:
        raise ConfigError(f"Baseline: {b['mwh_hora']} MWh/h supera el limite de {limite} MWh/h")
    energia_baseline = b["mwh_hora"] * (b["hora_fin"] - b["hora_inicio"])
    if abs(energia_baseline - flex) > _TOL:
        raise ConfigError(
            f"Baseline ({energia_baseline} MWh) distinto de la carga flexible ({flex} MWh)")

    o = cfg["optimizacion_s1"]
    if o["franja_preferente_fin"] <= o["franja_preferente_inicio"]:
        raise ConfigError("optimizacion_s1: franja_preferente_fin debe ser mayor que el inicio")

    m = cfg["mercado"]
    if m.get("fecha_inicio") and m.get("fecha_fin") and m["fecha_inicio"] > m["fecha_fin"]:
        raise ConfigError("mercado: fecha_inicio posterior a fecha_fin")


def _validar_tarifas(cfg: dict) -> None:
    """Valida TODO el catalogo y que exista la tarifa/año elegidos por la industria."""
    tarifas = cfg["tarifas_reguladas"]
    for acceso, bloque in tarifas.items():
        if acceso not in TARIFAS_ACCESO:
            raise ConfigError(f"tarifas_reguladas: tarifa desconocida {acceso!r}")
        for clave in ("calendario", "perdidas_reguladas_fraccion", "anios"):
            if clave not in bloque:
                raise ConfigError(f"tarifas_reguladas.{acceso}: falta '{clave}'")
        anios = bloque["anios"]
        if not isinstance(anios, dict) or not anios:
            raise ConfigError(f"tarifas_reguladas.{acceso}.anios vacio")
        for clave_anio, datos in anios.items():
            if isinstance(clave_anio, bool) or not isinstance(clave_anio, int):
                raise ConfigError(
                    f"tarifas_reguladas.{acceso}.anios: la clave {clave_anio!r} debe ser un entero (2026, sin comillas)")
            faltan = set(ESQUEMA_ANIO) - set(datos)
            if faltan:
                raise ConfigError(f"tarifas_reguladas.{acceso}.anios.{clave_anio}: faltan {sorted(faltan)}")
            fuera = [d for d in datos["festivos_nacionales"] if d.year != clave_anio]
            if fuera:
                raise ConfigError(f"tarifas_reguladas.{acceso}.anios.{clave_anio}: festivos de otro año {fuera}")
        cal = bloque["calendario"]
        if any(h < cal["p6_antes_de_hora"] for h in cal["horas_punta"]):
            raise ConfigError(f"tarifas_reguladas.{acceso}.calendario: horas_punta anteriores a p6_antes_de_hora")

    acceso = cfg["tarifa"]["acceso"]
    anio = cfg["tarifa"]["anio_regulatorio"]
    if acceso not in tarifas:
        raise ConfigError(
            f"No hay datos regulados de {acceso} en el catalogo; disponibles {sorted(tarifas)}")
    if anio not in tarifas[acceso]["anios"]:
        raise ConfigError(
            f"No hay peajes y cargos de {acceso} para {anio}; años disponibles {sorted(tarifas[acceso]['anios'])}")


def _tipo_optimizador(activas: list[str]) -> str:
    if not activas:
        return "greedy"  # ordenar horas por coste es optimo
    if {"min_horas_encendido", "coste_arranque_eur"} & set(activas):
        return "MILP"     # necesita variables binarias (encendido/arranque)
    return "LP"           # rampa y deposito son restricciones lineales


def derivados(cfg: dict) -> dict:
    """Valores calculados (source_type = derived). Valida coherencia antes de calcular."""
    _validar_coherencia(cfg)
    consumo, metodo = _consumo_diario(cfg["planta"])
    flex = cfg["carga_flexible"]["energia_diaria_mwh"]
    limite = cfg["carga_flexible"]["limite_mwh_hora"]
    restr = cfg["optimizacion_s1"]
    activas = [k for k in RESTRICCIONES_OPERATIVAS if restr.get(k) is not None]
    return {
        "consumo_estimado_mwh_dia": consumo,
        "consumo_estimado_gwh_ano": consumo * cfg["planta"]["dias_operacion_ano"] / 1000,
        "fraccion_flexible": flex / consumo,
        "horas_minimas_s1": math.ceil(flex / limite - _TOL),
        "requiere_programacion_lineal": bool(activas),  # nombre heredado: LP o MILP
        "restricciones_operativas_activas": activas,
        "tipo_optimizador_sugerido": _tipo_optimizador(activas),
        "metodo_consumo": metodo,
        "resolucion_minutos": 60,
    }


# --------------------------------------------------------------------------- carga
@dataclass(frozen=True)
class ConfigCargada:
    industria: str
    valores: dict
    tipos: dict          # "seccion.parametro" -> source_type (mismo formato que el loader actual)
    trazabilidad: dict   # "seccion.parametro" -> {source_type, nota, fuente, url, origen, valor_base}
    derivados: dict
    advertencias: tuple
    raw: dict = field(default_factory=dict, repr=False, compare=False)  # base+industria fusionado

    @property
    def apto_para_resultado_real(self) -> bool:
        """False mientras haya hipotesis criticas: el resultado es una simulacion."""
        return not self.advertencias


def _ruta_industria(industria: str, config_dir: Path) -> Path:
    if not isinstance(industria, str) or not _ID_INDUSTRIA.fullmatch(industria):
        raise ConfigError(f"Industria no valida: {industria!r} (solo a-z, 0-9 y _)")
    carpeta = (config_dir / "industrias").resolve()
    ruta = (carpeta / f"{industria}.yaml").resolve()
    if ruta.parent != carpeta:
        raise ConfigError(f"Industria no valida: {industria!r}")
    if not ruta.is_file():
        disponibles = sorted(p.stem for p in carpeta.glob("*.yaml"))
        raise ConfigError(f"No existe la industria {industria!r}; disponibles: {disponibles}")
    return ruta


def cargar_escenario(industria: str, config_dir: str | Path | None = None) -> ConfigCargada:
    config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR_POR_DEFECTO
    ruta_base = config_dir / "base.yaml"
    ruta_ind = _ruta_industria(industria, config_dir)
    nombre_ind = f"industrias/{ruta_ind.name}"
    raw_base, raw_ind = _leer_yaml(ruta_base), _leer_yaml(ruta_ind)

    hojas_base = _hojas(raw_base, ruta_base.name)
    hojas_ind = _hojas(raw_ind, nombre_ind)
    for r in OBLIGATORIAS_EN_INDUSTRIA:
        if r not in hojas_ind:
            raise ConfigError(f"{nombre_ind} debe declarar explicitamente {_ruta(r)}")

    raw = deep_merge(raw_base, raw_ind)
    calendario_heredado = _materializar_calendarios(raw)
    hojas = _hojas(raw, "config final")

    # Claves desconocidas (erratas) y valores por esquema.
    for r, hoja in hojas.items():
        validador = _validador_de(r)
        if validador is None:
            origen = nombre_ind if r in hojas_ind else ruta_base.name
            raise ConfigError(f"{origen}: clave desconocida '{_ruta(r)}' (¿errata?)")
        if (err := validador(hoja["value"])):
            raise ConfigError(f"{_ruta(r)}: {err}")
    for r, (_, obligatoria) in ESQUEMA.items():
        if obligatoria and r not in hojas:
            raise ConfigError(f"Falta campo obligatorio: {_ruta(r)}")

    # Contrato distinto del de referencia: no se heredan importes.
    modelo_base = hojas_base.get(("contrato", "modelo"), {}).get("value")
    if hojas_ind[("contrato", "modelo")]["value"] != modelo_base:
        faltan = [t for t in TERMINOS_CONTRATO
                  if not any(r[:2] == ("contrato", t) for r in hojas_ind)]
        if faltan:
            raise ConfigError(
                f"La industria usa otro contrato.modelo y no define: {faltan}. "
                "No se heredan importes de un contrato diferente.")

    valores = _a_valores(raw)
    _validar_tarifas(valores)
    der = derivados(valores)  # incluye _validar_coherencia

    fuentes = valores.get("fuentes_demo", {})
    tipos, traza = {}, {}
    for r, hoja in hojas.items():
        clave = _ruta(r)
        if r in hojas_ind:
            origen = "industria (sobrescribe base)" if r in hojas_base else "industria"
        elif len(r) >= 3 and r[0] == "tarifas_reguladas" and r[2] == "calendario" and r[1] in calendario_heredado:
            origen = "base (calendario_tarifario)"
        else:
            origen = "base"
        fuente = hoja.get("fuente")
        if fuente is not None and fuente not in fuentes:
            raise ConfigError(f"{clave}: fuente '{fuente}' no existe en fuentes_demo")
        tipos[clave] = hoja["source_type"]
        traza[clave] = {
            "source_type": hoja["source_type"],
            "nota": hoja.get("nota"),
            "fuente": fuente,
            "url": fuentes.get(fuente) if fuente else None,
            "origen": origen,
            "valor_base": deepcopy(hojas_base[r]["value"]) if origen.startswith("industria (") else None,
        }

    acceso = valores["tarifa"]["acceso"]
    return ConfigCargada(
        industria=industria,
        valores=valores,
        tipos=tipos,
        trazabilidad=traza,
        derivados=der,
        advertencias=tuple(_advertencias(valores, hojas, acceso, der)),
        raw=raw,
    )


def _advertencias(cfg: dict, hojas: dict, acceso: str, der: dict) -> list[str]:
    avisos = []
    anio = cfg["tarifa"]["anio_regulatorio"]
    criticos = list(CRITICOS) + [
        ("tarifas_reguladas", acceso, "anios", anio, "peajes_energia_eur_mwh"),
        ("tarifas_reguladas", acceso, "anios", anio, "cargos_energia_eur_mwh"),
        ("planta", "consumo_diario_mwh") if der["metodo_consumo"] == "directo"
        else ("planta", "consumo_especifico_kwh_m3"),
    ]
    for r in criticos:
        hoja = hojas.get(r)
        if hoja and hoja["source_type"] != "documented":
            avisos.append(f"{_ruta(r)} es {hoja['source_type']}: resultado simulado, no real")
    planta = cfg["planta"]
    if planta.get("consumo_diario_mwh") is not None and planta.get("volumen_m3_dia") is not None:
        avisos.append("planta: hay consumo_diario_mwh y volumen_m3_dia; se usa consumo_diario_mwh")
    if cfg["componentes"]["perdidas"] and cfg["tarifas_reguladas"][acceso]["perdidas_reguladas_fraccion"] is None:
        avisos.append(f"perdidas reguladas de {acceso} desconocidas: se usa solo contrato.perdidas_fraccion constante")
    if cfg["operacion_demo"].get("potencia_contratada_mw") is None:
        avisos.append("potencia contratada desconocida: no se pueden verificar excesos de potencia")
    if not cfg["operacion_demo"]["flexibilidad_validada_en_planta"]:
        avisos.append("flexibilidad no validada en planta")
    return avisos


def cargar_config_compuesta(industria: str, config_dir: str | Path | None = None) -> tuple[dict, dict]:
    """Compatibilidad con config_loader.cargar_config: devuelve (valores, tipos), ya validados."""
    escenario = cargar_escenario(industria, config_dir)
    return escenario.valores, escenario.tipos


def yaml_resuelto(escenario: ConfigCargada) -> str:
    """YAML unico (base + industria) con el formato de los YAML completos antiguos.

    Solo conserva la tarifa elegida (con su calendario ya copiado) y quita el bloque comun
    calendario_tarifario, de modo que lo puede leer config_loader.cargar_config, la app y
    src/tarifas_6_2td.py exactamente igual que config_desaladora.yaml.
    """
    raw = deepcopy(escenario.raw)
    if not raw:
        raise ConfigError("El escenario no contiene la configuracion fusionada (raw).")
    acceso = escenario.valores["tarifa"]["acceso"]
    raw["tarifas_reguladas"] = {acceso: raw["tarifas_reguladas"][acceso]}
    raw.pop("calendario_tarifario", None)
    cabecera = (
        f"# Configuracion RESUELTA: config/base.yaml + config/industrias/{escenario.industria}.yaml\n"
        "# Generada por src/config_loader_compuesto.py. No editar a mano.\n"
    )
    return cabecera + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
