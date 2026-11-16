import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.calidad import esios as quality


class EsiosQualityTests(unittest.TestCase):
    """Comprueba la lectura, normalización y deduplicación de datos ESIOS."""

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.raw = self.root / "raw"
        self.indicators = self.raw / "indicadores"

    def write_block(self, indicator_id, values, name=None):
        directory = self.indicators / str(indicator_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"indicador_{indicator_id}_2026-01-01_2026-01-30.json"
        payload = {
            "indicator": {
                "name": name or f"Indicador {indicator_id}",
                "short_name": f"I{indicator_id}",
                "magnitud": [{"name": "Energia"}],
                "tiempo": [{"name": "Hora"}],
                "values": values,
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_selects_only_requested_indicator_directories(self):
        """Demuestra que el alcance excluye indicadores no seleccionados."""
        selected = self.write_block(28, [])
        self.write_block(999, [])
        self.assertEqual(quality.select_raw_files(self.raw, {28}), [selected])

    def test_classifies_valid_empty_and_malformed_blocks(self):
        """Distingue datos válidos, respuestas vacías y JSON ilegible."""
        valid = self.write_block(28, [{"datetime_utc": "2026-01-01T00:00:00Z", "value": "12.5"}])
        empty = self.write_block(29, [])
        malformed = self.indicators / "30" / "indicador_30_2026-01-01_2026-01-30.json"
        malformed.parent.mkdir(parents=True)
        malformed.write_text("{bad json", encoding="utf-8")

        self.assertEqual(quality.classify_file(valid, self.root)["status"], "valid")
        self.assertEqual(quality.classify_file(empty, self.root)["status"], "empty")
        self.assertEqual(quality.classify_file(malformed, self.root)["status"], "unreadable")

    def test_classify_file_rejects_missing_values_list(self):
        """Comprueba que un indicador sin una lista values queda como malformado."""
        path = self.indicators / "31" / "indicador_31_2026-01-01_2026-01-30.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"indicator": {"name": "Sin valores", "values": None}}),
            encoding="utf-8",
        )

        result = quality.classify_file(path, self.root)

        self.assertEqual(result["status"], "malformed")
        self.assertEqual(result["error"], "Falta indicator.values como lista")

    def test_flatten_ignores_empty_and_non_dict_values(self):
        """Demuestra que solo se aplanan registros de valor válidos."""
        valid = quality.classify_file(
            self.write_block(28, [
                {"datetime_utc": "2026-01-01T00:00:00Z", "value": "12.5", "geo_id": 8741},
                "invalid",
            ]),
            self.root,
        )
        empty = quality.classify_file(self.write_block(29, []), self.root)

        values = quality.flatten_records([valid, empty])

        self.assertEqual(len(values), 1)
        self.assertEqual(values.iloc[0]["indicator_id"], 28)
        self.assertEqual(values.iloc[0]["valor"], "12.5")

    def test_normalize_reports_invalid_values_and_marks_window(self):
        """Comprueba la conversión de tipos y el diagnóstico de valores inválidos."""
        values = pd.DataFrame([
            {
                "indicator_id": 28,
                "fecha_inicio": "2025-12-31T23:00:00Z",
                "fecha_fin": None,
                "valor": "not-a-number",
                "geo_id": 8741,
                "geo_name": "Península",
            },
        ])

        normalized, report = quality.normalize_values(
            values,
            pd.Timestamp("2026-01-01", tz="UTC"),
            pd.Timestamp("2026-01-31 23:59:59", tz="UTC"),
        )

        self.assertEqual(report["invalid_numeric_values"], 1)
        self.assertEqual(report["missing_fecha_fin"], 1)
        self.assertTrue(normalized.iloc[0]["fecha_inicio_fuera_ventana"])

    def test_normalize_converts_utc_to_local_timezone(self):
        """Comprueba que los timestamps UTC se convierten a la zona local."""
        values = pd.DataFrame([{
            "indicator_id": 28,
            "fecha_inicio": "2026-01-01T00:00:00Z",
            "fecha_fin": "2026-01-01T01:00:00Z",
            "valor": "12.5",
            "geo_id": 8741,
            "geo_name": "Península",
        }])

        normalized, _ = quality.normalize_values(
            values,
            pd.Timestamp("2026-01-01", tz="UTC"),
            pd.Timestamp("2026-01-31 23:59:59", tz="UTC"),
            local_timezone="Europe/Madrid",
        )

        local_timestamp = normalized.iloc[0]["datetime_local"]
        self.assertEqual(local_timestamp.hour, 1)
        self.assertEqual(str(local_timestamp.tz), "Europe/Madrid")

    def test_deduplicate_keeps_last_occurrence(self):
        """Demuestra que la última aparición conserva el valor deduplicado."""
        values = pd.DataFrame([
            {
                "indicator_id": 28,
                "fecha_inicio": pd.Timestamp("2026-01-01", tz="UTC"),
                "fecha_fin": pd.NaT,
                "geo_id": 8741,
                "geo_name": "Península",
                "valor": 1.0,
                "source_file": "old.json",
            },
            {
                "indicator_id": 28,
                "fecha_inicio": pd.Timestamp("2026-01-01", tz="UTC"),
                "fecha_fin": pd.NaT,
                "geo_id": 8741,
                "geo_name": "Península",
                "valor": 2.0,
                "source_file": "new.json",
            },
        ])

        deduplicated, duplicates, count = quality.deduplicate_values(values)

        self.assertEqual(count, 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(deduplicated), 1)
        self.assertEqual(deduplicated.iloc[0]["valor"], 2.0)


if __name__ == "__main__":
    unittest.main()
