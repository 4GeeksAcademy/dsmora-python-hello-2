"""Carga el pipeline de precios de viviendas y predice con Prefect.

Para ver la ejecución en el dashboard, inicia primero el servidor Prefect:

    uv run prefect server start --host 0.0.0.0

En otra terminal, ejecuta este archivo con PREFECT_API_URL apuntando al servidor.
"""
import time
from datetime import date
from pathlib import Path

import joblib
import numpy as np
from prefect import flow, get_run_logger, task
from sklearn.datasets import fetch_california_housing
from sample_data import FRESHNESS_MONTHS, make_sample_dates, subtract_months, to_model_features

MODEL_PATH = Path(__file__).resolve().with_name("model_house_pricing_pipeline.joblib")


@task(name="Cargar modelo")
def load_model():
    """Carga la pipeline entrenada desde model_house_pricing_pipeline.joblib."""
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"No se encontró el modelo: {MODEL_PATH}")

    return joblib.load(MODEL_PATH)


@task(name="Predecir muestras")
def predict_batch(model, features):
    """Predice los precios de todas las muestras recibidas."""
    return model.predict(features)


@task(name="Filtrar muestras obsoletas")
def filter_stale_samples(features, sample_dates, as_of=None):
    """Descarta filas cuya fecha sea anterior al umbral de seis meses."""
    as_of = as_of or date.today()
    freshness_cutoff = np.datetime64(subtract_months(as_of, FRESHNESS_MONTHS), "D")
    fresh_mask = sample_dates >= freshness_cutoff
    return features[fresh_mask], sample_dates[fresh_mask], int((~fresh_mask).sum()), freshness_cutoff


@flow(name="Predicción de precios de viviendas de California")
def predict_example():
    """Predice los precios de las viviendas del dataset de California."""
    start = time.time()  # Iniciar temporizador

    logger = get_run_logger()
    dataset = fetch_california_housing()
    sample_dates = make_sample_dates(dataset.data.shape[0])
    features = to_model_features(dataset.data, sample_dates)
    logger.info(
        "Dataset cargado: %d filas, %d características (incluida fecha sintética)",
        features.shape[0],
        features.shape[1],
    )

    features, sample_dates, stale_count, freshness_cutoff = filter_stale_samples(
        features, sample_dates
    )
    logger.info(
        "Frescura de datos: se ignoran %d filas anteriores a %s; quedan %d filas",
        stale_count,
        freshness_cutoff,
        len(features),
    )
    if len(features) == 0:
        logger.warning("No hay muestras recientes para predecir.")
        return np.array([])

    model = load_model()
    predictions = predict_batch(model, features)

    logger.info(
        "Predicciones de precios completadas para %d viviendas. Precio medio predicho: %.3f (en unidades de 100.000 USD)",
        len(predictions),
        predictions.mean(),
    )
    print(
        f"Predicciones completadas para {len(predictions)} viviendas. "
        f"Precio medio predicho: {predictions.mean():.3f} (en unidades de 100.000 USD)"
    )
    end = time.time()  # Detener temporizador
    logger.info("Tiempo total de predicción: %.2f segundos", end - start)
    return predictions


if __name__ == "__main__":
    predict_example()
