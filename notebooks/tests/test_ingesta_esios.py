import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ingesta import esios as ingestion


class EsiosIngestionTests(unittest.TestCase):
    """Comprueba las operaciones reutilizables de la ingesta ESIOS."""

    def test_date_chunks_cover_window_without_overlap(self):
        """Demuestra que la ventana se divide sin huecos ni solapamientos."""
        chunks = list(ingestion.date_chunks(date(2026, 1, 1), date(2026, 2, 5), size=30))
        self.assertEqual(chunks, [
            (date(2026, 1, 1), date(2026, 1, 30)),
            (date(2026, 1, 31), date(2026, 2, 5)),
        ])

    def test_values_count_requires_indicator_values_list(self):
        """Valida la estructura mínima esperada en una respuesta de indicador."""
        self.assertEqual(ingestion.values_count({"indicator": {"values": [1, 2]}}), 2)
        with self.assertRaises(ValueError):
            ingestion.values_count({"indicator": {"values": None}})

    def test_get_json_retries_transient_error(self):
        """Demuestra que un HTTP 429 se reintenta con espera exponencial."""
        first = Mock(status_code=429)
        first.raise_for_status.side_effect = requests.HTTPError("rate limit")
        second = Mock(status_code=200)
        second.json.return_value = {"indicator": {"values": []}}
        request_get = Mock(side_effect=[first, second])
        sleeps = []

        payload = ingestion.get_json(
            "https://example.invalid",
            {"x-api-key": "test"},
            retries=2,
            request_get=request_get,
            sleep=sleeps.append,
        )

        self.assertEqual(payload["indicator"]["values"], [])
        self.assertEqual(request_get.call_count, 2)
        self.assertEqual(sleeps, [1])

    def test_get_json_retries_server_error(self):
        """Comprueba que un error HTTP 5xx permite reintentar la petición."""
        first = Mock(status_code=500)
        first.raise_for_status.side_effect = requests.HTTPError("server error")
        second = Mock(status_code=200)
        second.json.return_value = {"indicator": {"values": []}}
        request_get = Mock(side_effect=[first, second])
        sleeps = []

        payload = ingestion.get_json(
            "https://example.invalid",
            {"x-api-key": "test"},
            retries=2,
            request_get=request_get,
            sleep=sleeps.append,
        )

        self.assertEqual(payload["indicator"]["values"], [])
        self.assertEqual(request_get.call_count, 2)
        self.assertEqual(sleeps, [1])

    def test_get_json_does_not_retry_authentication_error(self):
        """Comprueba que un error de credenciales falla sin reintentos."""
        response = Mock(status_code=403)
        request_get = Mock(return_value=response)

        with self.assertRaises(PermissionError):
            ingestion.get_json(
                "https://example.invalid",
                {"x-api-key": "test"},
                request_get=request_get,
            )
        request_get.assert_called_once()

    def test_save_raw_writes_json_and_uploads_when_requested(self):
        """Verifica el guardado local y la subida opcional a S3."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "payload.json"
            s3_client = Mock()
            ingestion.save_raw(
                {"ok": True},
                path,
                "raw/esios/payload.json",
                upload_to_s3=True,
                bucket="test-bucket",
                s3_client=s3_client,
            )

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})
            s3_client.upload_file.assert_called_once_with(
                str(path), "test-bucket", "raw/esios/payload.json"
            )

    def test_download_one_saves_success_and_skips_existing_file(self):
        """Demuestra la descarga, persistencia y reanudación sin duplicados."""
        response = Mock(status_code=200)
        response.json.return_value = {"indicator": {"values": [{"value": 10}]}}
        request_get = Mock(return_value=response)
        sleeps = []
        task = (28, date(2026, 1, 1), date(2026, 1, 30))

        with TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            config = ingestion.EsiosIngestionConfig(
                raw_dir=raw_dir,
                base_url="https://example.invalid",
                headers={"x-api-key": "test"},
                retries=1,
                pause_seconds=0,
            )
            result = ingestion.download_one(
                task,
                config,
                request_get=request_get,
                sleep=sleeps.append,
            )
            skipped = ingestion.download_one(
                task,
                config,
                request_get=request_get,
                sleep=sleeps.append,
            )

        self.assertEqual(result[0], "downloaded")
        self.assertEqual(result[4], 1)
        self.assertEqual(skipped[0], "skipped")
        self.assertEqual(request_get.call_count, 1)

    def test_download_one_force_overwrites_existing_file(self):
        """Comprueba que force permite reemplazar un fichero raw existente."""
        response = Mock(status_code=200)
        response.json.return_value = {"indicator": {"values": [{"value": 20}]}}
        request_get = Mock(return_value=response)
        task = (28, date(2026, 1, 1), date(2026, 1, 30))

        with TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            existing = raw_dir / "indicadores" / "28" / (
                "indicador_28_2026-01-01_2026-01-30.json"
            )
            existing.parent.mkdir(parents=True)
            existing.write_text(json.dumps({"old": True}), encoding="utf-8")
            config = ingestion.EsiosIngestionConfig(
                raw_dir=raw_dir,
                base_url="https://example.invalid",
                headers={"x-api-key": "test"},
                retries=1,
                pause_seconds=0,
                force=True,
            )

            result = ingestion.download_one(
                task,
                config,
                request_get=request_get,
                sleep=lambda _: None,
            )

            self.assertEqual(result[0], "downloaded")
            self.assertEqual(
                json.loads(existing.read_text(encoding="utf-8")),
                {"indicator": {"values": [{"value": 20}]}},
            )
            request_get.assert_called_once()

    def test_download_one_returns_controlled_failure(self):
        """Comprueba que un fallo de la API se devuelve para el resumen de ingesta."""
        response = Mock(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError("server error")
        request_get = Mock(return_value=response)

        with TemporaryDirectory() as directory:
            config = ingestion.EsiosIngestionConfig(
                raw_dir=Path(directory),
                base_url="https://example.invalid",
                headers={"x-api-key": "test"},
                retries=1,
            )
            result = ingestion.download_one(
                (28, date(2026, 1, 1), date(2026, 1, 30)),
                config,
                request_get=request_get,
                sleep=lambda _: None,
            )

        self.assertEqual(result[0], "failed")
        self.assertIn("Fallo la peticion", result[5])


if __name__ == "__main__":
    unittest.main()
