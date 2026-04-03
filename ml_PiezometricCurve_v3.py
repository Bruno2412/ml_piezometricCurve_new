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
# HYDRO AVEC RELAXATION (solution 4)
# ---------------------------
def apply_hydro_with_relaxation(prediction, levels, storage,
                               recharge_factor, recharge_maitrisee,
                               pumping, hydro_strength):

    adjusted = prediction.to_numpy().copy()
    equilibrium = np.mean(levels)

    for i in range(len(adjusted)):
        recharge_naturelle = recharge_factor * np.sin(2*np.pi*i/12)
        recharge_totale = recharge_naturelle + recharge_maitrisee
        hydro_effect = (recharge_totale - pumping) / storage

        relaxation = -0.05 * (adjusted[i] - equilibrium)

        adjusted[i] += hydro_effect * hydro_strength + relaxation

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
# ETS SOLUTIONS
# ---------------------------

# Solution 1 : stable (pas de tendance)
def ets_solution_1(levels, steps):
    model = ExponentialSmoothing(levels,
                                 trend=None,
                                 seasonal='add',
                                 seasonal_periods=12)
    return model.fit().forecast(steps)

# Solution 2 : cycle pluriannuel
def add_multi_year_cycle(prediction, amplitude=0.3, period_years=6):
    adjusted = prediction.copy()
    for i in range(len(adjusted)):
        adjusted.iloc[i] += amplitude * np.sin(2*np.pi*i/(12*period_years))
    return adjusted

# Solution 3 : recentrage
def recenter_prediction(prediction, levels):
    mean_level = levels.mean()
    return prediction - prediction.mean() + mean_level

# ---------------------------
# ETP (Thornthwaite simplifié)
# ---------------------------
def compute_etp(dates, temp):
    etp = []
    for i in range(len(temp)):
        T = temp.iloc[i]
        if T < 0:
            etp.append(0)
        else:
            etp.append(16 * (T / 5) ** 1.514)
    return pd.Series(etp, index=dates)

# ---------------------------
# BILAN HYDRIQUE
# ---------------------------
def compute_recharge(rainfall, etp, soil_capacity=100):
    storage = 0
    recharge = []

    for i in range(len(rainfall)):
        P = rainfall.iloc[i]
        E = etp.iloc[i]

        storage += P - E

        if storage > soil_capacity:
            recharge.append(storage - soil_capacity)
            storage = soil_capacity
        else:
            recharge.append(0)

        if storage < 0:
            storage = 0

    return pd.Series(recharge, index=rainfall.index)

# ---------------------------
# MODELE HYDRO COMPLET
# ---------------------------
def simulate_groundwater_full(levels, recharge, steps,
                             storage_coeff=0.05,
                             recession_coeff=0.02,
                             pumping=0.0):

    h = levels.iloc[-1]
    h_eq = levels.mean()

    preds = []
    recharge_vals = recharge.values
    n = len(recharge_vals)

    for i in range(steps):
        R = recharge_vals[i % n] / 1000  # mm → m
        dh = (R - pumping)/storage_coeff - recession_coeff*(h - h_eq)
        h = h + dh
        preds.append(h)

    return pd.Series(preds)

# ---------------------------
# CALIBRATION NSE
# ---------------------------
def nash_sutcliffe(obs, sim):
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def calibrate_model(levels, recharge):

    best_score = -np.inf
    best_params = (0.05, 0.02)

    for storage in np.linspace(0.01, 0.1, 5):
        for recession in np.linspace(0.005, 0.05, 5):

            sim = simulate_groundwater_full(levels, recharge, len(levels),
                                            storage, recession)

            score = nash_sutcliffe(levels.values[-len(sim):], sim.values)

            if score > best_score:
                best_score = score
                best_params = (storage, recession)

    print(f"NSE calibration = {best_score:.2f}")
    return best_params

# ---------------------------
# SCENARIO CLIMAT
# ---------------------------
def generate_climate_scenario(rainfall, temp, factor=1.1):
    rain_future = rainfall * factor
    temp_future = temp + 1.5
    return rain_future, temp_future


# ---------------------------
# MODELES
# ---------------------------
def model_arima(levels, steps):
    return ARIMA(levels, order=(1,1,1)).fit().forecast(steps=steps)

def model_ets(levels, steps):
    model = ExponentialSmoothing(levels,
                                 trend='add',
                                 damped_trend=True,
                                 seasonal='add',
                                 seasonal_periods=12)
    return model.fit().forecast(steps)

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
              model_choice="ARIMA",
              ets_option="1"):

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

        if ets_option == "1":
            prediction = ets_solution_1(levels, steps)
            name = "ETS Stable"

        elif ets_option == "2":
            prediction = model_ets(levels, steps)
            prediction = add_multi_year_cycle(prediction)
            name = "ETS + Cycle long"

        elif ets_option == "3":
            prediction = model_ets(levels, steps)
            prediction = recenter_prediction(prediction, levels)
            name = "ETS recentré"

        elif ets_option == "4":
            prediction = model_ets(levels, steps)
            prediction = apply_hydro_with_relaxation(prediction,
                                                     levels,
                                                     storage,
                                                     recharge_factor,
                                                     recharge_maitrisee,
                                                     pumping,
                                                     hydro_strength)
            name = "ETS + Hydro réaliste"
        else:
            print("Option ETS invalide")
            return

    elif model_choice == "RandomForest":
        prediction = model_rf(levels, steps, rainfall)
        name = "RandomForest"

    elif model_choice == "XGBoost":
        prediction = model_xgb(levels, steps, rainfall)
        name = "XGBoost"

    else:
        print("Choix invalide")
        return

    # appliquer hydro sauf si solution 4
    if not (model_choice == "ETS" and ets_option == "4"):
        prediction = apply_hydro_model(prediction,
                                      storage,
                                      recharge_factor,
                                      recharge_maitrisee,
                                      pumping,
                                      hydro_strength)

    plot_result(dates, levels, prediction, name, years_validation)

# ---------------------------
# GUI
# ---------------------------
def launch_gui():

    def run():
        try:
            model_choice = model_var.get()
            ets_option = ets_var.get()

            recharge = float(entry_recharge.get())
            pumping_val = float(entry_pumping.get())
            years = int(entry_years.get())
            years_val = int(entry_validation.get())

            run_model(years, recharge, pumping_val, years_val,
                      model_choice, ets_option)

        except Exception as e:
            print("Erreur :", e)

    root = tk.Tk()
    root.title("Modèle Piézométrique")

    ttk.Label(root, text="Modèle").grid(row=0, column=0)
    model_var = tk.StringVar(value="ARIMA")
    ttk.Combobox(root, textvariable=model_var,
                 values=["ARIMA","ETS","RandomForest","XGBoost"],
                 state="readonly").grid(row=0, column=1)

    ttk.Label(root, text="Option ETS").grid(row=0, column=2)
    ets_var = tk.StringVar(value="1")
    ttk.Combobox(root, textvariable=ets_var,
                 values=["1","2","3","4"],
                 state="readonly").grid(row=0, column=3)

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