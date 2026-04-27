import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
from pathlib import Path
from dataclasses import dataclass, field
import warnings
warnings.filterwarnings('ignore')

APP_TITLE = 'Expert Piézométrie Pro'
APP_SIZE = '1250x820'

# ─── Config ────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    file_path: str = ''
    model: str = 'ETS'
    ets_type: str = '3'
    future_years: int = 5
    validation_years: int = 20
    ci_level: float = 0.05
    n_bootstraps: int = 200
    recharge_factor: float = 0.0  # Deviendra notre débit (m3/j)
    storage_coeff: float = 0.05   # Valeur par défaut pour une nappe libre
    influence_area: float = 100.0 # Surface d'influence en m2


# ─── Helpers feature engineering ───────────────────────────────────────────────

def make_features(dates: pd.Series) -> pd.DataFrame:
    """Crée des features temporelles pour RF / XGBoost."""
    df = pd.DataFrame({'date': dates})
    df['t'] = (df['date'] - df['date'].min()).dt.days
    df['month'] = df['date'].dt.month
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['year'] = df['date'].dt.year
    df['quarter'] = df['date'].dt.quarter
    return df.drop(columns=['date'])


def detect_frequency(dates: pd.Series) -> str:
    """Détecte automatiquement la fréquence dominante des données."""
    diffs = dates.diff().dropna().dt.days
    median_diff = diffs.median()
    if median_diff <= 1.5:
        return 'D'
    elif median_diff <= 8:
        return 'W'
    elif median_diff <= 35:
        return 'MS'
    elif median_diff <= 100:
        return 'QS'
    else:
        return 'YS'


def freq_to_seasonal_periods(freq: str) -> int:
    # Pour les nappes, la saisonnalité est toujours annuelle (365 jours ou 12 mois)
    return {'D': 365, 'W': 52, 'MS': 12, 'QS': 4, 'YS': 1}.get(freq, 12)


def future_steps(freq: str, years: int) -> int:
    return {'D': years * 365, 'W': years * 52, 'MS': years * 12,
            'QS': years * 4, 'YS': years}.get(freq, years * 12)


# ─── Modèles ───────────────────────────────────────────────────────────────────

class ETSModel:
    def __init__(self, ets_type: str, seasonal_periods: int, ci_level: float):
        self.ets_type = ets_type
        self.sp = seasonal_periods
        self.ci_level = ci_level
        self.fit_ = None

    def fit(self, y: np.ndarray):
        t = self.ets_type
        sp = self.sp if self.sp > 1 else None
        if t == '1':
            m = ExponentialSmoothing(y, trend=None, seasonal=None)
        elif t == '2':
            m = ExponentialSmoothing(y, trend='add', seasonal=None)
        elif t == '3':
            m = ExponentialSmoothing(y, trend=None,
                                     seasonal='add' if sp else None,
                                     seasonal_periods=sp)
        else:
            m = ExponentialSmoothing(y, trend='add',
                                     seasonal='add' if sp else None,
                                     seasonal_periods=sp)
        self.fit_ = m.fit(optimized=True)
        return self

    def predict(self, steps: int):
            # Augmenter les répétitions pour stabiliser l'IC
            sim = self.fit_.simulate(steps, repetitions=1000, error='add')
            pred = self.fit_.forecast(steps)
            
            # Astuce : On utilise l'écart-type des résidus pour un IC plus "serré" 
            # si la simulation est trop erratique
            alpha = self.ci_level
            
            # Calcul par quantiles (ton code actuel)
            lo = np.quantile(sim, alpha / 2, axis=1)
            hi = np.quantile(sim, 1 - alpha / 2, axis=1)
            
            return pred, lo, hi


class ARIMAModel:
    """
    SARIMA automatique : teste quelques combinaisons (p,d,q) et garde le
    meilleur AIC. Intervalles de confiance analytiques via statsmodels.
    """
    CANDIDATES = [
        (1, 1, 1), (1, 1, 0), (0, 1, 1),
        (2, 1, 1), (1, 1, 2), (2, 1, 2),
        (0, 1, 2), (2, 1, 0),
    ]

    def __init__(self, seasonal_periods: int, ci_level: float):
        self.sp = seasonal_periods
        self.ci_level = ci_level
        self.res_ = None
        self.order_ = None

    def _is_stationary(self, y):
        try:
            return adfuller(y)[1] < 0.05
        except Exception:
            return False

    def fit(self, y: np.ndarray):
        d = 0 if self._is_stationary(y) else 1
        sp = self.sp if self.sp > 1 else 0

        best_aic = np.inf
        best_res = None
        best_order = (1, d, 1)

        for p, _, q in self.CANDIDATES:
            try:
                if sp > 1:
                    m = SARIMAX(y, order=(p, d, q),
                                seasonal_order=(1, 1, 1, sp),
                                enforce_stationarity=False,
                                enforce_invertibility=False)
                else:
                    m = SARIMAX(y, order=(p, d, q),
                                enforce_stationarity=False,
                                enforce_invertibility=False)
                res = m.fit(disp=False, maxiter=200)
                if res.aic < best_aic:
                    best_aic = res.aic
                    best_res = res
                    best_order = (p, d, q)
            except Exception:
                continue

        if best_res is None:
            raise RuntimeError("ARIMA : impossible d'ajuster le modèle.")
        self.res_ = best_res
        self.order_ = best_order
        return self

    def predict(self, steps: int):
        fc = self.res_.get_forecast(steps=steps)
        pred = fc.predicted_mean
        ci = fc.conf_int(alpha=self.ci_level)   # FIX : ci_level est déjà alpha
        lo = ci.iloc[:, 0].values
        hi = ci.iloc[:, 1].values
        return pred, lo, hi


class SklearnModel:
    """
    RandomForest ou XGBoost/GradientBoosting avec intervalles de confiance
    par bootstrap (quantile regression).
    """
    def __init__(self, kind: str, ci_level: float, n_bootstraps: int):
        self.kind = kind          # 'RandomForest' ou 'XGBoost'
        self.ci_level = ci_level
        self.n_bootstraps = n_bootstraps
        self.models_ = []
        self.scaler_ = StandardScaler()
        self.train_dates_ = None

    def _make_model(self):
        if self.kind == 'RandomForest':
            return RandomForestRegressor(n_estimators=100, max_depth=6,
                                         random_state=42, n_jobs=-1)
        else:
            return GradientBoostingRegressor(n_estimators=200, max_depth=4,
                                             learning_rate=0.05,
                                             subsample=0.8, random_state=42)

    def fit(self, df: pd.DataFrame):
        """df doit contenir 'date' et 'level'."""
        self.train_dates_ = df['date'].copy()
        self.train_origin_ = df['date'].min()   # FIX : mémoriser l'origine pour predict
        X = make_features(df['date'])
        y = df['level'].values
        X_scaled = self.scaler_.fit_transform(X)

        # Bootstrap
        n = len(y)
        for _ in range(self.n_bootstraps):
            idx = np.random.choice(n, n, replace=True)
            m = self._make_model()
            m.fit(X_scaled[idx], y[idx])
            self.models_.append(m)
        return self

    def predict(self, future_dates: pd.Series):
        # FIX : reconstruire les features avec la même origine que l'entraînement
        df_feat = pd.DataFrame({'date': pd.to_datetime(future_dates)})
        df_feat['t'] = (df_feat['date'] - self.train_origin_).dt.days
        df_feat['month'] = df_feat['date'].dt.month
        df_feat['month_sin'] = np.sin(2 * np.pi * df_feat['month'] / 12)
        df_feat['month_cos'] = np.cos(2 * np.pi * df_feat['month'] / 12)
        df_feat['year'] = df_feat['date'].dt.year
        df_feat['quarter'] = df_feat['date'].dt.quarter
        X_fut = df_feat.drop(columns=['date'])

        X_scaled = self.scaler_.transform(X_fut)
        preds = np.array([m.predict(X_scaled) for m in self.models_])
        pred = preds.mean(axis=0)
        alpha = self.ci_level          # FIX : cohérence avec les autres modèles
        lo = np.quantile(preds, alpha / 2, axis=0)
        hi = np.quantile(preds, 1 - alpha / 2, axis=0)
        return pred, lo, hi


# ─── Application principale ────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(APP_SIZE)
        self.root.minsize(1050, 720)
        self.df = None
        self.pred_df = None
        self.cfg = Config()
        self.freq = 'MS'
        self.metrics = {}
        self.build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────────

    def build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = tk.Frame(self.root, bg='#1f2d3d', width=290)
        sidebar.grid(row=0, column=0, sticky='nswe')
        sidebar.grid_propagate(False)

        main = tk.Frame(self.root, bg='#f5f6fa')
        main.grid(row=0, column=1, sticky='nswe')
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        self.main = main

        # ── Sidebar header
        tk.Label(sidebar, text='Expert Piézométrie Pro',
                 fg='white', bg='#1f2d3d',
                 font=('Segoe UI', 14, 'bold')).pack(pady=18)

        ttk.Button(sidebar, text='📂  Charger Excel',
                   command=self.load_file).pack(fill='x', padx=14, pady=4)
        ttk.Button(sidebar, text='▶  Lancer Analyse',
                   command=self.run_analysis).pack(fill='x', padx=14, pady=4)
        ttk.Button(sidebar, text='💾  Exporter CSV',
                   command=self.export_csv).pack(fill='x', padx=14, pady=4)
        ttk.Button(sidebar, text='✕  Quitter',
                   command=self.root.destroy).pack(fill='x', padx=14, pady=14)

        # ── Paramètres modèle
        params = ttk.LabelFrame(sidebar, text='Paramètres modèle')
        params.pack(fill='x', padx=10, pady=6)

        # ── Simulation Recharge Maîtrisée (CORRIGÉ AVEC DIMENSION SPATIALE)
        recharge_frame = ttk.LabelFrame(sidebar, text='Injection Maîtrisée')
        recharge_frame.pack(fill='x', padx=10, pady=6)

        # 1. Débit d'injection
        self.recharge_var = tk.DoubleVar(value=0.0)
        ttk.Label(recharge_frame, text="Débit injecté (m³/jour)").pack(anchor='w', padx=8, pady=(5,0))
        ttk.Entry(recharge_frame, textvariable=self.recharge_var).pack(fill='x', padx=8, pady=2)

        # 2. Coefficient d'emmagasinement (S)
        self.s_coeff_var = tk.DoubleVar(value=0.05)
        ttk.Label(recharge_frame, text="Coeff. Emmagasinement (S)").pack(anchor='w', padx=8, pady=(5,0))
        ttk.Entry(recharge_frame, textvariable=self.s_coeff_var).pack(fill='x', padx=8, pady=2)

        # 3. Surface de l'ouvrage (m²)
        self.area_var = tk.DoubleVar(value=100.0)
        ttk.Label(recharge_frame, text="Surface de l'ouvrage (m²)").pack(anchor='w', padx=8, pady=(5,0))
        ttk.Entry(recharge_frame, textvariable=self.area_var).pack(fill='x', padx=8, pady=2)

        # 4. DISTANCE (Champ spatial 1)
        self.dist_var = tk.DoubleVar(value=50.0)
        ttk.Label(recharge_frame, text="Distance piézo/ouvrage (m)").pack(anchor='w', padx=8, pady=(5,0))
        ttk.Entry(recharge_frame, textvariable=self.dist_var).pack(fill='x', padx=8, pady=2)

        # 5. PERMÉABILITÉ K (Champ spatial 2)
        self.k_var = tk.DoubleVar(value=0.0001)
        ttk.Label(recharge_frame, text="Perméabilité K (m/s)").pack(anchor='w', padx=8, pady=(5,0))
        ttk.Entry(recharge_frame, textvariable=self.k_var).pack(fill='x', padx=8, pady=(2,10))

        # --- Fin du bloc Recharge ---

        self.model_var = tk.StringVar(value='ETS')
        ttk.Label(params, text='Modèle').pack(anchor='w', padx=8, pady=(8, 0))
        model_cb = ttk.Combobox(params, textvariable=self.model_var,
                                values=['ETS', 'ARIMA', 'RandomForest', 'XGBoost'],
                                state='readonly')
        model_cb.pack(fill='x', padx=8, pady=4)
        model_cb.bind('<<ComboboxSelected>>', self._on_model_change)

        self.ets_frame = ttk.Frame(params)
        self.ets_frame.pack(fill='x')
        self.ets_var = tk.StringVar(value='4')
        ttk.Label(self.ets_frame, text='Type ETS').pack(anchor='w', padx=8)
        ttk.Combobox(self.ets_frame, textvariable=self.ets_var,
                     values=['1 - Simple', '2 - Tendance',
                             '3 - Saisonnier', '4 - Complet'],
                     state='readonly').pack(fill='x', padx=8, pady=4)

        self.future_var = tk.IntVar(value=10)
        ttk.Label(params, text='Années futures').pack(anchor='w', padx=8)
        ttk.Entry(params, textvariable=self.future_var).pack(fill='x', padx=8, pady=4)

        self.val_var = tk.IntVar(value=5)
        ttk.Label(params, text='Années validation').pack(anchor='w', padx=8)
        ttk.Entry(params, textvariable=self.val_var).pack(fill='x', padx=8, pady=4)

        # ── Paramètres intervalles de confiance
        ci_frame = ttk.LabelFrame(sidebar, text='Intervalle de confiance')
        ci_frame.pack(fill='x', padx=10, pady=6)

        self.ci_var = tk.DoubleVar(value=68.0)
        ttk.Label(ci_frame, text='Niveau (%)').pack(anchor='w', padx=8, pady=(6, 0))
        ttk.Entry(ci_frame, textvariable=self.ci_var).pack(fill='x', padx=8, pady=4)

        self.boot_var = tk.IntVar(value=200)
        ttk.Label(ci_frame, text='Bootstraps (RF/XGB)').pack(anchor='w', padx=8)
        ttk.Entry(ci_frame, textvariable=self.boot_var).pack(fill='x', padx=8, pady=4)

        # ── Métriques
        self.metrics_frame = ttk.LabelFrame(sidebar, text='Métriques validation')
        self.metrics_frame.pack(fill='x', padx=10, pady=6)
        self.metrics_labels = {}
        for key in ('MAE', 'RMSE', 'MAPE'):
            row = tk.Frame(self.metrics_frame, bg='#f0f0f0')
            row.pack(fill='x', padx=6, pady=2)
            tk.Label(row, text=f'{key}:', width=6, anchor='w',
                     bg='#f0f0f0').pack(side='left')
            lbl = tk.Label(row, text='—', fg='#1a6ea8',
                           font=('Consolas', 10, 'bold'), bg='#f0f0f0')
            lbl.pack(side='left')
            self.metrics_labels[key] = lbl

        # ── Status bar
        top = tk.Frame(main, bg='#f5f6fa')
        top.grid(row=0, column=0, sticky='ew')
        self.status = tk.Label(top, text='Prêt — chargez un fichier Excel',
                               bg='#f5f6fa', fg='#555',
                               font=('Consolas', 10))
        self.status.pack(anchor='w', padx=15, pady=10)

        self.freq_label = tk.Label(top, text='', bg='#f5f6fa', fg='#888',
                                   font=('Consolas', 9))
        self.freq_label.pack(anchor='w', padx=15)

        # ── Zone de contenu
        self.content = tk.Frame(main, bg='white')
        self.content.grid(row=1, column=0, sticky='nswe', padx=10, pady=10)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.table = ttk.Treeview(self.content,
                                  columns=('date', 'level'), show='headings')
        self.table.heading('date', text='Date')
        self.table.heading('level', text='Niveau (m)')
        self.table.column('date', width=160)
        self.table.column('level', width=120)
        self.table.grid(row=0, column=0, sticky='nswe')

        sb = ttk.Scrollbar(self.content, orient='vertical',
                           command=self.table.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=sb.set)

    def _on_model_change(self, _event=None):
        if self.model_var.get() == 'ETS':
            self.ets_frame.pack(fill='x')
        else:
            self.ets_frame.pack_forget()

    def set_status(self, txt, color='#555'):
        self.status.config(text=txt, fg=color)
        self.root.update_idletasks()

    # ── Chargement ──────────────────────────────────────────────────────────────

    # Noms de colonnes BSS reconnus automatiquement
    DATE_ALIASES = [
        'date de la mesure', 'date_mesure', 'date mesure', 'date',
        'datetime', 'horodatage', 'timestamp',
    ]
    LEVEL_ALIASES = [
        'côte ngf', 'cote ngf', 'niveau ngf', 'niveau', 'level',
        'profondeur/repère de mesure', 'profondeur relative/repère de mesure',
        'valeur', 'mesure', 'hauteur',
    ]

    def _find_column(self, df: pd.DataFrame, aliases: list):
        """Retourne le nom de colonne correspondant à l'un des alias (insensible à la casse)."""
        cols_lower = {c.lower().strip(): c for c in df.columns}
        for alias in aliases:
            if alias in cols_lower:
                return cols_lower[alias]
        return None

    def load_file(self):
        path = filedialog.askopenfilename(
            filetypes=[('Excel', '*.xlsx *.xls')])
        if not path:
            return
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 2:
                raise ValueError(
                    'Le fichier doit contenir au moins 2 colonnes : date / niveau')

            # ── Détection automatique des colonnes date et niveau
            date_col = self._find_column(df, self.DATE_ALIASES)
            level_col = self._find_column(df, self.LEVEL_ALIASES)

            if date_col is None or level_col is None:
                available = list(df.columns)
                msg = (
                    f"Colonnes détectées : {available}\n\n"
                    f"Colonne date trouvée : {date_col or '❌ NON TROUVÉE'}\n"
                    f"Colonne niveau trouvée : {level_col or '❌ NON TROUVÉE'}\n\n"
                    "Renommez les colonnes en 'date' et 'level' dans votre fichier "
                    "ou vérifiez que les noms correspondent aux colonnes BSS standard."
                )
                raise ValueError(msg)

            df = df[[date_col, level_col]].copy()
            df.columns = ['date', 'level']
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df['level'] = pd.to_numeric(df['level'], errors='coerce')
            df = df.dropna().sort_values('date').reset_index(drop=True)

            if len(df) < 24:
                raise ValueError(
                    f'Données insuffisantes après nettoyage : {len(df)} observations valides '
                    f'(minimum 24 requis).\n'
                    f'Vérifiez le format de la colonne "{date_col}" et "{level_col}".'
                )

            self.df = df
            self.cfg.file_path = path

            # Détection fréquence
            self.freq = detect_frequency(df['date'])
            freq_names = {'D': 'Journalier', 'W': 'Hebdomadaire',
                          'MS': 'Mensuel', 'QS': 'Trimestriel', 'YS': 'Annuel'}
            self.freq_label.config(
                text=f'Fréquence détectée : {freq_names.get(self.freq, self.freq)}'
                     f' — {len(df)} observations')

            self.populate_table(df)
            self.set_status(f'Chargé : {Path(path).name}', '#1a7a1a')
        except Exception as e:
            messagebox.showerror('Erreur chargement', str(e))

    def populate_table(self, df):
        for item in self.table.get_children():
            self.table.delete(item)
        n = len(df)
        if n > 500:
            self.set_status(
                f'Aperçu limité à 500 lignes sur {n} — toutes les données'
                f' sont utilisées pour l\'analyse.', '#a07000')
        for _, row in df.head(500).iterrows():
            self.table.insert('', 'end',
                              values=(row['date'].date(),
                                      f"{row['level']:.3f}"))

    def calculate_spatial_impact(self, Q, S, K, distance, time_days, Area):
            """
            Calcule la remontée (m) à une distance R après un temps T.
            Modèle simplifié de dôme piézométrique.
            """
            if time_days <= 0 or S <= 0 or K <= 0:
                return 0
            
            # Rayon équivalent du bassin (si Area est la surface du bassin)
            R_bassin = np.sqrt(Area / np.pi)
            
            # Transmissivité estimée (K * épaisseur moyenne, ici fixée à 10m par défaut)
            T = K * 10 
            
            # Diffusivité hydraulique
            diffusivity = T / S
            
            # Calcul de la remontée à la distance r (Approximation de Hantush)
            # On utilise une décroissance logarithmique en fonction de la distance
            if distance <= R_bassin:
                # Sous le bassin, la remontée est maximale
                impact = (Q / (Area * S)) * (1 - np.exp(-time_days / 10)) # Stabilisation théorique
            else:
                # À l'extérieur, l'impact décroît avec la distance
                u = (distance**2 * S) / (4 * T * time_days)
                if u > 5: return 0 # Impact négligeable
                # Approximation de la fonction de puits (Theis inversé pour injection)
                from scipy.special import exp1
                impact = (Q / (4 * np.pi * T)) * exp1(u)
                
            return max(0, impact)


    # ── Analyse ─────────────────────────────────────────────────────────────────

    def run_analysis(self):
            if self.df is None:
                messagebox.showwarning('Attention', 'Chargez d\'abord un fichier Excel.')
                return
            try:
                # ── 1. Lecture et validation des paramètres UI
                self.cfg.future_years = int(self.future_var.get())
                self.cfg.validation_years = int(self.val_var.get())
                self.cfg.model = self.model_var.get()
                
                # Paramètres de recharge maîtrisée
                Q = float(self.recharge_var.get())     # m3/jour
                S = float(self.s_coeff_var.get())      # Coefficient emmagasinement
                Area = float(self.area_var.get())      # Surface m2
    
                # Validation du niveau de confiance
                ci_pct = float(self.ci_var.get())
                if not (50.0 < ci_pct < 100.0):
                    raise ValueError('Le niveau de confiance doit être entre 50 et 100 %.')
                self.cfg.ci_level = (100.0 - ci_pct) / 100.0
    
                self.cfg.n_bootstraps = int(self.boot_var.get())
                
                # Type ETS
                ets_raw = self.ets_var.get()
                self.cfg.ets_type = ets_raw[0]
    
                self.set_status('Calcul en cours…', '#a07000')
    
                # ── 2. Split validation
                v_steps = min(
                    future_steps(self.freq, self.cfg.validation_years),
                    len(self.df) // 4
                )
                if v_steps < 1:
                    raise ValueError('Pas assez de données pour la période de validation.')
    
                df_train = self.df.iloc[:-v_steps].copy()
                df_val   = self.df.iloc[-v_steps:].copy()
    
                # ── 3. Fit & Predict — validation (sans injection sur le passé)
                p_val, lo_v, hi_v = self._fit_predict(df_train, v_steps, df_val['date'])
    
                # Métriques
                y_true = df_val['level'].values
                mae  = mean_absolute_error(y_true, p_val)
                rmse = np.sqrt(mean_squared_error(y_true, p_val))
                nonzero = y_true != 0
                mape = (np.mean(np.abs((y_true[nonzero] - p_val[nonzero]) / y_true[nonzero])) * 100 
                        if nonzero.any() else float('nan'))
    
                self.metrics = {'MAE': mae, 'RMSE': rmse, 'MAPE': mape}
                self.metrics_labels['MAE'].config(text=f'{mae:.4f} m')
                self.metrics_labels['RMSE'].config(text=f'{rmse:.4f} m')
                self.metrics_labels['MAPE'].config(text=f'{mape:.2f} %' if not np.isnan(mape) else 'N/A')
    
                # ── 4. Fit Final & Prévision future
                fut_s = future_steps(self.freq, self.cfg.future_years)
                fut_dates = pd.date_range(
                    self.df['date'].max(), periods=fut_s + 1, freq=self.freq)[1:]
    
                p_fut, lo_f, hi_f = self._fit_predict(self.df, fut_s, pd.Series(fut_dates))
    
                # ── 5. CALCUL DE L'IMPACT SPATIAL CUMULÉ
                Q = float(self.recharge_var.get())
                S = float(self.s_coeff_var.get())
                Area = float(self.area_var.get())
                K = float(self.k_var.get())
                dist = float(self.dist_var.get())
                
                # On calcule l'impact pour chaque pas de temps futur
                impact_spatial = []
                days_per_step = {'D': 1, 'W': 7, 'MS': 30.44, 'QS': 91.25, 'YS': 365.25}.get(self.freq, 30.44)
                
                for i in range(1, len(p_fut) + 1):
                    total_days = i * days_per_step
                    # Calcul de la remontée spécifique à cette distance et ce temps
                    h = self.calculate_spatial_impact(Q, S, K, dist, total_days, Area)
                    impact_spatial.append(h)
                
                impact_spatial = np.array(impact_spatial)
                
                # Application de l'impact sur les prévisions
                p_fut = p_fut + impact_spatial
                lo_f  = lo_f  + impact_spatial
                hi_f  = hi_f  + impact_spatial
                
                # Sécurité anti-division par zéro
                if Area > 0 and S > 0:
                    # On s'assure que S est physiquement réaliste (entre 0.0001 et 1.0)
                    safe_s = max(0.0001, min(S, 1.0))
                    rise_per_step = (Q * days_per_step) / (Area * safe_s)
                else:
                    rise_per_step = 0
                
                # L'impact est cumulatif (l'eau reste dans la nappe)
                impact_cumule = np.cumsum(np.full(len(p_fut), rise_per_step))
                
                p_fut = p_fut + impact_cumule
                lo_f  = lo_f  + impact_cumule
                hi_f  = hi_f  + impact_cumule
    
                # ── 6. Sauvegarde et affichage
                self.pred_df = pd.DataFrame({
                    'date':      fut_dates,
                    'prevision': p_fut,
                    'ic_bas':    lo_f,
                    'ic_haut':   hi_f,
                })
    
                self.show_plot(df_train, df_val, p_val, lo_v, hi_v,
                               fut_dates, p_fut, lo_f, hi_f)
                self.set_status('Analyse terminée.', '#1a7a1a')
    
            except Exception as e:
                self.set_status('Erreur lors de l\'analyse.', '#cc0000')
                messagebox.showerror("Erreur analyse", str(e))

    def _fit_predict(self, df_fit: pd.DataFrame, steps: int,
                     future_dates: pd.Series):
        """Dispatch vers le bon modèle."""
        model_name = self.cfg.model
        sp = freq_to_seasonal_periods(self.freq)
        y = df_fit['level'].values

        if model_name == 'ETS':
            m = ETSModel(self.cfg.ets_type, sp, self.cfg.ci_level)
            m.fit(y)
            pred, lo, hi = m.predict(steps)

        elif model_name == 'ARIMA':
            m = ARIMAModel(sp, self.cfg.ci_level)
            m.fit(y)
            pred, lo, hi = m.predict(steps)

        elif model_name in ('RandomForest', 'XGBoost'):
            m = SklearnModel(model_name, self.cfg.ci_level,
                             self.cfg.n_bootstraps)
            m.fit(df_fit)
            pred, lo, hi = m.predict(future_dates)

        else:
            raise ValueError(f'Modèle inconnu : {model_name}')

        return np.array(pred), np.array(lo), np.array(hi)

    # ── Visualisation ───────────────────────────────────────────────────────────

    def show_plot(self, df_train, df_val,
                  pred_val, lo_val, hi_val,
                  future_dates, pred_fut, lo_fut, hi_fut):
        for w in self.content.winfo_children():
            w.destroy()

        plt.close('all')
        
        # On ne crée plus qu'un seul axe (ax) au lieu de deux
        fig, ax = plt.subplots(figsize=(11, 7), dpi=95)
        fig.patch.set_facecolor('#fafafa')

        ci_pct = int((1 - self.cfg.ci_level) * 100)
        val_dates = df_val['date'].values

        # ── Zones de fond colorées
        split_date   = df_val['date'].iloc[0]
        end_val_date = df_val['date'].iloc[-1]

        ax.axvspan(df_train['date'].iloc[0], split_date,
                   alpha=0.04, color='#2c7be5', zorder=0)
        ax.axvspan(split_date, end_val_date,
                   alpha=0.07, color='#f6c90e', zorder=0)
        ax.axvspan(end_val_date, future_dates[-1],
                   alpha=0.05, color='#20c997', zorder=0)

        # ── Séparateurs verticaux
        ax.axvline(split_date, color='#f6c90e', linewidth=1.4, linestyle='--', zorder=2)
        ax.axvline(end_val_date, color='#20c997', linewidth=1.4, linestyle='--', zorder=2)

        # ── 1. Historique entraînement
        ax.plot(df_train['date'], df_train['level'],
                color='#2c7be5', linewidth=1.6, label='Historique (entraînement)', zorder=3)

        # ── 2. Valeurs réelles de contrôle
        ax.plot(val_dates, df_val['level'],
                color='#f6c90e', linewidth=2.0, zorder=4, label='Valeurs réelles (contrôle)')

        # ── 3. Courbe modélisée — validation
        ax.plot(val_dates, pred_val,
                color='#e85d04', linewidth=1.8, linestyle='--',
                zorder=4, label='Modèle (validation)')
        ax.fill_between(val_dates, lo_val, hi_val,
                        alpha=0.15, color='#e85d04', label=f'IC {ci_pct}% (validation)')

        # ── 4. Raccord visuel et dernière valeur réelle
        last_real_date = df_val['date'].iloc[-1]
        last_real_level = df_val['level'].iloc[-1]
        ax.scatter([last_real_date], [last_real_level],
                   color='#e85d04', s=55, zorder=6, marker='D', label='Dernière valeur réelle')

        # ── 5. Prévision future
        ax.plot(future_dates, pred_fut,
                color='#20c997', linewidth=2.2, linestyle='--',
                zorder=4, label='Prévision future')
        ax.fill_between(future_dates, lo_fut, hi_fut,
                        alpha=0.15, color='#20c997', label=f'IC {ci_pct}% (futur)')

        # ── Formatage des Axes (Dates en abscisses) ──
        ax.set_title(f'Prévision Piézométrique — {self.cfg.model} | IC {ci_pct}%', 
                     fontsize=13, fontweight='bold', pad=12)
        ax.set_ylabel('Niveau piézométrique (m)')
        ax.grid(True, alpha=0.22)
        ax.legend(fontsize=8, ncol=3, loc='upper left')

        # Formatage précis de l'axe X
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m')) # Affiche Année-Mois
        
        # Incliner les dates pour éviter le chevauchement
        fig.autofmt_xdate()


        # Intégration dans Tkinter
        canvas = FigureCanvasTkAgg(fig, master=self.content)
        canvas.draw()
        
        # Utilise get_tk_widget() au lieu de get_widget()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')

    # ── Export ──────────────────────────────────────────────────────────────────

    def export_csv(self):
        if self.pred_df is None:
            messagebox.showwarning('Attention', 'Aucun résultat à exporter.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            out = self.pred_df.copy()
            out['date'] = out['date'].dt.date
            out.to_csv(path, index=False, float_format='%.4f')
            # Ajoute les métriques en commentaire
            if self.metrics:
                with open(path, 'a') as f:
                    f.write('\n# Métriques validation\n')
                    for k, v in self.metrics.items():
                        f.write(f'# {k},{v:.4f}\n')
            self.set_status('Export CSV terminé.', '#1a7a1a')


# ─── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    # Optionnel : Appliquer un style global plus moderne
    style = ttk.Style()
    if 'arc' in style.theme_names():
        style.theme_use('arc')
        
    app = App(root)
    root.mainloop()