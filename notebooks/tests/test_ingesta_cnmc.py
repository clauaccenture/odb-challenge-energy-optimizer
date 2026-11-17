import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ingesta import cnmc as ingestion


class CnmcIngestionTests(unittest.TestCase):
    """Comprueba la paginacion y persistencia de la ingesta CNMC."""

    def resource(self):
        return ingestion.CnmcResourceConfig(
            name="indice_mibgas",
            resource_id="resource-id",
            date_field="fecha_de_negociacion",
            price_field="precio_indice_mibgas",
        )

    def test_fetch_resource_paginates_until_total(self):
        first = Mock(status_code=200)
        first.json.return_value = {
            "success": True,
            "result": {"total": 2, "records": [{"id": 1}]},
        }
        second = Mock(status_code=200)
        second.json.return_value = {
            "success": True,
            "result": {"total": 2, "records": [{"id": 2}]},
        }
        request_get = Mock(side_effect=[first, second])

        payload = ingestion.fetch_resource(
            self.resource(),
            ingestion.CnmcIngestionConfig(
                raw_dir=Path("."),
                base_url="https://example.invalid",
                page_size=1,
                pause_seconds=0,
            ),
            request_get=request_get,
            sleep=lambda _: None,
        )

        self.assertEqual(payload["records"], [{"id": 1}, {"id": 2}])
        self.assertEqual(request_get.call_count, 2)
        self.assertEqual(request_get.call_args_list[1].kwargs["params"]["offset"], 1)

    def test_fetch_resource_advances_offset_for_invalid_records(self):
        first = Mock(status_code=200)
        first.json.return_value = {
            "success": True,
            "result": {"total": 3, "records": [{"id": 1}, "invalid"]},
        }
        second = Mock(status_code=200)
        second.json.return_value = {
            "success": True,
            "result": {"total": 3, "records": [{"id": 3}]},
        }
        request_get = Mock(side_effect=[first, second])

        payload = ingestion.fetch_resource(
            self.resource(),
            ingestion.CnmcIngestionConfig(
                raw_dir=Path("."),
                base_url="https://example.invalid",
                page_size=2,
                pause_seconds=0,
            ),
            request_get=request_get,
            sleep=lambda _: None,
        )

        self.assertEqual(payload["records"], [{"id": 1}, {"id": 3}])
        self.assertEqual(request_get.call_count, 2)
        self.assertEqual(request_get.call_args_list[1].kwargs["params"]["offset"], 2)

    def test_get_json_retries_server_error(self):
        first = Mock(status_code=500)
        first.raise_for_status.side_effect = requests.HTTPError("server error")
        second = Mock(status_code=200)
        second.json.return_value = {"ok": True}
        request_get = Mock(side_effect=[first, second])
        sleeps = []

        payload = ingestion.get_json(
            "https://example.invalid",
            {},
            retries=2,
            request_get=request_get,
            sleep=sleeps.append,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(sleeps, [1])

    def test_config_rejects_invalid_pagination_and_timeout(self):
        with self.assertRaises(ValueError):
            ingestion.CnmcIngestionConfig(
                raw_dir=Path("."),
                base_url="https://example.invalid",
                page_size=0,
            )
        with self.assertRaises(ValueError):
            ingestion.CnmcIngestionConfig(
                raw_dir=Path("."),
                base_url="https://example.invalid",
                timeout=0,
            )

    def test_ingest_resource_saves_and_skips_raw_file(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "result": {"total": 1, "records": [{"id": 1}]},
        }
        request_get = Mock(return_value=response)

        with TemporaryDirectory() as directory:
            config = ingestion.CnmcIngestionConfig(
                raw_dir=Path(directory),
                base_url="https://example.invalid",
                pause_seconds=0,
            )
            result = ingestion.ingest_resource(
                self.resource(), config, request_get=request_get, sleep=lambda _: None
            )
            skipped = ingestion.ingest_resource(
                self.resource(), config, request_get=request_get, sleep=lambda _: None
            )
            saved = json.loads((Path(directory) / "indice_mibgas.json").read_text(encoding="utf-8"))

        self.assertEqual(result[0], "downloaded")
        self.assertEqual(skipped[0], "skipped")
        self.assertEqual(saved["records"], [{"id": 1}])
        self.assertEqual(request_get.call_count, 1)

    def test_ingest_resource_redownloads_invalid_existing_file(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "result": {"total": 1, "records": [{"id": 1}]},
        }
        request_get = Mock(return_value=response)

        with TemporaryDirectory() as directory:
            config = ingestion.CnmcIngestionConfig(
                raw_dir=Path(directory),
                base_url="https://example.invalid",
                pause_seconds=0,
            )
            invalid_path = Path(directory) / "indice_mibgas.json"
            invalid_path.write_text("{invalid", encoding="utf-8")

            result = ingestion.ingest_resource(
                self.resource(), config, request_get=request_get, sleep=lambda _: None
            )

        self.assertEqual(result[0], "downloaded")
        request_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
