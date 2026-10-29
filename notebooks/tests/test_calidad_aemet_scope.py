import importlib.util
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / f"{name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load_script("02_calidad_aemet")
gold = load_script("03_gold_aemet")


class QualityScopeTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.processed = self.root / "processed"
        for module, name, value in (
            (quality, "RAW_DIR", self.raw),
            (quality, "OUT_DIR", self.processed),
            (gold, "SILVER", self.processed / "aemet_diario.json"),
            (gold, "OUT_DIR", self.root / "gold"),
        ):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        output = patch("sys.stdout", new_callable=StringIO)
        self.output = output.start()
        self.addCleanup(output.stop)
        self.old = self.write_raw("2026-06-05", ["MADRID", "SEVILLA"])
        self.new = self.write_raw("2026-10-20", ["MADRID"])

    def write_raw(self, day, provinces):
        name = f"aemet_{day}_{day}.json"
        rows = [{
            "fecha": day, "indicativo": province, "nombre": province,
            "provincia": province, "tmin": "1,0", "tmax": "15,0",
            "tmed": "8,0", "horatmin": "06:00", "horatmax": "15:00",
        } for province in provinces]
        (self.raw / name).write_text(json.dumps(rows), encoding="utf-8")
        return name

    def scope(self, files, status="completed"):
        (self.raw / "last_ingestion.json").write_text(json.dumps({
            "status": status, "files": files,
        }), encoding="utf-8")

    def run_quality(self):
        with patch("sys.argv", ["quality", "--no-s3"]):
            quality.main()
        return json.loads((self.processed / "calidad_aemet.json").read_text(encoding="utf-8"))

    def run_gold(self):
        self.output.truncate(0)
        self.output.seek(0)
        with patch("sys.argv", ["gold", "--no-s3"]):
            gold.main()
        return self.output.getvalue()

    def test_daily_report_is_scoped_but_tables_keep_history(self):
        self.scope([self.new])
        report = self.run_quality()
        self.assertEqual(report["rows_read"], 1)
        self.assertEqual(report["days"], 1)
        self.assertEqual(report["ingested_dates"], ["2026-10-20"])
        silver = json.loads((self.processed / "aemet_diario.json").read_text(encoding="utf-8"))
        self.assertEqual(len(silver), 3)
        output = self.run_gold()
        self.assertIn("menos de 2 provincias: ['2026-10-20']", output)
        self.assertNotIn("['2026-06-05']", output)
        table = pd.read_parquet(self.root / "gold" / gold.OUT_NAME)
        self.assertEqual(len(table), 2)

    def test_historical_ingestion_reports_all_its_records(self):
        self.scope([self.old, self.new])
        report = self.run_quality()
        self.assertEqual(report["rows_read"], 3)
        self.assertEqual(report["days"], 2)
        self.assertEqual(report["ingested_dates"], ["2026-06-05", "2026-10-20"])

    def test_no_updates_reports_zero_and_suppresses_historical_warnings(self):
        self.scope([])
        report = self.run_quality()
        self.assertEqual(report["rows_read"], 0)
        self.assertEqual(report["days"], 0)
        self.assertIsNone(report["date_min"])
        self.assertEqual(report["ingested_dates"], [])
        output = self.run_gold()
        self.assertIn("SIN NOVEDADES", output)
        self.assertNotIn("AVISO:", output)
        self.assertEqual(len(pd.read_parquet(self.root / "gold" / gold.OUT_NAME)), 2)

    def test_failed_ingestion_cannot_reuse_previous_scope(self):
        self.scope([], status="running")
        with self.assertRaisesRegex(ValueError, "no ha finalizado"):
            self.run_quality()

    def test_first_ingestion_without_published_data_generates_empty_gold(self):
        (self.raw / self.old).unlink()
        (self.raw / self.new).unlink()
        self.scope([])
        report = self.run_quality()
        self.assertEqual(report["rows_read"], 0)
        self.assertEqual(report["rows_output"], 0)
        self.assertEqual(report["ingested_dates"], [])
        self.assertEqual(json.loads((self.processed / "aemet_diario.json").read_text(encoding="utf-8")), [])
        output = self.run_gold()
        self.assertIn("AEMET SIN DATOS", output)
        table = pd.read_parquet(self.root / "gold" / gold.OUT_NAME)
        self.assertTrue(table.empty)
        self.assertEqual(table.columns.tolist(), gold.COLUMNAS)

    def test_missing_raw_without_completed_ingestion_is_still_an_error(self):
        (self.raw / self.old).unlink()
        (self.raw / self.new).unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_quality()

    def test_empty_gold_without_confirmed_no_data_report_is_an_error(self):
        self.scope([self.old])
        self.run_quality()
        (self.processed / "aemet_diario.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Silver AEMET vacío"):
            self.run_gold()

    def test_without_ingestion_record_explicitly_reports_history(self):
        report = self.run_quality()
        self.assertEqual(report["scope"], "historical")
        self.assertEqual(report["rows_read"], 3)
        self.assertIn("Sin registro", self.output.getvalue())

    def test_missing_ingested_file_is_an_error(self):
        self.scope(["aemet_missing.json"])
        with self.assertRaises(FileNotFoundError):
            self.run_quality()


if __name__ == "__main__":
    unittest.main()
