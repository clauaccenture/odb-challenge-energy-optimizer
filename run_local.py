"""Download JSON, build local Gold Parquet and start Streamlit on localhost."""

import argparse
from datetime import date
import os
from pathlib import Path
import runpy
import subprocess
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)
HOME = Path(sys.executable).resolve().parent if FROZEN else ROOT
PIPELINE_SCRIPTS = (
    "01_ingesta_redata.py", "01_ingesta_aemet.py",
    "02_calidad_redata.py", "02_calidad_aemet.py",
    "03_gold_redata.py", "03_gold_aemet.py",
)


def dispatch_packaged_command() -> None:
    if not FROZEN or len(sys.argv) < 2:
        return
    load_dotenv(HOME / ".env")
    if sys.argv[1] == "--_run-script":
        if len(sys.argv) < 3 or sys.argv[2] not in PIPELINE_SCRIPTS:
            raise SystemExit("ERROR: script interno no permitido.")
        script = ROOT / "notebooks" / sys.argv[2]
        sys.argv = [str(script), *sys.argv[3:]]
        runpy.run_path(str(script), run_name="__main__")
        raise SystemExit(0)
    if sys.argv[1] == "--_streamlit":
        from streamlit.web.cli import main as streamlit_main

        sys.argv = ["streamlit", *sys.argv[2:]]
        raise SystemExit(streamlit_main())


def run_script(name: str, *arguments: str) -> None:
    print(f"\n>>> {name}", flush=True)
    subprocess.run(
        ([sys.executable, "--_run-script", name, *arguments] if FROZEN else
         [sys.executable, "-u", str(ROOT / "notebooks" / name), *arguments]),
        cwd=HOME,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 10, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--skip-download", action="store_true", help="Reutilizar los JSON locales sin acceder a las API.")
    parser.add_argument("--prepare-only", action="store_true", help="Generar los Parquet sin arrancar Streamlit.")
    parser.add_argument("--dashboard-only", action="store_true", help="Abrir los Parquet existentes sin descargar ni transformar datos.")
    args = parser.parse_args()
    if args.dashboard_only and (args.skip_download or args.prepare_only):
        parser.error("--dashboard-only no se combina con --skip-download ni --prepare-only.")
    if args.end < args.start:
        parser.error("--end no puede ser anterior a --start.")
    load_dotenv(HOME / ".env")
    if not args.dashboard_only and not args.skip_download and not os.getenv("AEMET_API_KEY"):
        parser.error("Define AEMET_API_KEY en .env antes de descargar los datos.")

    try:
        if not args.dashboard_only and not args.skip_download:
            period = ("--start", str(args.start), "--end", str(args.end), "--no-s3")
            run_script("01_ingesta_redata.py", *period)
            run_script("01_ingesta_aemet.py", *period)
        for name in (() if args.dashboard_only else (
            "02_calidad_redata.py", "02_calidad_aemet.py",
            "03_gold_redata.py", "03_gold_aemet.py",
        )):
            run_script(name, "--no-s3")
    except subprocess.CalledProcessError as error:
        print(f"ERROR: fallo del pipeline local (codigo {error.returncode}). Streamlit no se iniciara.", file=sys.stderr)
        raise SystemExit(error.returncode) from error

    print(f"\nParquet locales disponibles en {HOME / 'data' / 'outputs'}", flush=True)
    if not args.prepare_only:
        print("Abre http://localhost:8501. Deten Streamlit con Ctrl+C.", flush=True)
        result = subprocess.run(
            [
                *([sys.executable, "--_streamlit"] if FROZEN else [sys.executable, "-m", "streamlit"]),
                "run",
                str(ROOT / "app" / "streamlit_app.py"),
                "--server.address", "127.0.0.1",
                "--server.port", "8501",
                "--global.developmentMode", "false",
                "--browser.gatherUsageStats", "false",
            ],
            cwd=HOME,
            check=False,
        )
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    dispatch_packaged_command()
    main()
