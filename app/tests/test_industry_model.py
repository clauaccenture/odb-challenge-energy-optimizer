from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from industry_model import in_window, simulate


class IndustryModelTests(unittest.TestCase):
    def test_windows_and_negative_prices(self) -> None:
        self.assertTrue(in_window(23, 19, 7))
        self.assertTrue(in_window(6, 19, 7))
        self.assertFalse(in_window(7, 19, 7))
        self.assertTrue(in_window(7, 0, 0))
        result = simulate([10, -5, 2, 8], [0, 1, 2, 3], 3, 2, (0, 0), (1, 3))
        self.assertEqual(result.baseline, [0.75] * 4)
        self.assertEqual(result.optimized, [0, 2, 1, 0])
        self.assertEqual(result.optimized_cost, -8)
        self.assertEqual(sum(result.optimized), 3)

    def test_rejects_infeasible_and_invalid_input(self) -> None:
        with self.assertRaisesRegex(ValueError, r"operación actual \(S0\)"):
            simulate([1, 2], [0, 1], 3, 1, (0, 0), (0, 0))
        with self.assertRaisesRegex(ValueError, r"horas disponibles \(S1\)"):
            simulate([1, 2], [0, 1], 2, 1, (0, 0), (0, 1))
        with self.assertRaisesRegex(ValueError, "finitos"):
            simulate([float("nan")], [0], 0, 1, (0, 0), (0, 0))
        with self.assertRaisesRegex(ValueError, "Modo S0"):
            simulate([1], [0], 0, 1, (0, 0), (0, 0), "otro")

    def test_immediate_baseline_charges_from_arrival_and_wraps_midnight(self) -> None:
        prices = [1, 2, 3, 4, 5, 6]
        hours = [0, 1, 2, 3, 4, 5]
        result = simulate(prices, hours, 2.5, 1, (4, 2), (4, 2), "immediate")
        self.assertEqual(result.baseline, [0.5, 0, 0, 0, 1, 1])
        self.assertEqual(result.optimized, [1, 1, 0, 0, 0.5, 0])
        self.assertEqual(result.baseline_cost, 11.5)

    def test_repeated_hour_is_two_real_intervals(self) -> None:
        result = simulate([4, 1, 2, 3], [1, 2, 2, 3], 2, 1, (2, 3), (2, 3))
        self.assertEqual(result.baseline, [0, 1, 1, 0])
        self.assertEqual(result.optimized, [0, 1, 1, 0])
        self.assertEqual(result.optimized_cost, 3)


if __name__ == "__main__":
    unittest.main()
