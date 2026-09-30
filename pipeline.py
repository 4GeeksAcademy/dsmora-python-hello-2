from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
import joblib

# Load dataset
cancer = load_breast_cancer()
X = cancer.data
Y = cancer.target

# Split dataset into train and test sets
X_train, X_test, y_train, y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

# # TODO: Build a Pipeline with two steps: a StandardScaler named 'scaler'
# # and a RandomForestClassifier named 'clf'.
# pipe = Pipeline([
#     ('scaler', StandardScaler()),
#     ('clf', RandomForestClassifier())
# ])

# # TODO: Fit the pipeline on the training data (this trains the scaler and the classifier together).
# pipe.fit(X_train, y_train)

# # TODO: Serialize the fitted pipeline to a file named 'model_pipeline.joblib' using joblib.dump.
# joblib.dump(pipe, 'model_pipeline.joblib')

# TODO: Load the pipeline back from disk with joblib.load.
loaded_pipe = joblib.load('model_pipeline.joblib')

# TODO: Evaluate loaded_pipe on the test set and print the accuracy
# formatted to four decimal places, e.g. "Test accuracy: 0.9649".
accuracy = loaded_pipe.score(X_test, y_test)
predict = loaded_pipe.predict(X_test)
print(f"Test accuracy: {accuracy:.4f}")
print(f"Predictions: {predict}")
