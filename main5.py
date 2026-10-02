from pathlib import Path

import joblib
from prefect import flow, task
from sklearn.datasets import load_breast_cancer

MODEL_PATH = "model_pipeline.joblib"


@task
def load_model(path):
    """Carga desde disco la pipeline serializada."""
    return joblib.load(path)


@task(cache_policy="INPUTS", cache_expiration=3600)
def predict_batch(model, data):
    """Predice las etiquetas para un grupo de muestras."""
    return model.predict(data)


@flow
def run_predictions(model_path, data):
    """Coordina la carga del modelo y la predicción del lote."""
    model = load_model(model_path)
    predictions = predict_batch(model, data)

    for number, prediction in enumerate(predictions, start=1):
        label = "benigno" if prediction == 1 else "maligno"
        print(f"Muestra {number}: {label}")


def main():
    # Cargar cinco muestras para demostrar la inferencia.
    dataset = load_breast_cancer()
    samples = dataset.data[:5]

    if not Path(MODEL_PATH).is_file():
        raise FileNotFoundError(
            f"No se encontró {MODEL_PATH}. Primero debes obtener o entrenar y "
            "guardar una pipeline compatible en esa ruta."
        )

    # Ejecutar el flow de Prefect para cargar el modelo y predecir las muestras.
    run_predictions(MODEL_PATH, samples)


if __name__ == "__main__":
    main()
