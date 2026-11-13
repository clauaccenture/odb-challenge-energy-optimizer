from pathlib import Path
from io import BytesIO
import hashlib
import runpy
import unittest
from unittest.mock import Mock, patch
import json
import tempfile

import pandas as pd
from botocore.exceptions import ClientError

GOLD = runpy.run_path(str(Path(__file__).resolve().parents[1] / "03_gold_redata.py"))
from src.config_loader import cargar_config  # noqa: E402
from src.desaladora import build_desaladora, precios_indexados  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "config_desaladora.yaml"

# Precios horarios reales del 15/01/2026 (plan_2026-01-15.csv).
PRECIOS_2026_01_15 = [
    119.045, 107.5575, 101.3875, 94.8275, 87.035, 86.3125, 98.8975, 112.5525,
    114.695, 105.475, 98.585, 94.8925, 92.2, 86.6675, 89.825, 94.51,
    105.03, 113.1425, 116.6575, 120.7225, 133.07, 138.2, 128.6425, 113.8,
]


def silver_dia(fecha, precios=None):
    inicio = pd.Timestamp(fecha, tz="Europe/Madrid")
    fin = pd.Timestamp(inicio.date() + pd.Timedelta(days=1), tz="Europe/Madrid")
    horas = pd.date_range(inicio, fin, freq="h", inclusive="left")
    return pd.DataFrame({
        "datetime_utc": horas.tz_convert("UTC"),
        "datetime_local": horas,
        "fecha_local": horas.date,
        "precio_eur_mwh": precios if precios is not None else [50.0] * len(horas),
    })


def silver_json(fecha):
    valores = [{"datetime": str(t), "value": 50} for t in silver_dia(fecha)["datetime_utc"]]
    return json.dumps({"included": [{
        "attributes": {"title": "Precio mercado spot", "values": valores}
    }]}).encode("utf-8")


class GoldPeajesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        negativos = [-5.0] * 6 + [60.0] * 18
        silver = pd.concat([
            silver_dia("2025-12-31"),
            silver_dia("2026-01-15", PRECIOS_2026_01_15),
            silver_dia("2026-04-19", negativos),
            silver_dia("2026-10-25"),
        ], ignore_index=True)
        cls.plan, resumen = GOLD["build_gold"](silver)
        cls.resumen = resumen.set_index("fecha_local")
        cls.mensual = GOLD["build_mensual"](cls.plan, resumen).set_index("mes")

    def dia(self, fecha):
        return self.plan[self.plan["fecha_local"] == pd.Timestamp(fecha).date()]

    def test_caso_15_enero_reproduce_calculo_manual(self):
        r = self.resumen.loc[pd.Timestamp("2026-01-15").date()]
        self.assertAlmostEqual(r["coste_baseline_total_eur"], 3081.01, places=2)
        self.assertAlmostEqual(r["coste_optimizado_total_eur"], 2633.28, places=2)
        self.assertAlmostEqual(r["coste_total_baseline_eur"], 3673.59, places=2)
        self.assertAlmostEqual(r["coste_total_optimizado_eur"], 2956.55, places=2)
        self.assertAlmostEqual(r["ahorro_total_eur"], 717.04, places=2)

    def test_columnas_horarias_coherentes(self):
        d = self.dia("2026-01-15")
        self.assertEqual(list(d["periodo_tarifario"].iloc[7:10]), ["P6", "P2", "P1"])
        for esc in ("baseline", "optimizado"):
            esperado = d[f"consumo_{esc}_mwh"] * (d["peaje_energia_eur_mwh"] + d["cargo_energia_eur_mwh"])
            pd.testing.assert_series_equal(d[f"coste_regulado_{esc}_eur"], esperado.round(5), check_names=False)
            pd.testing.assert_series_equal(
                d[f"coste_total_{esc}_eur"],
                (d[f"coste_{esc}_eur"] + d[f"coste_regulado_{esc}_eur"]).round(5),
                check_names=False,
            )

    def test_dia_sin_tarifa_queda_vacio_sin_romper_mercado(self):
        d = self.dia("2025-12-31")
        self.assertTrue(d["periodo_tarifario"].isna().all())
        self.assertTrue(d["coste_total_baseline_eur"].isna().all())
        r = self.resumen.loc[pd.Timestamp("2025-12-31").date()]
        self.assertTrue(pd.isna(r["ahorro_total_eur"]))
        self.assertFalse(pd.isna(r["ahorro_eur"]))
        self.assertTrue(pd.isna(self.mensual.loc["2025-12", "ahorro_total_mensual_eur"]))

    def test_domingo_con_negativos_todo_p6_y_coste_negativo(self):
        d = self.dia("2026-04-19")
        self.assertEqual(set(d["periodo_tarifario"]), {"P6"})
        self.assertLess(self.resumen.loc[pd.Timestamp("2026-04-19").date(), "coste_optimizado_total_eur"], 0)

    def test_dia_de_25_horas(self):
        d = self.dia("2026-10-25")
        self.assertEqual(len(d), 25)
        self.assertEqual(set(d["periodo_tarifario"]), {"P6"})

    def test_mensual_anual_con_peajes(self):
        total = self.resumen["ahorro_total_eur"].sum()
        self.assertAlmostEqual(self.mensual["ahorro_total_anual_eur"].iloc[0], total, places=4)


class DesaladoraTests(unittest.TestCase):
    def config(self, inicio="2026-01-15", fin=None):
        cfg, _ = cargar_config(CONFIG)
        cfg["mercado"]["fecha_inicio"] = inicio
        cfg["mercado"]["fecha_fin"] = fin or inicio
        return cfg

    def test_formula_manual_desglose_sin_doble_peaje_y_negativos(self):
        cfg = self.config()
        precios = precios_indexados(silver_dia("2026-01-15", [-100.0] * 24), cfg)
        # 01:00 = P6: todos los importes son EUR/MWh, antes de impuestos.
        esperado = 1.015 * ((-100 + .5 + 10 + 2 + .650 + .2) * 1.04 + 2 + 16) + .020 + .732
        self.assertAlmostEqual(precios.iloc[1]["precio_indexado_eur_mwh"], esperado)
        self.assertLess(esperado, 0)
        desglose = precios[[
            "precio_eur_mwh", "pc_eur_mwh", "sc_eur_mwh", "dsv_eur_mwh", "gdo_eur_mwh",
            "posom_eur_mwh", "perdidas_eur_mwh", "fe_eur_mwh", "f_eur_mwh",
            "ajuste_formula_eur_mwh", "peaje_energia_eur_mwh", "cargo_energia_eur_mwh",
        ]].sum(axis=1)
        pd.testing.assert_series_equal(desglose, precios["precio_indexado_eur_mwh"], check_names=False)
        abril = precios_indexados(silver_dia("2026-04-01"), cfg)
        self.assertEqual(abril.iloc[0]["gdo_eur_mwh"], .965)

    def test_reoptimiza_con_indexado_y_respeta_energia_y_potencia(self):
        cfg = self.config()
        # Cinco horas P1 ganan por spot; P6 desplaza carga al incluir el resto del precio.
        precios = [100.0] * 24
        precios[9:14] = [0.0] * 5
        precios[2] = 5.0
        silver = silver_dia("2026-01-15", precios)
        plan, resumen, mensual = build_desaladora(silver, cfg)
        self.assertEqual(plan.iloc[2]["consumo_optimizado_mwh"], 7)
        self.assertEqual(plan.iloc[13]["consumo_optimizado_mwh"], 0)
        mercado = GOLD["plan_dia"](silver)
        self.assertEqual(mercado.iloc[2]["consumo_optimizado_mwh"], 0)
        self.assertEqual(mercado.iloc[13]["consumo_optimizado_mwh"], 2)
        coste_plan_spot = (mercado["consumo_optimizado_mwh"] * plan["precio_indexado_eur_mwh"]).sum()
        coste_indexado = plan["coste_energia_flexible_optimizado_eur"].sum()
        self.assertLess(coste_indexado, coste_plan_spot)
        for escenario in ("baseline", "optimizado"):
            self.assertAlmostEqual(plan[f"consumo_{escenario}_mwh"].sum(), 30)
            self.assertAlmostEqual(plan[f"consumo_planta_{escenario}_mwh"].sum(), 150)
            self.assertTrue((plan[f"consumo_planta_{escenario}_mwh"] <= plan["potencia_contratada_mw"]).all())
        self.assertAlmostEqual(mensual["ahorro_energia_eur"].iloc[0], resumen["ahorro_energia_eur"].sum())
        ahorro_planta = (resumen["coste_energia_planta_baseline_eur"]
                         - resumen["coste_energia_planta_optimizado_eur"]).iloc[0]
        self.assertAlmostEqual(ahorro_planta, resumen["ahorro_energia_eur"].iloc[0])

    def test_potencia_limita_la_asignacion_y_baseline_inviable_falla(self):
        cfg = self.config()
        cfg["operacion_demo"]["potencia_contratada_mw"] = {f"p{i}": 8 for i in range(1, 7)}
        plan, _, _ = build_desaladora(silver_dia("2026-01-15"), cfg)
        self.assertLessEqual(plan["consumo_optimizado_mwh"].max(), 3)
        cfg["operacion_demo"]["potencia_contratada_mw"] = {f"p{i}": 7 for i in range(1, 7)}
        with self.assertRaisesRegex(ValueError, "potencia contratada insuficiente"):
            build_desaladora(silver_dia("2026-01-15"), cfg)

    def test_cambios_horarios_y_cobertura_no_inventan_datos(self):
        for fecha, horas in (("2026-03-29", 23), ("2026-10-25", 25)):
            with self.subTest(fecha=fecha):
                plan, _, _ = build_desaladora(silver_dia(fecha), self.config(fecha))
                self.assertEqual(len(plan), horas)
                self.assertEqual(len(plan["datetime_utc"].unique()), horas)
                self.assertAlmostEqual(plan["consumo_optimizado_mwh"].sum(), 30)
                self.assertAlmostEqual(plan["consumo_no_flexible_mwh"].sum(), 120)
        cfg = self.config("2026-01-15", "2026-01-17")
        datos = pd.concat([silver_dia("2026-01-15"), silver_dia("2026-01-16").iloc[:-1]])
        _, resumen, mensual = build_desaladora(datos, cfg)
        self.assertEqual(resumen["estado_optimizacion"].tolist(), ["optimo", "dia_incompleto", "sin_datos"])
        self.assertTrue(pd.isna(resumen.iloc[1]["ahorro_energia_eur"]))
        self.assertEqual(mensual.iloc[0]["dias_sin_programacion"], 2)

    def test_datos_invalidos_no_se_optimizan(self):
        cfg = self.config()
        datos = silver_dia("2026-01-15")
        with self.assertRaisesRegex(ValueError, "duplicado"):
            build_desaladora(pd.concat([datos, datos.iloc[:1]]), cfg)
        datos.loc[0, "precio_eur_mwh"] = float("nan")
        with self.assertRaisesRegex(ValueError, "no finito"):
            build_desaladora(datos, cfg)

    def test_ventana_automatica_incluye_noviembre_diciembre_sin_extender_tarifa(self):
        cfg, _ = cargar_config(CONFIG)
        datos = pd.concat([
            silver_dia("2025-12-31"), silver_dia("2026-11-12"),
            silver_dia("2026-12-24"), silver_dia("2027-01-01"),
        ], ignore_index=True)
        plan, resumen, mensual = build_desaladora(datos, cfg)
        self.assertEqual(set(plan["fecha_local"]), {
            pd.Timestamp("2026-11-12").date(), pd.Timestamp("2026-12-24").date(),
        })
        self.assertEqual(resumen["fecha_local"].min(), pd.Timestamp("2026-11-12").date())
        self.assertEqual(resumen["fecha_local"].max(), pd.Timestamp("2026-12-24").date())
        self.assertEqual(mensual["mes"].tolist(), ["2026-11", "2026-12"])
        with self.assertRaisesRegex(ValueError, "vigencia tarifaria 2026"):
            build_desaladora(silver_dia("2027-01-01"), cfg)

    def test_cli_guarda_parquet_y_trazabilidad_sin_aws_ni_gold_original(self):
        main = GOLD["main"]
        namespace = main.__globals__
        with tempfile.TemporaryDirectory() as carpeta:
            salida = Path(carpeta)
            silver_path = salida / "silver.json"
            silver_path.write_bytes(silver_json("2026-01-15"))
            argumentos = ["03_gold_redata.py", "--config", str(CONFIG), "--no-s3"]
            with patch.dict(namespace, {"SILVER": silver_path, "BUCKET": "no-debe-usarse",
                                        "OUT_DIR_DESALADORA": salida / "caso"}), patch("sys.argv", argumentos):
                main()
            metadata = json.loads((salida / "caso" / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata["es_simulacion"])
            self.assertIn("contrato.sc_eur_mwh", metadata["hipotesis"])
            self.assertEqual(metadata["dias_optimos"], 1)
            self.assertIn("Constante ilustrativa", metadata["config_yaml"])
            plan = pd.read_parquet(salida / "caso" / "programacion_horaria.parquet")
            self.assertEqual(len(plan), 24)
            self.assertIn("precio_indexado_eur_mwh", plan)
            self.assertEqual(len(metadata["outputs_sha256"]), 3)
            self.assertFalse((salida / "gold_programacion_horaria.parquet").exists())
        with patch("sys.argv", ["03_gold_redata.py", "--config", str(CONFIG)]):
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 2)


class DesaladoraS3Tests(unittest.TestCase):
    def test_metadata_conserva_bytes_yaml_con_finales_crlf(self):
        cliente = Mock()
        cliente.get_object.return_value = {"Body": BytesIO(silver_json("2026-01-15"))}
        contenido = CONFIG.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as carpeta:
            config = Path(carpeta) / "config_crlf.yaml"
            config.write_bytes(contenido)
            ejecutar = GOLD["ejecutar_desaladora"]
            with patch.dict(ejecutar.__globals__, {"BUCKET": "bucket-demo"}), \
                    patch("boto3.client", return_value=cliente):
                ejecutar(config, True)
        metadata = json.loads(cliente.put_object.call_args_list[-2].kwargs["Body"])
        self.assertEqual(metadata["config_yaml"].encode("utf-8"), contenido)
        self.assertEqual(metadata["config_sha256"], hashlib.sha256(contenido).hexdigest())

    def ejecutar(self, cliente, bucket="bucket-demo"):
        main = GOLD["main"]
        namespace = main.__globals__
        no_local = Mock(spec=Path)
        no_local.read_bytes.side_effect = AssertionError("No debe leer Silver del disco")
        no_local.mkdir.side_effect = AssertionError("No debe crear carpetas de datos")
        args = ["03_gold_redata.py", "--config", str(CONFIG), "--s3"]
        with patch.dict(namespace, {"BUCKET": bucket, "REDATA_S3_PREFIX": "redata_demo",
                                    "SILVER": no_local, "OUT_DIR_DESALADORA": no_local}), \
                patch("boto3.client", return_value=cliente), patch("sys.argv", args), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("Escritura en disco")), \
                patch.object(Path, "write_text", side_effect=AssertionError("Escritura en disco")):
            main()

    def test_s3_publica_ejecucion_completa_sin_datos_en_disco(self):
        cliente = Mock()
        payload = json.loads(silver_json("2026-12-24"))
        payload["included"][0]["attributes"]["values"].extend(
            json.loads(silver_json("2027-01-01"))["included"][0]["attributes"]["values"]
        )
        contenido = json.dumps(payload).encode("utf-8")
        body = BytesIO(contenido)
        cliente.get_object.return_value = {"Body": body, "VersionId": "silver-v1"}
        self.ejecutar(cliente)
        self.assertTrue(body.closed)
        cliente.get_object.assert_called_once_with(
            Bucket="bucket-demo", Key="processed/redata_demo/precios_horarios.json"
        )
        subidas = cliente.put_object.call_args_list
        self.assertEqual(len(subidas), 5)
        puntero = subidas[-1].kwargs
        self.assertEqual(puntero["Key"], "outputs/desaladora_som_energia/latest.json")
        objetos = {llamada.kwargs["Key"]: llamada.kwargs["Body"] for llamada in subidas}
        metadata_key = json.loads(puntero["Body"])["metadata_key"]
        metadata = json.loads(objetos[metadata_key])
        self.assertEqual(metadata["silver_version_id"], "silver-v1")
        self.assertEqual(metadata["silver_sha256"], hashlib.sha256(contenido).hexdigest())
        self.assertEqual(metadata["silver_origen"], "s3://bucket-demo/processed/redata_demo/precios_horarios.json")
        self.assertEqual(metadata["criterio_optimizacion"], "precio_indexado_eur_mwh")
        self.assertEqual(metadata["fecha_ultima_programacion"], "2026-12-24")
        self.assertEqual(metadata["horas_silver_fuera_vigencia_tarifa"], 24)
        for nombre, key in metadata["outputs_s3"].items():
            self.assertTrue(key.startswith("outputs/desaladora_som_energia/runs/"))
            self.assertEqual(hashlib.sha256(objetos[key]).hexdigest(), metadata["outputs_sha256"][nombre])
        plan = pd.read_parquet(BytesIO(objetos[metadata["outputs_s3"]["programacion_horaria.parquet"]]))
        self.assertEqual(len(plan), 24)
        self.assertIn("precio_indexado_eur_mwh", plan)
        self.assertEqual(subidas[-2].kwargs["Key"], metadata_key)

    def test_errores_s3_no_usan_local_ni_publican_puntero(self):
        for codigo in ("NoSuchKey", "AccessDenied"):
            with self.subTest(codigo=codigo):
                cliente = Mock()
                cliente.get_object.side_effect = ClientError(
                    {"Error": {"Code": codigo, "Message": "error simulado"}}, "GetObject"
                )
                with self.assertRaises(ClientError):
                    self.ejecutar(cliente)
                cliente.put_object.assert_not_called()
        cliente = Mock()
        cliente.get_object.return_value = {"Body": BytesIO(silver_json("2026-01-15"))}
        error = ClientError({"Error": {"Code": "AccessDenied", "Message": "sin escritura"}}, "PutObject")
        cliente.put_object.side_effect = [None, error]
        with self.assertRaises(ClientError):
            self.ejecutar(cliente)
        self.assertEqual(cliente.put_object.call_count, 2)
        self.assertFalse(any(c.kwargs["Key"].endswith("latest.json") for c in cliente.put_object.call_args_list))

    def test_s3_sin_bucket_falla_antes_de_leer_datos(self):
        cliente = Mock()
        with self.assertRaisesRegex(ValueError, "S3_BUCKET"):
            self.ejecutar(cliente, bucket=None)
        cliente.get_object.assert_not_called()
        cliente.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
