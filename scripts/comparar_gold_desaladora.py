"""Compara dos ejecuciones locales del caso desaladora (modo --config y modo --industria).

Uso (desde la raiz del repo):
    python scripts/comparar_gold_desaladora.py data/outputs/comparacion/antiguo data/outputs/comparacion/nuevo

Termina con codigo 0 si las tres tablas son identicas; si no, imprime la primera diferencia.
metadata.json NO se compara entero: cambia a proposito (hora, uuid, hash del YAML, campos nuevos).
"""
import json
import sys
from pathlib import Path

import pandas as pd

TABLAS = ("programacion_horaria.parquet", "resumen_diario.parquet", "resumen_mensual.parquet")
METADATA_IGUAL = ("schema", "es_simulacion", "criterio_optimizacion", "resolucion", "silver_sha256",
                  "tarifa", "dias_esperados", "dias_optimos", "fecha_primera_programacion",
                  "fecha_ultima_programacion")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    antiguo, nuevo = Path(sys.argv[1]), Path(sys.argv[2])
    for nombre in TABLAS:
        a, b = pd.read_parquet(antiguo / nombre), pd.read_parquet(nuevo / nombre)
        pd.testing.assert_frame_equal(a, b, check_exact=True)
        print(f"OK  {nombre}: {len(a)} filas identicas")
    meta_a = json.loads((antiguo / "metadata.json").read_text(encoding="utf-8"))
    meta_b = json.loads((nuevo / "metadata.json").read_text(encoding="utf-8"))
    distintos = [k for k in METADATA_IGUAL if meta_a.get(k) != meta_b.get(k)]
    if distintos:
        sys.exit(f"ERROR metadata distinta en: {distintos}")
    print("OK  metadata: mismos datos de entrada, tarifa y cobertura")
    print(f"    nuevo: industria={meta_b.get('industria')} | advertencias={len(meta_b.get('advertencias', []))}")
    print("RESULTADO: la Gold de la desaladora es IDENTICA con base.yaml + industria.")


if __name__ == "__main__":
    main()
