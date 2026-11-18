import tempfile
import unittest
from pathlib import Path

from src.config.mibgas import load_mibgas_config


class MibgasConfigTests(unittest.TestCase):
    def test_loads_source_and_common_model_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "mibgas.yaml").write_text(
                "mibgas:\n"
                "  ingestion: {}\n"
                "  product: {code: GDAES_D+1}\n",
                encoding="utf-8",
            )
            (root / "modelo.yaml").write_text(
                "model:\n"
                "  history_start: 2024-10-01\n"
                "  history_end: 2026-09-30\n"
                "  target_start: 2025-10-01\n"
                "  target_end: 2026-09-30\n"
                "  lag_days: [1, 7, 30, 365]\n",
                encoding="utf-8",
            )

            config = load_mibgas_config(root / "mibgas.yaml")

            self.assertEqual(str(config["mibgas"]["model"]["history_start"]), "2024-10-01")
            self.assertEqual(config["mibgas"]["product"]["code"], "GDAES_D+1")


if __name__ == "__main__":
    unittest.main()
