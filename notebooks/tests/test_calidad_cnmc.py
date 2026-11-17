import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.calidad import cnmc as quality
from src.ingesta.cnmc import CnmcResourceConfig


class CnmcQualityTests(unittest.TestCase):
    """Comprueba la lectura, normalizacion y deduplicacion CNMC."""

    def setUp(self):
        self.resource = CnmcResourceConfig(
            name="producto_diario_d1",
            resource_id="resource-id",
            date_field="fecha_de_negociacion",
            price_field="precios_de_los_productos_mibgas",
            product_field="producto_de_mibgas",
            product_value="Producto diario D+1",
        )

    def test_classify_raw_file_valid_empty_and_malformed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_text(
                json.dumps({"captured_at_utc": "2026-11-16T00:00:00+00:00", "records": [{"id": 1}]}),
                encoding="utf-8",
            )
            empty = root / "empty.json"
            empty.write_text(json.dumps({"records": []}), encoding="utf-8")
            malformed = root / "malformed.json"
            malformed.write_text(json.dumps({"result": {}}), encoding="utf-8")

            self.assertEqual(quality.classify_raw_file(valid)["status"], "valid")
            self.assertEqual(quality.classify_raw_file(empty)["status"], "empty")
            self.assertEqual(quality.classify_raw_file(malformed)["status"], "malformed")

    def test_normalize_filters_window_and_product_and_converts_price(self):
        payload = {
            "captured_at_utc": "2026-11-16T00:00:00+00:00",
            "records": [
                {
                    "fecha_de_negociacion": "2025-10-01",
                    "producto_de_mibgas": "Producto diario D+1",
                    "precios_de_los_productos_mibgas": "42,50",
                },
                {
                    "fecha_de_negociacion": "2025-10-01",
                    "producto_de_mibgas": "Otro producto",
                    "precios_de_los_productos_mibgas": "99,00",
                },
                {
                    "fecha_de_negociacion": "2025-09-30",
                    "producto_de_mibgas": "Producto diario D+1",
                    "precios_de_los_productos_mibgas": "40,00",
                },
            ],
        }

        values, report = quality.normalize_records(
            payload, self.resource, date(2025, 10, 1), date(2025, 10, 31)
        )

        self.assertEqual(len(values), 1)
        self.assertEqual(values.iloc[0]["precio_eur_mwh"], 42.5)
        self.assertEqual(report["outside_window"], 1)

    def test_deduplicate_keeps_last_record_and_calculates_age(self):
        values = pd.DataFrame([
            {
                "fecha_negociacion": date(2025, 10, 1),
                "producto": "Producto diario D+1",
                "source_resource": "producto_diario_d1",
                "precio_eur_mwh": 40.0,
            },
            {
                "fecha_negociacion": date(2025, 10, 1),
                "producto": "Producto diario D+1",
                "source_resource": "producto_diario_d1",
                "precio_eur_mwh": 42.0,
            },
        ])

        deduplicated, count = quality.deduplicate_records(values)
        aged = quality.add_age_days(
            deduplicated, pd.Timestamp("2025-10-08", tz="Europe/Madrid")
        )

        self.assertEqual(count, 1)
        self.assertEqual(aged.iloc[0]["precio_eur_mwh"], 42.0)
        self.assertEqual(aged.iloc[0]["edad_precio_gas_dias"], 7)


if __name__ == "__main__":
    unittest.main()
