"""Build a portable Windows distribution, without user credentials or datasets."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    output = args.dist_dir.resolve() / "EnergyOptimizer"
    if sys.platform != "win32":
        raise SystemExit("Este paquete se debe construir en Windows.")
    if (output / ".env").exists() or (output / "data").exists():
        raise SystemExit(
            "La distribucion existente contiene .env o data. Muevela a otra carpeta "
            "antes de reconstruir para no perder sus datos."
        )
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm",
            "--distpath", str(output.parent), str(ROOT / "energy_optimizer.spec"),
        ],
        cwd=ROOT,
        check=True,
    )
    shutil.copyfile(ROOT / ".env.example", output / ".env.example")
    shutil.copyfile(ROOT / "Abrir_dashboard.cmd", output / "Abrir_dashboard.cmd")
    print(f"Paquete generado en {output}. Comparte la carpeta completa, no solo el .exe.")


if __name__ == "__main__":
    main()
