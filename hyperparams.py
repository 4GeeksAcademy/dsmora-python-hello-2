"""Compara tres configuraciones de RandomForest en un problema desbalanceado."""

import numpy as np
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV


def main():
	# Muestra sintética con dimensiones y proporción de clases similares al caso:
	# 50 000 filas, 30 características y aproximadamente 10 % de positivos.
	X, y = make_classification(
		n_samples=50_000,
		n_features=30,
		n_informative=12,
		n_redundant=5,
		n_repeated=0,
		n_classes=2,
		weights=[0.90, 0.10],
		flip_y=0.01,
		class_sep=1.0,
		random_state=42,
	)

	print("Distribución de clases (total):")
	print(f"  Negativos: {np.count_nonzero(y == 0):,}")
	print(f"  Positivos: {np.count_nonzero(y == 1):,} ({y.mean():.1%})")
	print()

	model = RandomForestClassifier(
		n_estimators=100,
		min_samples_split=2,
		random_state=42,
		# GridSearchCV paraleliza las combinaciones; evita paralelismo anidado.
		n_jobs=1,
	)
	grid_params = {
		"class_weight": [None, "balanced", "balanced_subsample"],
		"max_depth": [5, 10],
		"min_samples_leaf": [1, 5],
		"max_features": ["sqrt", 0.3],
	}

	grid_search = GridSearchCV(
		estimator=model,
		param_grid=grid_params,
		scoring="recall",
		cv=3,
		n_jobs=-1,
		verbose=1,
	)
	grid_search.fit(X, y)

	print(f"Best parameters: {grid_search.best_params_}")
	print(f"Best CV score (recall): {grid_search.best_score_:.4f}")


if __name__ == "__main__":
	main()
