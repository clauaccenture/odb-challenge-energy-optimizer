from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
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
import desaladora_data


class DesaladoraDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gold = runpy.run_path(str(APP_DIR.parent / "notebooks" / "03_gold_redata.py"))
        cls.gold = gold
        values = []
        for day in ("2026-10-25", "2026-12-24", "2026-12-26"):
            start = pd.Timestamp(day, tz="Europe/Madrid")
            end = pd.Timestamp(start.date() + pd.Timedelta(days=1), tz="Europe/Madrid")
            for hour in pd.date_range(start, end, freq="h", inclusive="left"):
                values.append({"datetime": hour.isoformat(), "value": 6 if hour.hour in range(9, 14) else 8})
        silver = json.dumps({
            "included": [{"attributes": {"title": "Precio mercado spot", "values": values}}],
        }).encode("utf-8")
        publisher = Mock()
        publisher.get_object.return_value = {"Body": BytesIO(silver)}
        execute = gold["ejecutar_desaladora"]
        with patch.dict(execute.__globals__, {"BUCKET": data_loader.S3_BUCKET}):
            with patch.object(desaladora_data.boto3, "client", return_value=publisher):
                execute(APP_DIR.parent / "config" / "config_desaladora.yaml", True)
        cls.published = {
            call.kwargs["Key"]: call.kwargs["Body"] for call in publisher.put_object.call_args_list
        }
        cls.metadata_key = json.loads(cls.published[f"{desaladora_data.PREFIX}/latest.json"])["metadata_key"]
        cls.metadata = json.loads(cls.published[cls.metadata_key])

    def setUp(self):
        st.cache_data.clear()
        self.objects = dict(self.published)
        self.client = Mock()
        self.client.get_object.side_effect = self.get_object
        client_patch = patch.object(desaladora_data.boto3, "client", return_value=self.client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def get_object(self, *, Bucket, Key):
        self.assertEqual(Bucket, data_loader.S3_BUCKET)
        return {"Body": BytesIO(self.objects[Key])}

    def load(self):
        return desaladora_data.load_desaladora_tables()

    def edit_table(self, filename, mutate):
        metadata = deepcopy(self.metadata)
        key = metadata["outputs_s3"][filename]
        table = pd.read_parquet(BytesIO(self.objects[key]))
        mutate(table)
        content = BytesIO()
        table.to_parquet(content, index=False)
        self.objects[key] = content.getvalue()
        metadata["outputs_sha256"][filename] = sha256(content.getvalue()).hexdigest()
        self.objects[self.metadata_key] = json.dumps(metadata).encode()

    def test_reads_one_complete_run_and_preserves_gaps_and_dst(self):
        metadata, monthly, summary, plan = self.load()
        self.assertEqual(metadata["dias_optimos"], 3)
        self.assertEqual(monthly["month"].tolist(), ["2026-10", "2026-11", "2026-12"])
        self.assertTrue(pd.isna(monthly.loc[monthly["month"] == "2026-11", "saving_eur"].iloc[0]))
        gap = summary.loc[summary["fecha_local"] == pd.Timestamp("2026-12-25").date()].iloc[0]
        self.assertEqual(gap["estado_optimizacion"], "sin_datos")
        self.assertTrue(pd.isna(gap["ahorro_eur"]))
        autumn = plan[plan["fecha_local"] == pd.Timestamp("2026-10-25").date()]
        self.assertEqual(len(autumn), 25)
        self.assertEqual(len(set(autumn["datetime_local"].map(lambda t: t.isoformat()))), 25)
        keys = [call.kwargs["Key"] for call in self.client.get_object.call_args_list]
        self.assertEqual(keys.count(f"{desaladora_data.PREFIX}/latest.json"), 1)
        self.assertEqual(len(keys), 5)
        self.assertTrue(all("/runs/" in key for key in keys[1:]))
        valid = summary[summary["estado_optimizacion"] == "optimo"]
        self.assertAlmostEqual(valid["ahorro_eur"].sum(), monthly["saving_eur"].sum())

    def test_rejects_mixed_run_and_corrupt_file(self):
        for corruption in ("hash", "run"):
            with self.subTest(corruption=corruption):
                metadata = deepcopy(self.metadata)
                name = "programacion_horaria.parquet"
                if corruption == "hash":
                    metadata["outputs_sha256"][name] = "0" * 64
                else:
                    metadata["outputs_s3"][name] = "outputs/another-run.parquet"
                self.objects[self.metadata_key] = json.dumps(metadata).encode()
                with self.assertRaisesRegex(ValueError, "SHA256|misma ejecucion"):
                    self.load()

    def test_rejects_incoherent_prices_costs_and_monthly_results_even_with_valid_hash(self):
        cases = [
            ("programacion_horaria.parquet", "precio_indexado_eur_mwh", "desglose"),
            ("programacion_horaria.parquet", "coste_energia_flexible_baseline_eur", "coste de energia"),
            ("resumen_mensual.parquet", "ahorro_energia_eur", "resumen mensual"),
        ]
        for filename, column, message in cases:
            with self.subTest(column=column):
                self.objects = dict(self.published)
                self.edit_table(filename, lambda table: table.__setitem__(column, table[column] + 1))
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_crlf_yaml_snapshot_hash_is_verified_without_newline_normalization(self):
        metadata = deepcopy(self.metadata)
        metadata["config_yaml"] = metadata["config_yaml"].replace("\r\n", "\n").replace("\n", "\r\n")
        metadata["config_sha256"] = sha256(metadata["config_yaml"].encode()).hexdigest()
        self.objects[self.metadata_key] = json.dumps(metadata).encode()
        self.load()
        metadata["config_sha256"] = "0" * 64
        self.objects[self.metadata_key] = json.dumps(metadata).encode()
        with self.assertRaisesRegex(ValueError, "YAML no coincide"):
            self.load()

    def app(self, mode="som", view="Resumen ejecutivo"):
        app = AppTest.from_file(str(APP_DIR / "streamlit_app.py"), default_timeout=20)
        app.session_state["cost_mode"] = mode
        app.session_state["view"] = view
        app.run()
        self.assertEqual(list(app.exception), [])
        return app

    def test_all_four_views_use_indexed_run_without_legacy_and_refresh_s3(self):
        with patch.object(data_loader, "load_gold_tables", side_effect=AssertionError("No legacy fallback")):
            with patch.object(data_loader, "load_temperature_table", return_value=pd.DataFrame(columns=["fecha", "tmin", "tmax", "tmed"])):
                app = self.app()
                summary_key = self.metadata["outputs_s3"]["resumen_diario.parquet"]
                saving = pd.read_parquet(BytesIO(self.objects[summary_key]))["ahorro_energia_eur"].sum()
                formatted = f"{saving:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                self.assertIn(formatted + " €", "\n".join(item.value for item in app.markdown))
                self.assertTrue(any("precio indexado completo" in item.value for item in app.warning))
                app.selectbox(key="summary_month").set_value("2026-11").run()
                markup = "\n".join(item.value for item in app.markdown)
                self.assertIn("Sin datos", markup)
                self.assertNotIn("nan €", markup)
                app.radio(key="view").set_value("Programación diaria").run()
                self.assertEqual(list(app.exception), [])
                hourly = app.dataframe[0].value
                self.assertEqual(len(hourly), 25)
                repeated = hourly[hourly["Intervalo local"].str.startswith("02:00")]
                self.assertEqual(len(repeated), 2)
                self.assertTrue(repeated["Intervalo local"].str.contains("CEST").any())
                self.assertTrue(repeated["Intervalo local"].str.contains("CET").any())
                app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-12-01").date()).run()
                self.assertTrue(app.button(key="schedule_day_2026-12-25").disabled)
                app.button(key="schedule_day_2026-12-24").click().run()
                self.assertEqual(len(app.dataframe[0].value), 24)
                self.assertTrue(app.dataframe[0].value["Indexado EUR/MWh"].gt(app.dataframe[0].value["Spot EUR/MWh"]).all())
                hourly = app.dataframe[0].value
                chosen = hourly[hourly["Flexible S1 MWh"] > 0]
                self.assertTrue(chosen["Periodo"].eq("P6").all())
                self.assertGreater(chosen["Spot EUR/MWh"].min(), hourly["Spot EUR/MWh"].min())
                costs = app.dataframe[1].value
                self.assertAlmostEqual(costs["Ahorro EUR"].sum(), float(app.metric[-1].value.replace(" €", "").replace(".", "").replace(",", ".")), places=2)
                app.radio(key="view").set_value("Evolución del ahorro").run()
                self.assertEqual(list(app.exception), [])
                mean_saving = saving / 2
                formatted_mean = f"{mean_saving:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                self.assertIn(formatted_mean + " €", "\n".join(item.value for item in app.markdown))
                app.radio(key="view").set_value("Caso desaladora").run()
                self.assertEqual(list(app.exception), [])
                parameters = app.dataframe[1].value
                self.assertIn("Supuesto / aproximación", parameters["Clasificación"].tolist())
                self.assertIn("Documentado", parameters["Clasificación"].tolist())
                self.assertTrue(app.segmented_control(key="cost_mode").disabled)
                self.assertEqual(self.client.get_object.call_count, 5)
                next(button for button in app.button if button.label == "Actualizar datos de S3").click().run()
                self.assertEqual(list(app.exception), [])
                self.assertEqual(self.client.get_object.call_count, 10)

    def test_case_screen_loads_without_legacy_even_when_legacy_mode_selected(self):
        with patch.object(data_loader, "load_gold_tables", side_effect=AssertionError("Legacy must not load")):
            app = self.app(mode="tariff", view="Caso desaladora")
        parameters = app.dataframe[1].value.set_index("Parámetro")
        self.assertEqual(parameters.loc["contrato.f_eur_mwh", "Clasificación"], "Supuesto / aproximación")

    def test_can_switch_between_original_and_indexed_results(self):
        plan_key = self.metadata["outputs_s3"]["programacion_horaria.parquet"]
        silver = pd.read_parquet(BytesIO(self.objects[plan_key]))
        plan, daily = self.gold["build_gold"](silver)
        monthly = self.gold["build_mensual"](plan, daily)
        sources = {data_loader.MONTHLY_FILENAME: monthly, data_loader.HOURLY_FILENAME: plan}
        with patch.object(data_loader, "read_table", side_effect=lambda name, required: sources[name][required].copy()):
            legacy = data_loader.load_gold_tables()
        with patch.object(data_loader, "load_gold_tables", return_value=legacy) as legacy_loader:
            app = self.app(mode="market")
            self.assertEqual(self.client.get_object.call_count, 0)
            app.segmented_control(key="cost_mode").set_value("som").run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(self.client.get_object.call_count, 5)
            self.assertTrue(any("precio indexado completo" in item.value for item in app.warning))
            app.segmented_control(key="cost_mode").set_value("tariff").run()
            self.assertEqual(list(app.exception), [])
            self.assertFalse(any("precio indexado completo" in item.value for item in app.warning))
            legacy_loader.assert_called_once()

    def test_missing_run_shows_error_no_fallback_and_keeps_refresh_available(self):
        self.client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "latest not published"}}, "GetObject",
        )
        with patch.object(data_loader, "load_gold_tables", side_effect=AssertionError("No fallback")):
            app = self.app()
        self.assertTrue(app.error)
        self.assertIn("NoSuchKey", app.error[0].value)
        self.assertTrue(any("--config" in item.value for item in app.code))
        self.assertTrue(any(button.label == "Actualizar datos de S3" for button in app.button))
        self.assertFalse(app.dataframe)


if __name__ == "__main__":
    unittest.main()
