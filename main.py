import numpy as np
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

# Generate an imbalanced dataset
X, y = make_classification(n_samples=1000, n_features=20, n_classes=2,
                           weights=[0.95, 0.05], flip_y=0, random_state=42)

# Split into train and test sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

counts = np.bincount(y_train)
print(f"Class distribution in training: class 0 = {counts[0]}, class 1 = {counts[1]}")
print()

# Best configuration found: class_weight 1:20 with threshold 0.3
model = RandomForestClassifier(
    n_estimators=300,
    class_weight={0: 1.0, 1: 20.0},
    max_depth=10,
    min_samples_split=2,
    min_samples_leaf=2,
    random_state=42
)

model.fit(X_train, y_train)
probabilities = model.predict_proba(X_test)[:, 1]
predictions = (probabilities >= 0.3).astype(int)
print(classification_report(y_test, predictions))
