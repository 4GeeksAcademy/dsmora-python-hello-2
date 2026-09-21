# Este programa entrena un clasificador Naive Bayes con datos de flores Iris
# y utiliza lo aprendido para predecir la especie de flores nuevas.

# Importa la función que carga el conjunto de datos Iris incluido en scikit-learn.
# Iris contiene medidas de flores y las especies a las que pertenecen.
from sklearn.datasets import load_iris

# Importa el modelo Gaussian Naive Bayes, un algoritmo que sirve para clasificar
# ejemplos en diferentes categorías, en este caso, especies de flores.
from sklearn.naive_bayes import GaussianNB


# Este bloque se ejecuta únicamente cuando ejecutamos directamente este archivo,
# por ejemplo, mediante el comando: python main.py.
if __name__ == "__main__":
    # Carga el conjunto de datos Iris. El objeto iris contiene las características,
    # las etiquetas numéricas y los nombres de las especies.
    iris = load_iris()

    # X contiene las características o medidas de las flores. Cada fila representa
    # una flor y las cuatro columnas son: longitud y anchura del sépalo, y longitud
    # y anchura del pétalo.
    #
    # y contiene las etiquetas correctas de cada flor. Las etiquetas son números:
    # 0 representa setosa, 1 representa versicolor y 2 representa virginica.
    # El modelo necesita X e y para aprender la relación entre medidas y especies.
    X, y = iris.data, iris.target

    # Crea un modelo Gaussian Naive Bayes vacío. En este momento el modelo todavía
    # no conoce ningún patrón ni sabe clasificar flores.
    model = GaussianNB()

    # Entrena el modelo con las características X y las respuestas correctas y.
    # El método fit analiza los ejemplos y aprende estadísticas y patrones que
    # después utilizará para clasificar flores que no ha visto anteriormente.
    model.fit(X, y)

    # Define dos flores nuevas. Cada muestra contiene las cuatro medidas en el
    # mismo orden utilizado por el conjunto de datos durante el entrenamiento:
    # [longitud sépalo, anchura sépalo, longitud pétalo, anchura pétalo].
    new_samples = [
        [5.1, 3.5, 1.4, 0.2],
        [6.7, 3.0, 5.2, 2.3],
    ]

    # Utiliza el modelo ya entrenado para clasificar las flores nuevas.
    # predict devuelve números, por ejemplo 0, 1 o 2, que representan las especies.
    predictions = model.predict(new_samples)

    # Recorre todas las predicciones. enumerate también proporciona el número de
    # cada muestra y start=1 hace que la numeración empiece en 1, no en 0.
    for i, prediction in enumerate(predictions, start=1):
        # Convierte la predicción numérica en el nombre de la especie. Por ejemplo,
        # target_names[0] devuelve "setosa" y target_names[2] devuelve "virginica".
        species = iris.target_names[prediction]

        # Muestra en pantalla el número de la muestra y la especie predicha.
        print(f"Sample {i}: {species}")
