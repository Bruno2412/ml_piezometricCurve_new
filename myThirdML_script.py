import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

# ---------------------------
# FEATURES POUR ML (pluie optionnelle)
# ---------------------------
def create_features(series, rainfall=None, lags=12):
    df = pd.DataFrame(series.copy())
    df.columns = ["y"]

    for i in range(1, lags+1):
        df[f"lag_{i}"] = df["y"].shift(i)

    if rainfall is not None:
        df["rain"] = rainfall

    return df.dropna().astype(float)

# ---------------------------
# MODELE HYDROGEO
# ---------------------------
def apply_hydro_model(prediction,
                      storage,
                      recharge_factor,
                      recharge_maitrisee,
                      pumping,
                      hydro_strength):

    adjusted = prediction.to_numpy().copy()

    for i in range(len(adjusted)):
        recharge_naturelle = recharge_factor * np.sin(2*np.pi*i/12)
        recharge_totale = recharge_naturelle + recharge_maitrisee

        hydro_effect = (recharge_totale - pumping) / storage
        adjusted[i] = adjusted[i] + hydro_effect * hydro_strength

    return pd.Series(adjusted, index=prediction.index)

# ---------------------------
# CALIBRATION AUTOMATIQUE
# ---------------------------
def calibrate_params(levels):
    std = np.std(levels)

    storage = max(0.01, min(0.1, std / 10))
    recharge_factor = std / 20
    hydro_strength = 0.2

    return storage, recharge_factor, hydro_strength

# ---------------------------
# ARIMA
# ---------------------------
def model_arima(levels, steps):
    model = ARIMA(levels, order=(1,1,1))
    res = model.fit()
    return res.forecast(steps=steps)

# ---------------------------
# ETS
# ---------------------------
def model_ets(levels, steps):
    model = ExponentialSmoothing(levels,
                                 trend='add',
                                 seasonal='add',
                                 seasonal_periods=12)
    res = model.fit()
    return res.forecast(steps)

# ---------------------------
# RANDOM FOREST
# ---------------------------
def model_rf(levels, steps, rainfall=None):
    df = create_features(levels, rainfall)
    X = df.drop(columns=["y"])
    y = df["y"]

    model = RandomForestRegressor()
    model.fit(X, y)

    last_values = levels[-12:].values.tolist()
    preds = []

    for _ in range(steps):
        features = last_values[-12:]
        if rainfall is not None:
            features = features + [rainfall.iloc[-1]]

        feature_names = X.columns
        X_pred = pd.DataFrame([features], columns=feature_names)
        pred = model.predict(X_pred)[0]
        preds.append(pred)
        last_values.append(pred)

    return pd.Series(preds)

# ---------------------------
# XGBOOST
# ---------------------------
def model_xgb(levels, steps, rainfall=None):
    df = create_features(levels, rainfall)
    X = df.drop(columns=["y"])
    y = df["y"]

    model = XGBRegressor()
    model.fit(X, y)

    last_values = levels[-12:].values.tolist()
    preds = []

    for _ in range(steps):
        features = last_values[-12:]
        if rainfall is not None:
            features = features + [rainfall.iloc[-1]]

        X_pred = np.array(features).reshape(1, -1)
        pred = model.predict(X_pred)[0]
        preds.append(pred)
        last_values.append(pred)

    return pd.Series(preds)

# ---------------------------
# GRAPHIQUE
# ---------------------------
def plot_result(dates, levels, prediction, model_name, years_validation=5):

    plt.figure(figsize=(14,6))
    plt.plot(dates, levels, label="Observé")

    # zone validation (5 ans)
    months = years_validation * 12
    cutoff = dates.iloc[-months]

    plt.axvspan(cutoff, dates.iloc[-1], color='gray', alpha=0.2, label="Validation (5 ans)")

    last_date = dates.iloc[-1]

    future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1),
                                periods=len(prediction), freq='MS')

    plt.plot(future_dates, prediction, linestyle='--', label=model_name)

    plt.legend()
    plt.grid()
    plt.title(f"Prédiction avec {model_name}")
    plt.show()

# ---------------------------
# CHOIX DU MODELE
# ---------------------------
def choose_model():
    print("\nChoisis un modèle :")
    print("1 - ARIMA")
    print("2 - ETS")
    print("3 - Random Forest")
    print("4 - XGBoost")

    return input("Ton choix : ")

# ---------------------------
# MAIN
# ---------------------------
def run_model(years_to_predict=5,
              recharge_maitrisee=0.0,
              pumping=0.0,
              years_validation=5):

    df = pd.read_excel("C:/Users/bruno.DESKTOP-I2NE6NI/OneDrive/Bureau/Projet_Courbes_piezo/chro_piezo_1995_2024_mensuelle.xlsx")

    dates = pd.to_datetime(df.iloc[:,0])
    levels = df.iloc[:,1].astype(float)

    rainfall = None

    steps = years_to_predict * 12

    storage, recharge_factor, hydro_strength = calibrate_params(levels)

    choice = choose_model()

    if choice == "1":
        prediction = model_arima(levels, steps)
        name = "ARIMA"

    elif choice == "2":
        prediction = model_ets(levels, steps)
        name = "ETS"

    elif choice == "3":
        prediction = model_rf(levels, steps, rainfall)
        name = "RandomForest"

    elif choice == "4":
        prediction = model_xgb(levels, steps, rainfall)
        name = "XGBoost"

    else:
        print("Choix invalide")
        return

    prediction = apply_hydro_model(prediction,
                                   storage,
                                   recharge_factor,
                                   recharge_maitrisee,
                                   pumping,
                                   hydro_strength)

    plot_result(dates, levels, prediction, name + " + Hydro", years_validation)


if __name__ == '__main__':
    run_model(years_to_predict=5,
              recharge_maitrisee=0.5,
              pumping=0.0)