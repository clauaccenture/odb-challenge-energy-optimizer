"""View 05: industrial load-shifting simulator with the Som Energia indexed price."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from textwrap import dedent
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

from industry_model import simulate
from industry_tariffs import VOLTAGES, config, has_calendar, indexed_prices, is_p6_day, regulated_terms

PURPLE, PURPLE_DARK = "#A100FF", "#7500C0"
DESAL, DESAL_DARK = "#1f6e61", "#173d38"
PERIOD_COLORS = {"P1": "#E63946", "P2": "#F4845F", "P3": "#F6BD60", "P4": "#84C69B", "P5": "#4EA8DE", "P6": "#3A0CA3"}
ICONS = {
    "desal": '<path d="M12 2.5s5 6 5 9.6a5 5 0 0 1-10 0C7 8.5 12 2.5 12 2.5z"/><path d="M2 20.5c2 0 2-1.4 4-1.4s2 1.4 4 1.4 2-1.4 4-1.4 2 1.4 4 1.4 2-1.4 4-1.4"/>',
    "pump": '<rect x="3" y="11" width="8" height="10" rx="1.5"/><circle cx="7" cy="16" r="2"/><path d="M11 14h5V5h4M18 3l2 2-2 2"/>',
    "silo": '<path d="M4 21V8a4 4 0 0 1 8 0v13M12 21V10a3 3 0 0 1 6 0v11M2.5 21h19"/><path d="M4 12h8M12 14h6"/>',
    "metal": '<path d="M3 6h12l-1.4 8.5A3 3 0 0 1 10.6 17H7.4a3 3 0 0 1-3-2.5z"/><path d="M15 8h2.5a1.5 1.5 0 0 1 0 3H14.6"/><path d="M5 21h8"/>',
    "cold": '<path d="M12 2v20M3.5 7l17 10M3.5 17l17-10M9 4l3 2.2L15 4M9 20l3-2.2 3 2.2"/>',
    "cart": '<path d="M2.5 4h2.3l2.5 11h11.2L21 7.5H6"/><circle cx="9" cy="19" r="1.6"/><circle cx="17" cy="19" r="1.6"/>',
    "van": '<path d="M2 7h12v9H2zM14 10h4.5l3 3v3H14z"/><circle cx="6" cy="17.5" r="1.8"/><circle cx="17.5" cy="17.5" r="1.8"/>',
}
MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
INDUSTRY_CONFIG = Path(__file__).resolve().parents[1] / "config" / "config_industrias.yaml"


@dataclass(frozen=True)
class Sector:
    id: str
    name: str
    icon: str
    tariff: str
    summary: str
    days: int
    limit: float
    s0: tuple[int, int]
    s1: tuple[int, int]
    params: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def value(node):
    return node["value"] if isinstance(node, dict) and "value" in node else node


@lru_cache(maxsize=1)
def load_sectors() -> tuple[Sector, ...]:
    """Sectors from config_industrias.yaml; desalination comes from config_desaladora.yaml (case 4)."""
    desal = config()
    plant, flexible, base = desal["planta"], desal["carga_flexible"], desal["baseline_s0"]
    total = plant["volumen_m3_dia"] * plant["consumo_especifico_kwh_m3"] / 1000
    share = round(flexible["energia_diaria_mwh"] / total * 100, 1)
    sectors = [Sector(
        "desal", "Desalación", "desal", desal["tarifa"]["acceso"],
        f"Caso 4: planta de {number(plant['volumen_m3_dia'], 0)} m³/día a {plant['conexion_kv']} kV; "
        "produce agua en horas baratas y la guarda en el depósito.",
        plant["dias_operacion_ano"], flexible["limite_mwh_hora"],
        (base["hora_inicio"], base["hora_fin"] % 24), (0, 0),
        {
            "volumen_m3_dia": {"value": plant["volumen_m3_dia"], "etiqueta": "Producción · m³/día", "min": 0, "max": 1_000_000, "paso": 5_000},
            "kwh_m3": {"value": plant["consumo_especifico_kwh_m3"], "etiqueta": "Consumo · kWh/m³", "min": 0.0, "max": 20.0, "paso": 0.1},
            "desplazable_pct": {"value": share, "etiqueta": "Desplazable · %", "min": 0.0, "max": 100.0, "paso": 5.0},
        },
    )]
    raw = yaml.safe_load(INDUSTRY_CONFIG.read_text(encoding="utf-8"))["sectores"]
    for sector_id, node in raw.items():
        sectors.append(Sector(
            sector_id, node["nombre"], node["icono"], value(node["tarifa"]), node["resumen"],
            value(node["dias_operacion_ano"]), value(node.get("potencia_flexible_mw", 0.0)),
            tuple(value(node["operacion_actual"])), tuple(value(node.get("horas_disponibles", node["operacion_actual"]))),
            node.get("parametros", {}), node,
        ))
    return tuple(sectors)


def plant_energy(sector_id: str, p: dict) -> tuple[float, float]:
    """Flexible and total daily energy, MWh, from the sector parameters."""
    share = p["desplazable_pct"] / 100
    total = {
        "desal": lambda: p["volumen_m3_dia"] * p["kwh_m3"] / 1000,
        "bombeo": lambda: p["volumen_m3_dia"] * 9.81 * p["altura_m"] / (p["rendimiento"] * 3.6e6),
        "cemento": lambda: p["molinos_mw"] * p["horas_dia"],
        "metal": lambda: p["acero_t_dia"] * p["horno_kwh_t"] / 1000,
        "frio": lambda: p["compresores_kw"] * 24 * p["uso_pct"] / 100 / 1000,
        "super": lambda: p["tiendas"] * p["sala_m2"] * 400 / 365 / 1000,
    }[sector_id]()
    return total * share, total


@dataclass
class Operation:
    energy: float
    limit: float
    s0: tuple[int, int]
    s1: tuple[int, int]
    days: int
    total_energy: float = 0.0
    baseline_mode: str = "uniform"
    s0_label: str = "Operación actual"
    warnings: list[str] = field(default_factory=list)


def number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def markup(content: str) -> None:
    st.markdown(dedent(content), unsafe_allow_html=True)


def init(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def icon_uri(name: str, color: str) -> str:
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='1.8' "
           f"stroke-linecap='round' stroke-linejoin='round'>{ICONS[name]}</svg>").replace('"', "'")
    return "data:image/svg+xml," + quote(svg)


def styles() -> None:
    option = '.st-key-ind_{group} [role="radiogroup"] > div:nth-of-type({i}) [data-testid="stRadioOption"]'
    rules = []
    for i, sector in enumerate(load_sectors(), start=1):
        selector = option.format(group="sector", i=i)
        rules.append(f'{selector}::before{{background-image:url("{icon_uri(sector.icon, "#5F5E66")}");}}')
        rules.append(f'{selector}[data-selected="true"]::before{{background-image:url("{icon_uri(sector.icon, "#FFFFFF")}");}}')
    for i, volts in enumerate(VOLTAGES.values(), start=1):
        rules.append(f'{option.format(group="tariff", i=i)}::after{{content:"{volts}";}}')
    markup("""
    <style>
    .stApp:has(.st-key-ind_root), .stApp:has(.st-key-ind_root) [data-testid="stAppViewContainer"] { background:#FAFAFC; }
    .stApp:has(.st-key-ind_root) .block-container { max-width:1180px; padding-top:2.2rem; }
    .st-key-ind_root, .st-key-ind_root input, .st-key-ind_root button, .st-key-ind_root p, .st-key-ind_root summary {
        font-family:"Aptos","Segoe UI",sans-serif !important; }
    .st-key-ind_root { gap:12px; color:#14131a; }
    .ind-eyebrow { color:#A100FF; font-size:12px; font-weight:600; letter-spacing:.08em; text-transform:uppercase; }
    .ind-title { margin:6px 0 0; padding:0; font:700 clamp(22px, 2.2vw, 28px)/1.2 "Aptos","Segoe UI",sans-serif; letter-spacing:-.02em; color:#14131a; }
    .ind-sub { margin:6px 0 10px; color:#6b6a75; font-size:14px; }
    .ind-label { margin-top:14px; color:#6b6a75; font-size:12px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; }

    /* Chip selectors */
    .st-key-ind_sector [data-testid="stElementContainer"], .st-key-ind_tariff [data-testid="stElementContainer"],
    .st-key-ind_sector [data-testid="stRadio"], .st-key-ind_tariff [data-testid="stRadio"] { width:100% !important; }
    .st-key-ind_sector [role="radiogroup"], .st-key-ind_tariff [role="radiogroup"] { display:flex !important; flex-wrap:wrap; gap:8px; }
    .st-key-ind_sector [role="radiogroup"] > div, .st-key-ind_tariff [role="radiogroup"] > div { margin:0; display:flex; }
    .st-key-ind_sector [data-testid="stRadioOption"], .st-key-ind_tariff [data-testid="stRadioOption"] {
        margin:0; cursor:pointer; display:flex; align-items:center; gap:8px; background:#fff; border:1px solid #E6E3EA;
        border-radius:999px; padding:5px 12px; transition:background .15s, border-color .15s, color .15s; }
    .st-key-ind_sector [data-testid="stRadioOption"] > div > div:first-child,
    .st-key-ind_tariff [data-testid="stRadioOption"] > div > div:first-child { display:none; }
    .st-key-ind_sector [data-testid="stRadioOption"] p, .st-key-ind_tariff [data-testid="stRadioOption"] p {
        margin:0; font-size:13px; font-weight:500; color:#14131a; white-space:nowrap; }
    .st-key-ind_sector [data-testid="stRadioOption"]::before { content:""; width:14px; height:14px; background:center/contain no-repeat; }
    .st-key-ind_tariff [data-testid="stRadioOption"] { order:0; }
    .st-key-ind_tariff [data-testid="stRadioOption"] > div { order:1; }
    .st-key-ind_tariff [data-testid="stRadioOption"]::after { order:2; font-size:12px; color:#8a8893; }
    .st-key-ind_sector [data-testid="stRadioOption"]:hover, .st-key-ind_tariff [data-testid="stRadioOption"]:hover { border-color:#C9A6FF; }
    .st-key-ind_sector [data-testid="stRadioOption"][data-selected="true"],
    .st-key-ind_tariff [data-testid="stRadioOption"][data-selected="true"] { background:#14131a; border-color:#14131a; }
    .st-key-ind_sector [data-testid="stRadioOption"][data-selected="true"] p,
    .st-key-ind_tariff [data-testid="stRadioOption"][data-selected="true"] p { color:#fff; }
    .st-key-ind_tariff [data-testid="stRadioOption"][data-selected="true"]::after { color:#c9c6cf; }
    .ind-hint { color:#6b6a75; font-size:13px; }
    .ind-hint b { color:#14131a; font-weight:600; }

    /* Operation card */
    .st-key-ind_ops { background:#fff; border:1px solid #ECEAF0; border-radius:14px; padding:16px 18px 6px; }
    .st-key-ind_ops [data-testid="stHorizontalBlock"] { flex-wrap:wrap; gap:10px 14px; }
    .st-key-ind_ops [data-testid="stColumn"] { flex:1 1 130px !important; min-width:130px !important; width:auto !important; }
    .st-key-ind_root [data-testid="stWidgetLabel"] p { font-size:12px !important; font-weight:500; color:#6b6a75 !important; }
    .st-key-ind_root [data-testid="stNumberInputContainer"], .st-key-ind_root [data-testid="stSelectbox"] [role="group"] {
        background:#fff !important; border:1px solid #E6E3EA !important; border-radius:8px !important; min-height:36px; }
    .st-key-ind_root [data-testid="stNumberInputContainer"]:focus-within, .st-key-ind_root [data-testid="stSelectbox"] [role="group"]:focus-within {
        border-color:#A100FF !important; box-shadow:0 0 0 3px rgba(161,0,255,.10); }
    .st-key-ind_root [data-testid="stNumberInputField"], .st-key-ind_root [data-testid="stSelectbox"] input {
        background:#fff !important; color:#14131a !important; -webkit-text-fill-color:#14131a; font-size:14px; font-weight:500; }
    .st-key-ind_root [data-testid="stSelectbox"] button { background:transparent !important; color:#8a8893 !important; }
    .st-key-ind_root [data-testid="stNumberInputStepDown"], .st-key-ind_root [data-testid="stNumberInputStepUp"] {
        background:transparent !important; color:#8a8893 !important; }
    .st-key-ind_root [data-testid="stNumberInputStepDown"]:hover, .st-key-ind_root [data-testid="stNumberInputStepUp"]:hover { color:#A100FF !important; }
    .st-key-ind_root [data-testid="stCheckbox"] p { font-size:13px; color:#14131a !important; }
    .ind-energy { margin:2px 0 8px; font-size:13px; color:#6b6a75; }
    .ind-energy b { color:#14131a; font-weight:600; }

    /* Results */
    .ind-result { display:grid; grid-template-columns:1.2fr 1fr 1fr 1fr; gap:1px; background:#ECEAF0; border:1px solid #ECEAF0; border-radius:14px; overflow:hidden; }
    .ind-result > div { background:#fff; padding:16px 18px; }
    .ind-result span { display:block; font-size:12px; color:#6b6a75; }
    .ind-result b { display:block; margin-top:4px; font-size:22px; font-weight:650; letter-spacing:-.01em; color:#14131a; white-space:nowrap; }
    .ind-result small { display:block; margin-top:2px; font-size:12px; color:#8a8893; }
    .ind-result .hero { background:#A100FF; }
    .ind-result .hero span, .ind-result .hero small { color:#EBD9FF; }
    .ind-result .hero b { color:#fff; font-size:28px; }
    .ind-chart { background:#fff; border:1px solid #ECEAF0; border-radius:14px; padding:14px 18px 8px; }
    .ind-chart-h { display:flex; flex-wrap:wrap; align-items:center; gap:6px 18px; font-size:13px; color:#6b6a75; }
    .ind-chart-h b { font-size:14px; color:#14131a; font-weight:600; }
    .ind-chart-h .lg { margin-left:auto; display:flex; gap:14px; }
    .ind-chart-h i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
    .ind-chart svg { display:block; width:100%; height:auto; margin-top:4px; }
    .ind-warn { background:#FFF6EC; color:#8A3B00; border-radius:10px; padding:10px 14px; font-size:13px; }
    .st-key-ind_root [data-testid="stExpander"] details { border:1px solid #ECEAF0 !important; border-radius:14px !important; background:#fff; }
    .st-key-ind_root [data-testid="stExpander"] summary p { font-size:14px; font-weight:600; color:#14131a; }
    .ind-formula { font-size:13px; color:#14131a; background:#F6F3FA; border-radius:8px; padding:10px 12px; }
    .ind-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }
    .ind-table th, .ind-table td { padding:6px 8px; border-bottom:1px solid #F0EEF3; text-align:right; }
    .ind-table th:first-child, .ind-table td:first-child { text-align:left; color:#6b6a75; font-weight:500; }
    .ind-table th { color:#6b6a75; font-weight:600; }
    .ind-note { margin-top:10px; font-size:12px; color:#8a8893; line-height:1.5; }
    @media (max-width: 900px) { .ind-result { grid-template-columns:1fr 1fr; } }
    """ + "".join(rules) + "</style>")


def sectors_by_id() -> dict[str, Sector]:
    return {sector.id: sector for sector in load_sectors()}


def vehicles() -> dict:
    return sectors_by_id()["flota"].raw["vehiculos"]


def on_sector_change() -> None:
    st.session_state.industry_tariff = sectors_by_id()[st.session_state.industry_sector].tariff


def on_vehicle_change() -> None:
    vehicle = vehicles()[st.session_state.industry_flota_vehicle]
    st.session_state.industry_flota_consumption = float(vehicle["kwh_100km"])
    st.session_state.industry_flota_km = int(vehicle["km_dia"])
    st.session_state.industry_flota_charger = float(vehicle["cargador_kw"])


def hour_select(column, label: str, key: str, default: int) -> int:
    init(key, default)
    return column.selectbox(label, range(24), format_func=lambda h: f"{h:02d}:00", key=key)


def number_field(column, label: str, key: str, default, minimum, maximum, step):
    numeric = float if any(isinstance(x, float) for x in (default, minimum, maximum, step)) else int
    init(key, numeric(default))
    return column.number_input(label, min_value=numeric(minimum), max_value=numeric(maximum), step=numeric(step), key=key)


def fleet_operation(sector: Sector) -> Operation:
    key = "industry_flota"
    fleet = vehicles()
    first = next(iter(fleet))
    default = fleet["furgoneta"] if "furgoneta" in fleet else fleet[first]
    init(key + "_vehicle", "furgoneta" if "furgoneta" in fleet else first)
    init(key + "_consumption", float(default["kwh_100km"]))
    init(key + "_km", int(default["km_dia"]))
    init(key + "_charger", float(default["cargador_kw"]))
    init(key + "_in_base", True)
    row = st.columns(5)
    vehicle = row[0].selectbox("Vehículo", list(fleet), format_func=lambda v: fleet[v]["nombre"],
                               key=key + "_vehicle", on_change=on_vehicle_change)
    units = number_field(row[1], "Unidades", key + "_count", value(sector.raw["unidades"]), 1, 5000, 1)
    km = row[2].number_input("km/día", min_value=1, max_value=1000, step=5, key=key + "_km")
    consumption = row[3].number_input("kWh/100 km", min_value=1.0, max_value=200.0, step=0.5, key=key + "_consumption")
    charger = row[4].number_input("Cargador · kW", min_value=1.0, max_value=350.0, step=0.1, key=key + "_charger")
    row = st.columns(5)
    arrive = hour_select(row[0], "Llega a base", key + "_arrive", sector.s0[0])
    leave = hour_select(row[1], "Sale de base", key + "_leave", sector.s0[1])
    days = number_field(row[2], "Días/año", key + "_days", sector.days, 1, 366, 1)
    with row[3]:
        st.write("")
        only_base = st.checkbox("Solo en base", key=key + "_in_base", help="Respeta el horario de trabajo: en ruta no se carga.")
    per_vehicle = km * consumption / 100
    energy = units * per_vehicle / 1000
    markup(f'<div class="ind-energy">Energía a cargar: <b>{number(energy, 2)} MWh/día</b> · {number(per_vehicle, 0)} kWh por vehículo</div>')
    warnings = []
    if per_vehicle > fleet[vehicle]["bateria_kwh"]:
        warnings.append(f"Cada vehículo necesita {number(per_vehicle, 0)} kWh/día y su batería de referencia es de {fleet[vehicle]['bateria_kwh']} kWh.")
    if not only_base:
        warnings.append("Sin respetar el horario de trabajo el resultado es un límite teórico: puede cargar en horas en ruta.")
    return Operation(energy=energy, limit=units * charger / 1000, s0=(arrive, leave),
                     s1=(arrive, leave) if only_base else (0, 0), days=days, total_energy=energy,
                     baseline_mode="immediate", s0_label="Cargar al llegar", warnings=warnings)


def plant_operation(sector: Sector) -> Operation:
    key = f"industry_{sector.id}"
    params = list(sector.params.items())
    row = st.columns(len(params) + 1)
    values = {
        name: number_field(row[i], node["etiqueta"], f"{key}_{name}", node["value"], node["min"], node["max"], node["paso"])
        for i, (name, node) in enumerate(params)
    }
    label = "Horno · MW" if sector.id == "metal" else "Potencia máx. · MW"
    limit = number_field(row[-1], label, key + "_limit", float(sector.limit), 0.1, 1000.0, 0.1)
    energy, total = plant_energy(sector.id, values)
    row = st.columns(5)
    s0 = (hour_select(row[0], "Opera hoy desde", key + "_s0_start", sector.s0[0]),
          hour_select(row[1], "hasta", key + "_s0_end", sector.s0[1]))
    s1 = (hour_select(row[2], "Puede consumir desde", key + "_s1_start", sector.s1[0]),
          hour_select(row[3], "hasta", key + "_s1_end", sector.s1[1]))
    days = number_field(row[4], "Días/año", key + "_days", sector.days, 1, 366, 1)
    markup(f'<div class="ind-energy">Energía flexible: <b>{number(energy, 1)} MWh/día</b> de {number(total, 1)} MWh/día de consumo total</div>')
    return Operation(energy=energy, limit=limit, s0=s0, s1=s1, days=days, total_energy=total)


def chart(hours: list[int], prices: list[float], periods: list[str], baseline: list[float], optimized: list[float],
          accent: str = PURPLE, accent_dark: str = PURPLE_DARK) -> str:
    count = len(hours)
    width, left, right, top, plot = 760, 40, 4, 16, 150
    bar = (width - left - right) / count
    strip = top + plot + 8
    height = strip + 34
    high = max(max(prices), 1.0) * 1.15
    low = min(min(prices), 0.0) * 1.15
    y = lambda v: top + plot * (high - v) / (high - low)
    raw = (high - low) / 4
    step = next(s for s in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if s >= raw)
    parts = []
    value = (low // step) * step
    while value <= high:
        if value >= low:
            parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="{"#D7D4DD" if value == 0 else "#F2F0F5"}"/>'
                         f'<text x="{left - 8}" y="{y(value) + 4:.1f}" text-anchor="end" font-size="11" fill="#8a8893">{number(value, 0)}</text>')
        value += step
    for i in range(count):
        x, w = left + i * bar + bar * 0.15, bar * 0.7
        chosen = optimized[i] > 1e-9
        tip = f"{hours[i]:02d}:00 · {periods[i]} · {number(prices[i])} €/MWh"
        if chosen:
            tip += f" · S1 {number(optimized[i])} MWh"
        parts.append(f'<rect x="{x:.1f}" y="{min(y(0), y(prices[i])):.1f}" width="{w:.1f}" height="{max(abs(y(0) - y(prices[i])), 1):.1f}" rx="3" '
                     f'fill="{accent if chosen else "#E4E1EA"}"><title>{escape(tip)}</title></rect>')
        if chosen:
            parts.append(f'<text x="{x + w / 2:.1f}" y="{min(y(0), y(prices[i])) - 5:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{accent_dark}">{number(optimized[i], 1)}</text>')
        if baseline[i] > 1e-9:
            parts.append(f'<rect x="{x:.1f}" y="{strip}" width="{w:.1f}" height="3" rx="1.5" fill="#14131a"/>')
        parts.append(f'<rect x="{left + i * bar + 1:.1f}" y="{strip + 7}" width="{bar - 2:.1f}" height="5" rx="2" fill="{PERIOD_COLORS[periods[i]]}"><title>{periods[i]}</title></rect>')
        if i % 3 == 0:
            parts.append(f'<text x="{left + i * bar + bar / 2:.1f}" y="{height - 4}" text-anchor="middle" font-size="11" fill="#8a8893">{hours[i]:02d}h</text>')
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Precio final por hora y horas elegidas" '
            f'font-family="Aptos, Segoe UI, sans-serif">{"".join(parts)}</svg>')


def method_section(tariff: str, day_prices: pd.DataFrame) -> None:
    contract = config()["contrato"]
    terms = regulated_terms(tariff, 2026) or {}
    mean = day_prices[["mercado", "suministro", "regulado", "total"]].mean()
    with st.expander("Cómo se calcula"):
        markup(f"""
        <div class="ind-formula">Precio hora = 1,015 × [(Mercado + Pc + Sc + Dsv + GdO + POsOm) × (1 + pérdidas) + FE + F] + peaje + cargo</div>
        <table class="ind-table">
          <tr><th>Precio medio del día</th><th>€/MWh</th></tr>
          <tr><td>Mercado (REData · Gold S3)</td><td>{number(mean['mercado'])}</td></tr>
          <tr><td>Suministro Som: sistema, pérdidas {number(contract['perdidas_fraccion'] * 100, 0)} %, margen {number(contract['f_eur_mwh'], 0)} €/MWh y factor 1,015</td><td>{number(mean['suministro'])}</td></tr>
          <tr><td>Peaje + cargo de energía {tariff}</td><td>{number(mean['regulado'])}</td></tr>
          <tr><td><b>Total</b></td><td><b>{number(mean['total'])}</b></td></tr>
        </table>
        <table class="ind-table">
          <tr><th>Peaje + cargo {tariff} 2026 · €/MWh</th>{"".join(f"<th>{p}</th>" for p in terms)}</tr>
          <tr><td>BOE</td>{"".join(f"<td>{number(v)}</td>" for v in terms.values())}</tr>
        </table>
        <div class="ind-note">Precio de mercado: REData, tabla Gold de S3. Términos Som: bloque <code>contrato</code> de
        <code>config_desaladora.yaml</code>, los mismos supuestos que el caso desaladora. Peajes y cargos 2026: Res. CNMC 18/12/2025
        (BOE-A-2025-26348) y Orden TED/1524/2025 (BOE-A-2025-26705); S3 solo publica los de 6.2TD, las demás tarifas se leen del YAML.
        Periodos P1–P6: Circular CNMC 3/2020. Antes de impuestos, sin término de potencia. Consumos de referencia editables,
        no datos de una instalación real.</div>
        """)


def render_industries(plan: pd.DataFrame, dates: list[date]) -> None:
    styles()
    dates = [d for d in dates if has_calendar(d)]
    init("industry_sector", "desal")
    init("industry_tariff", sectors_by_id()[st.session_state.industry_sector].tariff)
    with st.container(key="ind_root"):
        markup("""
        <div class="ind-eyebrow">Energy Optimizer</div>
        <h1 class="ind-title">Mueve tu consumo a las horas más baratas</h1>
        <div class="ind-sub">Elige tu industria y descubre cuánto ahorras con precios horarios reales.</div>
        """)
        if not dates:
            markup('<div class="ind-warn">No hay días con calendario tarifario cargado en el año seleccionado.</div>')
            return
        with st.container(key="ind_sector"):
            sector_id = st.radio("Industria", [s.id for s in load_sectors()], key="industry_sector", horizontal=True,
                                 label_visibility="collapsed", format_func=lambda v: sectors_by_id()[v].name,
                                 on_change=on_sector_change)
        sector = sectors_by_id()[sector_id]
        markup('<div class="ind-label">Conexión</div>')
        with st.container(key="ind_tariff"):
            tariff = st.radio("Conexión", list(VOLTAGES), key="industry_tariff", horizontal=True, label_visibility="collapsed")
        hint = f"{escape(sector.summary)} Conexión habitual: <b>{sector.tariff}</b>."
        markup(f'<div class="ind-hint">{hint}</div>')

        markup('<div class="ind-label">Tu operación</div>')
        with st.container(key="ind_ops"):
            operation = fleet_operation(sector) if sector.id == "flota" else plant_operation(sector)

        laborable = [d for d in dates if not is_p6_day(d)]
        if st.session_state.get("industry_date") not in dates:
            st.session_state.industry_date = (laborable or dates)[-1]
        rows = plan[plan["fecha_local"].isin(dates)].reset_index(drop=True)
        priced = pd.concat([rows[["fecha_local", "hora_local"]], indexed_prices(rows, tariff)], axis=1)
        by_day = {day: frame for day, frame in priced.groupby("fecha_local", sort=True)}
        for warning in operation.warnings:
            markup(f'<div class="ind-warn">{escape(warning)}</div>')

        selected_date = st.session_state.industry_date
        prices_day = by_day[selected_date]
        hours = prices_day["hora_local"].astype(int).tolist()
        try:
            result = simulate(prices_day["total"].tolist(), hours, operation.energy, operation.limit,
                              operation.s0, operation.s1, operation.baseline_mode)
        except ValueError as error:
            markup(f'<div class="ind-warn"><b>No se puede programar.</b> {escape(str(error))} Aumenta la potencia o amplía las horas.</div>')
            return
        savings, bills = [], []
        rest = max(operation.total_energy - operation.energy, 0.0)
        for frame in by_day.values():
            try:
                run = simulate(frame["total"].tolist(), frame["hora_local"].astype(int).tolist(), operation.energy,
                               operation.limit, operation.s0, operation.s1, operation.baseline_mode)
            except ValueError:
                continue
            savings.append(run.baseline_cost - run.optimized_cost)
            # Non-flexible consumption assumed flat over the day.
            bills.append(run.baseline_cost + rest * frame["total"].mean())
        daily_mean = sum(savings) / len(savings)
        bill_pct = daily_mean / (sum(bills) / len(bills)) * 100 if sum(bills) > 0 else 0.0
        saving = result.baseline_cost - result.optimized_cost
        per_mwh = lambda cost: number(cost / operation.energy if operation.energy else 0, 0)
        pct = f"−{number(saving / result.baseline_cost * 100, 0)} % de la parte flexible" if result.baseline_cost > 0 and saving > 0 else "este día"
        markup(f"""
        <div class="ind-label">Resultado</div>
        <div class="ind-result">
          <div class="hero"><span>Ahorro anual estimado</span><b>{number(daily_mean * operation.days, 0)} €</b>
            <small>{number(bill_pct, 1)} % de la factura de energía · media de {len(savings)} días × {operation.days} días/año</small></div>
          <div><span>{escape(operation.s0_label)}</span><b>{number(result.baseline_cost, 0)} €</b><small>{per_mwh(result.baseline_cost)} €/MWh</small></div>
          <div><span>Optimizado</span><b>{number(result.optimized_cost, 0)} €</b><small>{per_mwh(result.optimized_cost)} €/MWh</small></div>
          <div><span>Ahorro del día</span><b>{number(saving, 0)} €</b><small>{pct}</small></div>
        </div>
        """)

        head, pick = st.columns([3, 1], vertical_alignment="bottom")
        with pick:
            st.selectbox("Día", dates, key="industry_date", label_visibility="collapsed",
                         format_func=lambda d: f"{WEEKDAYS[d.weekday()]} {d:%d/%m/%Y}")
        day_kind = "fin de semana o festivo: todo P6" if is_p6_day(selected_date) else "laborable"
        periods = prices_day["periodo"].tolist()
        legend = "".join(f'<span><i style="background:{c}"></i>{p}</span>' for p, c in PERIOD_COLORS.items())
        with head:
            markup(f'<div class="ind-chart-h"><b>Precio final por hora · €/MWh</b>{day_kind} · {tariff}</div>')
        markup(f"""
        <div class="ind-chart">
          <div class="ind-chart-h"><span><i style="background:{PURPLE}"></i>Horas elegidas (MWh)</span>
            <span><i style="background:#14131a;height:3px;vertical-align:3px"></i>{escape(operation.s0_label)}</span>
            <span class="lg">{legend}</span></div>
          {chart(hours, prices_day["total"].tolist(), periods, result.baseline, result.optimized)}
        </div>
        """)
        method_section(tariff, prices_day)


def render_desal_demo(plan: pd.DataFrame, summary: pd.DataFrame, details, monthly: pd.DataFrame | None = None, show_daily_trend: bool = False) -> None:
    """View 04: published case 4 run (Som price, S0/S1 already optimised by the pipeline), no recalculation."""
    styles()
    cfg = config()
    plant, flexible, base = cfg["planta"], cfg["carga_flexible"], cfg["baseline_s0"]
    optimum = summary[summary["estado_optimizacion"] == "optimo"]
    dates = sorted(optimum["fecha_local"])
    markup("""<style>
    .stApp:has(.st-key-desal_root), .stApp:has(.st-key-desal_root) [data-testid="stAppViewContainer"] { background:#f4f6f2; }
    .st-key-desal_root .ind-eyebrow { color:#1f6e61; font-size:10px; font-weight:800; letter-spacing:1.15px; }
    .st-key-desal_root .ind-title { font:500 30px/1.1 Georgia,serif; letter-spacing:0; color:#183432; }
    .desal-specs { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0 14px; }
    .desal-specs span { padding:4px 9px; border:1px solid #dce4df; border-radius:5px; background:transparent; color:#758581; font-size:11px; }
    .desal-specs b { color:#183432; font-weight:600; }
    .desal-heading { padding-top:18px; border-top:1px solid #dce4df; }
    .desal-heading h2 { margin:0; padding:0; font-size:14px; font-weight:750; color:#183432; }
    .desal-heading p { margin:3px 0 0; color:#758581; font-size:11px; }
    .st-key-desal_root .ind-chart, .st-key-desal_root [data-testid="stExpander"] details { border-color:#dce4df !important; border-radius:7px !important; }
    .st-key-desal_root [data-testid="stTable"] table, .st-key-desal_root [data-testid="stTable"] th,
    .st-key-desal_root [data-testid="stTable"] td, .st-key-desal_root [data-testid="stMarkdownContainer"],
    .st-key-desal_root [data-testid="stMarkdownContainer"] p, .st-key-desal_root [data-testid="stMarkdownContainer"] li,
    .st-key-desal_root h3, .st-key-desal_root .katex { color:#14131a !important; background:transparent; }
    .st-key-desal_root [data-testid="stCaptionContainer"], .st-key-desal_root [data-testid="stCaptionContainer"] p { color:#6b6a75 !important; }
    .st-key-desal_root [data-testid="stTable"] th { background:#F4F6F5 !important; font-weight:600; }
    .st-key-desal_root [data-testid="stTable"] td, .st-key-desal_root [data-testid="stTable"] th { border-color:#E3E8E6 !important; }
    </style>""")
    with st.container(key="desal_root"), st.container(key="ind_root"):
        specs = [
            ("Producción", f"{number(plant['volumen_m3_dia'], 0)} m³/día"),
            ("Conexión", f"{plant['conexion_kv']} kV · {cfg['tarifa']['acceso']}"),
            ("Contrato", "Som Energia indexado"),
            ("Carga flexible", f"{number(flexible['energia_diaria_mwh'], 0)} MWh/día"),
            ("Límite", f"{number(flexible['limite_mwh_hora'], 0)} MWh/h"),
            ("Operación actual", f"{base['hora_inicio']:02d}–{base['hora_fin']:02d} h · {number(base['mwh_hora'], 1)} MWh/h"),
        ]
        markup(f"""
        <div class="ind-eyebrow">Desaladora</div>
        <h1 class="ind-title">Planificación energética</h1>
        <div class="desal-specs">{"".join(f"<span>{k} <b>{escape(v)}</b></span>" for k, v in specs)}</div>
        """)
        if not dates:
            markup('<div class="ind-warn">La ejecución publicada no contiene días optimizados.</div>')
            return
        total_s0 = optimum["coste_energia_flexible_baseline_eur"].sum()
        saving = optimum["ahorro_energia_eur"].sum()
        plant_s0 = optimum["coste_energia_planta_baseline_eur"].sum()
        daily = saving / len(optimum)
        cards = [
            ("Extrapolación anual ilustrativa" if show_daily_trend else "Ahorro anual estimado", f"{number(daily * plant['dias_operacion_ano'], 0)} €",
             f"{number(daily, 0)} €/día · {plant['dias_operacion_ano']} días/año", True),
            ("Ahorro en el periodo", f"{number(saving, 0)} €",
             f"{dates[0]:%d/%m} – {dates[-1]:%d/%m/%Y} · {len(optimum)} días", False),
            ("Carga flexible", f"−{number(saving / total_s0 * 100, 1)} %", f"S0 {number(total_s0, 0)} €", False),
            ("Energía planta", f"−{number(saving / plant_s0 * 100, 1)} %", f"S0 {number(plant_s0, 0)} €", False),
        ]
        for column, (label, amount, foot, emphasis) in zip(st.columns(4), cards):
            with column:
                markup(f'<article class="kpi{" emphasis" if emphasis else ""}"><div class="kpi-label">{label}</div>'
                       f'<div class="kpi-value{" green" if emphasis else ""}">{amount}</div>'
                       f'<div class="kpi-foot">{foot}</div></article>')
        laborable = [d for d in dates if not is_p6_day(d)]
        if st.session_state.get("desal_demo_date") not in dates:
            st.session_state.desal_demo_date = (laborable or dates)[-1]
        head, pick = st.columns([3, 1], vertical_alignment="bottom")
        with pick:
            day = st.selectbox("Día", dates, key="desal_demo_date", label_visibility="collapsed",
                               format_func=lambda d: f"{WEEKDAYS[d.weekday()]} {d:%d/%m/%Y}")
        schedule = plan[plan["fecha_local"] == day].sort_values("datetime_local")
        row = optimum[optimum["fecha_local"] == day].iloc[0]
        kind = "Festivo · P6" if is_p6_day(day) else "Laborable"
        with head:
            markup(f'<div class="ind-chart-h"><b>Precio horario · €/MWh</b>{kind} · '
                   f'S0 {number(row["coste_energia_flexible_baseline_eur"], 0)} € → S1 {number(row["coste_energia_flexible_optimizado_eur"], 0)} € '
                   f'· −{number(row["ahorro_energia_eur"], 0)} €</div>')
        legend = "".join(f'<span><i style="background:{c}"></i>{p}</span>' for p, c in PERIOD_COLORS.items())
        markup(f"""
        <div class="ind-chart">
          <div class="ind-chart-h"><span><i style="background:{DESAL}"></i>Consumo programado (MWh)</span>
            <span><i style="background:#14131a;height:3px;vertical-align:3px"></i>Operación actual</span>
            <span class="lg">{legend}</span></div>
          {chart(schedule["hora_local"].astype(int).tolist(), schedule["precio_indexado_eur_mwh"].tolist(),
                 schedule["periodo_tarifario"].tolist(), schedule["consumo_baseline_mwh"].tolist(),
                 schedule["consumo_optimizado_mwh"].tolist(), DESAL, DESAL_DARK)}
        </div>
        """)
        if monthly is not None:
            savings_sections(monthly, optimum if show_daily_trend else None)
        with st.expander("Contrato y datos"):
            details()


def savings_sections(monthly: pd.DataFrame, daily: pd.DataFrame | None = None) -> None:
    """Cumulative saving and monthly contribution, same layout as view 03."""
    monthly = monthly[monthly["days"] > 0]
    if monthly.empty:
        return
    names = [f"{MONTHS[int(m[5:7]) - 1]} {m[:4]}" for m in monthly["month"]]
    daily_values = None
    if daily is not None and len(daily) > 1:
        daily_values = daily.sort_values("fecha_local").copy()
        daily_values["ahorro_acumulado_eur"] = daily_values["ahorro_energia_eur"].cumsum()
    trend, contribution = st.columns([1.6, 1])
    with trend:
        title_detail = "EUR · acumulación diaria del periodo" if daily_values is not None else "EUR · acumulación por mes"
        markup(f'<div class="desal-heading"><h2>Ahorro acumulado</h2><p>{title_detail}</p></div>')
        if daily_values is not None:
            labels = [d.strftime("%d/%m") for d in daily_values["fecha_local"]]
            cumulative = daily_values["ahorro_acumulado_eur"].tolist()
            axis_x = list(range(1, len(labels) + 1))
        else:
            labels = names
            cumulative = monthly["saving_eur"].cumsum().tolist()
            axis_x = list(range(1, len(labels) + 1))
        figure = go.Figure(go.Scatter(
            x=[0] + axis_x, y=[0] + cumulative,
            customdata=["Inicio"] + labels, mode="lines+markers", fill="tozeroy", fillcolor="#eaf1f7",
            line=dict(color="#547d99", width=3), marker=dict(size=7, color="#547d99", line=dict(color="white", width=1)),
            hovertemplate="%{customdata}: %{y:,.2f} € acumulados<extra></extra>",
        ))
        figure.update_layout(
            height=360, margin=dict(l=55, r=15, t=18, b=35), paper_bgcolor="#f4f6f2", plot_bgcolor="#f4f6f2", showlegend=False,
            font=dict(family="Aptos, Segoe UI, sans-serif", color="#758581", size=11),
            xaxis=dict(tickmode="array", tickvals=(axis_x[::max(1, len(axis_x) // 10)] + ([axis_x[-1]] if len(axis_x) > 10 and axis_x[-1] not in axis_x[::max(1, len(axis_x) // 10)] else [])) if daily_values is not None else axis_x, ticktext=(labels[::max(1, len(labels) // 10)] + ([labels[-1]] if len(labels) > 10 and labels[-1] not in labels[::max(1, len(labels) // 10)] else [])) if daily_values is not None else labels, tickangle=-45 if daily_values is not None else 0, showgrid=False, zeroline=False, fixedrange=True),
            yaxis=dict(title="EUR", rangemode="tozero", gridcolor="#dce4df", zeroline=False, fixedrange=True),
        )
        st.plotly_chart(figure, config={"displayModeBar": False})
    with contribution:
        markup('<div class="desal-heading"><h2>Aportación mensual</h2><p>Ahorro S0 − S1 · EUR</p></div>')
        peak = max(float(monthly["saving_eur"].abs().max()), 1)
        rows = "".join(
            f'<div class="contribution-row" role="listitem" aria-label="{name}: {number(row.saving_eur)} €; {row.days} días">'
            f'<span>{name[:3]}</span><div class="contribution-track" aria-hidden="true"><div class="contribution-bar" '
            f'style="width:{abs(row.saving_eur) / peak * 100}%;background:{"#1f6e61" if row.saving_eur >= 0 else "#b9554e"}"></div></div>'
            f'<strong>{number(row.saving_eur)} €</strong></div>'
            for name, row in zip(names, monthly.itertuples(index=False))
        )
        markup(f'<div role="list">{rows}</div>')
