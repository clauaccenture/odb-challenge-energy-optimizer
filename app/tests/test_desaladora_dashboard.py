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
            with patch.object(data_loader, "load_temperature_table", return_value=pd.DataFrame(columns=["fecha", "tmin", "tmax", "tmed"])) as temperature_loader:
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
                chosen = app.dataframe[0].value
                self.assertEqual(len(chosen), 5)
                self.assertEqual(chosen["Energía a mover (MWh)"].sort_values().tolist(), [2, 7, 7, 7, 7])
                self.assertEqual(list(chosen.columns), ["Hora elegida", "Energía a mover (MWh)"])
                self.assertEqual(len(app.dataframe), 1)
                temperature_loader.assert_not_called()
                app.session_state["som_price_details"] = True
                app.run()
                self.assertEqual(len(app.dataframe), 2)
                app.selectbox(key="schedule_month").set_value(pd.Timestamp("2026-12-01").date()).run()
                self.assertTrue(app.button(key="schedule_day_2026-12-25").disabled)
                app.button(key="schedule_day_2026-12-24").click().run()
                self.assertEqual(app.dataframe[0].value["Energía a mover (MWh)"].sum(), 30)
                costs = app.dataframe[1].value
                self.assertAlmostEqual(costs["Ahorro EUR"].sum(), float(app.metric[-1].value.replace(" €", "").replace(".", "").replace(",", ".")), places=2)
                app.session_state["som_temperature_details"] = True
                app.run()
                temperature_loader.assert_called_once()
                self.assertEqual(list(app.exception), [])
                app.radio(key="view").set_value("Evolución del ahorro").run()
                self.assertEqual(list(app.exception), [])
                mean_saving = saving / 2
                formatted_mean = f"{mean_saving:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                self.assertIn(formatted_mean + " €", "\n".join(item.value for item in app.markdown))
                app.radio(key="view").set_value("Caso desaladora").run()
                self.assertEqual(list(app.exception), [])
                legend = app.table[0].value
                self.assertEqual(set(legend["Símbolo"]), {
                    "PH", "PHM", "Pc", "Sc", "Dsv", "GdO", "POsOm", "Perd", "FE", "F", "PTD", "CA", "1,015",
                })
                self.assertEqual(len(app.dataframe), 0)
                self.assertFalse(any(item.value.startswith("SHA256 Silver:") for item in app.caption))
                app.session_state["som_case_details"] = True
                app.run()
                self.assertEqual(list(app.dataframe[0].value.columns), ["Fecha", "Resultado"])
                self.assertIn("Sin precios disponibles", app.dataframe[0].value["Resultado"].tolist())
                self.assertEqual(len(app.dataframe), 2)
                self.assertFalse(app.code)
                self.assertFalse(app.json)
                self.assertFalse(app.get("download_button"))
                self.assertFalse(any("SHA256" in item.value or "s3://" in item.value for item in app.caption))
                self.assertTrue(app.segmented_control(key="cost_mode").disabled)
                self.assertEqual(self.client.get_object.call_count, 5)
                next(button for button in app.button if button.label == "Actualizar datos de S3").click().run()
                self.assertEqual(list(app.exception), [])
                self.assertEqual(self.client.get_object.call_count, 10)

    def test_case_screen_loads_without_legacy_even_when_legacy_mode_selected(self):
        with patch.object(data_loader, "load_gold_tables", side_effect=AssertionError("Legacy must not load")):
            app = self.app(mode="tariff", view="Caso desaladora")
        legend = app.table[0].value.set_index("Símbolo")
        self.assertIn("Supuesto", legend.loc["F", "Base del dato"])
        self.assertIn("Publicado", legend.loc["1,015", "Base del dato"])
        markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("Referencia del TFM", [item.value for item in app.subheader])
        self.assertIn("66", markup)

    def test_daily_csv_and_cost_card_only_include_flexible_load_with_matching_savings(self):
        source = pd.read_parquet(BytesIO(self.objects[self.metadata["outputs_s3"]["programacion_horaria.parquet"]]))
        with patch.object(st, "download_button", wraps=st.download_button) as downloads:
            app = self.app(view="Programación diaria")
            for day, expected_hours in (("2026-10-25", 25), ("2026-12-24", 24)):
                with self.subTest(day=day):
                    app.session_state["selected_date"] = pd.Timestamp(day).date()
                    app.run()
                    self.assertEqual(list(app.exception), [])
                    exported = pd.read_csv(BytesIO(downloads.call_args.args[1]))
                    self.assertEqual(list(exported.columns), [
                        "Hora local", "Precio EUR/MWh", "Carga S0 MWh", "Carga S1 MWh",
                        "Coste S0 EUR", "Coste S1 EUR", "Ahorro EUR",
                    ])
                    self.assertEqual(len(exported), expected_hours)
                    self.assertEqual(pd.to_datetime(exported["Hora local"], utc=True).nunique(), expected_hours)
                    self.assertAlmostEqual(exported["Carga S0 MWh"].sum(), 30)
                    self.assertAlmostEqual(exported["Carga S1 MWh"].sum(), 30)
                    self.assertEqual(exported.loc[exported["Carga S1 MWh"] > 0, "Carga S1 MWh"].sort_values().tolist(), [2, 7, 7, 7, 7])
                    daily_source = source[source["fecha_local"] == pd.Timestamp(day).date()]
                    self.assertAlmostEqual(exported["Coste S0 EUR"].sum(), daily_source["coste_energia_flexible_baseline_eur"].sum())
                    self.assertAlmostEqual(exported["Coste S1 EUR"].sum(), daily_source["coste_energia_flexible_optimizado_eur"].sum())
                    self.assertAlmostEqual(exported["Ahorro EUR"].sum(), exported["Coste S0 EUR"].sum() - exported["Coste S1 EUR"].sum())
                    metrics = {metric.label: float(metric.value.replace(" €", "").replace(".", "").replace(",", ".")) for metric in app.metric}
                    self.assertEqual(set(metrics), {"Coste S0 · antes", "Coste S1 · después", "Ahorro del día"})
                    for metric, column in [
                        ("Coste S0 · antes", "Coste S0 EUR"), ("Coste S1 · después", "Coste S1 EUR"), ("Ahorro del día", "Ahorro EUR"),
                    ]:
                        self.assertAlmostEqual(metrics[metric], exported[column].sum(), places=2)
                    self.assertTrue(any("Coste del día" == item.value for item in app.subheader))
                    percentage = (exported["Ahorro EUR"].sum() / exported["Coste S0 EUR"].sum()) * 100
                    formatted_percentage = f"{percentage:.1f}".replace(".", ",") + " %"
                    self.assertTrue(any(formatted_percentage + " sobre el coste S0." == item.value for item in app.caption))
                    self.assertAlmostEqual(app.dataframe[0].value["Energía a mover (MWh)"].sum(), 30)
                    self.assertFalse(any("planta" in metric.label.lower() for metric in app.metric))

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
        self.assertFalse(app.code)
        self.assertTrue(any("Solicita su actualización" in item.value for item in app.caption))
        self.assertTrue(any(button.label == "Actualizar datos de S3" for button in app.button))
        self.assertFalse(app.dataframe)


if __name__ == "__main__":
    unittest.main()
