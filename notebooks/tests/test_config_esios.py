from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.esios_config import load_model_config


class ModelConfigTests(unittest.TestCase):
    """Comprueba la carga y estructura mínima de la configuración versionada."""

    def test_load_model_config_validates_required_sections(self):
        """Rechaza configuraciones sin las secciones que consumen los notebooks."""
        invalid_configs = (
            "esios: {}\n",
            "esios:\n  ingestion: {}\n  model: {}\n",
            "esios:\n  ingestion: {}\n  indicator_ids: [28]\n",
            "esios:\n  model: {}\n  indicator_ids: [28]\n",
        )

        with TemporaryDirectory() as directory:
            for content in invalid_configs:
                with self.subTest(content=content):
                    path = Path(directory) / "modelo.yml"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_model_config(path)

    def test_load_model_config_esi_config(self):
        """Comprueba que la configuración ESIOS versionada se puede cargar."""
        project_root = Path(__file__).resolve().parents[2]

        config = load_model_config(project_root / "config" / "modelo.yml")

        self.assertIn("esios", config)
        self.assertEqual(config["esios"]["timezone"], "Europe/Madrid")
        self.assertTrue(config["esios"]["indicator_ids"])


if __name__ == "__main__":
    unittest.main()
