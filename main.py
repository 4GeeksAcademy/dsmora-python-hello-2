"""Pipeline de limpieza y normalización del dataset de viajes."""

from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean
from typing import Any

INPUT_FILE = Path(__file__).with_name("travel_raw_dataset.csv")
OUTPUT_FILE = Path(__file__).with_name("travel_clean_dataset.csv")
NUMERIC_COLUMNS = {"trip_duration_days", "number_of_travelers", "budget_usd"}
MISSING_VALUES = {"", "na", "n/a", "null", "none", "unknown"}


def _missing(value: Any) -> bool:
    return value is None or str(value).strip().lower() in MISSING_VALUES


def _normalise(column: str, value: str) -> Any:
    value = value.strip()
    if _missing(value):
        return None
    if column in NUMERIC_COLUMNS:
        try:
            number = int(value)
        except ValueError:
            # Un texto como ``two weeks`` o ``many`` no puede convertirse a
            # número: se trata como dato ausente y seguirá la misma política
            # de porcentaje que una celda vacía.
            return None
        # Una duración, un número de viajeros o un presupuesto no pueden ser
        # negativos. Se convierten en ausentes para que se aplique la regla
        # del porcentaje y, si corresponde, la imputación de la media.
        return number if number >= 0 else None
    return value.casefold()


def _similar_mean(rows: list[dict[str, Any]], column: str, row: dict[str, Any]) -> float:
    categorical = [
        key for key in row
        if key not in NUMERIC_COLUMNS and key != column and row[key] is not None
    ]
    values = [
        other[column] for other in rows
        if other[column] is not None
        and all(other[key] == row[key] for key in categorical)
    ]
    if not values:
        values = [other[column] for other in rows if other[column] is not None]
    return mean(values)


def clean_travel_dataset(
    input_file: Path = INPUT_FILE,
    output_file: Path = OUTPUT_FILE,
) -> tuple[int, int, int]:
    """Lee una vez, limpia y escribe el resultado en otro CSV.

    Ausentes menores al 5% eliminan sus filas. Con 5% o más, ``trip_purpose``
    recibe ``N/A``, las columnas numéricas reciben la media de semejantes y
    cualquier otra columna categórica solicita una decisión explícita.
    """
    # El origen se abre exactamente una vez.
    with input_file.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("El CSV no contiene cabecera")
        fieldnames = [name.strip() for name in reader.fieldnames]
        raw_rows = [
            {fieldnames[i]: row.get(original_name, "")
             for i, original_name in enumerate(reader.fieldnames)}
            for row in reader
        ]

    rows = [
        {column: _normalise(column, row.get(column, "")) for column in fieldnames}
        for row in raw_rows
    ]
    original_count = len(rows)
    unique_values = dict.fromkeys(tuple(row[column] for column in fieldnames) for row in rows)
    rows = [dict(zip(fieldnames, values)) for values in unique_values]
    duplicate_count = original_count - len(rows)

    ratios = {
        column: sum(row[column] is None for row in rows) / len(rows)
        for column in fieldnames
    }
    drop_columns = {
        column for column, ratio in ratios.items() if 0 < ratio < 0.05
    }
    unknown_categorical = {
        column for column, ratio in ratios.items()
        if ratio >= 0.05 and column not in NUMERIC_COLUMNS and column != "trip_purpose"
    }
    if unknown_categorical:
        columns = ", ".join(sorted(unknown_categorical))
        raise ValueError(
            f"Hay ausentes >= 5% en {columns}. "
            "¿Qué valor categórico debemos usar para completarlos?"
        )

    rows = [row for row in rows if all(row[column] is not None for column in drop_columns)]
    for row in rows:
        for column in fieldnames:
            if row[column] is not None or column in drop_columns:
                continue
            if column == "trip_purpose":
                row[column] = "N/A"
            elif column in NUMERIC_COLUMNS:
                row[column] = round(_similar_mean(rows, column, row), 2)

    with output_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(raw_rows), duplicate_count, len(rows)


if __name__ == "__main__":
    read, duplicates, final = clean_travel_dataset()
    print(f"CSV cargado una sola vez: {read} registros")
    print(f"Duplicados eliminados: {duplicates}")
    print(f"Resultado: {OUTPUT_FILE.name} ({final} registros)")
