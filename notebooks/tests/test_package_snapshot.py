import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
import sys
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("package_snapshot", ROOT / "package_snapshot.py")
assert spec is not None and spec.loader is not None
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SnapshotPackageTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.portable = self.root / "dist" / "EnergyOptimizer"
        (self.portable / "_internal").mkdir(parents=True)
        (self.portable / "EnergyOptimizer.exe").write_bytes(b"test executable")
        (self.portable / "_internal" / "library.dll").write_bytes(b"test library")
        (self.portable / "_internal" / "cacert.pem").write_bytes(b"-----BEGIN CERTIFICATE-----")
        (self.portable / ".env").write_text("PRIVATE_VALUE", encoding="utf-8")
        (self.root / ".env").write_text("PRIVATE_VALUE", encoding="utf-8")
        (self.root / "Abrir_dashboard.cmd").write_text("EnergyOptimizer.exe --dashboard-only", encoding="utf-8")
        for source in ("aemet", "redata"):
            path = self.root / "data" / "raw" / source
            path.mkdir(parents=True)
            (path / "raw.json").write_text("[]", encoding="utf-8")
        parquet = self.root / "data" / "outputs" / "redata"
        parquet.mkdir(parents=True)
        (parquet / "gold.parquet").write_bytes(b"test parquet")
        self.days = [pd.Timestamp("2026-10-24").date()]
        self.temperature = pd.DataFrame({"fecha": self.days})
        self.summary = pd.DataFrame({"fecha_local": self.days})
        loader = ModuleType("data_loader")
        loader.load_gold_tables = lambda: (pd.DataFrame(), self.summary, pd.DataFrame(index=range(24)))
        loader.load_temperature_table = lambda: self.temperature
        patcher = patch.dict(sys.modules, {"data_loader": loader})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(snapshot, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        original_path = sys.path.copy()
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original_path))

    def run_package(self):
        with patch("sys.argv", ["package_snapshot", "--start", "2026-10-24", "--end", "2026-10-24"]):
            snapshot.main()

    def test_zip_contains_portable_data_and_launcher_but_not_credentials(self):
        self.run_package()
        path = self.root / "dist" / "EnergyOptimizer_2026-10-24_2026-10-24.zip"
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertIn("EnergyOptimizer/EnergyOptimizer.exe", names)
            self.assertIn("EnergyOptimizer/Abrir_dashboard.cmd", names)
            self.assertIn("EnergyOptimizer/_internal/cacert.pem", names)
            self.assertIn("EnergyOptimizer/data/raw/aemet/raw.json", names)
            self.assertIn("EnergyOptimizer/data/raw/redata/raw.json", names)
            self.assertIn("EnergyOptimizer/data/outputs/redata/gold.parquet", names)
            self.assertFalse(any(Path(name).name == ".env" for name in names))
            self.assertTrue(all(b"PRIVATE_VALUE" not in archive.read(name) for name in names))
            self.assertIsNone(archive.testzip())

    def test_incomplete_or_extra_dates_cannot_be_packaged(self):
        for days in ([], [*self.days, pd.Timestamp("2026-10-25").date()]):
            with self.subTest(days=days):
                self.temperature = pd.DataFrame({"fecha": days})
                with self.assertRaises(SystemExit):
                    self.run_package()
        self.assertEqual(list((self.root / "dist").glob("*.zip")), [])

    def test_sensitive_file_in_internal_folder_blocks_delivery(self):
        (self.portable / "_internal" / ".env").write_text("PRIVATE_VALUE", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sensible"):
            self.run_package()
        self.assertEqual(list((self.root / "dist").glob("*.zip*")), [])

    def test_private_certificate_key_is_not_packaged(self):
        (self.portable / "_internal" / "client.pem").write_bytes(b"-----BEGIN RSA PRIVATE KEY-----")
        with self.assertRaisesRegex(ValueError, "sensible"):
            self.run_package()
        self.assertEqual(list((self.root / "dist").glob("*.zip*")), [])


if __name__ == "__main__":
    unittest.main()
