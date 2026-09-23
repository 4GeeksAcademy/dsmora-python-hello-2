"""Predicción visual del precio de viviendas de California."""

# Importa la función que carga el conjunto de datos Wine incluido en scikit-learn.
# Wine contiene análisis químicos de vinos y la clase a la que pertenece cada uno.
from sklearn.datasets import fetch_california_housing
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split


def barra_precio(precio: float, maximo: float) -> str:
    """Crea una barra sencilla para visualizar un precio en la terminal."""
    longitud = max(1, round(precio / maximo * 30))
    return "█" * longitud


def pedir_vivienda() -> list[float] | None:
    """Pide al usuario las ocho características de una vivienda.

    Devuelve None cuando el usuario escribe ``salir`` o deja la entrada vacía.
    """
    print("\nIntroduce los datos de una zona residencial")
    print("Orden: " + ", ".join(FEATURE_NAMES))
    print("Ejemplo: 8.3, 41, 6.5, 1.0, 322, 2.5, 37.9, -122.4")

    texto = input("Datos (o 'salir'): ").strip()
    if not texto or texto.lower() in {"salir", "exit", "q"}:
        return None

    try:
        valores = [float(valor.strip()) for valor in texto.split(",")]
    except ValueError:
        print("Error: escribe solamente números separados por comas.")
        return pedir_vivienda()

    if len(valores) != len(FEATURE_NAMES):
        print(f"Error: debes introducir exactamente {len(FEATURE_NAMES)} valores.")
        return pedir_vivienda()

    return valores


FEATURE_NAMES = [
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
]


# Este bloque se ejecuta únicamente cuando ejecutamos directamente este archivo,
# por ejemplo, mediante el comando: python main.py.
if __name__ == "__main__":
    # Carga el dataset. La primera ejecución puede descargarlo y guardarlo en
    # la caché local de scikit-learn.
    housing = fetch_california_housing()

    # X contiene características de cada zona y y el precio medio de sus viviendas.
    # El precio está expresado en cientos de miles de dólares.
    X, y = housing.data, housing.target

    print("=== Predicción de precios de viviendas en California ===")
    print(f"Viviendas disponibles: {len(X):,}")
    print(f"Características: {', '.join(housing.feature_names)}")
    print("Precio objetivo: cientos de miles de dólares\n")

    # Reservamos una parte de los datos para evaluar el modelo con ejemplos
    # que no ha visto durante el entrenamiento.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Random Forest combina muchos árboles de decisión y funciona bien con
    # datos tabulares y relaciones no lineales.
    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    error = mean_absolute_error(y_test, predictions)
    score = r2_score(y_test, predictions)

    print("Resultados del modelo")
    print(f"Error medio: ${error * 100_000:,.0f}")
    print(f"Puntuación R²: {score:.2f}\n")

    print("Comparación: precio real frente a precio predicho")
    max_price = max(max(y_test[:8]), max(predictions[:8]))
    for i, (real, predicted) in enumerate(
        zip(y_test[:8], predictions[:8]), start=1
    ):
        print(f"\nVivienda {i}")
        print(f"  Real:     ${real * 100_000:>9,.0f} |{barra_precio(real, max_price)}")
        print(
            f"  Predicho: ${predicted * 100_000:>9,.0f} "
            f"|{barra_precio(predicted, max_price)}"
        )

    # A partir de aquí comienza la inferencia: el modelo ya está entrenado y
    # permite probar predicciones con datos escritos por el usuario.
    print("\n=== Prueba tu propio modelo ===")
    print("El modelo está listo para hacer inferencias.")
    while True:
        vivienda = pedir_vivienda()
        if vivienda is None:
            print("Fin del programa.")
            break

        precio = model.predict([vivienda])[0]
        print(f"\nPrecio estimado: ${precio * 100_000:,.0f}")
        print(f"Valor en el dataset: {precio:.2f} cientos de miles de dólares")
