from pathlib import Path
import runpy
import unittest

import pandas as pd

GOLD = runpy.run_path(str(Path(__file__).resolve().parents[1] / "03_gold_redata.py"))

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


if __name__ == "__main__":
    unittest.main()
