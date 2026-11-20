import unittest

import pandas as pd

from src.calidad.mibgas import PRICE_COLUMN, deduplicate_records, normalize_records


class MibgasQualityTests(unittest.TestCase):
    def test_normalizes_d_plus_one_by_delivery_date(self):
        values = pd.DataFrame([
            {
                "Trading day": "30/09/2025",
                "Product": "GDAES_D+1",
                "Place of delivery": "PVB",
                "Area": "ES",
                "First Day Delivery": "01/10/2025",
                "Last Day Delivery": "01/10/2025",
                PRICE_COLUMN: "52.18",
            },
            {
                "Trading day": "30/09/2025",
                "Product": "GMAES",
                "Place of delivery": "PVB",
                "Area": "ES",
                "First Day Delivery": "01/10/2025",
                "Last Day Delivery": "31/10/2025",
                PRICE_COLUMN: "48.90",
            },
        ])

        normalized, report = normalize_records(values, "2025-10-01", "2025-10-01")

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized.loc[0, "precio_eur_mwh"], 52.18)
        self.assertEqual(report["filtered_by_product"], 1)
        self.assertEqual(report["outside_window"], 0)

    def test_does_not_use_negotiation_date_for_window(self):
        values = pd.DataFrame([
            {
                "Trading day": "30/09/2025",
                "Product": "GDAES_D+1",
                "Place of delivery": "PVB",
                "Area": "ES",
                "First Day Delivery": "01/10/2025",
                "Last Day Delivery": "01/10/2025",
                PRICE_COLUMN: "52.18",
            }
        ])

        normalized, report = normalize_records(values, "2025-10-01", "2025-10-01")

        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["outside_window"], 0)

    def test_deduplicate_keeps_latest_trading_day_not_input_order(self):
        values = pd.DataFrame([
            {
                "fecha_negociacion": pd.Timestamp("2025-09-30"),
                "fecha_entrega": pd.Timestamp("2025-10-01"),
                "producto": "GDAES_D+1",
                "precio_eur_mwh": 52.0,
            },
            {
                "fecha_negociacion": pd.Timestamp("2025-09-29"),
                "fecha_entrega": pd.Timestamp("2025-10-01"),
                "producto": "GDAES_D+1",
                "precio_eur_mwh": 50.0,
            },
        ])

        deduplicated, count = deduplicate_records(values)

        self.assertEqual(count, 1)
        self.assertEqual(deduplicated.iloc[0]["precio_eur_mwh"], 52.0)


if __name__ == "__main__":
    unittest.main()
