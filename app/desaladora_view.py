"""Presentation of the hypothetical indexed desalination case and its provenance."""

import json

import pandas as pd
import streamlit as st
import yaml

from desaladora_data import COMPONENTS

SOM_SCOPE = (
    "Simulación desaladora · referencia Som Energia 6.2TD, no contrato ni factura real. "
    "S1 se optimiza por el precio indexado completo, incluidos peajes y cargos. "
    "Aproximación horaria mediante media de cuatro cuartos; costes comerciales supuestos. "
    "Antes de IVA e IEE; sin término de potencia, excesos, reactiva ni otros conceptos de factura."
)
COMPONENT_LABELS = [
    "Mercado REData", "Pc", "Sc", "Desvíos", "GdO", "Operadores",
    "Pérdidas", "FE", "F", "Ajuste factor 1,015", "Peajes", "Cargos",
]


def configuration_rows(config: dict, prefix: str = "") -> list[dict]:
    rows = []
    labels = {"documented": "Documentado", "hypothesis": "Supuesto / aproximación", "derived": "Derivado"}
    for key, node in config.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(node, dict) and "value" in node and "source_type" in node:
            rows.append({
                "Parámetro": path, "Valor": json.dumps(node["value"], ensure_ascii=False),
                "Clasificación": labels[node["source_type"]], "Nota": node.get("nota", ""),
            })
        elif isinstance(node, dict):
            rows.extend(configuration_rows(node, path))
    return rows


def render_case(metadata: dict, summary: pd.DataFrame) -> None:
    cfg = yaml.safe_load(metadata["config_yaml"])
    st.subheader("Caso desaladora · Som Energia de referencia")
    st.caption(
        "Documentado significa respaldado por la referencia indicada, no verificado "
        "en una desaladora operativa ni confirmado por un contrato individual 6.2TD."
    )
    plant = cfg["planta"]
    flexible = cfg["carga_flexible"]
    volume = plant["volumen_m3_dia"]["value"]
    specific = plant["consumo_especifico_kwh_m3"]["value"]
    with st.container(horizontal=True):
        st.metric("Producción de referencia", f"{volume:,.0f} m³/día", border=True)
        st.metric("Energía estimada · derivada", f"{volume * specific / 1000:g} MWh/día", border=True)
        st.metric("Carga flexible · supuesta", f"{flexible['energia_diaria_mwh']['value']:g} MWh/día", border=True)
    st.markdown(
        "**Contrato ficticio peninsular:** fórmula pública de Som Energia, "
        "sin oferta individualizada 6.2TD. F se extrapola de 6.1TD; "
        "las pérdidas y los costes de adquisición son ilustrativos, no calibrados. "
        "La conservación de precios indexados negativos es una política simulada, "
        "no una liquidación contractual confirmada."
    )
    st.code("PH = 1.015 × [(PHM + Pc + Sc + Dsv + GdO + POsOm) × (1 + Perd) + FE + F] + PTD + CA", language=None)
    st.info(
        "S0 y S1 conservan la misma energía diaria. Se comprueba la potencia media horaria "
        "de toda la planta con la carga no flexible incluida. Eso no garantiza límites "
        "cuartohorarios ni viabilidad de bombas, membranas, rampas, arranques o depósito de agua."
    )
    st.subheader("Cobertura y trazabilidad")
    st.caption(f"Ejecución generada (UTC): {metadata['generado_utc']}")
    st.caption(f"Silver: {metadata['silver_origen']}")
    st.caption(f"Versión Silver: {metadata['silver_version_id'] or 'S3 sin identificador de versión'}")
    st.caption(f"SHA256 Silver: {metadata['silver_sha256']}")
    st.caption(f"SHA256 configuración: {metadata['config_sha256']}")
    st.caption(f"Vigencia tarifaria publicada: {metadata['tarifa']['anio']}. Sin extrapolación a otros años.")
    excluded = metadata["horas_silver_fuera_vigencia_tarifa"]
    if excluded:
        st.warning(f"{excluded} horas Silver excluidas por estar fuera de la vigencia tarifaria.")
    st.dataframe(
        summary[["fecha_local", "horas_esperadas", "horas_disponibles", "estado_optimizacion"]],
        hide_index=True, alt="Cobertura diaria y motivos de ausencia de programación",
    )
    st.download_button(
        "Descargar cobertura diaria", summary.to_csv(index=False).encode("utf-8"),
        file_name="desaladora_cobertura.csv", mime="text/csv",
    )
    st.subheader("Datos documentados, supuestos y aproximaciones")
    st.dataframe(
        pd.DataFrame(configuration_rows(cfg)), hide_index=True,
        alt="Parámetros de la configuración realmente utilizada y su clasificación",
    )
    with st.expander("Fuentes y configuración exacta de esta ejecución"):
        st.json(cfg["fuentes_demo"])
        st.code(metadata["config_yaml"], language="yaml")
        st.download_button(
            "Descargar YAML de la ejecución", metadata["config_yaml"].encode("utf-8"),
            file_name="config_desaladora_ejecucion.yaml", mime="text/yaml",
        )
        st.download_button(
            "Descargar metadata", json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="desaladora_metadata.json", mime="application/json",
        )


def render_indexed_schedule(schedule: pd.DataFrame) -> None:
    st.caption(
        "Plan S1 publicado por el backend: minimiza el precio indexado completo, no solo el spot. "
        "Los intervalos conservan su desfase UTC, también durante el cambio de hora."
    )
    display = schedule.copy()
    display["Intervalo local"] = display["datetime_local"].map(
        lambda value: f"{value:%H:%M %Z %z} – {value + pd.Timedelta(hours=1):%H:%M %Z %z}"
    )
    labels = {
        "periodo_tarifario": "Periodo", "precio_eur_mwh": "Spot EUR/MWh",
        "precio_indexado_eur_mwh": "Indexado EUR/MWh",
        "consumo_baseline_mwh": "Flexible S0 MWh", "consumo_optimizado_mwh": "Flexible S1 MWh",
        "consumo_planta_optimizado_mwh": "Planta S1 MWh",
        "potencia_contratada_mw": "Potencia supuesta MW",
        "coste_energia_flexible_baseline_eur": "Coste flexible S0 EUR",
        "coste_energia_flexible_optimizado_eur": "Coste flexible S1 EUR",
    }
    st.dataframe(
        display[["Intervalo local", *labels]].rename(columns=labels), hide_index=True,
        alt="Programación horaria indexada, consumos flexibles y potencia de planta",
    )
    st.subheader("Desglose del coste de energía del día")
    breakdown = pd.DataFrame({
        "Componente": COMPONENT_LABELS,
        "Flexible S0 EUR": [float((schedule[c] * schedule["consumo_baseline_mwh"]).sum()) for c in COMPONENTS],
        "Flexible S1 EUR": [float((schedule[c] * schedule["consumo_optimizado_mwh"]).sum()) for c in COMPONENTS],
    })
    breakdown["Ahorro EUR"] = breakdown["Flexible S0 EUR"] - breakdown["Flexible S1 EUR"]
    st.dataframe(breakdown, hide_index=True, alt="Coste por componente, con peajes y cargos contados una sola vez")
    st.caption("Las pérdidas, el factor 1,015 y los costes comerciales ya están incluidos; no se vuelven a sumar peajes ni cargos.")
    with st.expander("Componentes horarios del precio · EUR/MWh"):
        st.dataframe(
            display[["Intervalo local", *COMPONENTS, "precio_indexado_eur_mwh"]],
            hide_index=True, alt="Componentes horarios del precio indexado completo",
        )
    with st.container(horizontal=True):
        for scenario, label in (("baseline", "S0"), ("optimizado", "S1")):
            cost = schedule[f"coste_energia_planta_{scenario}_eur"].sum()
            st.metric(f"Energía de toda la planta {label}", f"{cost:,.2f} EUR", border=True)
    st.caption("Los indicadores de ahorro de las otras vistas usan solo la carga flexible; la carga no flexible es la misma en S0 y S1.")
    st.download_button(
        "Descargar plan del día", schedule.to_csv(index=False).encode("utf-8"),
        file_name=f"desaladora_plan_{schedule['fecha_local'].iloc[0]}.csv", mime="text/csv",
    )
