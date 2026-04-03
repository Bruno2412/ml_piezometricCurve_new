import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import ttk

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

# ---------------------------
# FEATURES POUR ML
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
def apply_hydro_model(prediction, storage, recharge_factor,
                      recharge_maitrisee, pumping, hydro_strength):

    adjusted = prediction.to_numpy().copy()

    for i in range(len(adjusted)):
        recharge_naturelle = recharge_factor * np.sin(2*np.pi*i/12)
        recharge_totale = recharge_naturelle + recharge_maitrisee
        hydro_effect = (recharge_totale - pumping) / storage
        adjusted[i] += hydro_effect * hydro_strength

    return pd.Series(adjusted, index=prediction.index)

# ---------------------------
# CALIBRATION
# ---------------------------
def calibrate_params(levels):
    std = np.std(levels)
    storage = max(0.01, min(0.1, std / 10))
    recharge_factor = std / 20
    hydro_strength = 0.2
    return storage, recharge_factor, hydro_strength

# ---------------------------
# MODELES
# ---------------------------
def model_arima(levels, steps):
    model = ARIMA(levels, order=(1,1,1))
    res = model.fit()
    return res.forecast(steps=steps)

def model_ets(levels, steps):
    model = ExponentialSmoothing(levels,
                                 trend='add',
                                 damped_trend=True,
                                 seasonal='add',
                                 seasonal_periods=12)
    res = model.fit()
    return res.forecast(steps)

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

        X_pred = pd.DataFrame([features], columns=X.columns)
        pred = model.predict(X_pred)[0]
        preds.append(pred)
        last_values.append(pred)

    return pd.Series(preds)

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
def plot_result(dates, levels, prediction, model_name, years_validation):

    plt.figure(figsize=(14,6))
    plt.plot(dates, levels, label="Observé")

    months = years_validation * 12
    cutoff = dates.iloc[-months]

    plt.axvspan(cutoff, dates.iloc[-1],
                color='gray', alpha=0.2,
                label=f"Validation ({years_validation} ans)")

    last_date = dates.iloc[-1]

    future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1),
                                periods=len(prediction), freq='MS')

    plt.plot(future_dates, prediction, linestyle='--', label=model_name)

    plt.legend()
    plt.grid()
    plt.title(f"Prédiction avec {model_name}")
    plt.show()

# ---------------------------
# MAIN MODEL
# ---------------------------
def run_model(years_to_predict=5,
              recharge_maitrisee=0.0,
              pumping=0.0,
              years_validation=5,
              model_choice="ARIMA"):

    df = pd.read_excel("C:/Users/bruno.DESKTOP-I2NE6NI/OneDrive/Bureau/Projet_Courbes_piezo/chro_piezo_1995_2024_mensuelle.xlsx")

    dates = pd.to_datetime(df.iloc[:,0])
    levels = df.iloc[:,1].astype(float)

    rainfall = None
    steps = years_to_predict * 12

    storage, recharge_factor, hydro_strength = calibrate_params(levels)

    if model_choice == "ARIMA":
        prediction = model_arima(levels, steps)
        name = "ARIMA"

    elif model_choice == "ETS":
        prediction = model_ets(levels, steps)
        name = "ETS"

    elif model_choice == "RandomForest":
        prediction = model_rf(levels, steps, rainfall)
        name = "RandomForest"

    elif model_choice == "XGBoost":
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

# ---------------------------
# GUI
# ---------------------------
def launch_gui():

    def run():
        try:
            model_choice = model_var.get()
            recharge = float(entry_recharge.get())
            pumping_val = float(entry_pumping.get())
            years = int(entry_years.get())
            years_val = int(entry_validation.get())

            run_model(years, recharge, pumping_val, years_val, model_choice)

        except Exception as e:
            print("Erreur :", e)

    root = tk.Tk()
    root.title("Modèle Piézométrique")

    ttk.Label(root, text="Modèle").grid(row=0, column=0)
    model_var = tk.StringVar(value="ARIMA")
    ttk.Combobox(root, textvariable=model_var,
                 values=["ARIMA","ETS","RandomForest","XGBoost"],
                 state="readonly").grid(row=0, column=1)

    ttk.Label(root, text="Recharge maîtrisée").grid(row=1, column=0)
    entry_recharge = ttk.Entry(root)
    entry_recharge.insert(0, "0.5")
    entry_recharge.grid(row=1, column=1)

    ttk.Label(root, text="Pompage").grid(row=2, column=0)
    entry_pumping = ttk.Entry(root)
    entry_pumping.insert(0, "0.0")
    entry_pumping.grid(row=2, column=1)

    ttk.Label(root, text="Années prédiction").grid(row=3, column=0)
    entry_years = ttk.Entry(root)
    entry_years.insert(0, "5")
    entry_years.grid(row=3, column=1)

    ttk.Label(root, text="Années validation").grid(row=4, column=0)
    entry_validation = ttk.Entry(root)
    entry_validation.insert(0, "5")
    entry_validation.grid(row=4, column=1)

    ttk.Button(root, text="Lancer", command=run)\
        .grid(row=5, column=0, columnspan=2)

    root.mainloop()

# ---------------------------
# MAIN
# ---------------------------
if __name__ == '__main__':
    launch_gui()