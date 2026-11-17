from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root from a notebook or module working directory."""
    start = start or Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / "requirements.txt").is_file() and (candidate / "notebooks").is_dir():
            return candidate
    raise FileNotFoundError("No se encontro la raiz del proyecto.")
