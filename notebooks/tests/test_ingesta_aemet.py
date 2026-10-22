import importlib.util
import json
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

import requests


SPEC = importlib.util.spec_from_file_location(
    "ingesta_aemet", Path(__file__).resolve().parents[1] / "01_ingesta_aemet.py",
)
assert SPEC is not None and SPEC.loader is not None
aemet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aemet)


class DailyIngestionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (("RAW_DIR", self.root), ("API_KEY", "test-key"), ("BUCKET", "test-bucket")):
            patcher = patch.object(aemet, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        output = patch("sys.stdout", new_callable=StringIO)
        self.output = output.start()
        self.addCleanup(output.stop)

    def history(self, dates):
        path = self.root / "aemet_2026-10-01_2026-10-21.json"
        path.write_text(json.dumps([{"fecha": day} for day in dates]), encoding="utf-8")
        return path

    def test_walks_back_to_real_history_and_saves_only_available_dates(self):
        historical = self.history(["2026-10-18", "2026-10-19"])

        def fetch(start, end):
            self.assertEqual(start, end)
            if start == date(2026, 10, 20):
                return [{"fecha": "2026-10-20", "tmed": "12,8"}]
            raise aemet.NoDataAvailable("Sin datos")

        with patch.object(aemet, "fetch", side_effect=fetch) as download, \
                patch.object(aemet, "upload_s3") as upload:
            aemet.ingest_daily(date(2026, 10, 23), False)
        self.assertEqual(download.call_args_list, [
            call(date(2026, 10, day), date(2026, 10, day)) for day in (23, 22, 21, 20)
        ])
        saved = self.root / "aemet_2026-10-20_2026-10-20.json"
        self.assertTrue(saved.is_file())
        self.assertEqual(upload.call_args_list, [call(historical), call(saved)])
        self.assertIn("Última fecha disponible: 2026-10-20", self.output.getvalue())
        self.assertFalse((self.root / "aemet_2026-10-23_2026-10-23.json").exists())

    def test_no_updates_is_explicit_and_keeps_history(self):
        self.history(["2026-10-19"])
        with patch.object(aemet, "fetch", side_effect=aemet.NoDataAvailable("Sin datos")), \
                patch.object(aemet, "upload_s3") as upload:
            aemet.ingest_daily(date(2026, 10, 22), True)
        self.assertIn("AEMET SIN NOVEDADES", self.output.getvalue())
        upload.assert_not_called()
        self.assertFalse((self.root / "manifest.jsonl").exists())

    def test_repeated_target_does_not_download_or_duplicate_manifest(self):
        self.history(["2026-10-19"])
        with patch.object(aemet, "fetch") as download, patch.object(aemet, "upload_s3"):
            aemet.ingest_daily(date(2026, 10, 19), False)
        download.assert_not_called()
        self.assertFalse((self.root / "manifest.jsonl").exists())

    def test_requires_local_history(self):
        with self.assertRaisesRegex(ValueError, "histórico"):
            aemet.ingest_daily(date(2026, 10, 22), True)

    def test_real_api_error_is_not_no_updates(self):
        self.history(["2026-10-19"])
        with patch.object(aemet, "fetch", side_effect=requests.Timeout("timeout")):
            with self.assertRaises(requests.Timeout):
                aemet.ingest_daily(date(2026, 10, 22), True)
        self.assertNotIn("SIN NOVEDADES", self.output.getvalue())

    def test_s3_failure_can_be_recovered_on_next_run(self):
        self.history(["2026-10-19"])
        with patch.object(aemet, "fetch", side_effect=lambda start, end: [{"fecha": str(start)}]), \
                patch.object(aemet, "upload_s3", side_effect=[None, RuntimeError("S3")]):
            with self.assertRaisesRegex(RuntimeError, "S3"):
                aemet.ingest_daily(date(2026, 10, 21), False)
        failed_path = self.root / "aemet_2026-10-20_2026-10-20.json"
        self.assertTrue(failed_path.exists())
        self.assertFalse((self.root / "aemet_2026-10-21_2026-10-21.json").exists())
        with patch.object(aemet, "fetch", return_value=[{"fecha": "2026-10-21"}]), \
                patch.object(aemet, "upload_s3") as upload:
            aemet.ingest_daily(date(2026, 10, 21), False)
        self.assertEqual(upload.call_args_list[0], call(failed_path))
        self.assertTrue((self.root / "aemet_2026-10-21_2026-10-21.json").exists())

    def test_rejects_wrong_date_in_daily_response(self):
        self.history(["2026-10-19"])
        with patch.object(aemet, "fetch", return_value=[{"fecha": "2026-10-18"}]):
            with self.assertRaisesRegex(ValueError, "fuera del rango"):
                aemet.ingest_daily(date(2026, 10, 20), True)

    def test_api_no_data_status_is_distinct_from_real_errors(self):
        for http_status, body_status, error_type in (
            (404, None, aemet.NoDataAvailable),
            (200, 404, aemet.NoDataAvailable),
            (403, None, requests.HTTPError),
            (429, None, requests.HTTPError),
            (500, None, requests.HTTPError),
            (200, 429, RuntimeError),
        ):
            with self.subTest(http=http_status, body=body_status):
                response = Mock(status_code=http_status)
                response.json.return_value = {"estado": body_status}
                if http_status >= 400:
                    response.raise_for_status.side_effect = requests.HTTPError(str(http_status))
                with patch.object(aemet.requests, "get", return_value=response):
                    with self.assertRaises(error_type):
                        aemet.fetch(date(2026, 10, 22), date(2026, 10, 22))

    def test_valid_response_and_empty_or_malformed_data(self):
        for payload, error_type in (
            ([{"fecha": "2026-10-21"}], None),
            ([], aemet.NoDataAvailable),
            ({"error": "bad response"}, ValueError),
            ([{"fecha": "2026-10-20"}], ValueError),
        ):
            with self.subTest(payload=payload):
                control = Mock(status_code=200)
                control.json.return_value = {"estado": 200, "datos": "https://example.invalid/data"}
                data = Mock()
                data.json.return_value = payload
                with patch.object(aemet.requests, "get", side_effect=[control, data]):
                    if error_type is None:
                        self.assertEqual(aemet.fetch(date(2026, 10, 21), date(2026, 10, 21)), payload)
                    else:
                        with self.assertRaises(error_type):
                            aemet.fetch(date(2026, 10, 21), date(2026, 10, 21))

    def test_daily_cli_and_historical_mode_are_separate(self):
        with patch("sys.argv", ["ingesta", "--daily", "--end", "2026-10-22", "--no-s3"]), \
                patch.object(aemet, "ingest_daily") as daily:
            aemet.main()
        daily.assert_called_once_with(date(2026, 10, 22), True)
        with patch("sys.argv", [
            "ingesta", "--start", "2026-10-01", "--end", "2026-10-21", "--no-s3",
        ]), patch.object(aemet, "fetch", side_effect=lambda start, end: [{"fecha": str(start)}]) as download:
            aemet.main()
        self.assertEqual(download.call_args_list, [
            call(date(2026, 10, 1), date(2026, 10, 15)),
            call(date(2026, 10, 16), date(2026, 10, 21)),
        ])


if __name__ == "__main__":
    unittest.main()
