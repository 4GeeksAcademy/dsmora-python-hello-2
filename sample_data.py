"""Helpers para simular fechas de captura en California Housing.

El dataset original no incluye timestamps. Para demostrar monitorización de
frescura, se asignan fechas sintéticas distribuidas durante el último año.
"""
from calendar import monthrange
from datetime import date, timedelta

import numpy as np


FRESHNESS_MONTHS = 6
SIMULATED_HISTORY_DAYS = 365


def subtract_months(day: date, months: int) -> date:
    """Resta meses naturales a una fecha, ajustando el día si hace falta."""
    month_index = day.year * 12 + day.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def make_sample_dates(sample_count: int, as_of: date | None = None) -> np.ndarray:
    """Devuelve fechas sintéticas distribuidas a lo largo del último año."""
    if sample_count < 0:
        raise ValueError("sample_count no puede ser negativo")
    if sample_count == 0:
        return np.array([], dtype="datetime64[D]")

    as_of = as_of or date.today()
    start = np.datetime64(as_of - timedelta(days=SIMULATED_HISTORY_DAYS), "D")
    day_offsets = np.linspace(0, SIMULATED_HISTORY_DAYS, sample_count).astype("timedelta64[D]")
    return start + day_offsets


def to_model_features(features: np.ndarray, sample_dates: np.ndarray) -> np.ndarray:
    """Añade la fecha de muestra como característica numérica para sklearn."""
    if len(features) != len(sample_dates):
        raise ValueError("Debe haber una fecha por cada fila de características")
    date_as_days = sample_dates.astype("datetime64[D]").astype(np.int64)
    return np.column_stack((features, date_as_days))
