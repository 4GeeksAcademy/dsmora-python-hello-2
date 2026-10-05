"""Entrena y guarda un pipeline para predecir precios de viviendas de California."""
from pathlib import Path

import joblib
from sklearn.datasets import fetch_california_housing
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sample_data import make_sample_dates, to_model_features

MODEL_PATH = Path(__file__).resolve().with_name("model_house_pricing_pipeline.joblib")


def train_model():
    """Entrena el modelo con California Housing y guarda el pipeline serializado."""
    dataset = fetch_california_housing()
    sample_dates = make_sample_dates(dataset.data.shape[0])
    features = to_model_features(dataset.data, sample_dates)
    print(
        f"Dataset cargado con {features.shape[0]} muestras y "
        f"{features.shape[1]} características, incluida la fecha sintética."
    )
    target = dataset.target

    X_train, X_test, y_train, y_test = train_test_split(
        features, target, test_size=0.2, random_state=42
    )

    pipeline = make_pipeline(StandardScaler(), LinearRegression())
    pipeline.fit(X_train, y_train)

    test_predictions = pipeline.predict(X_test)
    print(f"Test MSE: {mean_squared_error(y_test, test_predictions):.4f}")
    print(f"Test R²: {r2_score(y_test, test_predictions):.4f}")

    # Reajustar con todos los datos para que el artefacto use el dataset completo.
    pipeline.fit(features, target)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"Modelo guardado en: {MODEL_PATH}")
    return pipeline


if __name__ == "__main__":
    train_model()
