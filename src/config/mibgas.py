from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_mibgas_config(path: Path, window_path: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe la configuracion MIBGAS: {path}")
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict) or not isinstance(config.get("mibgas"), dict):
        raise ValueError("La configuracion MIBGAS debe incluir la seccion mibgas.")
    mibgas = config["mibgas"]
    if not isinstance(mibgas.get("ingestion"), dict):
        raise ValueError("La configuracion MIBGAS debe incluir ingestion.")
    if not isinstance(mibgas.get("product"), dict):
        raise ValueError("La configuracion MIBGAS debe incluir product.")
    window_path = window_path or path.parent / "modelo.yml"
    if not window_path.is_file():
        raise FileNotFoundError(f"No existe la ventana comun: {window_path}")
    with window_path.open(encoding="utf-8") as window_file:
        window = yaml.safe_load(window_file) or {}
    if not isinstance(window, dict) or not isinstance(window.get("model"), dict):
        raise ValueError("La ventana comun debe incluir la seccion model.")
    model = window["model"]
    for key in ("history_start", "history_end", "target_start", "target_end", "lag_days"):
        if key not in model:
            raise ValueError(f"Falta parametros en la ventana comun: {key}")
    mibgas["model"] = model
    return config
