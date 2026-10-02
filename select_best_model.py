from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
import numpy as np

# Load dataset
cancer = load_breast_cancer()
X = cancer.data
Y = cancer.target

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

# Build pipeline
pipe = Pipeline([
    ('scaler', StandardScaler()),
    ('model', RandomForestClassifier(random_state=42))
])

# Define parameter distribution
param_dist = {
    'model__n_estimators': np.arange(10, 201, 10),
    'model__max_depth': [None] + list(np.arange(5, 21, 5)),
    'model__min_samples_split': np.arange(2, 11)
}

# Setup RandomizedSearchCV
search = RandomizedSearchCV(
    pipe,
    param_distributions=param_dist,
    n_iter=20,
    scoring='recall',
    cv=5,
    random_state=42
)

# Fit search
search.fit(X_train, y_train)

# Evaluate best estimator
best_model = search.best_estimator_
preds = best_model.predict(X_test)

print("Best parameters:", search.best_params_)
print("CV Recall score:", round(search.best_score_, 4))
print("Test accuracy:", round(accuracy_score(y_test, preds), 4))
