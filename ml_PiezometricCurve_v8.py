import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.filedialog import askopenfilename
from dateutil.relativedelta import relativedelta

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor


# ---------------------------
# FEATURES ET MODÈLES ML
# ---------------------------
def create_features(series, lags=12):
    df_y = pd.DataFrame(series.copy())
    df_y.columns = ["y"]
    lag_cols = []
    for i in range(1, lags + 1):
        col = df_y["y"].shift(i).rename(f"lag_{i}")
        lag_cols.append(col)
    df = pd.concat([df_y] + lag_cols, axis=1)
    return df.dropna().astype(float)


def model_rf(levels, steps, points_per_year):
    df = create_features(levels, lags=points_per_year)
    X = df.drop(columns=["y"])
    y = df["y"]
    feature_names = X.columns.tolist()
    model = RandomForestRegressor(n_estimators=100, random_state=42).fit(X, y)
    curr_values = levels[-points_per_year:].values.tolist()
    preds = []
    for _ in range(steps):
        X_pred_raw = np.array(curr_values[-points_per_year:]).reshape(1, -1)
        X_pred_df = pd.DataFrame(X_pred_raw, columns=feature_names)
        p = model.predict(X_pred_df)[0]
        preds.append(p)
        curr_values.append(p)
    return np.array(preds)


def model_xgb(levels, steps, points_per_year):
    df = create_features(levels, lags=points_per_year)
    X, y = df.drop(columns=["y"]), df["y"]
    model = XGBRegressor(n_estimators=100).fit(X, y)
    curr_values = levels[-points_per_year:].values.tolist()
    preds = []
    for _ in range(steps):
        X_pred = np.array(curr_values[-points_per_year:]).reshape(1, -1)
        p = model.predict(X_pred)[0]
        preds.append(p)
        curr_values.append(p)
    return np.array(preds)


# ---------------------------
# LOGIQUE HYDRO
# ---------------------------
def add_natural_cycle(prediction_series, amplitude=0.4, period_years=7):
    n = len(prediction_series)
    x = np.arange(n)
    variation = 1 + 0.2 * np.sin(2 * np.pi * x / (12 * period_years * 3))
    cycle = amplitude * np.sin(2 * np.pi * x / (12 * period_years)) * variation
    drift = np.cumsum(np.random.normal(0, 0.005, n))
    noise = np.random.normal(0, amplitude * 0.1, n)
    return prediction_series + cycle + drift + noise


def apply_hydro_model(prediction_series, storage, recharge_factor, recharge_maitrisee, pumping, hydro_strength,
                      points_per_year, last_obs_date):
    adjusted = prediction_series.values.copy()
    dates = prediction_series.index
    cumul_impact = 0.0
    s_val = storage if storage > 0 else 0.02
    for i in range(len(adjusted)):
        oscillation = recharge_factor * np.sin(2 * np.pi * i / points_per_year)
        adjusted[i] += oscillation
        if dates[i] > last_obs_date:
            flux_net = (recharge_maitrisee - pumping) / 12
            cumul_impact += (flux_net / s_val) * hydro_strength
        adjusted[i] += cumul_impact
    return pd.Series(adjusted, index=prediction_series.index)


def calibrate_params(levels):
    std = np.std(levels)
    return max(0.01, min(0.1, std / 10)), std / 20, 0.2


# ---------------------------
# AFFICHAGE
# ---------------------------
def plot_result_v3(dates_hist, levels_hist, prediction_series, start_val_date, model_name, mape, erreur, mae):
    plt.figure(figsize=(15, 8))

    # Courbe Observée
    plt.plot(dates_hist, levels_hist, label="Observé (Historique)", color='tab:blue', alpha=0.6, linewidth=1.5)

    # Zone d'incertitude et Courbe de Prédiction
    plt.fill_between(prediction_series.index, prediction_series - erreur, prediction_series + erreur,
                     color='tab:red', alpha=0.15, label=f"Incertitude (±{erreur:.2f} m)")
    plt.plot(prediction_series.index, prediction_series, label=f"Prédiction {model_name}",
             color='tab:red', linestyle='--', linewidth=2)

    # Zone de validation
    plt.axvspan(start_val_date, dates_hist.max(), color='gray', alpha=0.15, label="Période de Validation")

    # Placement des statistiques (Badge)
    text_x = start_val_date + pd.DateOffset(months=6)
    y_max = max(levels_hist.max(), prediction_series.max())
    color_box = 'green' if mape <= 1 else 'orange' if mape <= 5 else 'red'

    stats_text = f"MAPE: {mape:.2f}%\nMAE: {mae:.2f} m\nIncertitude: ±{erreur:.2f} m"
    plt.text(text_x, y_max, stats_text, fontsize=10, fontweight='bold', color='white',
             bbox=dict(facecolor=color_box, alpha=0.8, boxstyle='round,pad=0.5'))

    plt.title(f"Analyse Piézométrique : {model_name}", fontsize=14, fontweight='bold')
    plt.ylabel("Niveau (m NGF)")
    plt.xlabel("Années")
    plt.legend(loc='upper left', frameon=True)
    plt.grid(True, which='both', linestyle=':', alpha=0.5)

    ax = plt.gca()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(base=5))

    plt.tight_layout()
    plt.show()


# ---------------------------
# COEUR DU CALCUL
# ---------------------------
def run_model(years_to_predict, recharge_maitrisee, pumping, years_validation, model_choice, ets_option, parent_root):
    file_path = askopenfilename(title="Choisir le fichier Excel", filetypes=[("Excel", "*.xlsx")])
    if not file_path: return

    loading_screen = tk.Toplevel(parent_root)
    loading_screen.title("Patience...")
    loading_screen.geometry("300x100")
    loading_screen.transient(parent_root)
    loading_screen.grab_set()

    label = tk.Label(loading_screen, text="\nTraitement des données en cours...\nVeuillez patienter.",
                     font=("Helvetica", 10))
    label.pack()
    parent_root.update()

    try:
        # Chargement et nettoyage
        df = pd.read_excel(file_path)
        df_clean = pd.DataFrame({
            'date': pd.to_datetime(df.iloc[:, 4]),
            'level': df.iloc[:, 6].astype(float)
        }).sort_values('date').set_index('date')

        last_obs_date = df_clean.index.max()
        start_val_date = last_obs_date - relativedelta(years=years_validation)
        train_data = df_clean[df_clean.index < start_val_date]['level']

        points_per_year = 12
        steps_total = int((years_validation + years_to_predict) * points_per_year)
        storage, r_factor, h_strength = calibrate_params(df_clean['level'])

        # 1. Prédiction brute selon modèle
        if model_choice == "ARIMA":
            raw = ARIMA(train_data.values, order=(1, 1, 1)).fit().forecast(steps=steps_total)
        elif model_choice == "ETS":
            trend = None if ets_option == "1" else 'add'
            raw = ExponentialSmoothing(train_data.values, trend=trend, seasonal='add',
                                       seasonal_periods=12).fit().forecast(steps_total)
        elif model_choice == "RandomForest":
            raw = model_rf(train_data, steps_total, points_per_year)
        else:
            raw = model_xgb(train_data, steps_total, points_per_year)

        # Dates de prédiction
        pred_dates = pd.date_range(start=start_val_date + pd.DateOffset(months=1), periods=steps_total, freq='MS')
        prediction = pd.Series(raw, index=pred_dates)

        if model_choice == "ETS" and ets_option == "2":
            prediction = add_natural_cycle(prediction, amplitude=0.4, period_years=7)

        # Application des paramètres hydrogéologiques
        prediction = apply_hydro_model(prediction, storage, r_factor, recharge_maitrisee, pumping, h_strength,
                                       points_per_year, last_obs_date)

        # --- NOUVEAU CALCUL DE LA MAPE SUR TOUTE LA TEMPORALITÉ COMMUNE ---
        # On crée un DataFrame temporaire pour aligner exactement les dates communes (bleue vs rouge)
        comparison_df = pd.DataFrame({
            'observe': df_clean['level'],
            'predit': prediction
        }).dropna()

        if not comparison_df.empty:
            y_obs = comparison_df['observe'].values
            y_pred = comparison_df['predit'].values

            # Calcul de la MAPE point par point sur la coordonnée x
            mape = np.mean(np.abs((y_obs - y_pred) / y_obs)) * 100
            # Calcul de la MAE (Erreur moyenne absolue en mètres)
            mae = np.mean(np.abs(y_obs - y_pred))
            # Écart-type des résidus (Incertitude)
            std_err = np.nanstd(y_obs - y_pred)
        else:
            mape, mae, std_err = 0, 0, 0

        loading_screen.destroy()

        # Affichage final
        plot_result_v3(df_clean.index, df_clean['level'], prediction, start_val_date,
                       model_choice, mape, std_err, mae)

    except Exception as e:
        if loading_screen.winfo_exists(): loading_screen.destroy()
        messagebox.showerror("Erreur", f"Une erreur est survenue :\n{e}")


# ---------------------------
# INTERFACE
# ---------------------------
def launch_gui():
    root = tk.Tk()
    root.title("Expert Piézométrie v3")

    fields = [("Modèle", ["ARIMA", "ETS", "RandomForest", "XGBoost"]),
              ("Option ETS (1-4)", ["1", "2", "3", "4"]),
              ("Recharge maîtrisée (m)", "0.5"),
              ("Pompage (m)", "0.0"),
              ("Années futur", "10"),
              ("Années validation", "15")]

    vars = {}
    for i, (label, default) in enumerate(fields):
        ttk.Label(root, text=label).grid(row=i, column=0, padx=10, pady=5)
        var = tk.StringVar(value=default[0] if isinstance(default, list) else default)
        if isinstance(default, list):
            ttk.Combobox(root, textvariable=var, values=default, state="readonly").grid(row=i, column=1)
        else:
            ttk.Entry(root, textvariable=var).grid(row=i, column=1)
        vars[label] = var

    ttk.Button(root, text="Lancer l'Analyse", command=lambda: run_model(
        int(vars["Années futur"].get()), float(vars["Recharge maîtrisée (m)"].get()),
        float(vars["Pompage (m)"].get()), int(vars["Années validation"].get()),
        vars["Modèle"].get(), vars["Option ETS (1-4)"].get(), root)).grid(row=len(fields), columnspan=2, pady=20)

    root.mainloop()


if __name__ == '__main__':
    launch_gui()