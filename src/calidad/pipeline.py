from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd


def collect_file_results(
    paths: Iterable[Path],
    process_file: Callable[[Path], tuple[pd.DataFrame, dict[str, Any]]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Process files while preserving one report entry for each source file."""
    frames: list[pd.DataFrame] = []
    reports: list[dict[str, Any]] = []
    for path in paths:
        values, report = process_file(path)
        frames.append(values)
        reports.append(report)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, reports


def save_values_json(values: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    values.to_json(path, orient="records", date_format="iso", force_ascii=False, indent=2)
    return path


def save_quality_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
