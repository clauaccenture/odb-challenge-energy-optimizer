import importlib.util
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "ingesta_redata", Path(__file__).resolve().parents[1] / "01_ingesta_redata.py",
)
assert spec is not None and spec.loader is not None
redata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redata)


class REDataAvailabilityTests(unittest.TestCase):
    def run_ingestion(self, payload):
        with TemporaryDirectory() as directory, \
                patch.object(redata, "RAW_DIR", Path(directory)), \
                patch.object(redata, "fetch", return_value=payload), \
                patch.object(redata, "upload_s3") as upload, \
                patch("sys.argv", ["ingesta", "--start", "2026-10-24", "--end", "2026-10-24"]), \
                patch("sys.stdout", new_callable=StringIO) as output:
            redata.main()
            self.assertEqual(list(Path(directory).iterdir()), [])
            upload.assert_not_called()
            return output.getvalue()

    def test_no_series_or_empty_prices_is_success_without_raw(self):
        for payload in (
            {"included": []},
            {"included": [{"attributes": {"title": "Otra serie", "values": []}}]},
            {"included": [{"attributes": {"title": redata.SPOT_TITLE, "values": []}}]},
        ):
            with self.subTest(payload=payload):
                output = self.run_ingestion(payload)
                self.assertIn("REDATA SIN DATOS PUBLICADOS para 2026-10-24", output)
                self.assertIn("sin datos publicados: 1 | fallidos: 0", output)

    def test_malformed_response_is_not_reported_as_no_updates(self):
        for payload in ({}, {"included": None}, {"errors": ["error"]}, {
            "included": [{"attributes": {"title": redata.SPOT_TITLE, "values": None}}],
        }):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.run_ingestion(payload)

    def test_real_download_failure_still_fails(self):
        with patch.object(redata, "fetch", side_effect=RuntimeError("API failure")), \
                patch("sys.argv", ["ingesta", "--start", "2026-10-24",
                                  "--end", "2026-10-24", "--force", "--no-s3"]), \
                patch("sys.stdout", new_callable=StringIO) as output:
            with self.assertRaises(SystemExit) as error:
                redata.main()
            self.assertEqual(error.exception.code, 1)
            self.assertIn("fallidos: 1", output.getvalue())
            self.assertNotIn("REDATA SIN DATOS PUBLICADOS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
