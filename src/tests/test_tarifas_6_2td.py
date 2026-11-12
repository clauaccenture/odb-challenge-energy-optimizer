from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.tarifas_6_2td import (  # noqa: E402
    PERIODOS,
    ZONA_PENINSULA,
    coste_horario_eur,
    periodo_6_2td,
    periodo_desde_datetime,
    termino_regulado_eur_mwh,
)

# Datos horarios de plan_2026-01-15.csv: (precio €/MWh, MWh S0, MWh S1).
PLAN_2026_01_15 = [
    (119.045, 0, 0), (107.5575, 0, 0), (101.3875, 0, 0), (94.8275, 0, 0),
    (87.035, 0, 7), (86.3125, 0, 7), (98.8975, 0, 0), (112.5525, 0, 0),
    (114.695, 2.5, 0), (105.475, 2.5, 0), (98.585, 2.5, 0), (94.8925, 2.5, 0),
    (92.2, 2.5, 2), (86.6675, 2.5, 7), (89.825, 2.5, 7), (94.51, 2.5, 0),
    (105.03, 2.5, 0), (113.1425, 2.5, 0), (116.6575, 2.5, 0), (120.7225, 2.5, 0),
    (133.07, 0, 0), (138.2, 0, 0), (128.6425, 0, 0), (113.8, 0, 0),
]


def periodos_del_dia(dia):
    return [periodo_6_2td(dia, hora) for hora in range(24)]


class CalendarioPeriodosTests(unittest.TestCase):
    def test_laborable_temporada_alta(self):
        esperado = ["P6"] * 8 + ["P2"] + ["P1"] * 5 + ["P2"] * 4 + ["P1"] * 4 + ["P2"] * 2
        self.assertEqual(periodos_del_dia(date(2026, 1, 15)), esperado)

    def test_laborable_por_temporada(self):
        casos = {
            date(2026, 3, 10): ("P2", "P3"),
            date(2026, 6, 10): ("P3", "P4"),
            date(2026, 4, 14): ("P4", "P5"),
            date(2026, 7, 15): ("P1", "P2"),
        }
        for dia, (punta, llano) in casos.items():
            with self.subTest(dia=dia):
                periodos = periodos_del_dia(dia)
                self.assertEqual(periodos[:8], ["P6"] * 8)
                self.assertEqual(periodos[10], punta)
                self.assertEqual(periodos[19], punta)
                self.assertEqual(periodos[8], llano)
                self.assertEqual(periodos[15], llano)
                self.assertEqual(periodos[23], llano)

    def test_fines_de_semana_y_festivos_todo_p6(self):
        for dia in [date(2026, 1, 17), date(2026, 1, 18), date(2026, 1, 1),
                    date(2026, 1, 6), date(2026, 5, 1), date(2026, 10, 12)]:
            with self.subTest(dia=dia):
                self.assertEqual(periodos_del_dia(dia), ["P6"] * 24)

    def test_viernes_santo_no_es_festivo_tarifario(self):
        self.assertEqual(periodo_6_2td(date(2026, 4, 3), 10), "P4")

    def test_anio_sin_calendario_falla(self):
        with self.assertRaises(ValueError):
            periodo_6_2td(date(2027, 1, 15), 10)

    def test_datetime_utc_se_convierte_a_hora_peninsular(self):
        # Enero es UTC+1 y julio UTC+2.
        self.assertEqual(periodo_desde_datetime(datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc)), "P1")
        self.assertEqual(periodo_desde_datetime(datetime(2026, 1, 15, 7, 30, tzinfo=timezone.utc)), "P2")
        self.assertEqual(periodo_desde_datetime(datetime(2026, 7, 15, 6, 30, tzinfo=timezone.utc)), "P2")

    def test_dias_de_cambio_de_hora_tienen_23_y_25_horas(self):
        for dia, horas in [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]:
            with self.subTest(dia=dia):
                inicio = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc) - timedelta(hours=2)
                locales = [(inicio + timedelta(hours=h)).astimezone(ZONA_PENINSULA) for h in range(27)]
                del_dia = [m for m in locales if m.date() == dia]
                self.assertEqual(len(del_dia), horas)
                self.assertEqual({periodo_desde_datetime(m) for m in del_dia}, {"P6"})


class CosteReguladoTests(unittest.TestCase):
    def test_termino_regulado_decrece_de_p1_a_p6(self):
        valores = [termino_regulado_eur_mwh(p) for p in PERIODOS]
        self.assertEqual(valores, sorted(valores, reverse=True))
        self.assertAlmostEqual(termino_regulado_eur_mwh("P1"), 23.880)
        self.assertAlmostEqual(termino_regulado_eur_mwh("P6"), 0.752)

    def test_precio_negativo_no_se_trunca(self):
        self.assertAlmostEqual(coste_horario_eur(7, -5.0, "P6"), 7 * (-5.0 + 0.752))

    def test_caso_referencia_15_enero_2026(self):
        dia = date(2026, 1, 15)
        mercado_s0 = mercado_s1 = total_s0 = total_s1 = 0.0
        for hora, (precio, s0, s1) in enumerate(PLAN_2026_01_15):
            periodo = periodo_6_2td(dia, hora)
            mercado_s0 += s0 * precio
            mercado_s1 += s1 * precio
            total_s0 += coste_horario_eur(s0, precio, periodo)
            total_s1 += coste_horario_eur(s1, precio, periodo)
        self.assertAlmostEqual(mercado_s0, 3081.01, places=2)
        self.assertAlmostEqual(mercado_s1, 2633.28, places=2)
        self.assertAlmostEqual(total_s0, 3673.59, places=2)
        self.assertAlmostEqual(total_s1, 2956.55, places=2)
        self.assertAlmostEqual(total_s0 - total_s1, 717.04, places=2)


if __name__ == "__main__":
    unittest.main()
