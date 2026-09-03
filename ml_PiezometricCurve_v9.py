import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.filedialog import askopenfilename
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Circle, FancyArrowPatch
import matplotlib.patches as mpatches
from dateutil.relativedelta import relativedelta
from scipy.special import exp1
from scipy.optimize import minimize
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
from pathlib import Path
from dataclasses import dataclass
import warnings
import threading
import time
warnings.filterwarnings('ignore')

APP_TITLE = 'Expert Piézométrie Pro — Digital Twin'
APP_SIZE  = '1350x880'

# ─── Palette Digital Twin ───────────────────────────────────────────────────────
DT_BG        = '#0d1b2a'   # fond très sombre
DT_PANEL     = '#112233'   # panneaux
DT_ACCENT    = '#00d4ff'   # cyan tech
DT_ACCENT2   = '#00ff9f'   # vert eau
DT_WARN      = '#ff6b35'   # alerte orange
DT_CRIT      = '#ff2d55'   # critique rouge
DT_GRID      = '#1a3045'   # grille
DT_TEXT      = '#cde0f0'   # texte clair
DT_DIM       = '#4a6a80'   # texte atténué


# ─── Config ────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    file_path:         str   = ''
    model:             str   = 'ETS'
    ets_type:          str   = '3'
    future_years:      int   = 5
    validation_years:  int   = 20
    ci_level:          float = 0.05
    n_bootstraps:      int   = 200
    recharge_factor:   float = 0.0
    storage_coeff:     float = 0.05
    influence_area:    float = 100.0
    aquifer_thickness: float = 10.0


# ─── Helpers feature engineering ───────────────────────────────────────────────

def make_features(dates: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({'date': pd.to_datetime(dates)})
    df['t']         = (df['date'] - df['date'].min()).dt.days
    df['month']     = df['date'].dt.month
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['year']      = df['date'].dt.year
    df['quarter']   = df['date'].dt.quarter
    return df.drop(columns=['date'])

def _compute_correlation_matrix(self, loaded):
    resampled = {}
    for i, c in loaded.items():
        s = c['df'].set_index('date')['level'].sort_index()
        resampled[c['name']] = s.resample('MS').mean()
    combined = pd.DataFrame(resampled).dropna()
    if len(combined) < 3:
        return None, 0
    return combined.corr(method='pearson'), len(combined)

def detect_frequency(dates: pd.Series) -> str:
    diffs = dates.diff().dropna().dt.days
    median_diff = diffs.median()
    if median_diff <= 1.5:   return 'D'
    elif median_diff <= 8:   return 'W'
    elif median_diff <= 35:  return 'MS'
    elif median_diff <= 100: return 'QS'
    else:                    return 'YS'


def align_chronicle(df_source, target_dates):
    s = df_source.set_index('date')['level'].sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(target_dates))
    combined = s.index.union(idx)
    s_full = s.reindex(combined).astype(float).interpolate(method='time', limit_direction='both')
    return s_full.reindex(idx).values

def freq_to_seasonal_periods(freq: str) -> int:
    return {'D': 365, 'W': 52, 'MS': 12, 'QS': 4, 'YS': 1}.get(freq, 12)


def future_steps(freq: str, years: int) -> int:
    return {'D': years * 365, 'W': years * 52, 'MS': years * 12,
            'QS': years * 4, 'YS': years}.get(freq, years * 12)


def create_features(series, lags):
    df_y = pd.DataFrame(series.copy())
    df_y.columns = ['y']
    lag_cols = [df_y['y'].shift(i).rename(f'lag_{i}') for i in range(1, lags + 1)]
    df = pd.concat([df_y] + lag_cols, axis=1)
    return df.dropna().astype(float)


def calibrate_params(levels):
    std = np.std(levels)
    return max(0.01, min(0.1, std / 10)), std / 20, 0.2


def apply_hydro_model(prediction_series, storage, r_factor, r_mait, pumping,
                      h_str, ppy, last_date):
    adjusted = prediction_series.values.copy()
    cumul    = 0.0
    s_val    = storage if storage > 0 else 0.02
    for i in range(len(adjusted)):
        adjusted[i] += r_factor * np.sin(2 * np.pi * i / ppy)
        if prediction_series.index[i] > last_date:
            cumul += ((r_mait - pumping) / 12 / s_val) * h_str
        adjusted[i] += cumul
    return pd.Series(adjusted, index=prediction_series.index)


# ─── Modèles ───────────────────────────────────────────────────────────────────

class ETSModel:
    def __init__(self, ets_type: str, seasonal_periods: int, ci_level: float):
        self.ets_type = ets_type
        self.sp       = seasonal_periods
        self.ci_level = ci_level
        self.fit_     = None

    def fit(self, y: np.ndarray):
        t  = self.ets_type
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
        sim  = self.fit_.simulate(steps, repetitions=500, error='mul')
        pred = self.fit_.forecast(steps)
        alpha = self.ci_level
        lo   = np.quantile(sim, alpha / 2,     axis=1)
        hi   = np.quantile(sim, 1 - alpha / 2, axis=1)
        return pred, lo, hi


class ARIMAModel:
    CANDIDATES = [
        (1, 1, 1), (1, 1, 0), (0, 1, 1),
        (2, 1, 1), (1, 1, 2), (2, 1, 2),
        (0, 1, 2), (2, 1, 0),
    ]

    def __init__(self, seasonal_periods: int, ci_level: float):
        self.sp       = seasonal_periods
        self.ci_level = ci_level
        self.res_     = None
        self.order_   = None

    def _is_stationary(self, y):
        try:
            return adfuller(y)[1] < 0.05
        except Exception:
            return False

    def fit(self, y: np.ndarray):
        d  = 0 if self._is_stationary(y) else 1
        sp = self.sp if self.sp > 1 else 0
        best_aic = np.inf
        best_res = None
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
                    self.order_ = (p, d, q)
            except Exception:
                continue
        if best_res is None:
            raise RuntimeError("ARIMA : impossible d'ajuster le modèle.")
        self.res_ = best_res
        return self

    def predict(self, steps: int):
        fc   = self.res_.get_forecast(steps=steps)
        pred = fc.predicted_mean
        ci   = fc.conf_int(alpha=self.ci_level)
        lo   = ci.iloc[:, 0].values
        hi   = ci.iloc[:, 1].values
        return pred, lo, hi


class SklearnModel:
    def __init__(self, kind: str, ci_level: float, n_bootstraps: int):
        self.kind         = kind
        self.ci_level     = ci_level
        self.n_bootstraps = n_bootstraps
        self.models_      = []
        self.scaler_      = StandardScaler()
        self.train_origin_ = None

    def _make_model(self):
        if self.kind == 'RandomForest':
            return RandomForestRegressor(n_estimators=100, max_depth=6,
                                         random_state=42, n_jobs=-1)
        else:
            return GradientBoostingRegressor(n_estimators=200, max_depth=4,
                                             learning_rate=0.05,
                                             subsample=0.8, random_state=42)

    def fit(self, df: pd.DataFrame):
        self.train_origin_ = df['date'].min()
        X = make_features(df['date'])
        y = df['level'].values
        X_scaled = self.scaler_.fit_transform(X)
        n = len(y)
        for _ in range(self.n_bootstraps):
            idx = np.random.choice(n, int(n * 0.8), replace=True)
            m   = self._make_model()
            m.fit(X_scaled[idx], y[idx])
            self.models_.append(m)
        return self

    def predict(self, future_dates: pd.Series):
        df_feat = pd.DataFrame({'date': pd.to_datetime(future_dates)})
        df_feat['t']         = (df_feat['date'] - self.train_origin_).dt.days
        df_feat['month']     = df_feat['date'].dt.month
        df_feat['month_sin'] = np.sin(2 * np.pi * df_feat['month'] / 12)
        df_feat['month_cos'] = np.cos(2 * np.pi * df_feat['month'] / 12)
        df_feat['year']      = df_feat['date'].dt.year
        df_feat['quarter']   = df_feat['date'].dt.quarter
        X_fut    = df_feat.drop(columns=['date'])
        X_scaled = self.scaler_.transform(X_fut)
        preds    = np.array([m.predict(X_scaled) for m in self.models_])
        pred     = preds.mean(axis=0)
        lo       = np.percentile(preds, self.ci_level * 100, axis=0)
        hi       = np.percentile(preds, (1 - self.ci_level) * 100, axis=0)
        lo = pd.Series(lo).rolling(3, min_periods=1).mean().values
        hi = pd.Series(hi).rolling(3, min_periods=1).mean().values
        return pred, lo, hi


# ─── Application principale ────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root    = root
        self.root.title(APP_TITLE)
        self.root.geometry(APP_SIZE)
        self.root.minsize(1100, 750)
        #self.df      = None
        self.chronicles = {1: None, 2: None, 3: None}
        self.target_idx = 1
        self.df = None
        self.pred_df = None
        self.cfg     = Config()
        self.freq    = 'MS'
        self.metrics = {}

        # État Digital Twin
        self.dt_running      = False
        self.dt_thread       = None
        self.dt_tick         = 0
        self.dt_sim_Q        = None   # sera créé dans l'onglet DT
        self.dt_sim_S        = None
        self.dt_sim_K        = None
        self.dt_sim_dist     = None
        self.dt_sim_thick    = None
        self.dt_canvas_2d    = None
        self.dt_canvas_dash  = None
        self.dt_canvas_sim   = None
        self._last_dt_params = None

        self.build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────────
    def build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
    
        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = tk.Frame(self.root, bg='#1f2d3d', width=290)
        sidebar.grid(row=0, column=0, sticky='nswe')
        sidebar.grid_propagate(False)
    
        main = tk.Frame(self.root, bg='#f5f6fa')
        main.grid(row=0, column=1, sticky='nswe')
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        
        self.main = main
    
        tk.Label(sidebar, text='Expert Piézométrie Pro',
                 fg='white', bg='#1f2d3d',
                 font=('Segoe UI', 13, 'bold')).pack(pady=14)
    
        # ── Chroniques ADES (3 requises) ────────────────────────────────────
        chron_frame = ttk.LabelFrame(sidebar, text="Chroniques ADES (3 points — même masse d'eau)")
        chron_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(chron_frame,
                  text="Fichier Excel unique contenant date / niveau / nom du point (une colonne par point).",
                  wraplength=250, font=('Segoe UI', 8)).pack(fill='x', padx=8, pady=(6, 4))
        
        ttk.Button(chron_frame, text='📂  Charger fichier ADES',
                   command=self.load_multi_source).pack(fill='x', padx=8, pady=3)
        
        self.source_status_lbl = ttk.Label(chron_frame, text='Aucun fichier chargé.',
                                            foreground='#cc0000', font=('Segoe UI', 8),
                                            wraplength=250, justify='left')
        self.source_status_lbl.pack(fill='x', padx=8, pady=(2, 6))
        
        self.point_vars = []
        self.point_cbs  = []
        
        for i in (1, 2, 3):
            row = ttk.Frame(chron_frame)
            row.pack(fill='x', padx=8, pady=2)
            ttk.Label(row, text=f'Point {i} :', width=8).pack(side='left')
            pv = tk.StringVar(value='')
            cb = ttk.Combobox(row, textvariable=pv, state='readonly', values=[])
            cb.pack(side='left', fill='x', expand=True)
            cb.bind('<<ComboboxSelected>>', self._on_point_selection_change)
            self.point_vars.append(pv)
            self.point_cbs.append(cb)
        
        target_row = ttk.Frame(chron_frame)
        target_row.pack(fill='x', padx=8, pady=(4, 2))
        ttk.Label(target_row, text='Piézomètre à prévoir :',
                  font=('Segoe UI', 8, 'bold')).pack(anchor='w')
        
        self.target_var = tk.StringVar(value='')
        self.target_cb = ttk.Combobox(target_row, textvariable=self.target_var,
                                       state='readonly', values=[])
        self.target_cb.pack(fill='x', pady=(2, 0))
        self.target_cb.bind('<<ComboboxSelected>>', self._on_target_change)
        
        self.ready_status_lbl = ttk.Label(chron_frame,
                                           text='3 points requis avant analyse.',
                                           foreground='#cc0000', font=('Segoe UI', 8),
                                           wraplength=250, justify='left')
        self.ready_status_lbl.pack(fill='x', padx=8, pady=(4, 8))
    
        # ── Actions ──────────────────────────────────────────────────────────
        self.run_btn = ttk.Button(sidebar, text='▶  Lancer Analyse',
                                   command=self.run_analysis, state='disabled')
        self.run_btn.pack(fill='x', padx=14, pady=3)
    
        ttk.Button(sidebar, text='💾  Exporter CSV',
                   command=self.export_csv).pack(fill='x', padx=14, pady=3)
        ttk.Button(sidebar, text='✕  Quitter',
                   command=self.root.destroy).pack(fill='x', padx=14, pady=10)
    
        # ── Paramètres modèle
        params = ttk.LabelFrame(sidebar, text='Paramètres modèle')
        params.pack(fill='x', padx=10, pady=5)
    
        self.model_var = tk.StringVar(value='ETS')
        ttk.Label(params, text='Modèle').pack(anchor='w', padx=8, pady=(6, 0))
        model_cb = ttk.Combobox(params, textvariable=self.model_var,
                                values=['ETS', 'ARIMA', 'RandomForest', 'XGBoost'],
                                state='readonly')
        model_cb.pack(fill='x', padx=8, pady=3)
        model_cb.bind('<<ComboboxSelected>>', self._on_model_change)
    
        ttk.Label(params,
                  text="ETS = univarié (chronique cible seule).\nARIMA/RandomForest/XGBoost exploitent les 3 chroniques.",
                  foreground='#888', font=('Segoe UI', 7), wraplength=250,
                  justify='left').pack(fill='x', padx=8, pady=(0, 4))
    
        self.ets_frame = ttk.Frame(params)
        self.ets_frame.pack(fill='x')
        self.ets_var = tk.StringVar(value='4')
        ttk.Label(self.ets_frame, text='Type ETS').pack(anchor='w', padx=8)
        ttk.Combobox(self.ets_frame, textvariable=self.ets_var,
                     values=['1 - Simple', '2 - Tendance',
                             '3 - Saisonnier', '4 - Complet'],
                     state='readonly').pack(fill='x', padx=8, pady=3)
    
        self.future_var = tk.IntVar(value=5)
        ttk.Label(params, text='Années futures').pack(anchor='w', padx=8)
        ttk.Entry(params, textvariable=self.future_var).pack(fill='x', padx=8, pady=3)
    
        self.val_var = tk.IntVar(value=20)
        ttk.Label(params, text='Années validation').pack(anchor='w', padx=8)
        ttk.Entry(params, textvariable=self.val_var).pack(fill='x', padx=8, pady=3)
    
        # ── Injection Maîtrisée
        recharge_frame = ttk.LabelFrame(sidebar, text='Injection Maîtrisée')
        recharge_frame.pack(fill='x', padx=10, pady=5)
    
        self.thick_var = tk.DoubleVar(value=10.0)
        ttk.Label(recharge_frame, text="Épaisseur Aquifère (m)").pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.thick_var).pack(fill='x', padx=8, pady=2)
    
        self.recharge_var = tk.DoubleVar(value=0.0)
        ttk.Label(recharge_frame, text='Débit injecté (m³/jour)').pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.recharge_var).pack(fill='x', padx=8, pady=2)
    
        self.s_coeff_var = tk.DoubleVar(value=0.05)
        ttk.Label(recharge_frame, text='Coeff. Emmagasinement (S)').pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.s_coeff_var).pack(fill='x', padx=8, pady=2)
    
        self.area_var = tk.DoubleVar(value=100.0)
        ttk.Label(recharge_frame, text="Surface de l'ouvrage (m²)").pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.area_var).pack(fill='x', padx=8, pady=2)
    
        self.dist_var = tk.DoubleVar(value=50.0)
        ttk.Label(recharge_frame, text='Distance piézo/ouvrage (m)').pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.dist_var).pack(fill='x', padx=8, pady=2)
    
        self.k_var = tk.DoubleVar(value=0.0001)
        ttk.Label(recharge_frame, text='Perméabilité K (m/s)').pack(anchor='w', padx=8, pady=(4, 0))
        ttk.Entry(recharge_frame, textvariable=self.k_var).pack(fill='x', padx=8, pady=(2, 6))
    
        ttk.Button(recharge_frame, text="🎯 Caler sur l'historique",
                   command=self.calibrate_hydro_parameters).pack(fill='x', padx=8, pady=6)
    
        # ── Intervalle de confiance
        ci_frame = ttk.LabelFrame(sidebar, text='Intervalle de confiance')
        ci_frame.pack(fill='x', padx=10, pady=5)
    
        self.ci_var = tk.DoubleVar(value=68.0)
        ttk.Label(ci_frame, text='Niveau (%)').pack(anchor='w', padx=8, pady=(5, 0))
        ttk.Entry(ci_frame, textvariable=self.ci_var).pack(fill='x', padx=8, pady=3)
    
        self.boot_var = tk.IntVar(value=200)
        ttk.Label(ci_frame, text='Bootstraps (RF/XGB)').pack(anchor='w', padx=8)
        ttk.Entry(ci_frame, textvariable=self.boot_var).pack(fill='x', padx=8, pady=3)
    
        # ── Métriques
        self.metrics_frame = ttk.LabelFrame(sidebar, text='Métriques validation')
        self.metrics_frame.pack(fill='x', padx=10, pady=5)
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
        self.status = tk.Label(top, text='Prêt — chargez les 3 chroniques piézométriques (ADES)',
                               bg='#f5f6fa', fg='#555',
                               font=('Consolas', 10))
        self.status.pack(anchor='w', padx=15, pady=8)
        self.freq_label = tk.Label(top, text='', bg='#f5f6fa', fg='#888',
                                   font=('Consolas', 9))
        self.freq_label.pack(anchor='w', padx=15)
    
        # ── Notebook Onglets
        self.nb = ttk.Notebook(main)
        self.nb.grid(row=1, column=0, sticky='nswe', padx=10, pady=8)
    
        # Onglet 1 : Réseau piézométrique (3 chroniques)
        self.tab_network = tk.Frame(self.nb, bg='white')
        self.nb.add(self.tab_network, text='🌊  Réseau Piézo')
        self._build_network_tab()
    
        # Onglet 2 : tableau + graphique principal
        self.tab_main = tk.Frame(self.nb, bg='white')
        self.nb.add(self.tab_main, text='📊  Analyse')
        self.tab_main.rowconfigure(0, weight=1)
        self.tab_main.columnconfigure(0, weight=1)
    
        self.content = self.tab_main   # compatibilité avec show_plot
    
        self.table = ttk.Treeview(self.tab_main,
                                  columns=('date', 'level'), show='headings')
        self.table.heading('date',  text='Date')
        self.table.heading('level', text='Niveau (m)')
        self.table.column('date',  width=160)
        self.table.column('level', width=120)
        self.table.grid(row=0, column=0, sticky='nswe')
        sb = ttk.Scrollbar(self.tab_main, orient='vertical',
                           command=self.table.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=sb.set)
    
        # Onglet 3 : Digital Twin
        self.tab_dt = tk.Frame(self.nb, bg=DT_BG)
        self.nb.add(self.tab_dt, text='🌐  Digital Twin')
        self._build_digital_twin_tab()
    
    # def build_ui(self):
    #     self.root.columnconfigure(1, weight=1)
    #     self.root.rowconfigure(0, weight=1)

    #     # ── Sidebar ──────────────────────────────────────────────────────────
    #     sidebar = tk.Frame(self.root, bg='#1f2d3d', width=290)
    #     sidebar.grid(row=0, column=0, sticky='nswe')
    #     sidebar.grid_propagate(False)

    #     main = tk.Frame(self.root, bg='#f5f6fa')
    #     main.grid(row=0, column=1, sticky='nswe')
    #     main.rowconfigure(1, weight=1)
    #     main.columnconfigure(0, weight=1)
    #     self.main = main

    #     tk.Label(sidebar, text='Expert Piézométrie Pro',
    #              fg='white', bg='#1f2d3d',
    #              font=('Segoe UI', 13, 'bold')).pack(pady=14)

    #     ttk.Button(sidebar, text='📂  Charger Excel',
    #                command=self.load_file).pack(fill='x', padx=14, pady=3)
    #     ttk.Button(sidebar, text='▶  Lancer Analyse',
    #                command=self.run_analysis).pack(fill='x', padx=14, pady=3)
    #     ttk.Button(sidebar, text='💾  Exporter CSV',
    #                command=self.export_csv).pack(fill='x', padx=14, pady=3)
    #     ttk.Button(sidebar, text='✕  Quitter',
    #                command=self.root.destroy).pack(fill='x', padx=14, pady=10)

    #     # ── Paramètres modèle
    #     params = ttk.LabelFrame(sidebar, text='Paramètres modèle')
    #     params.pack(fill='x', padx=10, pady=5)

    #     self.model_var = tk.StringVar(value='ETS')
    #     ttk.Label(params, text='Modèle').pack(anchor='w', padx=8, pady=(6, 0))
    #     model_cb = ttk.Combobox(params, textvariable=self.model_var,
    #                             values=['ETS', 'ARIMA', 'RandomForest', 'XGBoost'],
    #                             state='readonly')
    #     model_cb.pack(fill='x', padx=8, pady=3)
    #     model_cb.bind('<<ComboboxSelected>>', self._on_model_change)

    #     self.ets_frame = ttk.Frame(params)
    #     self.ets_frame.pack(fill='x')
    #     self.ets_var = tk.StringVar(value='4')
    #     ttk.Label(self.ets_frame, text='Type ETS').pack(anchor='w', padx=8)
    #     ttk.Combobox(self.ets_frame, textvariable=self.ets_var,
    #                  values=['1 - Simple', '2 - Tendance',
    #                          '3 - Saisonnier', '4 - Complet'],
    #                  state='readonly').pack(fill='x', padx=8, pady=3)

    #     self.future_var = tk.IntVar(value=5)
    #     ttk.Label(params, text='Années futures').pack(anchor='w', padx=8)
    #     ttk.Entry(params, textvariable=self.future_var).pack(fill='x', padx=8, pady=3)

    #     self.val_var = tk.IntVar(value=20)
    #     ttk.Label(params, text='Années validation').pack(anchor='w', padx=8)
    #     ttk.Entry(params, textvariable=self.val_var).pack(fill='x', padx=8, pady=3)

    #     # ── Injection Maîtrisée
    #     recharge_frame = ttk.LabelFrame(sidebar, text='Injection Maîtrisée')
    #     recharge_frame.pack(fill='x', padx=10, pady=5)

    #     self.thick_var = tk.DoubleVar(value=10.0)
    #     ttk.Label(recharge_frame, text="Épaisseur Aquifère (m)").pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.thick_var).pack(fill='x', padx=8, pady=2)

    #     self.recharge_var = tk.DoubleVar(value=0.0)
    #     ttk.Label(recharge_frame, text='Débit injecté (m³/jour)').pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.recharge_var).pack(fill='x', padx=8, pady=2)

    #     self.s_coeff_var = tk.DoubleVar(value=0.05)
    #     ttk.Label(recharge_frame, text='Coeff. Emmagasinement (S)').pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.s_coeff_var).pack(fill='x', padx=8, pady=2)

    #     self.area_var = tk.DoubleVar(value=100.0)
    #     ttk.Label(recharge_frame, text="Surface de l'ouvrage (m²)").pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.area_var).pack(fill='x', padx=8, pady=2)

    #     self.dist_var = tk.DoubleVar(value=50.0)
    #     ttk.Label(recharge_frame, text='Distance piézo/ouvrage (m)').pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.dist_var).pack(fill='x', padx=8, pady=2)

    #     self.k_var = tk.DoubleVar(value=0.0001)
    #     ttk.Label(recharge_frame, text='Perméabilité K (m/s)').pack(anchor='w', padx=8, pady=(4, 0))
    #     ttk.Entry(recharge_frame, textvariable=self.k_var).pack(fill='x', padx=8, pady=(2, 6))

    #     ttk.Button(recharge_frame, text="🎯 Caler sur l'historique",
    #                command=self.calibrate_hydro_parameters).pack(fill='x', padx=8, pady=6)

    #     # ── Intervalle de confiance
    #     ci_frame = ttk.LabelFrame(sidebar, text='Intervalle de confiance')
    #     ci_frame.pack(fill='x', padx=10, pady=5)

    #     self.ci_var = tk.DoubleVar(value=68.0)
    #     ttk.Label(ci_frame, text='Niveau (%)').pack(anchor='w', padx=8, pady=(5, 0))
    #     ttk.Entry(ci_frame, textvariable=self.ci_var).pack(fill='x', padx=8, pady=3)

    #     self.boot_var = tk.IntVar(value=200)
    #     ttk.Label(ci_frame, text='Bootstraps (RF/XGB)').pack(anchor='w', padx=8)
    #     ttk.Entry(ci_frame, textvariable=self.boot_var).pack(fill='x', padx=8, pady=3)

    #     # ── Métriques
    #     self.metrics_frame = ttk.LabelFrame(sidebar, text='Métriques validation')
    #     self.metrics_frame.pack(fill='x', padx=10, pady=5)
    #     self.metrics_labels = {}
    #     for key in ('MAE', 'RMSE', 'MAPE'):
    #         row = tk.Frame(self.metrics_frame, bg='#f0f0f0')
    #         row.pack(fill='x', padx=6, pady=2)
    #         tk.Label(row, text=f'{key}:', width=6, anchor='w',
    #                  bg='#f0f0f0').pack(side='left')
    #         lbl = tk.Label(row, text='—', fg='#1a6ea8',
    #                        font=('Consolas', 10, 'bold'), bg='#f0f0f0')
    #         lbl.pack(side='left')
    #         self.metrics_labels[key] = lbl

    #     # ── Status bar
    #     top = tk.Frame(main, bg='#f5f6fa')
    #     top.grid(row=0, column=0, sticky='ew')
    #     self.status = tk.Label(top, text='Prêt — chargez un fichier Excel',
    #                            bg='#f5f6fa', fg='#555',
    #                            font=('Consolas', 10))
    #     self.status.pack(anchor='w', padx=15, pady=8)
    #     self.freq_label = tk.Label(top, text='', bg='#f5f6fa', fg='#888',
    #                                font=('Consolas', 9))
    #     self.freq_label.pack(anchor='w', padx=15)

    #     # ── Notebook Onglets
    #     self.nb = ttk.Notebook(main)
    #     self.nb.grid(row=1, column=0, sticky='nswe', padx=10, pady=8)

    #     # Onglet 1 : tableau + graphique principal
    #     self.tab_main = tk.Frame(self.nb, bg='white')
    #     self.nb.add(self.tab_main, text='📊  Analyse')
    #     self.tab_main.rowconfigure(0, weight=1)
    #     self.tab_main.columnconfigure(0, weight=1)

    #     self.content = self.tab_main   # compatibilité avec show_plot

    #     self.table = ttk.Treeview(self.tab_main,
    #                               columns=('date', 'level'), show='headings')
    #     self.table.heading('date',  text='Date')
    #     self.table.heading('level', text='Niveau (m)')
    #     self.table.column('date',  width=160)
    #     self.table.column('level', width=120)
    #     self.table.grid(row=0, column=0, sticky='nswe')
    #     sb = ttk.Scrollbar(self.tab_main, orient='vertical',
    #                        command=self.table.yview)
    #     sb.grid(row=0, column=1, sticky='ns')
    #     self.table.configure(yscrollcommand=sb.set)

    #     # Onglet 2 : Digital Twin
    #     self.tab_dt = tk.Frame(self.nb, bg=DT_BG)
    #     self.nb.add(self.tab_dt, text='🌐  Digital Twin')
    #     self._build_digital_twin_tab()

    def _on_model_change(self, _event=None):
        if self.model_var.get() == 'ETS':
            self.ets_frame.pack(fill='x')
        else:
            self.ets_frame.pack_forget()

    def _on_target_change(self, event=None):
        names = list(self.target_cb['values'])
        idx = names.index(self.target_var.get()) + 1
        self.target_idx = idx
        self.refresh_chronicles_view()
        
    def _refresh_target_choices(self):
        names = [
            self.chronicles[i]['name'] if self.chronicles[i] else f'Piézo {i}'
            for i in (1, 2, 3)
        ]
        self.target_cb['values'] = names
        if self.target_var.get() not in names:
            self.target_var.set(names[0])
            
    def _parse_multi_piezo_excel(self, path):
        df = pd.read_excel(path)
        if df.shape[1] < 3:
            raise ValueError("Le fichier doit contenir au moins 3 colonnes : date / niveau / nom du point.")
        date_col  = self._find_column(df, self.DATE_ALIASES)
        level_col = self._find_column(df, self.LEVEL_ALIASES)
        point_col = self._find_column(df, self.POINT_ALIASES)
        masse_col = self._find_column(df, self.MASSE_EAU_ALIASES)
        if date_col is None or level_col is None or point_col is None:
            raise ValueError(
                f'Colonnes détectées : {list(df.columns)}\n\n'
                f"Date : {date_col or '❌'}   Niveau : {level_col or '❌'}   Point : {point_col or '❌'}"
            )
        cols    = [date_col, level_col, point_col] + ([masse_col] if masse_col else [])
        names   = ['date', 'level', 'point'] + (['masse_eau'] if masse_col else [])
        df = df[cols].copy()
        df.columns = names
        df['date']  = pd.to_datetime(df['date'], errors='coerce')
        df['level'] = pd.to_numeric(df['level'], errors='coerce')
        df['point'] = df['point'].astype(str).str.strip()
        if 'masse_eau' in df.columns:
            df['masse_eau'] = df['masse_eau'].astype(str).str.strip()
        else:
            df['masse_eau'] = ''
        df = df.dropna(subset=['date', 'level', 'point']).sort_values(['point', 'date']).reset_index(drop=True)
        points = sorted(df['point'].unique().tolist())
        if len(points) < 3:
            raise ValueError(f"Seuls {len(points)} point(s) distinct(s) détecté(s) — 3 sont requis.")
        return df, points, (masse_col is not None)
    
    def load_multi_source(self):
        path = filedialog.askopenfilename(filetypes=[('Excel', '*.xlsx *.xls')])
        if not path:
            return
        try:
            df, points, has_masse = self._parse_multi_piezo_excel(path)
            self.source_df = df
            self.masse_eau_available = has_masse
            for cb in self.point_cbs:
                cb['values'] = points
            for i, pv in enumerate(self.point_vars):
                pv.set(points[i] if i < len(points) else '')
            self.source_status_lbl.config(
                text=f"✓ {len(points)} points détectés dans {Path(path).name}"
                     + ('' if has_masse else " (⚠ pas de colonne masse d'eau — à vérifier manuellement)"),
                foreground='#1a7a1a')
            self._on_point_selection_change()
        except Exception as e:
            messagebox.showerror('Erreur chargement', str(e))
    
    def _on_point_selection_change(self, event=None):
        sel = [pv.get() for pv in self.point_vars]
        if len(set(sel)) < 3 or any(not s for s in sel):
            self.chronicles = {1: None, 2: None, 3: None}
            self.ready_status_lbl.config(text='Sélectionnez 3 points distincts.', foreground='#cc0000')
            self.run_btn.config(state='disabled')
            self._plot_network_chronicles()
            return
    
        chronicles = {}
        for idx, point_name in enumerate(sel, start=1):
            sub = self.source_df.loc[self.source_df['point'] == point_name, ['date', 'level']] \
                                 .reset_index(drop=True)
            if len(sub) < 24:
                self.chronicles = {1: None, 2: None, 3: None}
                self.ready_status_lbl.config(
                    text=f"Point « {point_name} » : {len(sub)} observations valides (min 24).",
                    foreground='#cc0000')
                self.run_btn.config(state='disabled')
                self._plot_network_chronicles()
                return
            masse_vals = self.source_df.loc[self.source_df['point'] == point_name, 'masse_eau']
            chronicles[idx] = {
                'df': sub,
                'name': point_name,
                'masse_eau': masse_vals.iloc[0] if len(masse_vals) else '',
                'path': None,
            }
        self.chronicles = chronicles
        self._refresh_target_choices()
        self.refresh_chronicles_view()
            
    # def load_chronicle(self, idx):
    #     path = filedialog.askopenfilename(filetypes=[('Excel', '*.xlsx *.xls')])
    #     if not path:
    #         return
    #     try:
    #         df = self._parse_piezo_excel(path)
    #         w = self.chron_widgets[idx]
    #         self.chronicles[idx] = {
    #             'df': df,
    #             'name': w['name_var'].get().strip() or f'Piézo {idx}',
    #             'masse_eau': w['masse_var'].get().strip(),
    #             'path': path,
    #         }
    #         w['status_lbl'].config(text=f'✓ chargé ({len(df)} obs.)', foreground='#1a7a1a')
    #         self._refresh_target_choices()
    #         self.refresh_chronicles_view()
    #     except Exception as e:
    #         messagebox.showerror('Erreur chargement', str(e))
            
    # def _parse_piezo_excel(self, path):
    #     df = pd.read_excel(path)
    #     if df.shape[1] < 2:
    #         raise ValueError('Le fichier doit contenir au moins 2 colonnes : date / niveau')
    #     date_col  = self._find_column(df, self.DATE_ALIASES)
    #     level_col = self._find_column(df, self.LEVEL_ALIASES)
    #     if date_col is None or level_col is None:
    #         available = list(df.columns)
    #         raise ValueError(
    #             f'Colonnes détectées : {available}\n\n'
    #             f"Colonne date trouvée : {date_col or '❌ NON TROUVÉE'}\n"
    #             f"Colonne niveau trouvée : {level_col or '❌ NON TROUVÉE'}\n\n"
    #             "Renommez les colonnes en 'date' et 'level' dans votre fichier."
    #         )
    #     df = df[[date_col, level_col]].copy()
    #     df.columns = ['date', 'level']
    #     df['date']  = pd.to_datetime(df['date'],  errors='coerce')
    #     df['level'] = pd.to_numeric(df['level'], errors='coerce')
    #     df = df.dropna().sort_values('date').reset_index(drop=True)
    #     if len(df) < 24:
    #         raise ValueError(f'Données insuffisantes : {len(df)} observations valides (min 24).')
    #     return df
    
    def chronicles_ready(self):
        loaded = {i: c for i, c in self.chronicles.items() if c is not None}
        if len(loaded) < 3:
            return False, f"Il manque {3 - len(loaded)} point(s) — 3 sont requis."
        if not getattr(self, 'masse_eau_available', False):
            return True, "✓ 3 points prêts (masse d'eau non renseignée dans le fichier — à vérifier manuellement)."
        masses = [c['masse_eau'].strip() for c in loaded.values()]
        if any(not m for m in masses):
            return False, "Code masse d'eau manquant pour un ou plusieurs points."
        if len({m.lower() for m in masses}) > 1:
            return False, f"Points issus de masses d'eau différentes : {sorted(set(masses))}."
        return True, f"✓ 3 points prêts — masse d'eau : {masses[0]}"
    
    def refresh_chronicles_view(self):
        ok, msg = self.chronicles_ready()
        self.ready_status_lbl.config(text=msg, foreground=('#1a7a1a' if ok else '#cc0000'))
        self.run_btn.config(state='normal' if ok else 'disabled')
        self._plot_network_chronicles()
        if ok:
            self._build_merged_dataset()
    
    def _build_merged_dataset(self):
        target = self.chronicles[self.target_idx]['df'].copy()
        self.freq = detect_frequency(target['date'])
        merged = target.copy()
        j = 1
        for i in (1, 2, 3):
            if i == self.target_idx:
                continue
            merged[f'level_aux{j}'] = align_chronicle(self.chronicles[i]['df'], merged['date'])
            j += 1
        self.df = merged
        freq_names = {'D': 'Journalier', 'W': 'Hebdomadaire',
                      'MS': 'Mensuel', 'QS': 'Trimestriel', 'YS': 'Annuel'}
        self.freq_label.config(
            text=f'Fréquence détectée : {freq_names.get(self.freq, self.freq)}'
                 f' — {len(target)} observations (cible : {self.chronicles[self.target_idx]["name"]})')
        self.populate_table(target)
        self.set_status('Chroniques prêtes — analyse disponible.', '#1a7a1a')
        
    def _compute_correlation_matrix(self, loaded):
        resampled = {}
        for i, c in loaded.items():
            s = c['df'].set_index('date')['level'].sort_index()
            resampled[c['name']] = s.resample('MS').mean()
        combined = pd.DataFrame(resampled).dropna()
        if len(combined) < 3:
            return None, 0
        return combined.corr(method='pearson'), len(combined)

    def _build_network_tab(self):
        tab = self.tab_network
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(2, weight=0)
        tab.columnconfigure(0, weight=1)
        header = tk.Frame(tab, bg='white')
        header.grid(row=0, column=0, sticky='ew')
        tk.Label(header, text="Réseau de 3 chroniques piézométriques ADES (même masse d'eau)",
                 font=('Segoe UI', 11, 'bold'), bg='white').pack(anchor='w', padx=10, pady=8)
        self.network_plot_frame = tk.Frame(tab, bg='white')
        self.network_plot_frame.grid(row=1, column=0, sticky='nswe')
        self.network_plot_frame.rowconfigure(0, weight=1)
        self.network_plot_frame.columnconfigure(0, weight=1)
    
        self.corr_frame = tk.Frame(tab, bg='#f5f6fa', highlightbackground='#ccc', highlightthickness=1)
        self.corr_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=(0, 10))
        self.corr_label = tk.Label(self.corr_frame, text='Corrélation : chargez les 3 points.',
                                    bg='#f5f6fa', fg='#555', font=('Consolas', 9),
                                    justify='left', anchor='w')
        self.corr_label.pack(fill='x', padx=10, pady=8)
    
        self._plot_network_chronicles()

    # def _build_network_tab(self):
    #     tab = self.tab_network
    #     tab.rowconfigure(1, weight=1)
    #     tab.rowconfigure(2, weight=0)
    #     tab.columnconfigure(0, weight=1)
    #     header = tk.Frame(tab, bg='white')
    #     header.grid(row=0, column=0, sticky='ew')
    #     tk.Label(header, text="Réseau de 3 chroniques piézométriques ADES (même masse d'eau)",
    #              font=('Segoe UI', 11, 'bold'), bg='white').pack(anchor='w', padx=10, pady=8)
        
    #     self.network_plot_frame = tk.Frame(tab, bg='white')
    #     self.network_plot_frame.grid(row=1, column=0, sticky='nswe')
    #     self.network_plot_frame.rowconfigure(0, weight=1)
    #     self.network_plot_frame.columnconfigure(0, weight=1)
    #     self._plot_network_chronicles()
    
    def _plot_network_chronicles(self):
        
        for w in self.network_plot_frame.winfo_children():
            w.destroy()
        loaded = {i: c for i, c in self.chronicles.items() if c is not None}
        if not loaded:
            tk.Label(self.network_plot_frame,
                     text="Chargez les 3 chroniques piézométriques (panneau de gauche) pour afficher le réseau.",
                     bg='white', fg='#888', font=('Segoe UI', 10)).grid(row=0, column=0, pady=40)
            if hasattr(self, 'corr_label'):
                self.corr_label.config(text='Corrélation : chargez les 3 points.', fg='#555')
            return
        
        for w in self.network_plot_frame.winfo_children():
            w.destroy()
        loaded = {i: c for i, c in self.chronicles.items() if c is not None}
        if not loaded:
            tk.Label(self.network_plot_frame,
                     text="Chargez les 3 chroniques piézométriques (panneau de gauche) pour afficher le réseau.",
                     bg='white', fg='#888', font=('Segoe UI', 10)).grid(row=0, column=0, pady=40)
            return
        plt.close('all')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), dpi=95, facecolor='white')
        colors = {1: '#2c7be5', 2: '#e85d04', 3: '#20c997'}
        for i, c in loaded.items():
            df = c['df']
            ax1.plot(df['date'], df['level'], color=colors[i], linewidth=1.4,
                      label=f"{c['name']} (masse d'eau : {c['masse_eau'] or '—'})")
            z = (df['level'] - df['level'].mean()) / (df['level'].std() or 1)
            ax2.plot(df['date'], z, color=colors[i], linewidth=1.2, label=c['name'])
        ax1.set_title('Chroniques piézométriques brutes', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Niveau (m)')
        ax1.legend(fontsize=8)
        ax1.grid(alpha=0.25)
        ax2.set_title("Comparaison normalisée (z-score) — cohérence hydrogéologique", fontsize=10)
        ax2.set_ylabel('Niveau centré-réduit')
        ax2.legend(fontsize=8)
        ax2.grid(alpha=0.25)
        fig.autofmt_xdate()
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.network_plot_frame)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')
        
        canvas = FigureCanvasTkAgg(fig, master=self.network_plot_frame)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')
    
        # ── Corrélation par paires ──────────────────────────────────────────
        if hasattr(self, 'corr_label'):
            if len(loaded) < 3:
                self.corr_label.config(
                    text=f"Corrélation : {len(loaded)}/3 point(s) chargé(s).", fg='#a07000')
            else:
                corr, n_pts = self._compute_correlation_matrix(loaded)
                if corr is None:
                    self.corr_label.config(
                        text="Corrélation : pas assez de dates communes entre les 3 points.",
                        fg='#cc0000')
                else:
                    names = corr.columns.tolist()
                    pairs = [(names[0], names[1]), (names[0], names[2]), (names[1], names[2])]
                    lines = []
                    for a, b in pairs:
                        r = corr.loc[a, b]
                        tag = '✓ forte' if abs(r) >= 0.7 else ('~ modérée' if abs(r) >= 0.4 else '✗ faible')
                        lines.append(f'r({a}, {b}) = {r:+.2f}  [{tag}]')
                    txt = f"Corrélation (Pearson, base mensuelle, n={n_pts} mois communs) :\n" + '\n'.join(lines)
                    min_abs_r = corr.where(~np.eye(len(corr), dtype=bool)).abs().min().min()
                    self.corr_label.config(
                        text=txt,
                        fg=('#1a7a1a' if min_abs_r >= 0.7 else ('#a07000' if min_abs_r >= 0.4 else '#cc0000')))

    # ══════════════════════════════════════════════════════════════════════════
    # ─── DIGITAL TWIN TAB ──────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════

    def _build_digital_twin_tab(self):
        """Construit l'onglet Digital Twin avec 3 zones."""
        tab = self.tab_dt
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=3)
        tab.rowconfigure(1, weight=2)

        # ── En-tête Digital Twin
        hdr = tk.Frame(tab, bg=DT_BG)
        hdr.grid(row=0, column=0, columnspan=2, sticky='ew', padx=0, pady=0)

        tk.Label(hdr, text='◈  JUMEAU NUMÉRIQUE AQUIFÈRE',
                 bg=DT_BG, fg=DT_ACCENT,
                 font=('Courier New', 14, 'bold')).pack(side='left', padx=18, pady=8)

        self.dt_status_lbl = tk.Label(hdr, text='● HORS LIGNE',
                                      bg=DT_BG, fg=DT_WARN,
                                      font=('Courier New', 10, 'bold'))
        self.dt_status_lbl.pack(side='left', padx=20)

        self.dt_tick_lbl = tk.Label(hdr, text='TICK: 0',
                                    bg=DT_BG, fg=DT_DIM,
                                    font=('Courier New', 9))
        self.dt_tick_lbl.pack(side='left', padx=10)

        btn_frame = tk.Frame(hdr, bg=DT_BG)
        btn_frame.pack(side='right', padx=12)

        self.dt_start_btn = tk.Button(
            btn_frame, text='▶ DÉMARRER',
            bg='#00443a', fg=DT_ACCENT2,
            font=('Courier New', 9, 'bold'),
            relief='flat', padx=10, pady=4,
            command=self.dt_start)
        self.dt_start_btn.pack(side='left', padx=4)

        self.dt_stop_btn = tk.Button(
            btn_frame, text='■ ARRÊTER',
            bg='#440018', fg=DT_CRIT,
            font=('Courier New', 9, 'bold'),
            relief='flat', padx=10, pady=4,
            command=self.dt_stop,
            state='disabled')
        self.dt_stop_btn.pack(side='left', padx=4)

        tk.Button(btn_frame, text='⟳ RAFRAÎCHIR',
                  bg='#002244', fg=DT_ACCENT,
                  font=('Courier New', 9, 'bold'),
                  relief='flat', padx=10, pady=4,
                  command=self.dt_refresh_all).pack(side='left', padx=4)

        # ── Zone 1 : Simulation 2D de la nappe (haut-gauche)
        frame_2d = tk.Frame(tab, bg=DT_PANEL,
                            highlightbackground=DT_ACCENT,
                            highlightthickness=1)
        frame_2d.grid(row=1, column=0, sticky='nswe', padx=(8, 4), pady=(4, 8))
        frame_2d.rowconfigure(1, weight=1)
        frame_2d.columnconfigure(0, weight=1)

        tk.Label(frame_2d, text='◇  CARTE NAPPE 2D — ZONES D\'INFLUENCE & FLUX',
                 bg=DT_PANEL, fg=DT_ACCENT,
                 font=('Courier New', 10, 'bold')).grid(row=0, column=0,
                                                         sticky='w', padx=10, pady=6)

        self.frame_2d_inner = tk.Frame(frame_2d, bg=DT_PANEL)
        self.frame_2d_inner.grid(row=1, column=0, sticky='nswe')
        self.frame_2d_inner.rowconfigure(0, weight=1)
        self.frame_2d_inner.columnconfigure(0, weight=1)

        # ── Zone 2 : Tableau de bord live (haut-droite)
        frame_dash = tk.Frame(tab, bg=DT_PANEL,
                              highlightbackground=DT_ACCENT2,
                              highlightthickness=1)
        frame_dash.grid(row=1, column=1, sticky='nswe', padx=(4, 8), pady=(4, 8))
        frame_dash.rowconfigure(1, weight=1)
        frame_dash.columnconfigure(0, weight=1)

        tk.Label(frame_dash, text='◇  TABLEAU DE BORD TEMPS RÉEL',
                 bg=DT_PANEL, fg=DT_ACCENT2,
                 font=('Courier New', 10, 'bold')).grid(row=0, column=0,
                                                         sticky='w', padx=10, pady=6)

        self.frame_dash_inner = tk.Frame(frame_dash, bg=DT_PANEL)
        self.frame_dash_inner.grid(row=1, column=0, sticky='nswe')
        self.frame_dash_inner.rowconfigure(0, weight=1)
        self.frame_dash_inner.columnconfigure(0, weight=1)

        self._build_dashboard(self.frame_dash_inner)

        # ── Zone 3 : Simulation interactive (bas, toute la largeur)
        frame_sim = tk.Frame(tab, bg=DT_PANEL,
                             highlightbackground='#ffaa00',
                             highlightthickness=1)
        frame_sim.grid(row=2, column=0, columnspan=2, sticky='nswe',
                       padx=8, pady=(0, 8))
        frame_sim.rowconfigure(1, weight=1)
        frame_sim.columnconfigure(0, weight=1)

        tk.Label(frame_sim, text='◇  SIMULATEUR INTERACTIF — PARAMÈTRES EN TEMPS RÉEL',
                 bg=DT_PANEL, fg='#ffaa00',
                 font=('Courier New', 10, 'bold')).grid(row=0, column=0,
                                                         sticky='w', padx=10, pady=6)

        self.frame_sim_inner = tk.Frame(frame_sim, bg=DT_PANEL)
        self.frame_sim_inner.grid(row=1, column=0, sticky='nswe')
        self.frame_sim_inner.rowconfigure(0, weight=1)
        self.frame_sim_inner.columnconfigure(0, weight=1)

        self._build_interactive_sim(self.frame_sim_inner)

        # Ajuster les proportions des lignes
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=5)
        tab.rowconfigure(2, weight=3)

    # ── Dashboard live ────────────────────────────────────────────────────────

    def _build_dashboard(self, parent):
        """Tableau de bord avec jauges et indicateurs numériques."""
        # Canvas pour les jauges matplotlib
        fig, axes = plt.subplots(2, 3, figsize=(5.5, 3.8),
                                 facecolor=DT_PANEL)
        fig.subplots_adjust(wspace=0.35, hspace=0.45,
                            left=0.06, right=0.97,
                            top=0.88, bottom=0.12)
        self.dt_dash_fig  = fig
        self.dt_dash_axes = axes.flatten()

        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')
        self.dt_canvas_dash = canvas

        self._draw_dashboard_empty()

    def _draw_dashboard_empty(self):
        """Dessine les jauges vides au démarrage."""
        indicators = [
            ('Niveau actuel', '—', 'm NGF', DT_ACCENT),
            ('Variation 30j', '—', 'm', DT_ACCENT2),
            ('Tendance', '—', 'm/an', '#ffaa00'),
            ('Impact injection', '—', 'm', DT_WARN),
            ('Risque nappe', '—', '%', DT_CRIT),
            ('Temps rech.', '—', 'jours', '#cc99ff'),
        ]
        for i, (title, val, unit, color) in enumerate(indicators):
            ax = self.dt_dash_axes[i]
            ax.set_facecolor(DT_GRID)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            ax.set_title(title, color=DT_DIM, fontsize=7.5,
                         fontfamily='Courier New', pad=3)
            ax.text(0.5, 0.52, val, ha='center', va='center',
                    color=color, fontsize=20, fontweight='bold',
                    fontfamily='Courier New',
                    transform=ax.transAxes)
            ax.text(0.5, 0.18, unit, ha='center', va='center',
                    color=DT_DIM, fontsize=8,
                    fontfamily='Courier New',
                    transform=ax.transAxes)
            for spine in ax.spines.values():
                spine.set_edgecolor(color)
                spine.set_linewidth(0.8)
                spine.set_visible(True)
        self.dt_canvas_dash.draw()

    def _update_dashboard(self, niveau_actuel, variation_30j, tendance,
                          impact_inj, risque, temps_rech):
        """Met à jour les valeurs affichées dans le dashboard."""
        def fmt(v, decimals=2):
            return f'{v:+.{decimals}f}' if isinstance(v, float) and v != 0 else f'{v:.{decimals}f}' if isinstance(v, float) else str(v)

        # Couleur dynamique selon seuils
        def risk_color(r):
            if r < 30:   return DT_ACCENT2
            elif r < 60: return '#ffaa00'
            else:        return DT_CRIT

        data = [
            ('Niveau actuel', f'{niveau_actuel:.2f}',   'm NGF',  DT_ACCENT),
            ('Variation 30j', fmt(variation_30j),        'm',      DT_ACCENT2 if variation_30j >= 0 else DT_WARN),
            ('Tendance',      fmt(tendance),             'm/an',   DT_ACCENT2 if tendance >= 0 else DT_WARN),
            ('Impact inj.',   f'{impact_inj:+.3f}',     'm',      DT_ACCENT),
            ('Risque nappe',  f'{risque:.0f}',           '%',      risk_color(risque)),
            ('Temps rech.',   f'{temps_rech:.0f}',       'jours',  '#cc99ff'),
        ]
        for i, (title, val, unit, color) in enumerate(data):
            ax = self.dt_dash_axes[i]
            ax.cla()
            ax.set_facecolor(DT_GRID)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            ax.set_title(title, color=DT_DIM, fontsize=7.5,
                         fontfamily='Courier New', pad=3)
            ax.text(0.5, 0.52, val, ha='center', va='center',
                    color=color, fontsize=18, fontweight='bold',
                    fontfamily='Courier New',
                    transform=ax.transAxes)
            ax.text(0.5, 0.18, unit, ha='center', va='center',
                    color=DT_DIM, fontsize=8, fontfamily='Courier New',
                    transform=ax.transAxes)
            for spine in ax.spines.values():
                spine.set_edgecolor(color)
                spine.set_linewidth(1.2)
                spine.set_visible(True)
        self.dt_canvas_dash.draw_idle()

    # ── Simulation 2D nappe ───────────────────────────────────────────────────

    def _draw_nappe_2d(self, Q, S, K, thickness, distance, time_days, Area,
                       niveau_base=0.0):
        """Dessine la carte 2D de la nappe avec zones d'influence (Theis)."""
        parent = self.frame_2d_inner
        for w in parent.winfo_children():
            w.destroy()

        fig, ax = plt.subplots(figsize=(5.8, 3.8), facecolor=DT_BG)
        ax.set_facecolor('#06101a')

        # Grille de calcul
        size  = max(distance * 3, 200)
        nx, ny = 120, 120
        x = np.linspace(-size, size, nx)
        y = np.linspace(-size, size, ny)
        X, Y = np.meshgrid(x, y)
        R    = np.sqrt(X**2 + Y**2)
        R    = np.maximum(R, 1e-3)

        # Calcul rabattement / hausse (Theis)
        T = K * thickness
        impact_grid = np.zeros_like(R)
        if T > 0 and S > 0 and time_days > 0 and Q > 0:
            u = (R**2 * S) / (4 * T * time_days)
            mask = u < 5
            impact_grid[mask] = (Q / (4 * np.pi * T)) * exp1(u[mask])
            impact_grid = np.clip(impact_grid, 0, niveau_base + 10)

        # Niveaux piézométriques
        niveau_field = niveau_base + impact_grid

        # Fond coloré
        levels_cmap = np.linspace(niveau_field.min(), niveau_field.max(), 60)
        cf = ax.contourf(X, Y, niveau_field,
                         levels=levels_cmap,
                         cmap='Blues_r', alpha=0.85)
        # Lignes isopièzes
        cs = ax.contour(X, Y, niveau_field,
                        levels=12, colors=DT_ACCENT,
                        linewidths=0.6, alpha=0.55)
        ax.clabel(cs, inline=True, fontsize=6, fmt='%.1f m',
                  colors=DT_ACCENT)

        # Colorbar
        cbar = fig.colorbar(cf, ax=ax, fraction=0.035, pad=0.02)
        cbar.ax.tick_params(colors=DT_DIM, labelsize=7)
        cbar.set_label('Niveau piézo. (m)', color=DT_DIM, fontsize=7)
        cbar.ax.yaxis.set_tick_params(color=DT_DIM)

        # Marqueur ouvrage (source)
        R_bassin = np.sqrt(Area / np.pi)
        circ_src = Circle((0, 0), R_bassin,
                           color=DT_WARN, fill=True, alpha=0.5, zorder=6)
        ax.add_patch(circ_src)
        ax.plot(0, 0, 'o', color=DT_WARN, ms=8, zorder=7, label='Ouvrage injection')

        # Rayon d'influence (Theis à seuil 1 cm)
        if T > 0 and S > 0 and time_days > 0 and Q > 0:
            # u tel que W(u) ≈ 0.01 * 4πT/Q → rayon limite
            r_inf = min(size * 0.95, np.sqrt(4 * T * time_days / S) * 2)
            circ_inf = Circle((0, 0), r_inf,
                              color=DT_ACCENT2, fill=False,
                              linestyle='--', linewidth=1.4,
                              alpha=0.8, zorder=5, label=f"R influence ≈{r_inf:.0f}m")
            ax.add_patch(circ_inf)

        # Piézomètre
        ax.plot(distance, 0, '^', color='#ffee00', ms=10, zorder=8,
                label=f'Piézomètre ({distance:.0f}m)')
        ax.annotate(f' Piézo\n {distance:.0f} m',
                    (distance, 0),
                    color='#ffee00', fontsize=7,
                    fontfamily='Courier New',
                    xytext=(distance + size * 0.05, size * 0.08))

        # Flèches flux radial
        n_arr = 8
        angles = np.linspace(0, 2 * np.pi, n_arr, endpoint=False)
        arr_r  = r_inf * 0.45 if T > 0 and Q > 0 else size * 0.4
        for ang in angles:
            dx = np.cos(ang) * arr_r * 0.18
            dy = np.sin(ang) * arr_r * 0.18
            ax.annotate('', xy=(np.cos(ang) * arr_r * 0.55,
                                np.sin(ang) * arr_r * 0.55),
                        xytext=(np.cos(ang) * arr_r * 0.25,
                                np.sin(ang) * arr_r * 0.25),
                        arrowprops=dict(arrowstyle='->', color=DT_ACCENT2,
                                        lw=0.9, alpha=0.55))

        ax.set_xlim(-size, size)
        ax.set_ylim(-size, size)
        ax.set_aspect('equal')
        ax.set_title(f'Simulation Theis — t={time_days:.0f}j  Q={Q:.1f}m³/j  '
                     f'K={K:.1e}m/s',
                     color=DT_TEXT, fontsize=8, fontfamily='Courier New', pad=6)
        ax.set_xlabel('Distance Est (m)', color=DT_DIM, fontsize=7)
        ax.set_ylabel('Distance Nord (m)', color=DT_DIM, fontsize=7)
        ax.tick_params(colors=DT_DIM, labelsize=6.5)
        for spine in ax.spines.values():
            spine.set_edgecolor(DT_GRID)
        ax.legend(fontsize=6.5, loc='upper right',
                  facecolor=DT_PANEL, edgecolor=DT_ACCENT,
                  labelcolor=DT_TEXT)
        ax.grid(True, color=DT_GRID, linewidth=0.4, alpha=0.6)

        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')
        self.dt_canvas_2d = canvas

    # ── Simulation interactive ─────────────────────────────────────────────────

    def _build_interactive_sim(self, parent):
        """Panneau de simulation avec sliders et graphique temps réel."""
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        # Sliders
        sliders_frame = tk.Frame(parent, bg=DT_PANEL)
        sliders_frame.grid(row=0, column=0, sticky='nswe', padx=8, pady=6)

        def make_slider(frame, row, label, from_, to, var, fmt='%.3f', res=0.001):
            tk.Label(frame, text=label, bg=DT_PANEL, fg=DT_DIM,
                     font=('Courier New', 8)).grid(row=row*2, column=0,
                                                    columnspan=2,
                                                    sticky='w', pady=(6, 0))
            val_lbl = tk.Label(frame, text=fmt % var.get(),
                               bg=DT_PANEL, fg=DT_ACCENT,
                               font=('Courier New', 9, 'bold'), width=10)
            val_lbl.grid(row=row*2, column=2, sticky='e')

            def on_change(v, vl=val_lbl, fmt=fmt, var=var):
                vl.config(text=fmt % float(v))
                self._on_sim_slider_change()

            sl = tk.Scale(frame, from_=from_, to=to,
                          orient='horizontal', resolution=res,
                          variable=var,
                          bg=DT_PANEL, fg=DT_TEXT,
                          troughcolor=DT_GRID,
                          highlightthickness=0,
                          showvalue=False,
                          command=on_change)
            sl.grid(row=row*2+1, column=0, columnspan=3, sticky='ew', pady=1)
            frame.columnconfigure(0, weight=1)
            return sl

        # Variables sliders DT
        self.dt_Q_var     = tk.DoubleVar(value=50.0)
        self.dt_S_var     = tk.DoubleVar(value=0.05)
        self.dt_K_var     = tk.DoubleVar(value=0.0001)
        self.dt_dist_var  = tk.DoubleVar(value=50.0)
        self.dt_thick_var = tk.DoubleVar(value=10.0)
        self.dt_t_var     = tk.DoubleVar(value=180.0)

        make_slider(sliders_frame, 0, 'Q — Débit injecté (m³/j)',
                    0, 500, self.dt_Q_var, fmt='%.1f m³/j', res=1.0)
        make_slider(sliders_frame, 1, 'S — Coeff. emmagasinement',
                    0.0001, 0.3, self.dt_S_var, fmt='%.4f', res=0.0001)
        make_slider(sliders_frame, 2, 'K — Perméabilité (m/s)',
                    1e-7, 1e-2, self.dt_K_var, fmt='%.2e m/s', res=1e-6)
        make_slider(sliders_frame, 3, 'r — Distance piézo/ouvrage (m)',
                    1, 500, self.dt_dist_var, fmt='%.0f m', res=1.0)
        make_slider(sliders_frame, 4, 'b — Épaisseur aquifère (m)',
                    1, 100, self.dt_thick_var, fmt='%.1f m', res=0.5)
        make_slider(sliders_frame, 5, 't — Durée simulation (jours)',
                    1, 3650, self.dt_t_var, fmt='%.0f j', res=1.0)

        # Bouton sync depuis sidebar
        tk.Button(sliders_frame, text='⬇ Sync depuis paramètres principaux',
                  bg='#001833', fg=DT_ACCENT,
                  font=('Courier New', 8), relief='flat',
                  command=self._sync_sliders_from_sidebar).grid(
            row=13, column=0, columnspan=3, sticky='ew', pady=10)

        # Graphique simulation réponse temporelle
        sim_plot_frame = tk.Frame(parent, bg=DT_PANEL)
        sim_plot_frame.grid(row=0, column=1, sticky='nswe', padx=(0, 8), pady=6)
        sim_plot_frame.rowconfigure(0, weight=1)
        sim_plot_frame.columnconfigure(0, weight=1)

        fig, ax = plt.subplots(figsize=(5.5, 3.0), facecolor=DT_PANEL)
        ax.set_facecolor(DT_BG)
        ax.set_title('Réponse piézométrique — Impact cumulé', color=DT_TEXT,
                     fontsize=9, fontfamily='Courier New')
        ax.tick_params(colors=DT_DIM, labelsize=7)
        for sp in ax.spines.values():
            sp.set_edgecolor(DT_GRID)
        ax.grid(True, color=DT_GRID, linewidth=0.4)
        fig.tight_layout()

        self.dt_sim_fig = fig
        self.dt_sim_ax  = ax
        canvas = FigureCanvasTkAgg(fig, master=sim_plot_frame)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')
        self.dt_canvas_sim = canvas

        # Dessin initial
        self.root.after(200, self._on_sim_slider_change)

    def _sync_sliders_from_sidebar(self):
        """Synchronise les sliders DT depuis les valeurs de la sidebar."""
        try:
            self.dt_Q_var.set(float(self.recharge_var.get()))
            self.dt_S_var.set(float(self.s_coeff_var.get()))
            self.dt_K_var.set(float(self.k_var.get()))
            self.dt_dist_var.set(float(self.dist_var.get()))
            self.dt_thick_var.set(float(self.thick_var.get()))
            self._on_sim_slider_change()
        except Exception:
            pass

    def _on_sim_slider_change(self, *_):
        """Réponse immédiate aux changements de sliders : mise à jour du graphique."""
        try:
            Q     = self.dt_Q_var.get()
            S     = max(self.dt_S_var.get(), 1e-5)
            K     = max(self.dt_K_var.get(), 1e-8)
            dist  = self.dt_dist_var.get()
            thick = self.dt_thick_var.get()
            t_max = self.dt_t_var.get()
            Area  = float(self.area_var.get())

            # Réponse temporelle au piézomètre
            t_arr     = np.linspace(1, t_max, 300)
            impact_t  = np.array([
                self.calculate_spatial_impact(Q, S, K, thick, dist, t, Area)
                for t in t_arr
            ])

            # Impact cumulé volumétrique simplifié
            days_step = t_arr[1] - t_arr[0]
            vol_rise  = np.cumsum(np.full(len(t_arr),
                                           (Q * days_step) / (Area * S) if Area > 0 else 0))

            total_impact = impact_t + vol_rise

            # Niveau de base
            niveau_base = self.df['level'].iloc[-1] if self.df is not None else 0.0

            ax = self.dt_sim_ax
            ax.cla()
            ax.set_facecolor(DT_BG)

            ax.plot(t_arr, impact_t + niveau_base,
                    color=DT_ACCENT, linewidth=1.8, label='Impact Theis (spatial)')
            ax.plot(t_arr, total_impact + niveau_base,
                    color=DT_ACCENT2, linewidth=2.0,
                    linestyle='--', label='Impact total (spatial + volumétrique)')
            ax.axhline(niveau_base, color=DT_DIM, linewidth=0.8,
                       linestyle=':', label='Niveau de base')

            # Zone d'alerte
            seuil_haut = niveau_base + max(impact_t.max(), total_impact.max()) * 0.7
            ax.axhspan(seuil_haut, seuil_haut + 5, alpha=0.15, color=DT_WARN)

            ax.set_title(f'Réponse piézométrique — Q={Q:.0f}m³/j  K={K:.1e}m/s  r={dist:.0f}m',
                         color=DT_TEXT, fontsize=8, fontfamily='Courier New')
            ax.set_xlabel('Temps (jours)', color=DT_DIM, fontsize=7.5)
            ax.set_ylabel('Niveau NGF (m)', color=DT_DIM, fontsize=7.5)
            ax.tick_params(colors=DT_DIM, labelsize=7)
            for sp in ax.spines.values():
                sp.set_edgecolor(DT_GRID)
            ax.grid(True, color=DT_GRID, linewidth=0.4, alpha=0.6)
            ax.legend(fontsize=7, facecolor=DT_PANEL,
                      edgecolor=DT_ACCENT, labelcolor=DT_TEXT)
            self.dt_sim_fig.tight_layout()
            self.dt_canvas_sim.draw_idle()

            # Mise à jour carte 2D si le tab DT est actif
            params = (Q, S, K, thick, dist, t_max, Area)
            if params != self._last_dt_params:
                self._last_dt_params = params
                self.root.after(50, lambda: self._draw_nappe_2d(
                    Q, S, K, thick, dist, t_max, Area, niveau_base))

                # Mise à jour dashboard
                if self.df is not None:
                    self._compute_and_update_dashboard(Q, S, K, thick, dist, Area)

        except Exception as e:
            pass  # Évite les crashs pendant le glissement

    def _compute_and_update_dashboard(self, Q, S, K, thick, dist, Area):
        """Calcule les indicateurs du dashboard et les affiche."""
        try:
            df = self.df
            niveau_actuel = df['level'].iloc[-1]

            # Variation sur les 30 derniers pas
            n_30 = min(30, len(df) - 1)
            variation_30j = df['level'].iloc[-1] - df['level'].iloc[-1 - n_30]

            # Tendance (régression linéaire)
            n_trend = min(120, len(df))
            x_t  = np.arange(n_trend)
            y_t  = df['level'].values[-n_trend:]
            p    = np.polyfit(x_t, y_t, 1)
            freq_factor = {'D': 365, 'W': 52, 'MS': 12,
                           'QS': 4, 'YS': 1}.get(self.freq, 12)
            tendance = p[0] * freq_factor

            # Impact injection actuel (6 mois)
            impact_inj = self.calculate_spatial_impact(Q, S, K, thick, dist, 180, Area)

            # Risque nappe : heuristique basée sur tendance et variation
            if tendance < -0.5:
                risque = min(95, 60 + abs(tendance) * 10)
            elif tendance < 0:
                risque = min(60, 30 + abs(tendance) * 20)
            else:
                risque = max(5, 30 - tendance * 10)

            # Temps de recharge estimé (atteindre +0.5m)
            if Q > 0 and Area > 0 and S > 0:
                target_rise = 0.5
                rise_rate   = (Q / (Area * S))
                temps_rech  = max(1, target_rise / rise_rate) if rise_rate > 0 else 9999
            else:
                temps_rech = 9999

            self._update_dashboard(niveau_actuel, variation_30j, tendance,
                                   impact_inj, risque, temps_rech)
        except Exception:
            pass

    # ── Boucle Digital Twin ───────────────────────────────────────────────────

    def dt_start(self):
        if self.df is None:
            messagebox.showwarning('Attention',
                                   'Chargez des données avant de démarrer le Digital Twin.')
            return
        self.dt_running = True
        self.dt_start_btn.config(state='disabled')
        self.dt_stop_btn.config(state='normal')
        self.dt_status_lbl.config(text='● EN LIGNE', fg=DT_ACCENT2)
        self.nb.select(self.tab_dt)
        self._sync_sliders_from_sidebar()
        self._dt_loop()

    def dt_stop(self):
        self.dt_running = False
        self.dt_start_btn.config(state='normal')
        self.dt_stop_btn.config(state='disabled')
        self.dt_status_lbl.config(text='● HORS LIGNE', fg=DT_WARN)

    def _dt_loop(self):
        """Boucle de rafraîchissement du Digital Twin (via after)."""
        if not self.dt_running:
            return
        self.dt_tick += 1
        self.dt_tick_lbl.config(text=f'TICK: {self.dt_tick:05d}')

        # Légère fluctuation simulée (bruit capteur)
        if self.df is not None:
            noise = np.random.normal(0, 0.001)
            base  = self.df['level'].iloc[-1] + noise
            Q     = self.dt_Q_var.get()
            S     = max(self.dt_S_var.get(), 1e-5)
            K     = max(self.dt_K_var.get(), 1e-8)
            dist  = self.dt_dist_var.get()
            thick = self.dt_thick_var.get()
            Area  = float(self.area_var.get())
            self._compute_and_update_dashboard(Q, S, K, thick, dist, Area)

        # Rafraîchissement toutes les 3 secondes
        self.root.after(3000, self._dt_loop)

    def dt_refresh_all(self):
        """Rafraîchit manuellement toutes les vues DT."""
        self._on_sim_slider_change()

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTHODES ORIGINALES (inchangées)
    # ─────────────────────────────────────────────────────────────────────────

    def set_status(self, txt, color='#555'):
        self.status.config(text=txt, fg=color)
        self.root.update_idletasks()

    POINT_ALIASES = [
        'identifiant national bss', 'ancien code national bss',
        'nom point', 'point', 'code bss', 'nom_ouvrage', 'ouvrage',
        'piezometre', 'piézomètre', 'code point', 'nom_point', 'nom du point',
    ]
    
    MASSE_EAU_ALIASES = [
    "masse d'eau", 'masse deau', 'code masse eau',
    'masse_eau', 'code_masse_eau',
    ]

    DATE_ALIASES = [
        'date de la mesure', 'date_mesure', 'date mesure', 'date',
        'datetime', 'horodatage', 'timestamp',
    ]
    
    LEVEL_ALIASES = [
        'côte ngf', 'cote ngf', 'niveau ngf', 'niveau', 'level',
        'profondeur/repère de mesure', 'profondeur relative/repère de mesure',
        'valeur', 'mesure', 'hauteur',
    ]

    def _find_column(self, df, aliases):
        cols_lower = {c.lower().strip(): c for c in df.columns}
        for alias in aliases:
            if alias in cols_lower:
                return cols_lower[alias]
        return None

    # def load_chronicle(self, idx):
    #     path = filedialog.askopenfilename(filetypes=[('Excel', '*.xlsx *.xls')])
    #     if not path:
    #         return
    #     try:
    #         df = self._parse_piezo_excel(path)
    #         w = self.chron_widgets[idx]
    #         self.chronicles[idx] = {
    #             'df': df,
    #             'name': w['name_var'].get().strip() or f'Piézo {idx}',
    #             'masse_eau': w['masse_var'].get().strip(),
    #             'path': path,
    #         }
    #         w['status_lbl'].config(text=f'✓ chargé ({len(df)} obs.)', foreground='#1a7a1a')
    #         self._refresh_target_choices()
    #         self.refresh_chronicles_view()
    #     except Exception as e:
    #         messagebox.showerror('Erreur chargement', str(e))

    def populate_table(self, df):
        for item in self.table.get_children():
            self.table.delete(item)
        n = len(df)
        if n > 500:
            self.set_status(
                f"Aperçu limité à 500 lignes sur {n}.", '#a07000')
        for _, row in df.head(500).iterrows():
            self.table.insert('', 'end',
                              values=(row['date'].date(),
                                      f"{row['level']:.3f}"))

    def calculate_spatial_impact(self, Q, S, K, thickness, distance, time_days, Area):
        if time_days <= 0 or S <= 0 or K <= 0 or thickness <= 0:
            return 0
        R_bassin = np.sqrt(Area / np.pi)
        T = K * thickness
        if distance <= R_bassin:
            impact = (Q / (Area * S)) * (1 - np.exp(-time_days / 10))
        else:
            u = (distance ** 2 * S) / (4 * T * time_days)
            if u > 5:
                return 0
            impact = (Q / (4 * np.pi * T)) * exp1(u)
        return max(0, impact)

    def calibrate_hydro_parameters(self):
        if self.df is None:
            messagebox.showwarning("Attention", "Chargez des données avant de caler.")
            return
        self.set_status("Calibration automatique en cours...", "#a07000")
        v_steps  = future_steps(self.freq, self.cfg.validation_years)
        df_train = self.df.iloc[:-v_steps].copy()
        df_val   = self.df.iloc[-v_steps:].copy()
        p_base, _, _ = self._fit_predict(df_train, v_steps, df_val['date'])
        y_reel   = df_val['level'].values
        Q        = float(self.recharge_var.get())
        Area     = float(self.area_var.get())
        dist     = float(self.dist_var.get())
        b        = float(self.thick_var.get())
        days_per_step = {'D': 1, 'W': 7, 'MS': 30.44, 'QS': 91.25, 'YS': 365.25}.get(self.freq, 30.44)

        def objective(params):
            S_test, K_test = params
            impacts = []
            safe_s  = max(1e-5, S_test)
            rise_per_step = (Q * days_per_step) / (Area * safe_s) if Area > 0 else 0
            cumul_vol = 0
            for i in range(1, len(p_base) + 1):
                spatial = self.calculate_spatial_impact(Q, S_test, K_test, b, dist,
                                                        i * days_per_step, Area)
                cumul_vol += rise_per_step
                impacts.append(spatial + cumul_vol)
            p_totale = p_base + np.array(impacts)
            return np.sqrt(mean_squared_error(y_reel, p_totale))

        res = minimize(objective, x0=[0.05, 1e-4],
                       bounds=[(0.0001, 0.3), (1e-7, 1e-2)],
                       method='L-BFGS-B')
        if res.success:
            new_S, new_K = res.x
            self.s_coeff_var.set(round(new_S, 4))
            self.k_var.set(f"{new_K:.2e}")
            self.set_status("Calibration réussie !", "#1a7a1a")
            self.run_analysis()
        else:
            self.set_status("Échec de la calibration.", "#cc0000")

    def run_analysis(self):
        if self.df is None:
            messagebox.showwarning('Attention', "Chargez d'abord un fichier Excel.")
            return
        try:
            self.cfg.future_years     = int(self.future_var.get())
            self.cfg.validation_years = int(self.val_var.get())
            self.cfg.model            = self.model_var.get()
            Q    = float(self.recharge_var.get())
            S    = float(self.s_coeff_var.get())
            Area = float(self.area_var.get())
            K    = float(self.k_var.get())
            dist = float(self.dist_var.get())
            b    = float(self.thick_var.get())
            ci_pct = float(self.ci_var.get())
            if not (50.0 < ci_pct < 100.0):
                raise ValueError('Le niveau de confiance doit être entre 50 et 100 %.')
            self.cfg.ci_level     = (100.0 - ci_pct) / 200.0
            self.cfg.n_bootstraps = int(self.boot_var.get())
            self.cfg.ets_type     = self.ets_var.get()[0]
            self.set_status('Calcul en cours…', '#a07000')

            v_steps = future_steps(self.freq, self.cfg.validation_years)
            if v_steps >= len(self.df):
                raise ValueError("Période de validation trop grande.")
            df_train = self.df.iloc[:-v_steps].copy()
            df_val   = self.df.iloc[-v_steps:].copy()
            if v_steps < 1:
                raise ValueError('Pas assez de données pour la validation.')

            p_val, lo_v, hi_v = self._fit_predict(df_train, v_steps, df_val['date'])
            y_true = df_val['level'].values
            mae    = mean_absolute_error(y_true, p_val)
            rmse   = np.sqrt(mean_squared_error(y_true, p_val))
            nonzero = y_true != 0
            mape   = (np.mean(np.abs((y_true[nonzero] - p_val[nonzero]) / y_true[nonzero])) * 100
                      if nonzero.any() else float('nan'))

            self.metrics = {'MAE': mae, 'RMSE': rmse, 'MAPE': mape}
            self.metrics_labels['MAE'].config(text=f'{mae:.4f} m')
            self.metrics_labels['RMSE'].config(text=f'{rmse:.4f} m')
            self.metrics_labels['MAPE'].config(
                text=f'{mape:.2f} %' if not np.isnan(mape) else 'N/A')

            fut_s     = future_steps(self.freq, self.cfg.future_years)
            fut_dates = pd.date_range(
                self.df['date'].max(), periods=fut_s + 1, freq=self.freq)[1:]
            p_fut, lo_f, hi_f = self._fit_predict(self.df, fut_s, pd.Series(fut_dates))

            days_per_step = {'D': 1, 'W': 7, 'MS': 30.44,
                             'QS': 91.25, 'YS': 365.25}.get(self.freq, 30.44)
            impact_spatial = np.array([
                self.calculate_spatial_impact(Q, S, K, b, dist, i * days_per_step, Area)
                for i in range(1, len(p_fut) + 1)
            ])
            p_fut += impact_spatial
            lo_f  += impact_spatial
            hi_f  += impact_spatial

            if Area > 0 and S > 0:
                safe_s        = max(0.0001, min(S, 1.0))
                rise_per_step = (Q * days_per_step) / (Area * safe_s)
            else:
                rise_per_step = 0

            impact_cumule = np.cumsum(np.full(len(p_fut), rise_per_step))
            p_fut += impact_cumule
            lo_f  += impact_cumule
            hi_f  += impact_cumule

            self.pred_df = pd.DataFrame({
                'date':      fut_dates,
                'prevision': p_fut,
                'ic_bas':    lo_f,
                'ic_haut':   hi_f,
            })

            bias  = self.df['level'].iloc[-1] - p_fut[0]
            p_fut += bias
            lo_f  += bias
            hi_f  += bias

            self.show_plot(df_train, df_val, p_val, lo_v, hi_v,
                           fut_dates, p_fut, lo_f, hi_f)
            self.set_status('Analyse terminée.', '#1a7a1a')

        except Exception as e:
            self.set_status("Erreur lors de l'analyse.", '#cc0000')
            messagebox.showerror('Erreur analyse', str(e))

    def _fit_predict(self, df_fit, steps, future_dates):
        model_name = self.cfg.model
        sp = freq_to_seasonal_periods(self.freq)
        y  = df_fit['level'].values
        if model_name == 'ETS':
            m = ETSModel(self.cfg.ets_type, sp, self.cfg.ci_level)
            m.fit(y)
            pred, lo, hi = m.predict(steps)
        elif model_name == 'ARIMA':
            m = ARIMAModel(sp, self.cfg.ci_level)
            m.fit(y)
            pred, lo, hi = m.predict(steps)
        elif model_name in ('RandomForest', 'XGBoost'):
            m = SklearnModel(model_name, self.cfg.ci_level, self.cfg.n_bootstraps)
            m.fit(df_fit)
            pred, lo, hi = m.predict(future_dates)
        else:
            raise ValueError(f'Modèle inconnu : {model_name}')
        return np.array(pred), np.array(lo), np.array(hi)

    def show_plot(self, df_train, df_val, pred_val, lo_val, hi_val,
                  future_dates, pred_fut, lo_fut, hi_fut):
        for w in self.content.winfo_children():
            if not isinstance(w, ttk.Scrollbar):
                w.destroy()
        # Cache le tableau
        for w in self.content.winfo_children():
            w.grid_remove()

        plt.close('all')
        fig, ax = plt.subplots(figsize=(11, 7), dpi=95)
        fig.patch.set_facecolor('#fafafa')

        ci_pct       = int((1 - self.cfg.ci_level) * 100)
        val_dates    = df_val['date'].values
        split_date   = df_val['date'].iloc[0]
        end_val_date = df_val['date'].iloc[-1]

        ax.axvspan(df_train['date'].iloc[0], split_date,
                   alpha=0.04, color='#2c7be5', zorder=0)
        ax.axvspan(split_date, end_val_date,
                   alpha=0.07, color='#f6c90e', zorder=0)
        ax.axvspan(end_val_date, future_dates[-1],
                   alpha=0.05, color='#20c997', zorder=0)

        ax.axvline(split_date,   color='#f6c90e', linewidth=1.4, linestyle='--', zorder=2)
        ax.axvline(end_val_date, color='#20c997', linewidth=1.4, linestyle='--', zorder=2)

        ax.plot(df_train['date'], df_train['level'],
                color='#2c7be5', linewidth=1.6,
                label='Historique (entraînement)', zorder=3)
        ax.plot(val_dates, df_val['level'],
                color='#f6c90e', linewidth=2.0, zorder=4,
                label='Valeurs réelles (contrôle)')
        ax.plot(val_dates, pred_val,
                color='#e85d04', linewidth=1.8, linestyle='--',
                zorder=4, label='Modèle (validation)')
        ax.fill_between(val_dates, lo_val, hi_val,
                        alpha=0.15, color='#e85d04',
                        label=f'IC {ci_pct}% (validation)')

        last_real_date  = df_val['date'].iloc[-1]
        last_real_level = df_val['level'].iloc[-1]
        ax.scatter([last_real_date], [last_real_level],
                   color='#e85d04', s=55, zorder=6,
                   marker='D', label='Dernière valeur réelle')

        ax.plot(future_dates, pred_fut,
                color='#20c997', linewidth=2.2, linestyle='--',
                zorder=4, label='Prévision future')
        ax.fill_between(future_dates, lo_fut, hi_fut,
                        alpha=0.15, color='#20c997',
                        label=f'IC {ci_pct}% (futur)')

        ax.set_title(f'Prévision Piézométrique — {self.cfg.model} | IC {ci_pct}%',
                     fontsize=13, fontweight='bold', pad=12)
        ax.set_ylabel('Niveau piézométrique (m)')
        ax.grid(True, alpha=0.22)
        ax.legend(fontsize=8, ncol=3, loc='upper left')
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        fig.autofmt_xdate()

        canvas = FigureCanvasTkAgg(fig, master=self.content)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky='nswe')

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
            if self.metrics:
                with open(path, 'a') as f:
                    f.write('\n# Métriques validation\n')
                    for k, v in self.metrics.items():
                        f.write(f'# {k},{v:.4f}\n')
            self.set_status('Export CSV terminé.', '#1a7a1a')
            
    def chronicles_ready(self):
        loaded = {i: c for i, c in self.chronicles.items() if c is not None}
        if len(loaded) < 3:
            return False, f"Il manque {3-len(loaded)} chronique(s) — 3 sont requises."
        masses = [c['masse_eau'].strip() for c in loaded.values()]
        if any(not m for m in masses):
            return False, "Renseignez le code de la masse d'eau ADES pour les 3 chroniques."
        if len({m.lower() for m in masses}) > 1:
            return False, "Les 3 chroniques doivent appartenir à la même masse d'eau ADES."
        return True, f"✓ 3 chroniques prêtes — masse d'eau : {masses[0]}"
    
    def refresh_chronicles_view(self):
        ok, msg = self.chronicles_ready()
        self.ready_status_lbl.config(text=msg, foreground=('#1a7a1a' if ok else '#cc0000'))
        self.run_btn.config(state='normal' if ok else 'disabled')
        self._plot_network_chronicles()
        if ok:
            self._build_merged_dataset()
    
    def _build_merged_dataset(self):
        target = self.chronicles[self.target_idx]['df'].copy()
        self.freq = detect_frequency(target['date'])
        merged = target.copy()
        j = 1
        for i in (1, 2, 3):
            if i == self.target_idx:
                continue
            merged[f'level_aux{j}'] = align_chronicle(self.chronicles[i]['df'], merged['date'])
            j += 1
        self.df = merged
        self.populate_table(target)


# ─── ToolTip ───────────────────────────────────────────────────────────────────

class ToolTip:
    def __init__(self, widget, text):
        self.widget    = widget
        self.text      = text
        self.tipwindow = None
        widget.bind('<Enter>', self.show_tip)
        widget.bind('<Leave>', self.hide_tip)

    def show_tip(self, event=None):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox('insert')
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        tk.Label(tw, text=self.text, justify=tk.LEFT,
                 background='#34495e', foreground='white',
                 relief=tk.SOLID, borderwidth=1,
                 font=('Arial', '9', 'normal'),
                 padx=8, pady=5).pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


# ─── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    style = ttk.Style()
    if 'arc' in style.theme_names():
        style.theme_use('arc')
    app = App(root)
    root.mainloop()