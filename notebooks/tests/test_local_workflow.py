import importlib.util
from contextlib import ExitStack
from datetime import date
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_module(ROOT / "run_local.py")


class LocalWorkflowTests(unittest.TestCase):
    def test_dashboard_only_needs_no_key_and_never_runs_pipeline(self):
        with patch("sys.argv", ["run_local", "--dashboard-only"]), \
                patch.object(runner, "load_dotenv"), patch.dict(os.environ, {}, clear=True), \
                patch.object(runner, "run_script") as pipeline, \
                patch.object(runner.subprocess, "run") as process:
            process.return_value.returncode = 0
            with self.assertRaises(SystemExit) as result:
                runner.main()
        self.assertEqual(result.exception.code, 0)
        pipeline.assert_not_called()
        self.assertEqual(process.call_count, 1)
        self.assertIn("streamlit", process.call_args.args[0])
        command = process.call_args.args[0]
        self.assertEqual(command[command.index("--global.developmentMode") + 1], "false")

    def test_dashboard_only_rejects_conflicting_pipeline_flags(self):
        for flag in ("--skip-download", "--prepare-only"):
            with self.subTest(flag=flag), patch("sys.argv", ["run_local", "--dashboard-only", flag]), \
                    patch.object(runner.subprocess, "run") as process:
                with self.assertRaises(SystemExit) as result:
                    runner.main()
                self.assertEqual(result.exception.code, 2)
                process.assert_not_called()

    def test_packaged_runner_dispatches_scripts_without_starting_itself_recursively(self):
        with patch.object(runner, "FROZEN", True), \
                patch.object(runner.sys, "executable", str(ROOT / "EnergyOptimizer.exe")), \
                patch.object(runner.subprocess, "run") as process:
            runner.run_script("03_gold_redata.py", "--no-s3")
        self.assertEqual(process.call_args.args[0], [
            str(ROOT / "EnergyOptimizer.exe"), "--_run-script", "03_gold_redata.py", "--no-s3",
        ])

    def test_packaged_dispatch_only_accepts_known_pipeline_scripts(self):
        with patch.object(runner, "FROZEN", True), patch.object(runner, "load_dotenv"), \
                patch("sys.argv", ["EnergyOptimizer.exe", "--_run-script", "..\\unknown.py"]), \
                patch.object(runner.runpy, "run_path") as execute:
            with self.assertRaisesRegex(SystemExit, "no permitido"):
                runner.dispatch_packaged_command()
            execute.assert_not_called()

    def test_packaged_dispatch_loads_external_env_and_preserves_script_arguments(self):
        with patch.object(runner, "FROZEN", True), patch.object(runner, "load_dotenv") as dotenv, \
                patch("sys.argv", ["EnergyOptimizer.exe", "--_run-script", "01_ingesta_aemet.py", "--help"]), \
                patch.object(runner.runpy, "run_path") as execute:
            with self.assertRaises(SystemExit) as result:
                runner.dispatch_packaged_command()
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(runner.sys.argv, [str(ROOT / "notebooks" / "01_ingesta_aemet.py"), "--help"])
        dotenv.assert_called_once_with(runner.HOME / ".env")
        execute.assert_called_once_with(str(ROOT / "notebooks" / "01_ingesta_aemet.py"), run_name="__main__")

    def test_packaged_data_paths_are_next_to_executable_not_internal_code(self):
        portable = ROOT / "portable-test"
        with patch.object(runner.sys, "frozen", True, create=True), \
                patch.object(runner.sys, "executable", str(portable / "EnergyOptimizer.exe")):
            for name in runner.PIPELINE_SCRIPTS:
                module = load_module(ROOT / "notebooks" / name)
                path = module.RAW_DIR if name.startswith("01") else module.OUT_DIR
                self.assertTrue(path.is_relative_to(portable / "data"))
            loader = load_module(ROOT / "app" / "data_loader.py")
            self.assertEqual(loader.GOLD_DIR, portable / "data" / "outputs" / "redata")

    def test_packaged_runner_starts_embedded_streamlit_and_uses_external_working_directory(self):
        with patch.object(runner, "FROZEN", True), \
                patch("sys.argv", ["EnergyOptimizer.exe", "--skip-download"]), \
                patch.object(runner, "run_script"), patch.object(runner, "load_dotenv"), \
                patch.object(runner.subprocess, "run") as process:
            process.return_value.returncode = 0
            with self.assertRaises(SystemExit) as result:
                runner.main()
        self.assertEqual(result.exception.code, 0)
        command = process.call_args.args[0]
        self.assertEqual(command[1:3], ["--_streamlit", "run"])
        self.assertNotIn("-m", command)
        self.assertEqual(process.call_args.kwargs["cwd"], runner.HOME)

    def test_runner_reaches_streamlit_when_first_aemet_download_has_no_data(self):
        names = (
            "01_ingesta_redata", "01_ingesta_aemet", "02_calidad_redata",
            "02_calidad_aemet", "03_gold_redata", "03_gold_aemet",
        )
        modules = {name: load_module(ROOT / "notebooks" / f"{name}.py") for name in names}
        start = pd.Timestamp("2026-10-29", tz="Europe/Madrid")
        quarters = pd.date_range(start, start + pd.DateOffset(days=1), freq="15min", inclusive="left")
        prices = {"included": [{"attributes": {
            "title": "Precio mercado spot",
            "values": [{"datetime": timestamp.isoformat(), "value": 20.0} for timestamp in quarters],
        }}]}

        def execute(command, **kwargs):
            if "-m" not in command:
                module = modules[Path(command[2]).stem]
                with patch("sys.argv", command[2:]):
                    module.main()
            return subprocess.CompletedProcess(command, 0)

        with TemporaryDirectory() as directory, ExitStack() as stack:
            data = Path(directory)
            stack.enter_context(patch("sys.stdout", new_callable=StringIO))
            stack.enter_context(patch.object(runner, "load_dotenv"))
            stack.enter_context(patch.dict(os.environ, {"AEMET_API_KEY": "test-key"}))
            stack.enter_context(patch("boto3.client", side_effect=AssertionError("AWS must not be used")))
            stack.enter_context(patch.object(modules["01_ingesta_redata"], "fetch", return_value=prices))
            stack.enter_context(patch.object(modules["01_ingesta_redata"].time, "sleep"))
            stack.enter_context(patch.object(
                modules["01_ingesta_aemet"], "fetch",
                side_effect=modules["01_ingesta_aemet"].NoDataAvailable("Sin datos publicados"),
            ))
            for name, module in modules.items():
                source = name.rsplit("_", 1)[-1]
                for attribute, path in (
                    ("RAW_DIR", data / "raw" / source),
                    ("OUT_DIR", data / ("outputs" if name.startswith("03") else "processed") / source),
                    ("SILVER", data / "processed" / source /
                     ("precios_horarios.json" if source == "redata" else "aemet_diario.json")),
                ):
                    if hasattr(module, attribute):
                        stack.enter_context(patch.object(module, attribute, path))
            with patch("sys.argv", ["run_local", "--start", "2026-10-29", "--end", "2026-10-29"]), \
                    patch.object(runner.subprocess, "run", side_effect=execute) as process:
                with self.assertRaises(SystemExit) as result:
                    runner.main()
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(process.call_count, 7)
            self.assertIn("streamlit", process.call_args_list[-1].args[0])
            self.assertEqual(len(pd.read_parquet(
                data / "outputs" / "redata" / "gold_programacion_horaria.parquet",
            )), 24)
            temperature = pd.read_parquet(data / "outputs" / "aemet" / "gold_temperatura_diaria.parquet")
            self.assertTrue(temperature.empty)
            self.assertEqual(temperature.columns.tolist(), modules["03_gold_aemet"].COLUMNAS)

    def test_downloads_json_and_builds_real_parquet_without_aws(self):
        names = (
            "01_ingesta_redata", "01_ingesta_aemet", "02_calidad_redata",
            "02_calidad_aemet", "03_gold_redata", "03_gold_aemet",
        )
        modules = {name: load_module(ROOT / "notebooks" / f"{name}.py") for name in names}
        start = pd.Timestamp("2026-03-29", tz="Europe/Madrid")
        quarters = pd.date_range(start, start + pd.DateOffset(days=1), freq="15min", inclusive="left")
        prices = {"included": [{"attributes": {
            "title": "Precio mercado spot",
            "values": [{"datetime": timestamp.isoformat(), "value": float(index)}
                       for index, timestamp in enumerate(quarters)],
        }}]}
        temperatures = [{
            "fecha": "2026-03-29", "indicativo": "TEST", "nombre": "Madrid",
            "provincia": "MADRID", "tmin": "2,0", "tmax": "20,0", "tmed": "11,0",
            "horatmin": "06:00", "horatmax": "15:00",
        }]

        with TemporaryDirectory() as directory, ExitStack() as stack:
            data = Path(directory)
            stack.enter_context(patch("sys.stdout", new_callable=StringIO))
            stack.enter_context(patch("boto3.client", side_effect=AssertionError("AWS must not be used")))
            stack.enter_context(patch.object(modules["01_ingesta_redata"], "fetch", return_value=prices))
            stack.enter_context(patch.object(modules["01_ingesta_redata"].time, "sleep"))
            download = stack.enter_context(
                patch.object(modules["01_ingesta_aemet"], "fetch", return_value=temperatures),
            )
            for name, module in modules.items():
                source = name.rsplit("_", 1)[-1]
                stack.enter_context(patch.object(module, "BUCKET", "must-not-be-used"))
                for attribute, path in (
                    ("RAW_DIR", data / "raw" / source),
                    ("OUT_DIR", data / ("outputs" if name.startswith("03") else "processed") / source),
                    ("SILVER", data / "processed" / source /
                     ("precios_horarios.json" if source == "redata" else "aemet_diario.json")),
                ):
                    if hasattr(module, attribute):
                        stack.enter_context(patch.object(module, attribute, path))
                argv = [name]
                if name.startswith("01"):
                    argv += ["--start", "2026-03-29", "--end", "2026-03-29"]
                with patch("sys.argv", argv):
                    module.main()

            self.assertEqual(len(list((data / "raw").rglob("*.json"))), 3)
            raw = data / "raw" / "redata" / "precios_2026-03-29_2026-03-29.json"
            self.assertEqual(json.loads(raw.read_text(encoding="utf-8")), prices)
            plan = pd.read_parquet(data / "outputs" / "redata" / "gold_programacion_horaria.parquet")
            monthly = pd.read_parquet(data / "outputs" / "redata" / "gold_plan_mensual.parquet")
            temperature = pd.read_parquet(data / "outputs" / "aemet" / "gold_temperatura_diaria.parquet")
            self.assertEqual(len(plan), 23)
            self.assertNotIn(2, plan["hora_local"].tolist())
            self.assertEqual(plan["consumo_baseline_mwh"].sum(), 30.0)
            self.assertEqual(plan["consumo_optimizado_mwh"].sum(), 30.0)
            self.assertLessEqual(plan["consumo_optimizado_mwh"].max(), 7.0)
            saving = plan["coste_baseline_eur"].sum() - plan["coste_optimizado_eur"].sum()
            self.assertAlmostEqual(monthly["ahorro_estimado_mensual_eur"].iloc[0], saving)
            self.assertEqual(temperature["tmed"].tolist(), [11.0])

            download.reset_mock()
            with patch("sys.argv", ["aemet", "--start", "2026-03-29", "--end", "2026-03-29"]):
                modules["01_ingesta_aemet"].main()
            download.assert_not_called()
            with patch("sys.argv", ["aemet", "--start", "2026-03-29", "--end", "2026-03-29", "--force"]):
                modules["01_ingesta_aemet"].main()
            download.assert_called_once_with(date(2026, 3, 29), date(2026, 3, 29))

    def test_script_paths_do_not_depend_on_working_directory(self):
        for path in sorted((ROOT / "notebooks").glob("*.py")):
            with self.subTest(script=path.name):
                module = load_module(path)
                for name in ("RAW_DIR", "OUT_DIR", "SILVER", "AEMET_PATH", "REDATA_PATH"):
                    if hasattr(module, name):
                        self.assertTrue(getattr(module, name).is_relative_to(ROOT / "data"))

    def test_runner_downloads_then_transforms_then_starts_local_streamlit(self):
        with patch("sys.argv", ["run_local"]), patch.object(runner, "load_dotenv"), \
                patch.dict(os.environ, {"AEMET_API_KEY": "test-key"}), \
                patch.object(runner.subprocess, "run") as process:
            process.return_value.returncode = 0
            with self.assertRaises(SystemExit) as result:
                runner.main()
        self.assertEqual(result.exception.code, 0)
        calls = process.call_args_list
        self.assertEqual(len(calls), 7)
        self.assertEqual([Path(call.args[0][2]).name for call in calls[:6]], [
            "01_ingesta_redata.py", "01_ingesta_aemet.py", "02_calidad_redata.py",
            "02_calidad_aemet.py", "03_gold_redata.py", "03_gold_aemet.py",
        ])
        for call in calls[:6]:
            self.assertIn("--no-s3", call.args[0])
            self.assertTrue(call.kwargs["check"])
            self.assertEqual(call.kwargs["cwd"], ROOT)
        self.assertIn("127.0.0.1", calls[-1].args[0])
        self.assertIn("false", calls[-1].args[0])

    def test_runner_skip_download_and_prepare_only_do_not_need_key_or_start_server(self):
        with patch("sys.argv", ["run_local", "--skip-download", "--prepare-only"]), \
                patch.object(runner, "load_dotenv"), patch.dict(os.environ, {}, clear=True), \
                patch.object(runner.subprocess, "run") as process:
            runner.main()
        self.assertEqual(process.call_count, 4)
        self.assertTrue(all("01_ingesta" not in str(call) for call in process.call_args_list))

    def test_runner_stops_before_streamlit_when_pipeline_fails(self):
        with patch("sys.argv", ["run_local", "--skip-download"]), \
                patch.object(runner.subprocess, "run", side_effect=subprocess.CalledProcessError(2, "quality")) as process:
            with self.assertRaises(SystemExit) as result:
                runner.main()
        self.assertEqual(result.exception.code, 2)
        self.assertEqual(process.call_count, 1)

    def test_runner_validates_dates_and_missing_key_before_any_download(self):
        for arguments in (["--start", "2026-10-02", "--end", "2026-10-01"], []):
            with self.subTest(arguments=arguments), patch("sys.argv", ["run_local", *arguments]), \
                    patch.object(runner, "load_dotenv"), patch.dict(os.environ, {}, clear=True), \
                    patch.object(runner.subprocess, "run") as process:
                with self.assertRaises(SystemExit) as result:
                    runner.main()
                self.assertEqual(result.exception.code, 2)
                process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
