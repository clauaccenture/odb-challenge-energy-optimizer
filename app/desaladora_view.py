"""Presentation of the hypothetical indexed desalination case and its provenance."""

import pandas as pd
import streamlit as st
import yaml

from desaladora_data import COMPONENTS
from formatting import format_eur, format_number, format_pct
from som_hour_table import render_hour_table

SOM_SCOPE = (
    "Simulación desaladora · referencia Som Energia 6.2TD, no contrato ni factura real. "
    "S1 se optimiza por el precio indexado completo, incluidos peajes y cargos. "
    "Aproximación horaria mediante media de cuatro cuartos; costes comerciales supuestos. "
    "Antes de IVA e IEE; sin término de potencia, excesos, reactiva ni otros conceptos de factura."
)
COMPONENT_LABELS = [
    "Mercado REData", "Pagos por capacidad", "Sobrecostes de gestión de la red",
    "Desvíos", "Garantías de origen", "Operadores REE y OMIE", "Pérdidas de energía (coste)",
    "Fondo de eficiencia energética", "Margen de la cooperativa", "Ajuste factor 1,015", "Peajes", "Cargos",
]


def render_case(metadata: dict, summary: pd.DataFrame) -> None:
    cfg = yaml.safe_load(metadata["config_yaml"])
    plant = cfg["planta"]
    flexible = cfg["carga_flexible"]
    volume = plant["volumen_m3_dia"]["value"]
    specific = plant["consumo_especifico_kwh_m3"]["value"]
    energy = volume * specific / 1000
    target = flexible["energia_diaria_mwh"]["value"]
    limit = flexible["limite_mwh_hora"]["value"]
    reference, assumptions = st.columns(2)
    with reference, st.container(border=True):
        st.subheader("Referencia del TFM")
        volume_label = f"{volume:,.0f}".replace(",", ".")
        st.markdown(
            f"- **Producción:** {volume_label} m³/día.\n"
            f"- **Conexión eléctrica:** {plant['conexion_kv']['value']:g} kV.\n"
        )
        st.caption("Datos de la referencia académica utilizada; no mediciones de una planta operativa.")
    with assumptions, st.container(border=True):
        st.subheader("Supuestos eléctricos de la demo")
        st.markdown(
            f"- **Contrato:** Som Energia indexado, 6.2TD peninsular supuesto; no contrato firmado.\n"
            f"- **Consumo específico:** {specific:g} kWh/m³ supuesto → {energy:g} MWh/día estimados.\n"
            f"- **Carga flexible:** {target:g} MWh/día, hasta {limit:g} MWh por hora.\n"
            f"- **Resto de la carga:** {energy - target:g} MWh/día, repartidos uniformemente.\n"
        )
        powers = cfg["operacion_demo"]["potencia_contratada_mw"]
        power_values = [node["value"] for node in powers.values()]
        power_label = (
            f"{power_values[0]:g} MW en P1–P6" if len(set(power_values)) == 1
            else "; ".join(f"{period.upper()}: {node['value']:g} MW" for period, node in powers.items())
        )
        st.caption(f"Potencia contratada supuesta: {power_label}. No es un dato confirmado de la instalación.")
    st.subheader("Precio indexado de referencia Som Energia")
    st.latex(r"PH = 1{,}015\,[(PHM + Pc + Sc + Dsv + GdO + POsOm)(1 + Perd) + FE + F] + PTD + CA")
    st.caption("La fórmula es pública. Su aplicación a este contrato 6.2TD es simulada. Importes en EUR/MWh; Perd es una fracción y 1,015 un factor.")
    st.table(formula_legend(cfg, metadata["tarifa"]["anio"]), hide_index=True, alt="Leyenda de la fórmula Som: significado, valor y procedencia de cada término")
    st.caption(
        "Los importes supuestos son ilustrativos, no costes calibrados ni una oferta Som. "
        "Dsv no es un recargo del 14 % sobre el spot. Los precios negativos se mantienen "
        "como hipótesis contractual. Peajes y cargos se suman una sola vez."
    )
    st.caption(
        "Fuera del cálculo: impuestos, término de potencia y excesos. "
        "La flexibilidad de bombas, membranas y depósito no está validada en planta."
    )
    excluded = metadata["horas_silver_fuera_vigencia_tarifa"]
    if excluded:
        st.warning(f"{excluded} horas Silver excluidas por estar fuera de la vigencia tarifaria.")
    with st.expander("Ver fuentes y cobertura del caso", key="som_case_details", on_change="rerun") as details:
        if details.open:
            st.caption("Documentado significa respaldado por la referencia, no confirmado en una planta ni en un contrato individual.")
            sources = cfg["fuentes_demo"]
            for key, label in [
                ("formula", "Fórmula de Som Energia"),
                ("historico_gdo", "Histórico de garantías de origen"),
                ("referencia_f_6_1td", "Referencia comercial 6.1TD"),
                ("condiciones_6_2td", "Condiciones de alta tensión"),
                ("peajes", "Peajes regulados"),
                ("cargos", "Cargos regulados"),
            ]:
                st.markdown(f"- [{label}]({sources[key]})")
            states = {"optimo": "Con programación", "sin_datos": "Sin precios disponibles", "dia_incompleto": "Precios incompletos"}
            st.dataframe(
                pd.DataFrame({"Fecha": summary["fecha_local"], "Resultado": summary["estado_optimizacion"].map(states)}),
                hide_index=True, alt="Cobertura diaria y motivos de ausencia de programación",
            )
            tariff = metadata["tarifa"]
            st.dataframe(pd.DataFrame({
                "Periodo": list(tariff["peajes_eur_mwh"]),
                "Peaje EUR/MWh": list(tariff["peajes_eur_mwh"].values()),
                "Cargo EUR/MWh": [tariff["cargos_eur_mwh"][period] for period in tariff["peajes_eur_mwh"]],
            }), hide_index=True, alt="Peajes y cargos publicados por periodo tarifario")


def formula_legend(cfg: dict, year: int) -> pd.DataFrame:
    contract = cfg["contrato"]
    rows = [
        ("PH", "Precio final de energía de la demo", "Resultado calculado", "Derivado; no factura"),
        ("PHM", "Precio del mercado diario", "REData · media horaria", "Dato de mercado; aproximación horaria"),
    ]
    for symbol, meaning, key, origin in [
        ("Pc", "Pagos por capacidad", "pc_eur_mwh", "Importe supuesto"),
        ("Sc", "Sobrecostes de gestión de la red", "sc_eur_mwh", "Importe supuesto"),
        ("Dsv", "Coste de desvíos de energía", "dsv_eur_mwh", "Importe supuesto"),
        ("GdO", "Garantías de origen renovable", "gdo_eur_mwh_por_trimestre", "Histórico publicado; criterio fiscal supuesto"),
        ("POsOm", "Operadores REE y OMIE", "posom_eur_mwh", "Importe supuesto"),
        ("Perd", "Coeficiente de pérdidas", "perdidas_fraccion", "Coeficiente supuesto"),
        ("FE", "Aportación al fondo de eficiencia energética", "fe_eur_mwh", "Importe supuesto"),
        ("F", "Franja o margen de la cooperativa", "f_eur_mwh", "Supuesto para 6.2TD; referencia 6.1TD"),
    ]:
        if key == "gdo_eur_mwh_por_trimestre":
            label = " / ".join(
                f"{quarter.upper()}: {node['value']:.3f}".replace(".", ",")
                for quarter, node in contract[key].items()
            )
        else:
            value = contract[key]["value"]
            label = (f"{value:g} ({value * 100:g} %)" if symbol == "Perd" else f"{value:g}").replace(".", ",")
        rows.append((symbol, meaning, label, origin))
    rows.extend([
        ("PTD", "Peaje de transporte y distribución", f"P1–P6 · {year}", "Importes BOE publicados"),
        ("CA", "Cargos del sistema eléctrico", f"P1–P6 · {year}", "Importes BOE publicados"),
        ("1,015", "Factor de la fórmula; no es IVA ni IEE",
         f"{contract['factor_formula']['value']:g}".replace(".", ","), "Publicado por Som Energia"),
    ])
    return pd.DataFrame(rows, columns=["Símbolo", "Significado", "Valor en la demo", "Base del dato"])


def render_indexed_schedule(schedule: pd.DataFrame) -> None:
    energy = schedule["consumo_optimizado_mwh"].sum()
    hours, results = st.columns([1.35, .65])
    with hours, st.container(border=True):
        st.subheader("Programación horaria")
        st.caption(f"{len(schedule)} horas · precio indexado Som · carga flexible S0/S1")
        selected_hour = render_hour_table(schedule)
        st.caption("Verde: horas programadas. Borde: hora consultada. Pulsa una fila para ver su precio y fórmula.")
    baseline = float(schedule["coste_energia_flexible_baseline_eur"].sum())
    optimized = float(schedule["coste_energia_flexible_optimizado_eur"].sum())
    saving = baseline - optimized
    with results, st.container(border=True):
        st.subheader("Coste del día")
        st.caption(f"Solo {format_number(energy)} MWh flexibles · antes de impuestos")
        for label, amount in [("Coste S0 · antes", baseline), ("Coste S1 · después", optimized), ("Ahorro del día", saving)]:
            st.metric(label, format_eur(amount))
        percentage = saving / baseline * 100 if baseline > 0 else float("nan")
        st.caption(f"{format_pct(percentage)} sobre el coste S0." if baseline > 0 else "Porcentaje no aplicable: coste S0 no positivo.")
    exported = schedule[[
        "datetime_local", "precio_indexado_eur_mwh", "consumo_baseline_mwh", "consumo_optimizado_mwh",
        "coste_energia_flexible_baseline_eur", "coste_energia_flexible_optimizado_eur",
    ]].copy()
    exported["ahorro_eur"] = exported["coste_energia_flexible_baseline_eur"] - exported["coste_energia_flexible_optimizado_eur"]
    exported = exported.rename(columns={
        "datetime_local": "Hora local", "precio_indexado_eur_mwh": "Precio EUR/MWh",
        "consumo_baseline_mwh": "Carga S0 MWh", "consumo_optimizado_mwh": "Carga S1 MWh",
        "coste_energia_flexible_baseline_eur": "Coste S0 EUR",
        "coste_energia_flexible_optimizado_eur": "Coste S1 EUR", "ahorro_eur": "Ahorro EUR",
    })
    st.download_button(
        "Descargar plan del día", exported.to_csv(index=False).encode("utf-8"),
        file_name=f"desaladora_plan_{schedule['fecha_local'].iloc[0]}.csv", mime="text/csv",
    )
    render_hour_formula(selected_hour)
    with st.expander("Ver desglose de energía flexible", key="som_price_details", on_change="rerun") as details:
        if details.open:
            breakdown = pd.DataFrame({
                "Componente": COMPONENT_LABELS,
                "Flexible S0 EUR": [float((schedule[c] * schedule["consumo_baseline_mwh"]).sum()) for c in COMPONENTS],
                "Flexible S1 EUR": [float((schedule[c] * schedule["consumo_optimizado_mwh"]).sum()) for c in COMPONENTS],
            })
            breakdown["Ahorro EUR"] = breakdown["Flexible S0 EUR"] - breakdown["Flexible S1 EUR"]
            st.dataframe(
                breakdown, hide_index=True, key="som_cost_details",
                alt="Desglose del coste con peajes y cargos contados una sola vez",
            )


def render_hour_formula(hour: pd.Series) -> None:
    start = hour["datetime_local"]
    st.subheader(f"Precio Som de la hora seleccionada · {start:%H:%M %Z %z}")
    st.latex(r"PH = 1{,}015\,[(PHM + Pc + Sc + Dsv + GdO + POsOm)(1 + Perd) + FE + F] + PTD + CA")

    def number(value: float) -> str:
        return f"{value:.4f}".replace(".", "{,}")

    acquisition = " + ".join(
        rf"\left({number(hour[column])}\right)" if hour[column] < 0 else number(hour[column])
        for column in ["precio_eur_mwh", "pc_eur_mwh", "sc_eur_mwh", "dsv_eur_mwh", "gdo_eur_mwh", "posom_eur_mwh"]
    )
    st.latex(
        r"\begin{aligned} PH &= "
        + number(hour["factor_formula"]) + r"\,\Big[(" + acquisition
        + r")\\ &\quad \times (1 + " + number(hour["perdidas_fraccion"])
        + r") + " + number(hour["fe_eur_mwh"]) + " + " + number(hour["f_eur_mwh"])
        + r"\Big] + " + number(hour["peaje_energia_eur_mwh"]) + " + " + number(hour["cargo_energia_eur_mwh"])
        + r"\\ &= \boxed{" + number(hour["precio_indexado_eur_mwh"]) + r"\ \text{EUR/MWh}}\end{aligned}"
    )
    st.caption(
        "Valores utilizados en el cálculo de esa hora, redondeados para mostrarlos. "
        "PHM: media horaria REData. PTD/CA: regulados. GdO: histórico publicado, criterio fiscal supuesto. "
        "Pc, Sc, Dsv, POsOm, FE, F y Perd: supuestos. 1,015: factor público Som. Antes de impuestos."
    )
    breakdown = pd.DataFrame({
        "Símbolo": ["PHM", "Pc", "Sc", "Dsv", "GdO", "POsOm", "Perd", "FE", "F", "1,015", "PTD", "CA"],
        "Componente": COMPONENT_LABELS,
        "EUR/MWh": [hour[column] for column in COMPONENTS],
    })
    st.table(
        breakdown.style.format({"EUR/MWh": lambda value: format_number(value, 4)}),
        hide_index=True, alt="Desglose del precio indexado de la hora seleccionada",
    )
