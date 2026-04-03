import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename

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
    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df["y"].shift(i)
    if rainfall is not None:
        df["rain"] = rainfall
    return df.dropna().astype(float)


# ---------------------------
# MODELES HYDRO ET CORRECTIONS
# ---------------------------
# def apply_hydro_model(prediction, storage, recharge_factor, recharge_maitrisee, pumping, hydro_strength,
#                       points_per_year):
#     adjusted = prediction.to_numpy().copy()
#     for i in range(len(adjusted)):
#         recharge_naturelle = recharge_factor * np.sin(2 * np.pi * i / points_per_year)
#         recharge_totale = recharge_naturelle + recharge_maitrisee
#         hydro_effect = (recharge_totale - pumping) / storage
#         adjusted[i] += hydro_effect * hydro_strength
#     return pd.Series(adjusted, index=prediction.index)

def apply_hydro_model(prediction_series, storage, recharge_factor, recharge_maitrisee, pumping, hydro_strength,
                      points_per_year, last_obs_date):
    # 1. On s'assure de travailler sur les valeurs numériques pures
    base_values = prediction_series.values.copy()
    dates = prediction_series.index

    # 2. On prépare un tableau de correction de la même taille
    corrections = np.zeros(len(base_values))
    cumul_anthropique = 0
    s_val = storage if storage > 0 else 0.05

    for i in range(len(base_values)):
        # Oscillation saisonnière simple
        oscillation = recharge_factor * np.sin(2 * np.pi * i / points_per_year)

        # Cumul de recharge UNIQUEMENT si la date dépasse l'historique
        if dates[i] > last_obs_date:
            flux_mensuel = (recharge_maitrisee - pumping) / 12
            cumul_anthropique += (flux_mensuel / s_val) * hydro_strength

        corrections[i] = oscillation + cumul_anthropique

    # 3. On reconstruit la série avec l'index d'origine
    # L'addition base_values + corrections est sûre car ce sont deux arrays numpy
    return pd.Series(base_values + corrections, index=dates)

def apply_hydro_with_relaxation(prediction, levels, storage, recharge_factor, recharge_maitrisee, pumping,
                                hydro_strength, points_per_year):
    adjusted = prediction.to_numpy().copy()
    equilibrium = np.mean(levels)
    for i in range(len(adjusted)):
        recharge_naturelle = recharge_factor * np.sin(2 * np.pi * i / points_per_year)
        recharge_totale = recharge_naturelle + recharge_maitrisee
        hydro_effect = (recharge_totale - pumping) / storage
        relaxation = -0.05 * (adjusted[i] - equilibrium)
        adjusted[i] += hydro_effect * hydro_strength + relaxation
    return pd.Series(adjusted, index=prediction.index)


def calibrate_params(levels):
    std = np.std(levels)
    storage = max(0.01, min(0.1, std / 10))
    recharge_factor = std / 20
    hydro_strength = 0.2
    return storage, recharge_factor, hydro_strength


# ---------------------------
# SOLUTIONS DE PREDICTION
# ---------------------------
def add_multi_year_cycle(prediction, amplitude=0.3, period_years=6):
    adjusted = prediction.copy()
    for i in range(len(adjusted)):
        adjusted.iloc[i] += amplitude * np.sin(2 * np.pi * i / (12 * period_years))
    return adjusted


def recenter_prediction(prediction, levels):
    return prediction - prediction.mean() + levels.mean()


def model_arima(levels, steps):
    return ARIMA(levels, order=(1, 1, 1)).fit().forecast(steps=steps)


def model_ets_base(levels, steps, trend='add'):
    model = ExponentialSmoothing(levels, trend=trend, damped_trend=(trend == 'add'),
                                 seasonal='add', seasonal_periods=12)
    return model.fit().forecast(steps)


def model_rf(levels, steps, points_per_year):
    df = create_features(levels, lags=points_per_year)
    X, y = df.drop(columns=["y"]), df["y"]
    model = RandomForestRegressor(n_estimators=100).fit(X, y)

    curr_values = levels[-points_per_year:].values.tolist()
    preds = []
    for _ in range(steps):
        X_pred = np.array(curr_values[-points_per_year:]).reshape(1, -1)
        p = model.predict(X_pred)[0]
        preds.append(p)
        curr_values.append(p)
    return pd.Series(preds)


# ---------------------------
# AFFICHAGE ET VALIDATION (CORRIGÉ)
# ---------------------------
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def plot_result_v2(dates_historique, levels_historique, prediction,
                   prediction_dates, start_validation_date, model_name, mape, erreur,
                   storage, recharge_factor, recharge_maitrisee, pumping):
    """
    Affiche le graphique avec enveloppe d'incertitude, validation, mois-années et paramètres.
    """

    plt.figure(figsize=(15, 8))

    # --- 1. TRACÉ DES DONNÉES ---
    plt.plot(dates_historique, levels_historique, label="Observé (Historique)",
             color='tab:blue', alpha=0.6, linewidth=1.5)

    # --- AJOUT : TRACÉ DE L'ENVELOPPE D'INCERTITUDE ---
    # On définit les bornes haute et basse basées sur l'écart constaté
    # On multiplie souvent l'erreur par 2 pour une enveloppe plus réaliste (95% de confiance)
    prediction_upper = prediction + erreur
    prediction_lower = prediction - erreur

    plt.fill_between(prediction_dates, prediction_lower, prediction_upper,
                     color='tab:red', alpha=0.15,
                     label=f"Incertitude (±{erreur:.2f} m)")

    # --- TRACÉ DE LA LIGNE DE PRÉDICTION ---
    plt.plot(prediction_dates, prediction, label=f"Prédiction {model_name}",
             color='tab:red', linestyle='--', linewidth=2)

    # --- 2. ZONE DE VALIDATION ---
    end_obs_date = dates_historique.max()
    plt.axvspan(start_validation_date, end_obs_date,
                color='gray', alpha=0.15, label="Période de Validation (20 ans)")

    # --- 3. AFFICHAGE DU SCORE ET DES PARAMÈTRES (DANS LA ZONE GRISE) ---
    text_x = start_validation_date + pd.DateOffset(months=3)
    all_values = np.concatenate([levels_historique.values, prediction])
    y_max = np.nanmax(all_values)
    text_x_2 = text_x + pd.DateOffset(years=10)
    y_commune = y_max

    # Bloc 1 : L'incertitude (MAPE)
    color_box = 'green' if mape <= 5 else 'orange' if mape <= 10 else 'red'
    plt.text(text_x, y_commune, f"MAPE Validation: {mape:.2f}%\nIncertitude: ±{erreur:.2f} m",
             fontsize=11, fontweight='bold', color='white',
             ha='left', va='top',
             bbox=dict(facecolor=color_box, alpha=0.9, edgecolor='none', boxstyle='round,pad=0.5'))

    # Bloc 2 : Les Paramètres de simulation
    param_text = (
        f"--- Paramètres de Simulation ---\n"
        f"Emmagasinement (S) : {storage:.4f}\n"
        f"Facteur Recharge (f) : {recharge_factor:.4f}\n"
        f"Recharge Maîtrisée : {recharge_maitrisee:,.0f} m³/an\n"
        f"Pompage Total : {pumping:,.0f} m³/an"
    ).replace(',', ' ')

    plt.text(text_x_2, y_commune, param_text,
             fontsize=9, color='#333333',
             ha='left', va='top',
             bbox=dict(facecolor='white', alpha=0.7, edgecolor='#cccccc', boxstyle='round,pad=0.5'))

    # --- 4. CONFIGURATION DES AXES (MOIS - ANNÉES) ---
    ax = plt.gca()
    plt.title(f"Analyse Piézométrique : {model_name}", fontsize=14, fontweight='bold', pad=20)
    plt.ylabel("Niveau piézométrique (m NGF)", fontsize=12)
    plt.xlabel("Échelle temporelle (Mois - Années)", fontsize=11)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=24))
    ax.xaxis.set_minor_locator(mdates.YearLocator())

    plt.xticks(rotation=45)

    plt.grid(True, which='major', linestyle=':', alpha=0.6)
    plt.grid(True, which='minor', linestyle='-', alpha=0.1)

    plt.legend(loc='upper left', frameon=True, fontsize=10)

    plt.tight_layout()
    plt.show()

# ---------------------------
# CŒUR DU CALCUL
# ---------------------------

from dateutil.relativedelta import relativedelta

import pandas as pd
import numpy as np
import tkinter as tk
from tkinter.filedialog import askopenfilename
from dateutil.relativedelta import relativedelta


def run_model(years_to_predict, recharge_maitrisee, pumping, years_validation,
              model_choice, ets_option, manual_s=None, manual_f=None):
    # --- 1. CHARGEMENT ET NETTOYAGE ---
    root = tk.Tk()
    root.withdraw()
    file_path = askopenfilename(title="Choisir le fichier Excel", filetypes=[("Excel", "*.xlsx")])
    if not file_path: return

    df = pd.read_excel(file_path)

    # Création du DataFrame indexé par date (Col 4 = Date, Col 6 = Niveau)
    df_clean = pd.DataFrame({
        'date': pd.to_datetime(df.iloc[:, 4]),
        'level': df.iloc[:, 6].astype(float)
    }).sort_values('date').set_index('date')

    # --- 2. GESTION DES PLAGES TEMPORELLES ---
    last_obs_date = df_clean.index.max()
    # Date charnière pour la séparation Entraînement / Validation
    start_validation_date = last_obs_date - relativedelta(years=years_validation)

    # Données d'entraînement : on isole le passé et on réinitialise l'index pour ARIMA/ETS
    train_data_subset = df_clean[df_clean.index < start_validation_date]['level']
    train_levels_series = pd.Series(train_data_subset.values)

    # Données de validation réelle
    y_true_val = df_clean[df_clean.index >= start_validation_date]['level']

    # --- 3. PARAMÈTRES ET POINTS ---
    points_per_year = 12  # Pas mensuel imposé pour la prédiction
    steps_total = int((years_validation + years_to_predict) * points_per_year)

    # Calcul des paramètres physiques (S, f, hydro)
    storage, recharge_factor, hydro_strength = calibrate_params(df_clean['level'])

    #
    if manual_s and manual_s > 0: storage = manual_s
    if manual_f and manual_f > 0: recharge_factor = manual_f

    # --- 4. EXÉCUTION DU MODÈLE ---
    prediction = None
    try:
        if model_choice == "ARIMA":
            prediction = model_arima(train_levels_series, steps_total)

        elif model_choice == "ETS":
            trend_type = None if ets_option == "1" else 'add'
            prediction = model_ets_base(train_levels_series, steps_total, trend=trend_type)

            # Options spécifiques ETS
            if ets_option == "2":
                prediction = add_multi_year_cycle(prediction)
            elif ets_option == "3":
                prediction = recenter_prediction(prediction, train_levels_series)
            elif ets_option == "4":
                # La solution 4 intègre déjà le modèle hydro
                prediction = apply_hydro_with_relaxation(
                    prediction, train_levels_series, storage,
                    recharge_factor, recharge_maitrisee,
                    pumping, hydro_strength, points_per_year
                )

        elif model_choice == "RandomForest":
            prediction = model_rf(train_levels_series, steps_total, points_per_year)

        elif model_choice == "XGBoost":
            prediction = model_xgb(train_levels_series, steps_total, points_per_year)

        if prediction is None: return

        # # --- 5. POST-PROCESS HYDRO (Sauf Solution 4) ---
        # if not (model_choice == "ETS" and ets_option == "4"):
        #     prediction = apply_hydro_model(
        #         prediction, storage, recharge_factor,
        #         recharge_maitrisee, pumping, hydro_strength,
        #         points_per_year
        #     )

        # --- 6. GÉNÉRATION DU CALENDRIER ---
        # On crée l'index temporel complet (Validation + Futur)
        prediction_dates = pd.date_range(
            start=start_validation_date + pd.DateOffset(months=1),
            periods=len(prediction),
            freq='MS'
        )

        # On convertit la prédiction brute en Series Pandas AVEC son index de dates
        # C'est crucial pour que apply_hydro_model puisse comparer avec last_obs_date
        prediction_series = pd.Series(prediction, index=prediction_dates)

        # --- 5. POST-PROCESS HYDRO ---
        if not (model_choice == "ETS" and ets_option == "4"):
            prediction_series = apply_hydro_model(
                prediction_series, storage, recharge_factor,
                recharge_maitrisee, pumping, hydro_strength,
                points_per_year,
                last_obs_date
            )

        # --- 7. CALCUL DE LA VALIDATION (MAPE & STD) ---
        # On ne calcule l'erreur QUE sur la période où l'on a des observations réelles
        # On filtre la prédiction pour s'arrêter à la date de la dernière observation
        mask_val = prediction_series.index <= last_obs_date
        pred_to_validate = prediction_series[mask_val]

        # On aligne les données réelles sur les dates de la prédiction
        # (évite les erreurs si le fichier Excel a des trous ou des dates décalées)
        obs_aligned = y_true_val.reindex(pred_to_validate.index, method='nearest')

        # Calcul de la différence (en NumPy pour éviter les conflits d'index)
        diff = obs_aligned.values - pred_to_validate.values

        # Nettoyage des valeurs vides (NaN) pour éviter l'erreur "Degrees of freedom <= 0"
        diff = diff[~np.isnan(diff)]
        obs_clean = obs_aligned.values[~np.isnan(diff)]

        if len(diff) > 1:
            std_erreur = np.nanstd(diff)
            mape = np.mean(np.abs(diff / obs_clean)) * 100
        else:
            std_erreur = 0.0
            mape = 0.0

        # --- 8. AFFICHAGE FINAL ---
        plot_result_v2(
            dates_historique=df_clean.index,
            levels_historique=df_clean['level'],
            prediction=prediction_series.values,  # On repasse en numpy pour le tracé
            prediction_dates=prediction_series.index,
            start_validation_date=start_validation_date,
            model_name=model_choice,
            mape=mape,
            erreur=std_erreur,
            storage=storage,
            recharge_factor=recharge_factor,
            recharge_maitrisee=recharge_maitrisee,
            pumping=pumping
        )

    except Exception as e:
        print(f"Erreur lors de la simulation : {e}")

def calculate_robust_mape(y_true, y_pred):
    # Mean Absolute Percentage Error
    # Ajustement de taille si nécessaire pour le calcul
    min_len = min(len(y_true), len(y_pred))
    if min_len == 0: return 0
    return np.mean(np.abs((y_true.values[:min_len] - y_pred[:min_len]) / y_true.values[:min_len])) * 100

# ---------------------------------------------------------
# RAPPEL : Ajustement de plot_result pour les dates
# ---------------------------------------------------------
# Dans plot_result, utilise cet index pour gérer l'irrégularité :
#
# avg_days = 365 / points_per_year
# prediction_dates = pd.date_range(start=dates.iloc[-val_points],
#                                  periods=len(prediction),
#                                  freq=f'{int(avg_days)}D')
# ---------------------------
# INTERFACE GRAPHIQUE
# ---------------------------
def launch_gui():
    root = tk.Tk()
    root.title("Expert Piézométrie")

    # 1. Les noms ici doivent être FIXES
    fields = [
        ("Modèle", ["ARIMA", "ETS", "RandomForest", "XGBoost"]),
        ("Option ETS (1-4)", ["1", "2", "3", "4"]),
        ("Recharge maîtrisée (m)", "0.5"),
        ("Pompage (m)", "0.0"),
        ("Emmagasinement (S)", "0"),  # <-- Retiens ce nom
        ("Facteur Recharge (f)", "0"),  # <-- Retiens ce nom
        ("Années futur", "5"),
        ("Années validation", "20")
    ]

    vars = {}
    for i, (label, default) in enumerate(fields):
        ttk.Label(root, text=label).grid(row=i, column=0, padx=10, pady=5)
        if isinstance(default, list):
            var = tk.StringVar(value=default[0])
            ttk.Combobox(root, textvariable=var, values=default, state="readonly").grid(row=i, column=1)
        else:
            var = tk.StringVar(value=default)
            ttk.Entry(root, textvariable=var).grid(row=i, column=1)
        vars[label] = var

    def on_run():
        try:
            # 2. Utilisation des noms EXACTS définis dans 'fields'
            s_val = float(vars["Emmagasinement (S)"].get())
            f_val = float(vars["Facteur Recharge (f)"].get())

            # 3. TOUT le bloc run_model doit être à l'intérieur du try et bien aligné
            run_model(
                int(vars["Années futur"].get()),
                float(vars["Recharge maîtrisée (m)"].get()),
                float(vars["Pompage (m)"].get()),
                int(vars["Années validation"].get()),
                vars["Modèle"].get(),
                vars["Option ETS (1-4)"].get(),
                manual_s=s_val,
                manual_f=f_val
            )

        except Exception as e:
            print(f"Erreur lors de l'exécution : {e}")

    ttk.Button(root, text="Lancer l'Analyse", command=on_run).grid(row=len(fields), columnspan=2, pady=20)
    root.mainloop()

if __name__ == '__main__':
    launch_gui()