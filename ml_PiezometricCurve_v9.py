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
# CLASSE TOOLTIP (L'INFOBULLE)
# ---------------------------
class ToolTip(object):
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)  # Supprime la bordure de fenêtre
        tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "9", "normal"), padx=5, pady=5)
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


# ---------------------------
# FONCTIONS MODÈLES & CALCULS
# ---------------------------
def create_features(series, lags):
    df_y = pd.DataFrame(series.copy())
    df_y.columns = ["y"]
    lag_cols = [df_y["y"].shift(i).rename(f"lag_{i}") for i in range(1, lags + 1)]
    df = pd.concat([df_y] + lag_cols, axis=1)
    return df.dropna().astype(float)


def model_rf(levels, steps, lags, n_est, m_depth):
    df = create_features(levels, lags=lags)
    X, y = df.drop(columns=["y"]), df["y"]
    model = RandomForestRegressor(n_estimators=n_est, max_depth=m_depth, random_state=42).fit(X, y)
    curr_values = levels[-lags:].values.tolist()
    preds = []
    for _ in range(steps):
        X_pred = pd.DataFrame(np.array(curr_values[-lags:]).reshape(1, -1), columns=X.columns)
        p = model.predict(X_pred)[0]
        preds.append(p)
        curr_values.append(p)
    return np.array(preds)


def model_xgb(levels, steps, lags, n_est, m_depth):
    df = create_features(levels, lags=lags)
    X, y = df.drop(columns=["y"]), df["y"]
    model = XGBRegressor(n_estimators=n_est, max_depth=m_depth, learning_rate=0.1).fit(X, y)
    curr_values = levels[-lags:].values.tolist()
    preds = []
    for _ in range(steps):
        X_pred = np.array(curr_values[-lags:]).reshape(1, -1)
        p = model.predict(X_pred)[0]
        preds.append(p)
        curr_values.append(p)
    return np.array(preds)


def apply_hydro_model(prediction_series, storage, r_factor, r_mait, pumping, h_str, ppy, last_date):
    adjusted = prediction_series.values.copy()
    cumul = 0.0
    s_val = storage if storage > 0 else 0.02
    for i in range(len(adjusted)):
        adjusted[i] += r_factor * np.sin(2 * np.pi * i / ppy)
        if prediction_series.index[i] > last_date:
            cumul += ((r_mait - pumping) / 12 / s_val) * h_str
        adjusted[i] += cumul
    return pd.Series(adjusted, index=prediction_series.index)


def calibrate_params(levels):
    std = np.std(levels)
    return max(0.01, min(0.1, std / 10)), std / 20, 0.2


def plot_result_v3(dates_hist, levels_hist, prediction_series, start_val_date, model_name, mape, erreur, mae):
    plt.figure(figsize=(15, 8))
    plt.plot(dates_hist, levels_hist, label="Observé (Historique)", color='tab:blue', alpha=0.6, linewidth=1.5)
    plt.fill_between(prediction_series.index, prediction_series - erreur, prediction_series + erreur, color='tab:red',
                     alpha=0.15)
    plt.plot(prediction_series.index, prediction_series, label=f"Prédiction {model_name}", color='tab:red',
             linestyle='--', linewidth=2)
    plt.axvspan(start_val_date, dates_hist.max(), color='gray', alpha=0.15, label="Validation")

    color_box = 'green' if mape <= 1 else 'orange' if mape <= 5 else 'red'
    stats_text = f"MAPE: {mape:.2f}%\nMAE: {mae:.2f} m\nIncertitude: ±{erreur:.2f} m"
    plt.text(start_val_date + pd.DateOffset(months=6), max(levels_hist), stats_text,
             fontsize=10, fontweight='bold', color='white', bbox=dict(facecolor=color_box, alpha=0.8, boxstyle='round'))
    plt.title(f"Analyse Piézométrique : {model_name}")
    plt.grid(True, linestyle=':', alpha=0.5)
    plt.show()


# ---------------------------
# LOGIQUE RUN
# ---------------------------
def run_model(vars, root):
    try:
        y_fut, y_val = int(vars["Années futur"].get()), int(vars["Années validation"].get())
        r_mait, pump = float(vars["Recharge maîtrisée (m)"].get()), float(vars["Pompage (m)"].get())
        mod, ets_opt = vars["Modèle"].get(), vars["Option ETS (1-4)"].get()
        lag = int(vars["Mémoire (Lags)"].get())
        order = tuple(map(int, vars["ARIMA (p,d,q)"].get().split(',')))
        n_est, m_dep = int(vars["ML: Nb Arbres"].get()), int(vars["ML: Profondeur Max"].get())
        m_depth = m_dep if m_dep > 0 else None
    except Exception as e:
        messagebox.showerror("Erreur", f"Données saisies incorrectes.\n{e}")
        return

    file_path = askopenfilename(filetypes=[("Excel", "*.xlsx")])
    if not file_path: return

    try:
        df = pd.read_excel(file_path)
        df_clean = pd.DataFrame(
            {'date': pd.to_datetime(df.iloc[:, 4]), 'level': df.iloc[:, 6].astype(float)}).sort_values(
            'date').set_index('date')
        last_date = df_clean.index.max()
        start_val = last_date - relativedelta(years=y_val)
        train = df_clean[df_clean.index < start_val]['level']
        steps = int((y_val + y_fut) * 12)
        storage, r_fact, h_str = calibrate_params(df_clean['level'])

        if mod == "ARIMA":
            raw = ARIMA(train.values, order=order).fit().forecast(steps)
        elif mod == "ETS":
            raw = ExponentialSmoothing(train.values, trend=('add' if ets_opt != '1' else None), seasonal='add',
                                       seasonal_periods=12).fit().forecast(steps)
        elif mod == "RandomForest":
            raw = model_rf(train, steps, lag, n_est, m_depth)
        else:
            raw = model_xgb(train, steps, lag, n_est, m_depth)

        dates = pd.date_range(start=start_val + pd.DateOffset(months=1), periods=steps, freq='MS')
        prediction = apply_hydro_model(pd.Series(raw, index=dates), storage, r_fact, r_mait, pump, h_str, 12, last_date)

        comp = pd.DataFrame({'obs': df_clean['level'], 'pre': prediction}).dropna()
        mape = np.mean(np.abs((comp['obs'] - comp['pre']) / comp['obs'])) * 100 if not comp.empty else 0
        mae = np.mean(np.abs(comp['obs'] - comp['pre'])) if not comp.empty else 0
        std = np.nanstd(comp['obs'] - comp['pre']) if not comp.empty else 0

        plot_result_v3(df_clean.index, df_clean['level'], prediction, start_val, mod, mape, std, mae)
    except Exception as e:
        messagebox.showerror("Erreur", str(e))


# ---------------------------
# INTERFACE GUI
# ---------------------------
def launch_gui():
    root = tk.Tk()
    root.title("Expert Piézométrie v3 - Calibration")
    frame = ttk.Frame(root, padding="20")
    frame.grid(row=0, column=0)

    # TES INFORMATIONS DE CALIBRATION
    DESC = {
        "Mémoire (Lags)": "Définit le passé analysé par le modèle (ex: 12 mois).\nAugmentez (24-36) pour les nappes inertielles à réaction lente.\nDiminuez pour les nappes alluviales réactives.",
        "ARIMA (p,d,q)": "p (Auto-régression) : Dépendance aux valeurs passées.\nd (Intégration) : Nombre de différenciations pour la stabilité.\nq (Moyenne mobile) : Dépendance aux erreurs passées.\nStandard : 1,1,1.",
        "ML: Nb Arbres": "Nombre d'arbres de décision combinés (RandomForest/XGBoost).\nPlus le nombre est élevé (ex: 500), plus la prédiction est stable.\nStandard : 100.",
        "ML: Profondeur Max": "Limite la complexité des arbres pour éviter le sur-apprentissage.\nRéduisez (3-5) si la courbe rouge est trop chaotique.\n0 = Illimité."
    }

    vars = {}
    r = 0
    ttk.Label(frame, text="PARAMÈTRES GÉNÉRAUX", font=('Helvetica', 10, 'bold')).grid(row=r, columnspan=3,
                                                                                      pady=(0, 10));
    r += 1

    gen_f = [("Modèle", ["ARIMA", "ETS", "RandomForest", "XGBoost"]), ("Option ETS (1-4)", ["1", "2", "3", "4"]),
             ("Années futur", "10"), ("Années validation", "15"), ("Recharge maîtrisée (m)", "0.5"),
             ("Pompage (m)", "0.0")]

    for label, default in gen_f:
        ttk.Label(frame, text=label).grid(row=r, column=0, sticky=tk.W, pady=2)
        var = tk.StringVar(value=default[0] if isinstance(default, list) else default)
        if isinstance(default, list):
            ttk.Combobox(frame, textvariable=var, values=default, state="readonly", width=17).grid(row=r, column=1,
                                                                                                   pady=2)
        else:
            ttk.Entry(frame, textvariable=var, width=20).grid(row=r, column=1, pady=2)
        vars[label] = var;
        r += 1

    ttk.Label(frame, text="RÉGLAGES DE CALIBRATION", font=('Helvetica', 10, 'bold')).grid(row=r, columnspan=3,
                                                                                          pady=(20, 10));
    r += 1

    cal_f = [("Mémoire (Lags)", "12"), ("ARIMA (p,d,q)", "1,1,1"), ("ML: Nb Arbres", "100"),
             ("ML: Profondeur Max", "6")]

    for label, default in cal_f:
        ttk.Label(frame, text=label).grid(row=r, column=0, sticky=tk.W, pady=2)
        var = tk.StringVar(value=default)
        ttk.Entry(frame, textvariable=var, width=20).grid(row=r, column=1, pady=2)

        # ICI : J'ai supprimé l'argument cursor="help" qui faisait planter ton Windows
        help_ico = tk.Label(frame, text=" [?]", fg="blue", font=("Helvetica", 9, "bold"))
        help_ico.grid(row=r, column=2, sticky=tk.W)
        ToolTip(help_ico, DESC[label])

        vars[label] = var;
        r += 1

    ttk.Button(frame, text="Lancer l'Analyse", command=lambda: run_model(vars, root)).grid(row=r, columnspan=3, pady=20)
    root.mainloop()


if __name__ == '__main__':
    launch_gui()