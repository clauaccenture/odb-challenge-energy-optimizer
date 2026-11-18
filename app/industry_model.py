"""Small, explicit model for the interactive industrial scenarios."""

from __future__ import annotations

from dataclasses import dataclass
import math


def in_window(hour: int, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


@dataclass(frozen=True)
class Simulation:
    baseline: list[float]
    optimized: list[float]
    baseline_cost: float
    optimized_cost: float


def simulate(
    prices: list[float], hours: list[int], energy: float, limit: float,
    baseline_window: tuple[int, int], available_window: tuple[int, int],
    baseline_mode: str = "uniform",
) -> Simulation:
    """S0 spreads the energy evenly over its window ("uniform") or charges at full power from the
    window start ("immediate", e.g. a fleet plugged in on arrival); S1 fills the cheapest hours."""
    if baseline_mode not in ("uniform", "immediate"):
        raise ValueError("Modo S0 no válido.")
    if not prices or len(prices) != len(hours):
        raise ValueError("Se necesita un precio por cada intervalo horario.")
    if any(not math.isfinite(price) for price in prices):
        raise ValueError("Los precios deben ser finitos.")
    if any(hour not in range(24) for hour in hours) or any(
        hour not in range(24) for hour in (*baseline_window, *available_window)
    ):
        raise ValueError("Las horas deben estar entre 00 y 23.")
    if not math.isfinite(energy) or not math.isfinite(limit) or energy < 0 or limit <= 0:
        raise ValueError("La energía debe ser no negativa y la potencia máxima, positiva.")
    baseline_indices = [i for i, hour in enumerate(hours) if in_window(hour, *baseline_window)]
    available_indices = [i for i, hour in enumerate(hours) if in_window(hour, *available_window)]
    if not baseline_indices or energy > limit * len(baseline_indices) + 1e-9:
        raise ValueError("La energía no cabe en la operación actual (S0) con la potencia máxima indicada.")
    if not available_indices or energy > limit * len(available_indices) + 1e-9:
        raise ValueError("La energía no cabe en las horas disponibles (S1) con la potencia máxima indicada.")
    baseline = [0.0] * len(prices)
    if baseline_mode == "uniform":
        for i in baseline_indices:
            baseline[i] = energy / len(baseline_indices)
    else:
        remaining = energy
        for i in sorted(baseline_indices, key=lambda index: ((hours[index] - baseline_window[0]) % 24, index)):
            baseline[i] = min(limit, remaining)
            remaining -= baseline[i]
            if remaining <= 1e-9:
                break
    optimized = [0.0] * len(prices)
    remaining = energy
    for i in sorted(available_indices, key=lambda index: (prices[index], index)):
        optimized[i] = min(limit, remaining)
        remaining -= optimized[i]
        if remaining <= 1e-9:
            break
    return Simulation(
        baseline, optimized,
        sum(price * amount for price, amount in zip(prices, baseline)),
        sum(price * amount for price, amount in zip(prices, optimized)),
    )
