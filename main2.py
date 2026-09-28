# Import necessary libraries
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

# Load dataset
iris = load_iris()
X = iris.data
y = iris.target

# Split dataset into training and test sets with stratification and 80/20 split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

# Initialize classifiers with appropriate hyperparameters
clf_tree = DecisionTreeClassifier(max_depth=5, random_state=42)
clf_logreg = LogisticRegression(max_iter=200, random_state=42)
clf_rf = RandomForestClassifier(n_estimators=100, random_state=42)

# Train classifiers
clf_tree.fit(X_train, y_train)
clf_logreg.fit(X_train, y_train)
clf_rf.fit(X_train, y_train)

# Predict on test set
pred_tree = clf_tree.predict(X_test)
pred_logreg = clf_logreg.predict(X_test)
pred_rf = clf_rf.predict(X_test)

# Calculate accuracy
acc_tree = accuracy_score(y_test, pred_tree)
acc_logreg = accuracy_score(y_test, pred_logreg)
acc_rf = accuracy_score(y_test, pred_rf)

# Print accuracy scores
print(f"Decision Tree accuracy: {acc_tree:.2f}")
print(f"Logistic Regression accuracy: {acc_logreg:.2f}")
print(f"Random Forest accuracy: {acc_rf:.2f}")
