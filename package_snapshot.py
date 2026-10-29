"""Validate a local data snapshot and ZIP the Windows portable without secrets."""

import argparse
from datetime import date
from pathlib import Path
import sys
import zipfile

import pandas as pd


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--portable-dir", type=Path, default=ROOT / "dist" / "EnergyOptimizer")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end no puede ser anterior a --start.")
    portable = args.portable_dir.resolve()
    if not (portable / "EnergyOptimizer.exe").is_file() or not (portable / "_internal").is_dir():
        parser.error("Construye primero el portable con build_windows.py.")

    sys.path.insert(0, str(ROOT / "app"))
    from data_loader import load_gold_tables, load_temperature_table

    _, summary, plan = load_gold_tables()
    temperature = load_temperature_table()
    if temperature.empty:
        parser.error("El paquete de datos solicitado no contiene temperaturas AEMET.")
    expected = pd.date_range(args.start, args.end, freq="D").date.tolist()
    for label, days in (
        ("REData", summary["fecha_local"].tolist()),
        ("AEMET", temperature["fecha"].tolist()),
    ):
        missing = sorted(set(expected) - set(days))
        extra = sorted(set(days) - set(expected))
        if missing or extra:
            parser.error(f"{label}: cobertura distinta del periodo pedido; faltan {len(missing)} dias, sobran {len(extra)}.")

    dataset = ROOT / "data"
    data_files = sorted(
        path for path in dataset.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".parquet"}
    )
    if not any(path.parent == dataset / "raw" / "aemet" for path in data_files):
        parser.error("Faltan los JSON raw AEMET.")
    if not any(path.parent == dataset / "raw" / "redata" for path in data_files):
        parser.error("Faltan los JSON raw REData.")
    output = ROOT / "dist" / f"EnergyOptimizer_{args.start}_{args.end}.zip"
    if output.exists():
        parser.error(f"Ya existe {output}. Muevelo antes de crear otro paquete.")
    temporary = output.with_suffix(".zip.tmp")
    description = (
        "Energy Optimizer - datos locales\n\n"
        f"Periodo: {args.start} a {args.end} (ambos incluidos).\n"
        f"Dias REData: {len(summary)}. Horas: {len(plan)}. Dias AEMET: {len(temperature)}.\n\n"
        "1. Descomprime toda la carpeta en una ubicacion con permisos de escritura.\n"
        "2. Haz doble clic en Abrir_dashboard.cmd.\n"
        "3. Abre http://localhost:8501 si el navegador no se abre automaticamente.\n"
        "No necesitas Python, clave AEMET, AWS ni descargar datos.\n"
        "Conserva la consola abierta. Para terminar pulsa Ctrl+C.\n"
        "No ejecutes desde dentro del ZIP ni separes el .exe de _internal y data.\n"
        "Las temperaturas anteriores a la fecha seleccionada se identifican con su fecha real.\n"
        "Fuentes: Red Electrica de Espana (REData) y Agencia Estatal de Meteorologia (AEMET).\n"
    )
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            base = "EnergyOptimizer"
            archive.write(portable / "EnergyOptimizer.exe", f"{base}/EnergyOptimizer.exe")
            for path in sorted((portable / "_internal").rglob("*")):
                if path.is_file():
                    private_pem = path.suffix.lower() == ".pem" and b"PRIVATE KEY-----" in path.read_bytes()
                    if path.name == ".env" or path.suffix.lower() == ".key" or private_pem:
                        raise ValueError(f"Archivo sensible no permitido en el paquete: {path.name}")
                    archive.write(path, f"{base}/{path.relative_to(portable).as_posix()}")
            archive.write(ROOT / "Abrir_dashboard.cmd", f"{base}/Abrir_dashboard.cmd")
            for path in data_files:
                archive.write(path, f"{base}/data/{path.relative_to(dataset).as_posix()}")
            archive.writestr(f"{base}/LEEME.txt", description)
        with zipfile.ZipFile(temporary) as archive:
            invalid = archive.testzip()
            if invalid is not None:
                raise ValueError(f"Fallo de integridad del ZIP: {invalid}")
            if any(Path(name).name == ".env" for name in archive.namelist()):
                raise ValueError("No se permite incluir .env.")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"ZIP creado y verificado: {output}")
    print(f"Tamano: {output.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
