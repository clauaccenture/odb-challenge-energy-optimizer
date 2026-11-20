import tempfile
import unittest
from pathlib import Path

from src.ingesta.mibgas import MibgasIngestionConfig, ingest_year


CSV = b'''Fecha Emision :31/12/2025 - 21:39;\nTrading day;Product;Place of delivery;Area;First Day Delivery;Last Day Delivery;\n"MIBGAS Daily Price [EUR/MWh]";\n31/12/2025;GDAES_D+1;PVB;ES;01/01/2026;01/01/2026;28.96;\n'''


class FakeResponse:
    status_code = 200
    content = CSV

    def raise_for_status(self):
        return None


class MibgasIngestionTests(unittest.TestCase):
    def test_ingest_year_saves_csv_without_real_api(self):
        requests = []

        def fake_get(url, **kwargs):
            requests.append((url, kwargs))
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temporary:
            config = MibgasIngestionConfig(
                raw_dir=Path(temporary),
                base_url="https://example.test",
            )
            status, path, lines = ingest_year(2025, config, request_get=fake_get, sleep=lambda _: None)

            self.assertEqual(status, "downloaded")
            self.assertEqual(lines, 4)
            self.assertTrue(path.is_file())
            self.assertIn("MIBGAS_Data_2025.csv", requests[0][0])

    def test_config_rejects_invalid_timeout(self):
        with self.assertRaises(ValueError):
            MibgasIngestionConfig(
                raw_dir=Path("."),
                base_url="https://example.test",
                timeout=0,
            )

    def test_ingest_year_redownloads_invalid_existing_file(self):
        requests = []

        def fake_get(url, **kwargs):
            requests.append((url, kwargs))
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temporary:
            raw_dir = Path(temporary)
            path = raw_dir / "MIBGAS_Data_2025.csv"
            path.write_bytes(b"truncated")
            config = MibgasIngestionConfig(
                raw_dir=raw_dir,
                base_url="https://example.test",
            )

            status, _, _ = ingest_year(
                2025, config, request_get=fake_get, sleep=lambda _: None
            )

        self.assertEqual(status, "downloaded")
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
