from __future__ import annotations

from io import BytesIO
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st
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
        aemet = runpy.run_path(str(APP_DIR.parent / "notebooks" / "03_gold_aemet.py"))
        cls.temperature_source, _, _ = aemet["build_gold"](pd.DataFrame([
            {"fecha": "2026-01-01", "provincia": "MADRID", "localidad": "Madrid",
             "tmin": -2.0, "tmax": 12.0, "tmed": 5.0, "hora_tmin": "06:15", "hora_tmax": "14:30"},
            {"fecha": "2026-01-01", "provincia": "SEVILLA", "localidad": "Sevilla",
             "tmin": 4.0, "tmax": 18.0, "tmed": 11.0, "hora_tmin": "05:00", "hora_tmax": "15:45"},
            {"fecha": "2026-01-02", "provincia": "MADRID", "localidad": "Madrid",
             "tmin": 0.0, "tmax": None, "tmed": None, "hora_tmin": None, "hora_tmax": None},
        ]))

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.gold_dir = Path(directory.name) / "redata"
        self.temperature_dir = Path(directory.name) / "aemet"
        self.gold_dir.mkdir()
        self.temperature_dir.mkdir()
        for name, value in (("GOLD_DIR", self.gold_dir), ("TEMPERATURE_DIR", self.temperature_dir)):
            patcher = patch.object(data_loader, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.monthly = self.monthly_source.copy(deep=True)
        self.summary = self.summary_source.copy(deep=True)
        self.plan = self.plan_source.copy(deep=True)
        st.cache_data.clear()
        temperature_patch = patch.object(
            data_loader, "load_temperature_table", return_value=self.temperature_source.copy(deep=True),
        )
        self.temperature_loader = temperature_patch.start()
        self.addCleanup(temperature_patch.stop)

    def load_tables(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        tables = {
            data_loader.MONTHLY_FILENAME: self.monthly,
            data_loader.HOURLY_FILENAME: self.plan,
        }

        for filename, table in tables.items():
            table.to_parquet(self.gold_dir / filename, index=False)
        return data_loader.load_gold_tables()

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

    def test_missing_local_file_is_explicit(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "run_local.py"):
            data_loader.load_gold_tables()

    def test_app_reads_local_parquet_without_mocking_the_gold_loader(self) -> None:
        self.load_tables()
        app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.error)
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("PARQUET LOCAL", markup)
        self.assertNotIn("S3", markup)
        self.assertTrue(any(button.label == "Actualizar datos locales" for button in app.button))

    def test_app_explains_how_to_generate_missing_local_parquet(self) -> None:
        app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        self.assertEqual(list(app.exception), [])
        self.assertIn("run_local.py", app.error[0].value)
        self.assertFalse(app.radio)

    def test_corrupt_local_parquet_is_not_hidden(self) -> None:
        (self.gold_dir / data_loader.MONTHLY_FILENAME).write_text("not parquet", encoding="utf-8")
        with self.assertRaises(ValueError):
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

    def read_temperature(self, table: pd.DataFrame) -> pd.DataFrame:
        table.to_parquet(self.temperature_dir / data_loader.TEMPERATURE_FILENAME, index=False)
        return self.real_temperature_loader()

    real_temperature_loader = staticmethod(data_loader.load_temperature_table)

    def test_reads_national_temperature_gold_and_preserves_nulls(self) -> None:
        table = self.read_temperature(self.temperature_source)
        pd.testing.assert_frame_equal(table, self.temperature_source)
        self.assertEqual(table.loc[0, "tmed"], 8.0)
        self.assertEqual(table.loc[0, "provincia_tmin"], "MADRID")
        self.assertEqual(table.loc[0, "provincia_tmax"], "SEVILLA")
        self.assertTrue(pd.isna(table.loc[1, "tmax"]))
        self.assertTrue(pd.isna(table.loc[1, "hora_tmin"]))

    def test_empty_temperature_gold_is_readable_and_does_not_block_dashboard(self) -> None:
        aemet = runpy.run_path(str(APP_DIR.parent / "notebooks" / "03_gold_aemet.py"))
        silver = pd.DataFrame(columns=[
            "fecha", "provincia", "localidad", "tmin", "tmax", "tmed", "hora_tmin", "hora_tmax",
        ])
        empty, _, _ = aemet["build_gold"](silver)
        self.assertTrue(self.read_temperature(empty).empty)
        self.temperature_loader.side_effect = self.real_temperature_loader
        self.load_tables()
        app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        app.radio(key="view").set_value("Programación diaria").run()
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.error)
        self.assertTrue(any("No hay datos de temperatura disponibles" in item.value for item in app.caption))
        self.assertEqual(len(app.get("download_button")), 1)

    def test_rejects_invalid_temperature_data(self) -> None:
        for column, value in (
            ("fecha", None), ("fecha", "invalid"),
            ("tmin", float("inf")), ("tmed", "invalid"),
            ("hora_tmin", "24:00"), ("hora_tmax", "15:60"),
        ):
            with self.subTest(column=column, value=value):
                table = self.temperature_source.copy()
                table[column] = table[column].astype("string" if isinstance(value, str) else object)
                table.loc[0, column] = value
                with self.assertRaises(ValueError):
                    self.read_temperature(table)
        with self.assertRaisesRegex(ValueError, "duplicadas"):
            self.read_temperature(pd.concat([self.temperature_source] * 2, ignore_index=True))
        with self.assertRaisesRegex(ValueError, "faltan columnas"):
            self.read_temperature(self.temperature_source.drop(columns="tmed"))

    def test_temperature_panel_matches_date_and_handles_missing_measurements(self) -> None:
        tables = self.load_tables()
        app = self.run_app(tables)
        self.temperature_loader.assert_not_called()
        app.radio(key="view").set_value("Programación diaria").run()
        self.assertEqual(list(app.exception), [])
        markup = "\n".join(item.value for item in app.markdown)
        self.assertLess(markup.index("Coste del día"), markup.index("Temperatura diaria"))
        self.assertLess(markup.index("Temperatura diaria"), markup.index("Regla de decisión"))
        for text in ("-2,0 °C", "18,0 °C", "8,0 °C", "06:15", "15:45", "MADRID", "SEVILLA"):
            self.assertIn(text, markup)
        self.assertFalse(any("el día más reciente" in item.value for item in app.caption))
        app.button(key="schedule_day_2026-01-02").click().run()
        self.assertEqual(list(app.exception), [])
        markup = "\n".join(item.value for item in app.markdown)
        for text in ("0,0 °C", "Sin dato", "Hora no disponible"):
            self.assertIn(text, markup)
        self.assertNotIn("-2,0 °C", markup)
        self.assertEqual(self.temperature_loader.call_count, 1)
        app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-03-01").date()).run()
        app.button(key="schedule_day_2026-03-29").click().run()
        self.assertTrue(any(
            "2 enero 2026" in item.value and "el día más reciente" in item.value
            for item in app.caption
        ))
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("0,0 °C", markup)
        self.assertIn("Sin dato", markup)
        self.assertNotIn("-2,0 °C", markup)
        self.assertFalse(app.error)
        self.assertFalse(app.warning)
        self.assertEqual(list(app.exception), [])
        with patch.object(data_loader, "load_gold_tables", return_value=tables):
            next(button for button in app.button if button.label == "Actualizar datos locales").click().run()
        self.assertEqual(self.temperature_loader.call_count, 2)

    def test_temperature_fallback_uses_latest_prior_date_even_if_unsorted(self) -> None:
        future = self.temperature_source.iloc[[0]].copy()
        future["fecha"] = pd.Timestamp("2026-04-01").date()
        future["tmin"] = -99.0
        self.temperature_loader.return_value = pd.concat(
            [future, self.temperature_source.iloc[::-1]], ignore_index=True,
        )
        app = self.run_app(self.load_tables())
        app.radio(key="view").set_value("Programación diaria").run()
        app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-03-01").date()).run()
        app.button(key="schedule_day_2026-03-29").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any(
            "2 enero 2026" in item.value and "el día más reciente" in item.value
            for item in app.caption
        ))
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("0,0 °C", markup)
        self.assertNotIn("-99,0 °C", markup)
        self.assertEqual(len(app.get("download_button")), 1)

    def test_temperature_fallback_skips_selected_date_with_all_measurements_missing(self) -> None:
        missing = self.temperature_source.iloc[[0]].copy()
        missing["fecha"] = pd.Timestamp("2026-10-22").date()
        missing[["tmin", "tmax", "tmed"]] = None
        previous = self.temperature_source.iloc[[0]].copy()
        previous["fecha"] = pd.Timestamp("2026-10-19").date()
        previous[["tmin", "tmax", "tmed"]] = [-1.0, 20.0, 10.0]
        self.temperature_loader.return_value = pd.concat([missing, previous], ignore_index=True)
        app = self.run_app(self.load_tables())
        app.radio(key="view").set_value("Programación diaria").run()
        app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-10-01").date()).run()
        app.button(key="schedule_day_2026-10-25").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any(
            "19 octubre 2026" in item.value and "el día más reciente" in item.value
            for item in app.caption
        ))
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("-1,0 °C", markup)
        self.assertIn("20,0 °C", markup)
        self.assertIn("10,0 °C", markup)

    def test_temperature_without_prior_data_does_not_use_future_measurements(self) -> None:
        for table in (self.temperature_source, self.temperature_source.iloc[:0]):
            with self.subTest(empty=table.empty):
                st.cache_data.clear()
                self.temperature_loader.return_value = table.copy()
                app = self.run_app(self.load_tables())
                app.selectbox(key="selected_year").set_value(2025).run()
                app.radio(key="view").set_value("Programación diaria").run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any(
                    "No hay datos de temperatura disponibles" in item.value for item in app.caption
                ))
                self.assertNotIn("°C", "\n".join(item.value for item in app.markdown))
                self.assertFalse(app.error)
                self.assertFalse(app.warning)
                self.assertEqual(len(app.get("download_button")), 1)

    def test_temperature_local_error_does_not_block_energy_results(self) -> None:
        self.temperature_loader.side_effect = FileNotFoundError("No existe el Parquet AEMET local")
        app = self.run_app(self.load_tables())
        app.radio(key="view").set_value("Programación diaria").run()
        self.assertEqual(list(app.exception), [])
        self.assertIn("No existe el Parquet AEMET local", app.error[0].value)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertIn("Regla de decisión", "\n".join(item.value for item in app.markdown))

    def test_app_stops_on_loading_error(self) -> None:
        with patch.object(data_loader, "load_gold_tables", side_effect=ValueError("tablas incompatibles")):
            app = AppTest.from_file(str(APP_DIR / "streamlit_app.py")).run(timeout=20)
        self.assertEqual(list(app.exception), [])
        self.assertIn("tablas incompatibles", app.error[0].value)
        self.assertFalse(app.radio)


if __name__ == "__main__":
    unittest.main()
