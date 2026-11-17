import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.calidad.pipeline import (
    collect_file_results,
    save_quality_report,
    save_values_json,
)
from src.project import find_project_root


class PipelineTests(unittest.TestCase):
    def test_collect_file_results_preserves_reports(self):
        def process(path):
            return pd.DataFrame({"source": [path.name]}), {"source_file": path.name}

        values, reports = collect_file_results(
            [Path("one.json"), Path("two.json")], process
        )

        self.assertEqual(values["source"].tolist(), ["one.json", "two.json"])
        self.assertEqual(reports, [
            {"source_file": "one.json"},
            {"source_file": "two.json"},
        ])

    def test_collect_file_results_handles_empty_input(self):
        values, reports = collect_file_results([], lambda _: (pd.DataFrame(), {}))

        self.assertTrue(values.empty)
        self.assertEqual(reports, [])

    def test_processed_outputs_create_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "nested"
            values_path = save_values_json(
                pd.DataFrame({"value": [1]}), output_dir / "values.json"
            )
            report_path = save_quality_report(
                {"output_records": 1}, output_dir / "quality.json"
            )

            self.assertTrue(values_path.is_file())
            self.assertTrue(report_path.is_file())
            self.assertIn('"output_records": 1', report_path.read_text())

    def test_find_project_root_from_nested_path(self):
        root = find_project_root(Path(__file__).parent)

        self.assertTrue((root / "requirements.txt").is_file())
        self.assertTrue((root / "notebooks").is_dir())


if __name__ == "__main__":
    unittest.main()
