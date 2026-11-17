from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.cnmc import load_cnmc_config


class CnmcConfigTests(unittest.TestCase):
    """Comprueba la configuracion especifica de CNMC/MIBGAS."""

    def test_loads_cnmc_resources_and_common_window(self):
        project_root = Path(__file__).resolve().parents[2]

        config = load_cnmc_config(
            project_root / "config" / "cnmc.yml",
            project_root / "config" / "modelo.yml",
        )

        self.assertIn("indice_mibgas", config["cnmc"]["resources"])
        self.assertIn("producto_diario_d1", config["cnmc"]["resources"])
        self.assertEqual(config["cnmc"]["model"]["history_start"].isoformat(), "2024-10-01")


if __name__ == "__main__":
    unittest.main()
