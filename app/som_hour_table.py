"""Clickable HTML schedule; UTC identities keep repeated local hours distinct."""

import pandas as pd
import streamlit as st
import streamlit.components.v2 as components

from formatting import format_eur, format_number

_TABLE = components.component(
    "som_hourly_schedule",
    html="""
<div class="table-wrap">
  <table aria-label="Programación horaria Som Energia">
    <thead><tr>
      <th>Hora</th><th>Periodo</th><th>Precio Som EUR/MWh</th><th>S0 MWh</th>
      <th>S1 MWh</th><th>Coste S0</th><th>Coste S1</th><th>Acción S1</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>
""",
    css="""
:host { font-family: var(--st-font); color: #405a56; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th { padding: 9px 7px; border-bottom: 1px solid #dce4df; color: #758581;
     font-size: 9px; text-align: left; text-transform: uppercase; white-space: nowrap; }
td { padding: 8px 7px; border-bottom: 1px solid #edf1ee;
     font-variant-numeric: tabular-nums; white-space: nowrap; }
td.numeric { text-align: right; }
tr { cursor: pointer; }
tr.picked { background: #f1f8f3; }
tr.picked td:first-child { color: #1f6e61; font-weight: 750; }
tr.selected { outline: 2px solid #1f6e61; outline-offset: -2px; }
tr:hover { background: #e4f2eb; }
button { font: inherit; color: inherit; border: 0; background: transparent;
         padding: 0; cursor: pointer; font-weight: inherit; }
button:focus-visible { outline: 2px solid #1f6e61; outline-offset: 3px; }
.action { color: #195c50; background: #dcefe4; padding: 2px 5px; border-radius: 3px; }
""",
    js="""
export default function ({ parentElement, data, setStateValue }) {
  const body = parentElement.querySelector("tbody");
  body.replaceChildren();
  for (const item of data.rows) {
    const row = body.insertRow();
    row.dataset.hourUtc = item.utc;
    row.classList.toggle("picked", item.picked);
    row.classList.toggle("selected", item.utc === data.selected);
    item.cells.forEach((value, index) => {
      const cell = row.insertCell();
      if (index >= 2 && index <= 6) cell.className = "numeric";
      if (index === 0) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = value;
        button.setAttribute("aria-label", `Consultar ${value}`);
        button.setAttribute("aria-pressed", String(item.utc === data.selected));
        cell.append(button);
      } else if (index === 7 && item.picked) {
        const action = document.createElement("span");
        action.className = "action";
        action.textContent = value;
        cell.append(action);
      } else {
        cell.textContent = value;
      }
    });
    row.onclick = () => setStateValue("selected_hour", item.utc);
  }
}
""",
)


def render_hour_table(schedule: pd.DataFrame) -> pd.Series:
    rows = []
    for row in schedule.itertuples(index=False):
        start = row.datetime_local
        end = start + pd.Timedelta(hours=1)
        baseline = float(row.consumo_baseline_mwh)
        optimized = float(row.consumo_optimizado_mwh)
        picked = optimized > 0
        rows.append({
            "utc": pd.Timestamp(row.datetime_utc).tz_convert("UTC").isoformat(),
            "picked": picked,
            "cells": [
                f"{start:%H:%M %Z}–{end:%H:%M %Z}", str(row.periodo_tarifario),
                format_number(row.precio_indexado_eur_mwh, 4),
                f"{baseline:g}".replace(".", ","),
                f"{optimized:g}".replace(".", ","),
                format_eur(row.coste_energia_flexible_baseline_eur),
                format_eur(row.coste_energia_flexible_optimizado_eur),
                "Programar" if picked else ("S0" if baseline > 0 else "—"),
            ],
        })
    key = f"som_hour_table_{schedule['fecha_local'].iloc[0]}"
    selected = st.session_state.get(key, {}).get("selected_hour", rows[0]["utc"])
    result = _TABLE(
        key=key, data={"rows": rows, "selected": selected},
        default={"selected_hour": rows[0]["utc"]}, on_selected_hour_change=lambda: None,
    )
    matching = [index for index, row in enumerate(rows) if row["utc"] == result.selected_hour]
    if not matching:
        raise ValueError("La hora seleccionada no pertenece al día mostrado.")
    return schedule.iloc[matching[0]]
