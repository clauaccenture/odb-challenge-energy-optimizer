"""Loaders for source and common model configuration."""

from src.config.esios import load_esios_config
from src.config.mibgas import load_mibgas_config

__all__ = ["load_esios_config", "load_mibgas_config"]
