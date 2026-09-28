import pandas as pd
from sklearn.datasets import fetch_california_housing
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import xgboost as xgb

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
print(f"Linear Regression MSE: {mean_squared_error(y_test, lr_preds):.2f}, R2: {r2_score(y_test, lr_preds):.2f}")
print(f"Random Forest MSE: {mean_squared_error(y_test, rf_preds):.2f}, R2: {r2_score(y_test, rf_preds):.2f}")
print(f"XGBoost        MSE: {mean_squared_error(y_test, xgb_preds):.2f}, R2: {r2_score(y_test, xgb_preds):.2f}")
