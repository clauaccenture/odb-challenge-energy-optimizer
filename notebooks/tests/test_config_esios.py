from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.esios import load_esios_config


class ModelConfigTests(unittest.TestCase):
    """Comprueba la carga y estructura mínima de la configuración versionada."""

    def test_load_esios_config_validates_required_sections(self):
        """Rechaza configuraciones sin las secciones que consumen los notebooks."""
        invalid_configs = (
            "esios: {}\n",
            "esios:\n  ingestion: {}\n  model: {}\n",
        )

        with TemporaryDirectory() as directory:
            model_path = Path(directory) / "modelo.yaml"
            model_path.write_text(
                "model:\n"
                "  history_start: 2024-10-01\n"
                "  history_end: 2026-09-30\n"
                "  target_start: 2025-10-01\n"
                "  target_end: 2026-09-30\n"
                "  lag_days: [1, 7, 30, 365]\n",
                encoding="utf-8",
            )
            for content in invalid_configs:
                with self.subTest(content=content):
                    path = Path(directory) / "esios.yaml"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_esios_config(path, model_path)

    def test_load_esios_config_reads_source_and_model(self):
        """Comprueba que la configuración ESIOS versionada se puede cargar."""
        project_root = Path(__file__).resolve().parents[2]

        config = load_esios_config(project_root / "config" / "esios.yaml")

        self.assertIn("esios", config)
        self.assertEqual(config["esios"]["timezone"], "Europe/Madrid")
        self.assertTrue(config["esios"]["indicator_ids"])


if __name__ == "__main__":
    unittest.main()
