"""Energy Optimizer dashboard backed by Gold Parquet results in S3."""

from __future__ import annotations

from calendar import Calendar
from datetime import date
from html import escape
from textwrap import dedent

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError
from pyarrow import ArrowException

from data_loader import GOLD_S3_URI, TEMPERATURE_S3_URI, load_gold_tables, load_temperature_table


st.set_page_config(
    page_title="Energy Optimizer | Grupo 4",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
VIEWS = ["Resumen ejecutivo", "Programación diaria", "Evolución del ahorro"]


def format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def format_eur(value: float) -> str:
    return f"{format_number(value)} €"


def month_label(value: str) -> str:
    year, month = value.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def markup(content: str) -> None:
    st.markdown(dedent(content), unsafe_allow_html=True)


def format_pct(value: float) -> str:
    if pd.isna(value):
        return "No aplica"
    return f"{value:.1f}".replace(".", ",") + " %"


def format_date(value: date) -> str:
    return f"{value.day} {MONTH_NAMES[value.month - 1].lower()} {value.year}"


def apply_styles() -> None:
    markup("""
        <style>
        :root { color-scheme: light; }
        .stApp, [data-testid="stAppViewContainer"] { background: #f4f6f2; color: #183432; }
        .stApp, .stApp input, .stApp button, .stApp select { font-family: "Aptos", "Segoe UI", sans-serif; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stExpandSidebarButton"] {
            background: #d00000 !important;
            color: #ffffff !important;
            border: 2px solid #a00000 !important;
            border-radius: 6px;
        }
        [data-testid="stExpandSidebarButton"]:hover {
            background: #a00000 !important;
        }
        [data-testid="stExpandSidebarButton"] svg { fill: currentColor; }
        .block-container { max-width: 1500px; padding: 2.4rem 3rem 2rem; }
        [data-testid="stSidebar"] { background: #173d38; color: #e8f1ec; min-width: 232px; }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color: #c7d7d0; }
        [data-testid="stSidebar"] [role="radiogroup"] { gap: 5px; }
        [data-testid="stSidebar"] [role="radiogroup"] label { padding: 9px 10px; border-radius: 6px; }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background: #28574e; }
        [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #28574e; }
        [data-testid="stSidebar"] hr { border-color: #41635b; }
        .brand { display: flex; align-items: center; gap: 11px; margin-bottom: 28px; }
        .brand-mark { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid #74a88d; border-radius: 8px; color: #bde1cd; font: bold 17px Georgia, serif; }
        .brand-name { color: #e8f1ec; font-weight: 700; font-size: 15px; }
        .brand-sub, .nav-label { color: #a9c1b6; font-size: 10px; text-transform: uppercase; letter-spacing: .7px; }
        .source-box { padding: 13px 12px; border: 1px solid #41635b; border-radius: 7px; background: #20453f; }
        .source-title { color: #b3cec0; font-size: 10px; font-weight: 700; text-transform: uppercase; }
        .source-row { display: flex; justify-content: space-between; margin-top: 9px; color: #eff5f1; font-size: 12px; }
        .source-state { color: #a9d6ba; font-size: 10px; }
        .sidebar-note { margin-top: 12px; color: #9eb5aa; font-size: 10px; }
        .topline { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 23px; }
        .crumb { color: #758581; font-size: 12px; }
        .crumb strong { color: #405a56; }
        .data-badge { padding: 6px 9px; border: 1px solid #bbd9c9; border-radius: 4px; color: #1f6e61; background: #e4f2eb; font-size: 10px; font-weight: 800; letter-spacing: .65px; }
        .page-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin-bottom: 6px; }
        .eyebrow { margin-bottom: 5px; color: #1f6e61; font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.15px; }
        .page-heading h1 { margin: 0 0 5px; padding: 0; font: 500 34px/1.1 Georgia, serif; color: #183432; }
        .heading-sub { margin: 0; color: #758581; font-size: 13px; }
        .period-tag { flex-shrink: 0; color: #758581; font-size: 11px; }
        .kpi { min-width: 0; min-height: 117px; padding: 16px 17px 13px; border: 1px solid #dce4df; border-radius: 7px; background: white; }
        .kpi.emphasis { border-color: #bbd9c9; background: #f6fbf7; }
        .kpi-label { display: flex; justify-content: space-between; gap: 6px; color: #758581; font-size: 11px; font-weight: 600; }
        .kpi-unit { font-size: 10px; color: #9aa8a3; }
        .kpi-value { margin-top: 12px; color: #183432; font: 29px/1 Georgia, serif; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
        .green { color: #1f6e61; }
        .kpi-foot { margin-top: 9px; color: #758581; font-size: 10px; }
        [data-testid="stVerticalBlockBorderWrapper"] > div { border-color: #dce4df !important; border-radius: 7px !important; background: white; }
        .stApp [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .panel-heading) { color: #183432; background: white; border: 1px solid #dce4df; border-radius: 7px; }
        .panel-heading h2, .widget-heading { margin: 0; padding: 0; font-size: 14px; font-weight: 750; color: #183432; }
        .panel-subtitle { margin: 3px 0 0; color: #758581; font-size: 11px; }
        .chart-total { color: #758581; font-size: 10px; }
        .chart-total strong { margin-right: 8px; color: #183432; font-size: 15px; }
        .selected-month { display: flex; justify-content: space-between; padding: 9px 11px; border-radius: 5px; background: #eaf2eb; color: #758581; font-size: 10px; }
        .selected-month strong { color: #1f6e61; font-size: 12px; }
        .insight-label { margin: 8px 0 6px; color: #758581; font-size: 10px; font-weight: 700; text-transform: uppercase; }
        .saving-large { color: #1f6e61; font: 33px/1 Georgia, serif; }
        .saving-large small { font: 12px "Aptos", "Segoe UI", sans-serif; }
        .impact-note { margin: 8px 0 13px; color: #405a56; font-size: 11px; }
        .compare-row { display: grid; grid-template-columns: 28px 1fr 90px; align-items: center; gap: 8px; margin-top: 9px; color: #758581; font-size: 10px; }
        .compare-track { height: 7px; border-radius: 8px; background: #edf1ee; overflow: hidden; }
        .compare-fill { height: 100%; background: #1f6e61; }
        .compare-value { color: #405a56; text-align: right; }
        .recommendation { margin-top: 15px; padding: 11px; border-left: 3px solid #1f6e61; background: #e4f2eb; font-size: 11px; }
        .recommendation p { margin: 3px 0 0; color: #405a56; font-size: 10px; }
        .date-preview { margin-top: 8px; color: #1f6e61; font-size: 12px; }
        .stApp [data-testid="stButton"] button,
        .stApp [data-testid="stDownloadButton"] button { background: #ffffff; border: 1px solid #52756b; color: #183432; border-radius: 5px; }
        .stApp [data-testid="stButton"] button:hover,
        .stApp [data-testid="stDownloadButton"] button:hover { background: #e4f2eb; border-color: #1f6e61; color: #183432; }
        .stApp [data-testid="stButton"] button[kind="primary"] { background: #1f6e61; border-color: #1f6e61; color: #ffffff; }
        .stApp [data-testid="stButton"] button[kind="primary"]:hover { background: #18574d; border-color: #18574d; color: #ffffff; }
        .stApp [data-testid="stButton"] button [data-testid="stMarkdownContainer"] p,
        .stApp [data-testid="stDownloadButton"] button [data-testid="stMarkdownContainer"] p { color: inherit; }
        .stApp [data-testid="stButton"] button:focus-visible,
        .stApp [data-testid="stDownloadButton"] button:focus-visible { outline: 3px solid #1f6e61; outline-offset: 3px; }
        [data-baseweb="input"] > div, [data-baseweb="select"] > div { background: white; color: #183432; border-color: #dce4df; border-radius: 5px; }
        label [data-testid="stMarkdownContainer"] p { color: #405a56; font-size: 11px; }
        .stApp [data-testid="stSidebar"] [role="radiogroup"] label p { color: #c7d7d0; font-size: 13px; }
        .stApp [data-testid="stMarkdownContainer"] .widget-heading { font-size: 14px; margin: 0; padding: 0; }
        .stApp [data-testid="stMarkdownContainer"] p.panel-subtitle { font-size: 11px; margin: 3px 0 0; }
        .stApp [data-testid="stMarkdownContainer"] p.heading-sub { font-size: 13px; margin: 0; }
        .stApp [data-testid="stMarkdownContainer"] p.impact-note { font-size: 11px; margin: 8px 0 13px; }
        .stApp [data-testid="stMarkdownContainer"] .recommendation p { font-size: 10px; margin: 3px 0 0; }
        .stApp [data-testid="stMarkdownContainer"] p.date-preview { font-size: 12px; margin: 8px 0 0; }
        .stApp [data-testid="stMarkdownContainer"] p.section-intro { font-size: 12px; margin: 0; }
        [data-testid="stButton"]:has(button[kind="primary"]) { padding-top: 24px; }
        .section-intro { margin: 0; color: #758581; font-size: 12px; }
        .sample-label { display: inline-block; margin: 8px 0; padding: 4px 7px; border: 1px solid #e6c990; border-radius: 3px; color: #81551f; background: #fff3e1; font-size: 9px; font-weight: 750; text-transform: uppercase; }
        .table-wrap { overflow-x: auto; }
        .dispatch-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .dispatch-table th { padding: 9px 7px; border-bottom: 1px solid #dce4df; color: #758581; font-size: 9px; text-align: left; text-transform: uppercase; white-space: nowrap; }
        .dispatch-table td { padding: 8px 7px; border-bottom: 1px solid #edf1ee; color: #405a56; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .dispatch-table .numeric { text-align: right; }
        .dispatch-table tr.picked { background: #f1f8f3; }
        .dispatch-table tr.picked td:first-child { color: #1f6e61; font-weight: 750; }
        .tag-shift, .tag-current { display: inline-block; min-width: 44px; padding: 2px 5px; border-radius: 3px; font-size: 9px; text-align: center; }
        .tag-shift { color: #195c50; background: #dcefe4; }
        .tag-current { color: #5e6e68; background: #e9eeeb; }
        .daily-result { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; padding: 13px 0; border-bottom: 1px solid #edf1ee; }
        .daily-result span { color: #758581; font-size: 11px; }
        .daily-result strong { color: #183432; font-size: 13px; text-align: right; }
        .daily-result strong.positive { color: #1f6e61; }
        .daily-result small { grid-column: 1 / -1; color: #758581; font-size: 10px; }
        .notice { margin-top: 11px; padding: 11px 12px; border-left: 3px solid #d68b36; color: #795520; background: #fff3e1; font-size: 10px; }
        .formula { padding: 12px 13px; border-radius: 5px; color: #e4eee8; background: #183432; font: 11px/1.7 Consolas, monospace; }
        .analysis-heading { padding-top: 18px; border-top: 1px solid #dce4df; }
        .contribution-row { display: grid; grid-template-columns: 30px minmax(0, 1fr) 76px; gap: 10px; align-items: center; margin-top: 13px; font-size: 11px; }
        .contribution-track { height: 13px; background: #e5ece8; border-radius: 2px; overflow: hidden; }
        .contribution-bar { height: 100%; background: #1f6e61; }
        .contribution-row strong { text-align: right; font-variant-numeric: tabular-nums; }
        .footer-note { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin-top: 16px; padding-top: 12px; border-top: 1px solid #dce4df; color: #758581; font-size: 10px; }
        .footer-note strong { color: #9a6320; }
        @media (max-width: 720px) {
            .block-container { padding: 2rem 14px 24px; }
            .page-heading { align-items: start; flex-direction: column; gap: 10px; }
            .page-heading h1 { font-size: 28px; }
            .kpi-value { font-size: 25px; }
        }
        </style>
    """)


def panel_heading(title: str, subtitle: str) -> None:
    markup(f'<div class="panel-heading"><h2>{title}</h2>'
           f'<p class="panel-subtitle">{subtitle}</p></div>')


def kpi(label: str, value: str, foot: str, emphasis: bool = False, unit: str = "") -> None:
    markup(f'<article class="kpi{" emphasis" if emphasis else ""}">'
           f'<div class="kpi-label">{label}<span class="kpi-unit">{unit}</span></div>'
           f'<div class="kpi-value{" green" if emphasis else ""}">{value}</div>'
           f'<div class="kpi-foot">{foot}</div></article>')


def save_selected_date(selected_date: date) -> None:
    st.session_state.selected_date = selected_date


def render_date_picker(dates: list[date]) -> date:
    selected_date = st.session_state.selected_date
    available_dates = set(dates)
    months = [date(selected_date.year, month, 1) for month in range(1, 13)]
    if st.session_state.get("schedule_month") not in months:
        st.session_state.schedule_month = selected_date.replace(day=1)
    st.caption("Día de resultados")
    with st.popover(format_date(selected_date), icon=":material/calendar_month:", width="stretch"):
        month = st.selectbox(
            "Mes del calendario", months, key="schedule_month",
            format_func=lambda value: f"{MONTH_NAMES[value.month - 1]} {value.year}",
        )
        for column, name in zip(st.columns(7), ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]):
            column.caption(name)
        for week in Calendar(firstweekday=0).monthdatescalendar(month.year, month.month):
            for column, day in zip(st.columns(7), week):
                available = day.month == month.month and day in available_dates
                with column:
                    st.button(
                        str(day.day),
                        key=f"schedule_day_{day.isoformat()}",
                        disabled=not available,
                        type="primary" if day == selected_date else "secondary",
                        help=(
                            f"Ver resultados del {day:%d/%m/%Y}"
                            if available else f"{day:%d/%m/%Y}: sin resultados disponibles en este mes"
                        ),
                        on_click=save_selected_date,
                        args=(day,),
                        width="stretch",
                    )
        st.caption("Solo se pueden seleccionar los días con estado óptimo del año elegido. Los demás están deshabilitados.")
    return selected_date


def open_daily_schedule() -> None:
    st.session_state.view = VIEWS[1]


def render_summary(monthly: pd.DataFrame, daily: pd.DataFrame, saving: float) -> None:
    cost_s0 = float(daily["coste_baseline_total_eur"].sum())
    cost_s1 = float(daily["coste_optimizado_total_eur"].sum())
    saving_pct = saving / cost_s0 * 100 if cost_s0 else float("nan")
    dates = daily["fecha_local"].tolist()
    metrics = st.columns(4)
    with metrics[0]:
        kpi("Coste S0 del período", format_eur(cost_s0), f"Operación de referencia · {len(daily)} días", unit="EUR")
    with metrics[1]:
        kpi("Coste S1 del período", format_eur(cost_s1), "Programación optimizada · tabla Gold", unit="EUR")
    with metrics[2]:
        kpi("Ahorro del período", format_eur(saving), "S0 − S1 · días con estado óptimo", True, "EUR")
    with metrics[3]:
        kpi("Ahorro sobre S0", format_pct(saving_pct), "Ahorro total / coste S0 total", True, "PORCENTAJE")

    chart_column, insight_column = st.columns([1.75, .92])
    with chart_column, st.container(border=True):
        panel_heading("Ahorro por mes", "Indicador mensual leído de Gold; no se extrapolan meses incompletos.")
        markup(f'<div class="chart-total"><strong>{format_eur(saving)}</strong>ahorro acumulado del período</div>')
        options = monthly["month"].tolist()
        if st.session_state.get("summary_month") not in options:
            st.session_state.summary_month = options[0]
        selected = st.session_state.summary_month
        figure = go.Figure(go.Bar(
            x=[month_label(value) for value in options], y=monthly["saving_eur"],
            customdata=monthly["days"],
            marker_color=["#1f6e61" if value == selected else "#9dc6b2" for value in options],
            width=.5, hovertemplate="%{x}: %{y:,.2f} € · %{customdata} días<extra></extra>",
        ))
        figure.update_layout(
            height=180, margin=dict(l=0, r=0, t=8, b=20),
            paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
            font=dict(family="Aptos, Segoe UI, sans-serif", color="#758581", size=10),
            xaxis=dict(fixedrange=True, showgrid=False),
            yaxis=dict(visible=False, fixedrange=True, rangemode="tozero"),
        )
        st.plotly_chart(figure, config={"displayModeBar": False})
        selected = st.selectbox("Mes seleccionado", options, key="summary_month", format_func=month_label, label_visibility="collapsed")
        selected_month = monthly.loc[monthly["month"] == selected].iloc[0]
        markup(f'<div class="selected-month"><span>{month_label(selected)} · {int(selected_month["days"])} días</span><strong>{format_eur(selected_month["saving_eur"])}</strong></div>')

    with insight_column, st.container(border=True):
        panel_heading("Lectura de negocio", "Precio de mercado · resultados del período cargado")
        scale = max(abs(cost_s0), abs(cost_s1), 1)
        markup(f"""
            <div class="insight-label">Reducción frente a S0</div>
            <div class="saving-large">{format_pct(saving_pct)}</div>
            <p class="impact-note">Diferencia S0 − S1 de {format_eur(saving)} en {len(daily)} días con programación válida.</p>
            <div class="compare-row"><span>S0</span><div class="compare-track"><div class="compare-fill" style="width:{abs(cost_s0) / scale * 100}%;background:#aab7b1"></div></div><span class="compare-value">{format_eur(cost_s0)}</span></div>
            <div class="compare-row"><span>S1</span><div class="compare-track"><div class="compare-fill" style="width:{abs(cost_s1) / scale * 100}%"></div></div><span class="compare-value">{format_eur(cost_s1)}</span></div>
            <div class="recommendation"><strong>Alcance del resultado</strong><p>Consumos del escenario industrial del caso 4. El coste incluye solo energía a precio de mercado: no incluye peajes, cargos ni impuestos. Validar las restricciones de planta antes de aplicar la programación.</p></div>
        """)

    st.divider()
    description, date_column, button_column = st.columns([1.4, 1, 1])
    with description:
        markup(f'<h2 class="widget-heading">Programación diaria</h2>'
               '<p class="panel-subtitle">Fechas con programación disponible · Europe/Madrid</p>'
               f'<p class="date-preview">Programación horaria · {format_date(st.session_state.selected_date)}</p>')
    with date_column:
        render_date_picker(dates)
    with button_column:
        st.button("Ver programación diaria →", type="primary", on_click=open_daily_schedule, width="stretch")


@st.cache_data(ttl=300, max_entries=1, show_spinner="Cargando temperaturas Gold desde S3...")
def cached_temperature_table() -> pd.DataFrame:
    return load_temperature_table()


def render_daily_temperature(selected_date: date) -> None:
    with st.container(border=True):
        panel_heading("Temperatura diaria · España", "AEMET · resumen nacional")
        try:
            temperatures = cached_temperature_table()
        except (BotoCoreError, ClientError, ArrowException, OSError, ValueError, KeyError) as error:
            st.error(f"No se pudieron cargar las temperaturas Gold: {error}")
            st.caption(f"Origen S3: {TEMPERATURE_S3_URI}")
            return
        has_temperature = temperatures[["tmin", "tmax", "tmed"]].notna().any(axis=1)
        available = temperatures.loc[(temperatures["fecha"] <= selected_date) & has_temperature]
        if available.empty:
            st.caption("No hay datos de temperatura disponibles para la fecha elegida ni para días anteriores.")
            return
        temperature_date = available["fecha"].max()
        row = available.loc[available["fecha"] == temperature_date].iloc[0]
        if temperature_date != selected_date:
            st.caption(
                f"Las temperaturas mostradas corresponden al {format_date(temperature_date)}, "
                "el día más reciente con datos disponibles anterior a la fecha elegida."
            )
        else:
            st.caption(f"Temperaturas del {format_date(temperature_date)}.")
        for column, label in (("tmin", "Mínima nacional"), ("tmax", "Máxima nacional"), ("tmed", "Media diaria nacional")):
            value = "Sin dato" if pd.isna(row[column]) else f"{format_number(row[column], 1)} °C"
            if column == "tmed":
                detail = "Media de las medias provinciales; cada provincia tiene el mismo peso."
            elif pd.isna(row[column]):
                detail = "Sin medición disponible."
            else:
                hour = row[f"hora_{column}"]
                time_label = "Hora no disponible" if pd.isna(hour) else f"A las {hour}"
                location = [
                    str(row[key]) for key in (f"localidad_{column}", f"provincia_{column}")
                    if pd.notna(row[key])
                ]
                detail = " · ".join([time_label, *location])
            markup(f'<div class="daily-result"><span>{label}</span><strong>{value}</strong>'
                   f'<small>{escape(detail)}</small></div>')


def render_daily_schedule(schedule: pd.DataFrame, totals: pd.Series) -> None:
    markup(f'<p class="section-intro">Plan Gold · {int(totals["horas_del_dia"])} intervalos horarios reales · Europe/Madrid. Los cambios de hora se conservan.</p>')
    table_column, summary_column = st.columns([1.35, .65])
    with table_column, st.container(border=True):
        panel_heading(
            f"Programación horaria · {format_date(st.session_state.selected_date)}",
            "Precios REData · asignación S0/S1 leída de la programación horaria Gold.",
        )
        markup('<span class="sample-label">Resultados Gold</span>')
        rows = []
        for row in schedule.itertuples(index=False):
            start = row.datetime_local
            end = start + pd.Timedelta(hours=1)
            picked = row.consumo_optimizado_mwh > 0
            action = '<span class="tag-shift">Programar</span>' if picked else (
                '<span class="tag-current">S0</span>' if row.consumo_baseline_mwh > 0 else "—"
            )
            current = f"{row.consumo_baseline_mwh:g}".replace(".", ",")
            optimized = f"{row.consumo_optimizado_mwh:g}".replace(".", ",")
            rows.append(
                f'<tr class="{"picked" if picked else ""}"><td>{start:%H:%M %Z}–{end:%H:%M %Z}</td>'
                f'<td class="numeric">{format_number(row.precio_eur_mwh, 4)}</td>'
                f'<td class="numeric">{current}</td><td class="numeric">{optimized}</td>'
                f'<td class="numeric">{format_eur(row.coste_baseline_eur)}</td>'
                f'<td class="numeric">{format_eur(row.coste_optimizado_eur)}</td><td>{action}</td></tr>'
            )
        markup('<div class="table-wrap"><table class="dispatch-table"><thead><tr>'
               '<th>Hora</th><th class="numeric">Precio EUR/MWh</th><th class="numeric">S0 MWh</th>'
               '<th class="numeric">S1 MWh</th><th class="numeric">Coste S0</th><th class="numeric">Coste S1</th><th>Acción S1</th></tr></thead><tbody>'
               + "".join(rows) + '</tbody></table></div>')
        st.download_button(
            "Descargar plan del día", schedule.to_csv(index=False).encode("utf-8"),
            file_name=f"plan_{st.session_state.selected_date}.csv", mime="text/csv",
        )
    with summary_column:
        with st.container(border=True):
            panel_heading("Coste del día", "Suma de los resultados horarios Gold · sin reoptimizar")
            markup(f"""
                <div class="daily-result"><span>Coste S0</span><strong>{format_eur(totals['coste_baseline_total_eur'])}</strong><small>{format_number(totals['consumo_baseline_total_mwh'])} MWh de consumo de referencia.</small></div>
                <div class="daily-result"><span>Coste S1</span><strong>{format_eur(totals['coste_optimizado_total_eur'])}</strong><small>{format_number(totals['consumo_optimizado_total_mwh'])} MWh de consumo optimizado.</small></div>
                <div class="daily-result"><span>Ahorro del día</span><strong class="positive">{format_eur(totals['ahorro_eur'])}</strong><small>{format_pct(totals['ahorro_pct'])} sobre el coste S0 del día.</small></div>
                <div class="notice">Resultado del escenario de carga flexible; no es la factura final. El ahorro de este día no se extrapola al año.</div>
            """)
        render_daily_temperature(st.session_state.selected_date)
        with st.container(border=True):
            panel_heading("Regla de decisión", "Parámetros del caso 4 · aplicados por el proceso Gold")
            markup(f'<div class="formula">energía diaria = {format_number(totals["energia_flexible_objetivo_mwh"])} MWh<br>límite = {format_number(totals["limite_flexible_mwh_por_hora"])} MWh/h<br>priorizar precios más bajos<br>empates: 08:00–17:00 y hora más temprana</div>')
            st.caption("Política del caso 4: precios negativos a cero antes de la media horaria (aplicada en Silver).")


def render_analysis(monthly: pd.DataFrame, period_saving: float) -> None:
    note_column, filter_column = st.columns([2, 1])
    with note_column:
        markup('<p class="section-intro">Resultados Gold · agregados de los días válidos disponibles.</p>')
    with filter_column:
        periods = ["Todo el período disponible", "T1 · Enero–marzo", "T2 · Abril–junio", "T3 · Julio–septiembre", "T4 · Octubre–diciembre"]
        if st.session_state.get("analysis_period") not in periods:
            st.session_state.analysis_period = periods[0]
        period = st.selectbox("Período", periods, key="analysis_period")
    if period == periods[0]:
        filtered = monthly.copy()
    else:
        quarter = pd.to_datetime(monthly["month"]).dt.quarter
        filtered = monthly[quarter == int(period[1])].copy()
    if filtered.empty:
        st.info("No hay resultados disponibles para este trimestre. No se interpreta como ahorro cero.")
        return
    total = period_saving if period == periods[0] else float(filtered["saving_eur"].sum())
    best = filtered.loc[filtered["saving_eur"].idxmax()]
    metrics = st.columns(3)
    with metrics[0]:
        kpi("Ahorro del período", format_eur(total), f"{period} · {int(filtered['days'].sum())} días", True)
    with metrics[1]:
        kpi("Media por mes con datos", format_eur(total / len(filtered)), "Solo meses disponibles; pueden ser parciales")
    with metrics[2]:
        kpi("Mes con mayor ahorro", month_label(best["month"]), format_eur(best["saving_eur"]))

    trend_column, contribution_column = st.columns([1.6, 1])
    with trend_column:
        markup('<div class="analysis-heading"><h2 class="widget-heading">Ahorro acumulado</h2>'
               '<p class="panel-subtitle">EUR · acumulación desde el inicio del período seleccionado</p></div>')
        names = [month_label(value) for value in filtered["month"]]
        accumulated = filtered["saving_eur"].cumsum().tolist()
        figure = go.Figure(go.Scatter(
            x=[0] + list(range(1, len(filtered) + 1)), y=[0] + accumulated,
            customdata=["Inicio"] + names, mode="lines+markers",
            fill="tozeroy", fillcolor="#eaf1f7", line=dict(color="#547d99", width=3),
            marker=dict(size=8, color="#547d99", line=dict(color="white", width=2)),
            hovertemplate="%{customdata}: %{y:,.2f} € acumulados<extra></extra>",
        ))
        figure.update_layout(
            height=360, margin=dict(l=55, r=15, t=18, b=35),
            paper_bgcolor="#f4f6f2", plot_bgcolor="#f4f6f2", showlegend=False,
            font=dict(family="Aptos, Segoe UI, sans-serif", color="#758581", size=11),
            xaxis=dict(tickmode="array", tickvals=list(range(1, len(filtered) + 1)), ticktext=names, showgrid=False, zeroline=False, fixedrange=True),
            yaxis=dict(title="EUR", rangemode="tozero", gridcolor="#dce4df", zeroline=False, fixedrange=True),
        )
        st.plotly_chart(figure, config={"displayModeBar": False})
    with contribution_column:
        markup('<div class="analysis-heading"><h2 class="widget-heading">Aportación mensual</h2>'
               '<p class="panel-subtitle">Ahorro S0 − S1 · EUR</p></div>')
        maximum = max(float(filtered["saving_eur"].abs().max()), 1)
        rows = [
            f'<div class="contribution-row" role="listitem" aria-label="{month_label(row.month)}: {format_eur(row.saving_eur)}; {row.days} días">'
            f'<span>{MONTH_NAMES[int(row.month[5:7]) - 1][:3]}</span><div class="contribution-track" aria-hidden="true">'
            f'<div class="contribution-bar" style="width:{abs(row.saving_eur) / maximum * 100}%;background:{"#1f6e61" if row.saving_eur >= 0 else "#b9554e"}"></div></div>'
            f'<strong>{format_eur(row.saving_eur)}</strong></div>'
            for row in filtered.itertuples(index=False)
        ]
        markup('<div role="list">' + "".join(rows) + '</div>')


@st.cache_data(ttl=300, max_entries=1, show_spinner="Cargando tablas Gold desde S3...")
def cached_gold_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return load_gold_tables()


def main() -> None:
    apply_styles()
    try:
        monthly, summary, plan = cached_gold_tables()
    except (BotoCoreError, ClientError, ArrowException, OSError, ValueError, KeyError) as error:
        st.error(f"No se pudieron cargar las tablas Gold: {error}")
        st.caption(f"Origen S3: {GOLD_S3_URI}")
        st.info("Comprueba las credenciales AWS de la EC2, los permisos s3:GetObject y la existencia de ambos Parquet.")
        st.stop()
    with st.sidebar:
        markup("""
            <div class="brand"><div class="brand-mark">E</div><div><div class="brand-name">Energy Optimizer</div><div class="brand-sub">Open Data Challenge</div></div></div>
            <div class="nav-label">Resultados de optimización</div>
        """)
        view = st.radio("Vistas", VIEWS, key="view", label_visibility="collapsed", format_func=lambda name: f"0{VIEWS.index(name) + 1}  {name}")
        years = sorted({value.year for value in summary["fecha_local"]})
        if st.session_state.get("selected_year") not in years:
            st.session_state.selected_year = years[-1]
        selected_year = st.selectbox("Año de resultados", years, key="selected_year")
        st.divider()
        markup("""
            <div class="source-box"><div class="source-title">Fuente de datos</div><div class="source-row"><span>REData · precios</span><span class="source-state">Gold S3</span></div></div>
            <div class="sidebar-note">gold_plan_mensual.parquet<br>gold_programacion_horaria.parquet<br>Zona horaria: Europe/Madrid</div>
        """)
        st.caption(f"Origen S3: {GOLD_S3_URI}")
        if st.button("Actualizar datos de S3"):
            cached_gold_tables.clear()
            cached_temperature_table.clear()
            st.rerun()
        st.caption("Caché de datos: 5 minutos. Actualiza tras completar la subida de los Parquet de REData y AEMET.")
    single_year = monthly["month"].str[:4].nunique() == 1
    monthly = monthly[monthly["month"].str[:4] == str(selected_year)].copy()
    summary = summary[summary["fecha_local"].map(lambda value: value.year == selected_year)].copy()
    daily = summary[summary["estado_optimizacion"] == "optimo"].copy()
    first, last = summary["fecha_local"].min(), summary["fecha_local"].max()
    calendar_days = (last - first).days + 1
    coverage = f"{first:%d/%m/%Y} – {last:%d/%m/%Y}"
    subtitles = {
        VIEWS[0]: "Comparación de costes S0/S1 sobre el período disponible.",
        VIEWS[1]: "Precios y programación de carga flexible por intervalo horario local.",
        VIEWS[2]: "Ahorro acumulado y contribución mensual de la programación optimizada.",
    }
    markup(f"""
        <div class="topline"><div class="crumb">Energía / <strong>Resultados</strong></div><div class="data-badge">TABLAS GOLD · PARQUET S3</div></div>
        <header class="page-heading"><div><div class="eyebrow">Caso 4 · Carga flexible industrial</div><h1>{view}</h1><p class="heading-sub">{subtitles[view]}</p></div><div class="period-tag">{coverage}</div></header>
    """)
    st.info(f"Cobertura disponible: {len(daily)} días con programación de {calendar_days} días naturales entre las fechas cargadas; {calendar_days - len(summary)} sin programación publicada. Gold no publica el motivo de las fechas ausentes. Los totales no se anualizan ni representan necesariamente meses completos.")
    if daily.empty:
        st.warning("No hay días con programación válida en el año seleccionado.")
        st.dataframe(summary, hide_index=True, width="stretch")
        st.stop()
    dates = daily["fecha_local"].tolist()
    if st.session_state.get("selected_date") not in dates:
        st.session_state.selected_date = dates[0]
    # Gold repeats a period-wide total, not a separate total for each year.
    period_saving = (
        float(monthly["ahorro_estimado_anual_eur"].iloc[0])
        if single_year else float(monthly["saving_eur"].sum())
    )
    if view == VIEWS[0]:
        render_summary(monthly, daily, period_saving)
    elif view == VIEWS[1]:
        selected_date = render_date_picker(dates)
        schedule = plan[plan["fecha_local"] == selected_date]
        totals = daily.loc[daily["fecha_local"] == selected_date].iloc[0]
        render_daily_schedule(schedule, totals)
    else:
        render_analysis(monthly, period_saving)
    markup("""
        <footer class="footer-note"><span><strong>Coste de energía a precio de mercado.</strong> Sin peajes, cargos ni impuestos.</span><span>Resultados del escenario de carga flexible · Caso 4</span></footer>
    """)


if __name__ == "__main__":
    main()