from __future__ import annotations

from io import BytesIO
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import streamlit as st
from botocore.exceptions import ClientError
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import data_loader


class GoldDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        gold = runpy.run_path(str(APP_DIR.parent / "notebooks" / "03_gold_redata.py"))
        days = []
        for value in ("2025-12-31", "2026-01-01", "2026-01-02", "2026-03-29", "2026-10-25"):
            start = pd.Timestamp(value, tz="Europe/Madrid")
            end = pd.Timestamp(start.date() + pd.Timedelta(days=1), tz="Europe/Madrid")
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            days.append(pd.DataFrame({
                "datetime_utc": hours.tz_convert("UTC"),
                "datetime_local": hours,
                "fecha_local": hours.date,
                "precio_eur_mwh": 0.0 if value == "2026-01-02" else list(range(1, len(hours) + 1)),
            }))
        partial = days[1].iloc[:5].copy()
        partial["datetime_local"] += pd.Timedelta(days=2)
        partial["datetime_utc"] += pd.Timedelta(days=2)
        partial["fecha_local"] = partial["datetime_local"].dt.date
        days.append(partial)
        plan, cls.summary_source = gold["build_gold"](pd.concat(days, ignore_index=True))
        cls.plan_source = plan
        cls.monthly_source = gold["build_mensual"](plan, cls.summary_source)

    def setUp(self) -> None:
        self.monthly = self.monthly_source.copy(deep=True)
        self.summary = self.summary_source.copy(deep=True)
        self.plan = self.plan_source.copy(deep=True)
        st.cache_data.clear()

    def load_tables(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        tables = {
            data_loader.MONTHLY_FILENAME: self.monthly,
            data_loader.HOURLY_FILENAME: self.plan,
        }

        def get_object(*, Bucket: str, Key: str) -> dict[str, BytesIO]:
            self.assertEqual(Bucket, data_loader.S3_BUCKET)
            self.assertTrue(Key.startswith("outputs/redata/"))
            buffer = BytesIO()
            tables[Key.rsplit("/", 1)[-1]].to_parquet(buffer, index=False)
            buffer.seek(0)
            return {"Body": buffer}

        client = Mock()
        client.get_object.side_effect = get_object
        with patch.object(data_loader.boto3, "client", return_value=client) as factory:
            result = data_loader.load_gold_tables()
        factory.assert_has_calls([
            unittest.mock.call("s3", region_name="eu-north-1"),
            unittest.mock.call("s3", region_name="eu-north-1"),
        ])
        self.assertEqual(client.get_object.call_count, 2)
        return result

    def run_app(self, tables: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> AppTest:
        with patch.object(data_loader, "load_gold_tables", return_value=tables):
            app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        self.assertEqual(list(app.exception), [])
        return app

    def test_reads_real_gold_output_and_preserves_indicators(self) -> None:
        monthly, summary, plan = self.load_tables()
        self.assertEqual(monthly["month"].tolist(), ["2025-12", "2026-01", "2026-03", "2026-10"])
        self.assertEqual(monthly["days"].tolist(), [1, 2, 1, 1])
        self.assertEqual(monthly["saving_eur"].tolist(), self.monthly["ahorro_estimado_mensual_eur"].tolist())
        self.assertEqual(monthly["ahorro_estimado_anual_eur"].nunique(), 1)
        self.assertEqual(summary["horas_del_dia"].tolist(), [24, 24, 24, 23, 25])
        zero = summary.loc[summary["fecha_local"] == pd.Timestamp("2026-01-02").date()].iloc[0]
        self.assertTrue(pd.isna(zero["ahorro_pct"]))
        self.assertNotIn("datetime_local", monthly)
        self.assertEqual(plan["hora_local"].tolist(), self.plan["hora_local"].tolist())
        valid_source = self.summary[self.summary["estado_optimizacion"] == "optimo"]
        for column in ("ahorro_eur", "coste_baseline_total_eur", "coste_optimizado_total_eur"):
            pd.testing.assert_series_equal(
                summary[column], valid_source[column].reset_index(drop=True),
                check_names=False, atol=1e-5, rtol=0,
            )

    def test_rejects_old_hourly_schema(self) -> None:
        self.monthly = pd.DataFrame({"datetime_local": ["2026-01-01"]})
        with self.assertRaisesRegex(ValueError, "faltan columnas"):
            self.load_tables()

    def test_rejects_inconsistent_monthly_savings(self) -> None:
        self.monthly.loc[0, "ahorro_estimado_mensual_eur"] += 1
        with self.assertRaisesRegex(ValueError, "ahorro mensual"):
            self.load_tables()

    def test_rejects_missing_month(self) -> None:
        self.monthly = self.monthly.iloc[1:].copy()
        with self.assertRaisesRegex(ValueError, "meses de Gold"):
            self.load_tables()

    def test_rejects_duplicate_or_invalid_month(self) -> None:
        for month in ("2025-12", "2026-13", None):
            with self.subTest(month=month):
                self.monthly = self.monthly_source.copy()
                self.monthly.loc[1, "mes"] = month
                with self.assertRaises(ValueError):
                    self.load_tables()

    def test_rejects_bad_annual_indicators(self) -> None:
        for column in ("ahorro_estimado_anual_eur", "precio_spot_medio_anual_eur_mwh"):
            with self.subTest(column=column):
                self.monthly = self.monthly_source.copy()
                self.monthly.loc[0, column] += 1
                with self.assertRaisesRegex(ValueError, "mismo valor"):
                    self.load_tables()
        self.monthly = self.monthly_source.copy()
        self.monthly["ahorro_estimado_anual_eur"] += 1
        with self.assertRaisesRegex(ValueError, "ahorro anual"):
            self.load_tables()

    def test_rejects_nonfinite_indicators(self) -> None:
        self.monthly.loc[0, "ahorro_estimado_mensual_eur"] = float("inf")
        with self.assertRaisesRegex(ValueError, "no finitos"):
            self.load_tables()

    def test_rejects_inconsistent_daily_results(self) -> None:
        for column, value in (
            ("coste_optimizado_eur", -1.0),
            ("consumo_optimizado_mwh", 8.0),
            ("consumo_baseline_mwh", 1.0),
            ("hora_local", 23),
            ("hora_local", 0.5),
            ("hora_local", float("nan")),
            ("fecha_local", None),
        ):
            with self.subTest(column=column):
                self.plan = self.plan_source.copy()
                if column == "hora_local":
                    self.plan[column] = self.plan[column].astype(float)
                self.plan.loc[0, column] = value
                with self.assertRaises(ValueError):
                    self.load_tables()

    def test_rejects_missing_or_reordered_hours(self) -> None:
        for plan in (
            self.plan_source.iloc[1:],
            self.plan_source.iloc[[1, 0, *range(2, len(self.plan_source))]],
            pd.concat([self.plan_source.iloc[[0]], self.plan_source], ignore_index=True),
        ):
            with self.subTest(rows=len(plan)):
                self.plan = plan.copy()
                with self.assertRaisesRegex(ValueError, "horas incompletas"):
                    self.load_tables()

    def test_dst_timestamps_keep_both_autumn_hours(self) -> None:
        _, _, plan = self.load_tables()
        autumn = plan[plan["fecha_local"] == pd.Timestamp("2026-10-25").date()]
        spring = plan[plan["fecha_local"] == pd.Timestamp("2026-03-29").date()]
        repeated = autumn[autumn["hora_local"] == 2]["datetime_local"]
        self.assertEqual(repeated.dt.strftime("%H:%M %z").tolist(), ["02:00 +0200", "02:00 +0100"])
        self.assertEqual(len(spring), 23)
        self.assertNotIn(2, spring["hora_local"].tolist())
        self.assertFalse(plan["datetime_local"].duplicated().any())

    def test_s3_error_is_not_replaced_with_local_data(self) -> None:
        client = Mock()
        client.get_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        with patch.object(data_loader.boto3, "client", return_value=client):
            with self.assertRaises(ClientError):
                data_loader.load_gold_tables()

    def test_app_keeps_views_and_restores_hourly_table_and_download(self) -> None:
        tables = self.load_tables()
        app = self.run_app(tables)
        self.assertEqual(app.selectbox(key="selected_year").value, 2026)
        markup = "\n".join(item.value for item in app.markdown)
        year_saving = tables[0].loc[tables[0]["month"].str.startswith("2026"), "saving_eur"].sum()
        formatted = f"{year_saving:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        self.assertIn(formatted + " €", markup)
        self.assertEqual(app.selectbox(key="summary_month").options, ["Enero 2026", "Marzo 2026", "Octubre 2026"])
        app.radio(key="view").set_value("Programación diaria").run()
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.warning)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertIn("Precio EUR/MWh", "\n".join(item.value for item in app.markdown))
        self.assertIn("Coste del día", "\n".join(item.value for item in app.markdown))
        app.button(key="schedule_day_2026-01-02").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertIn("No aplica", "\n".join(item.value for item in app.markdown))
        app.radio(key="view").set_value("Evolución del ahorro").run()
        self.assertEqual(list(app.exception), [])
        app.selectbox(key="analysis_period").set_value("T2 · Abril–junio").run()
        self.assertTrue(any("No hay resultados" in item.value for item in app.info))
        app.selectbox(key="selected_year").set_value(2025).run()
        self.assertEqual(list(app.exception), [])
        app.selectbox(key="analysis_period").set_value("Todo el período disponible").run()
        self.assertIn("Diciembre 2025", "\n".join(item.value for item in app.markdown))

    def test_single_year_uses_gold_total_once_and_disables_invalid_dates(self) -> None:
        self.summary = self.summary[self.summary["fecha_local"].map(lambda value: value.year == 2026)].copy()
        self.plan = self.plan[self.plan["fecha_local"].map(lambda value: value.year == 2026)].copy()
        self.monthly = self.monthly[self.monthly["mes"].str.startswith("2026")].copy()
        self.monthly["ahorro_estimado_anual_eur"] = self.monthly["ahorro_estimado_mensual_eur"].sum()
        self.monthly["precio_spot_medio_anual_eur_mwh"] = round(self.plan["precio_eur_mwh"].mean(), 4)
        app = self.run_app(self.load_tables())
        self.assertEqual(list(app.exception), [])
        total = self.monthly["ahorro_estimado_anual_eur"].iloc[0]
        formatted = f"{total:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        self.assertIn(formatted + " €", "\n".join(item.value for item in app.markdown))
        self.assertFalse(app.button(key="schedule_day_2026-01-01").disabled)
        self.assertTrue(app.button(key="schedule_day_2026-01-03").disabled)
        self.assertTrue(app.button(key="schedule_day_2026-01-04").disabled)
        app.radio(key="view").set_value("Evolución del ahorro").run()
        self.assertEqual(list(app.exception), [])
        app.selectbox(key="analysis_period").set_value("T1 · Enero–marzo").run()
        self.assertEqual(list(app.exception), [])
        self.assertIn("Media por mes con datos", "\n".join(item.value for item in app.markdown))

    def test_app_autumn_table_and_csv_have_25_distinct_intervals(self) -> None:
        tables = self.load_tables()
        app = self.run_app(tables)
        app.radio(key="view").set_value("Programación diaria").run()
        app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-10-01").date()).run()
        app.button(key="schedule_day_2026-10-25").click().run()
        self.assertEqual(list(app.exception), [])
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("25 intervalos horarios", markup)
        self.assertIn("02:00 CEST", markup)
        self.assertIn("02:00 CET", markup)
        schedule = tables[2][tables[2]["fecha_local"] == pd.Timestamp("2026-10-25").date()]
        exported = pd.read_csv(BytesIO(schedule.to_csv(index=False).encode("utf-8")))
        self.assertEqual(len(exported), 25)
        self.assertEqual(exported["datetime_local"].nunique(), 25)

    def test_rejects_inconsistent_mean_prices(self) -> None:
        for column in ("precio_spot_medio_mensual_eur_mwh", "precio_spot_medio_anual_eur_mwh"):
            with self.subTest(column=column):
                self.monthly = self.monthly_source.copy()
                self.monthly[column] += 1
                with self.assertRaisesRegex(ValueError, "precio medio"):
                    self.load_tables()

    def test_app_stops_on_loading_error(self) -> None:
        with patch.object(data_loader, "load_gold_tables", side_effect=ValueError("tablas incompatibles")):
            app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        self.assertEqual(list(app.exception), [])
        self.assertIn("tablas incompatibles", app.error[0].value)
        self.assertFalse(app.radio)


if __name__ == "__main__":
    unittest.main()
