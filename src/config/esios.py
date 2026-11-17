from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe la configuracion: {path}")
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"La configuracion debe ser un objeto YAML: {path}")
    return config


def load_esios_config(path: Path, model_path: Path | None = None) -> dict[str, Any]:
    config = _read_yaml(path)
    esios = config.get("esios")
    if not isinstance(esios, dict):
        raise ValueError("La configuracion del modelo debe incluir la seccion esios.")
    if not isinstance(esios.get("ingestion"), dict):
        raise ValueError("La seccion esios debe incluir ingestion.")
    if not isinstance(esios.get("indicator_ids"), list) or not esios["indicator_ids"]:
        raise ValueError("La seccion esios debe incluir indicator_ids.")
    model_path = model_path or path.parent / "modelo.yml"
    window = _read_yaml(model_path)
    model = window.get("model")
    if not isinstance(model, dict):
        raise ValueError("La ventana comun debe incluir la seccion model.")
    required_window_keys = ("history_start", "history_end", "target_start", "target_end", "lag_days")
    missing_keys = [key for key in required_window_keys if key not in model]
    if missing_keys:
        raise ValueError(f"Faltan parametros en la ventana comun: {missing_keys}")
    esios["ingestion"].update({
        "start": model["history_start"],
        "end": model["history_end"],
    })
    return {"model": model, "esios": esios}
