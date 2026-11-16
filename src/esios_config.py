from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_model_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe la configuracion del modelo: {path}")
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict):
        raise ValueError("La configuracion del modelo debe ser un objeto YAML.")
    esios = config.get("esios")
    if not isinstance(esios, dict):
        raise ValueError("La configuracion del modelo debe incluir la seccion esios.")
    for section in ("ingestion", "model"):
        if not isinstance(esios.get(section), dict):
            raise ValueError(f"La seccion esios debe incluir {section}.")
    if not isinstance(esios.get("indicator_ids"), list) or not esios["indicator_ids"]:
        raise ValueError("La seccion esios debe incluir indicator_ids.")
    return config
