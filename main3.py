import pandas as pd
import matplotlib.pyplot as plt
from sklearn.datasets import fetch_california_housing
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
from scipy.stats import normaltest
import xgboost as xgb
from sklearn.model_selection import learning_curve

# Load the house-price dataset (already prepared for you; 'price' is the target column)
data = fetch_california_housing()
house_data = pd.DataFrame(data.data, columns=data.feature_names)
house_data['price'] = data.target

# Drop rows with null values
clean_data = house_data.dropna()

# Separate features and target
X = clean_data.drop(columns=['price'])
y = clean_data['price']

# Split data into train and test sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)


# Scale features
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Train Linear Regression model
lr_model = LinearRegression()
lr_model.fit(X_train_scaled, y_train)

# Train Random Forest Regressor
rf_model = RandomForestRegressor(n_estimators=100, random_state=42)
rf_model.fit(X_train_scaled, y_train)

# Train XGBoost Regressor
xgb_model = xgb.XGBRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
xgb_model.fit(X_train_scaled, y_train)

# Predict on test set
lr_preds = lr_model.predict(X_test_scaled)
rf_preds = rf_model.predict(X_test_scaled)
xgb_preds = xgb_model.predict(X_test_scaled)

# Calculate and print Mean Squared Error and R2 score
# Calculate residuals for K2 (D'Agostino-Pearson) normality test
lr_residuals = y_test - lr_preds
rf_residuals = y_test - rf_preds
xgb_residuals = y_test - xgb_preds

# K2: tests if residuals follow a normal distribution
# H0: residuals are normal. Low K2 / high p-value = good.
lr_k2_stat, lr_k2_p = normaltest(lr_residuals)
rf_k2_stat, rf_k2_p = normaltest(rf_residuals)
xgb_k2_stat, xgb_k2_p = normaltest(xgb_residuals)

# print("\n=== MSE & R2 ===")
# print(f"Linear Regression   MSE: {mean_squared_error(y_test, lr_preds):.2f}, R2: {r2_score(y_test, lr_preds):.2f}")
# print(f"Random Forest       MSE: {mean_squared_error(y_test, rf_preds):.2f}, R2: {r2_score(y_test, rf_preds):.2f}")
# print(f"XGBoost             MSE: {mean_squared_error(y_test, xgb_preds):.2f}, R2: {r2_score(y_test, xgb_preds):.2f}")

# print("\n=== K2 Score (D'Agostino-Pearson) — Residual Normality ===")
# print(f"Linear Regression   K2={lr_k2_stat:.2f}, p-value={lr_k2_p:.2e} {'✅ Normal' if lr_k2_p > 0.05 else '❌ No normal'}")
# print(f"Random Forest       K2={rf_k2_stat:.2f}, p-value={rf_k2_p:.2e} {'✅ Normal' if rf_k2_p > 0.05 else '❌ No normal'}")
# print(f"XGBoost             K2={xgb_k2_stat:.2f}, p-value={xgb_k2_p:.2e} {'✅ Normal' if xgb_k2_p > 0.05 else '❌ No normal'}")

curve_model = make_pipeline(StandardScaler(), LinearRegression())
train_sizes, train_scores, val_scores = learning_curve(
	curve_model,
	X_train,
	y_train,
	cv=5,
	scoring='neg_mean_squared_error',
)

# sklearn uses negative loss scores so that larger scores are always better.
# Convert them back to MSE for plotting; this is a regression error, not an
# accuracy-based classification error.
train_error = -train_scores.mean(axis=1)
val_error = -val_scores.mean(axis=1)

plt.plot(train_sizes, train_error, label='Error de entrenamiento')
plt.plot(train_sizes, val_error, label='Error de validación')
plt.xlabel('Tamaño del conjunto de entrenamiento')
plt.ylabel('Error cuadrático medio (MSE)')
plt.legend()
plt.tight_layout()
plt.savefig('learning_curve.png', dpi=150, bbox_inches='tight')
plt.show()