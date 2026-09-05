# -*- coding: utf-8 -*-
"""
Created on Sat Sep  5 14:52:26 2026

@author: bruno
"""

import numpy as np
import pandas as pd
from scipy.special import exp1
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from scipy.interpolate import griddata
import matplotlib.pyplot as plt
import io
import base64


DATE_ALIASES = [
    'date de la mesure', 'date_mesure', 'date mesure', 'date',
    'datetime', 'horodatage', 'timestamp',
]
LEVEL_ALIASES = [
    'côte ngf', 'cote ngf', 'niveau ngf', 'niveau', 'level',
    'profondeur/repère de mesure', 'profondeur relative/repère de mesure',
    'valeur', 'mesure', 'hauteur',
]
POINT_ALIASES = [
    'identifiant national bss', 'ancien code national bss',
    'nom point', 'point', 'code bss', 'nom_ouvrage', 'ouvrage',
    'piezometre', 'piézomètre', 'code point', 'nom_point', 'nom du point',
]
MASSE_EAU_ALIASES = [
    "masse d'eau", 'masse deau', 'code masse eau',
    'masse_eau', 'code_masse_eau',
]


def find_column(df, aliases):
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for alias in aliases:
        if alias in cols_lower:
            return cols_lower[alias]
    return None


def parse_multi_piezo_excel(df_raw):
    """df_raw : DataFrame brut lu depuis le fichier Excel (déjà chargé)."""
    if df_raw.shape[1] < 3:
        raise ValueError("Le fichier doit contenir au moins 3 colonnes : date / niveau / nom du point.")
    date_col  = find_column(df_raw, DATE_ALIASES)
    level_col = find_column(df_raw, LEVEL_ALIASES)
    point_col = find_column(df_raw, POINT_ALIASES)
    masse_col = find_column(df_raw, MASSE_EAU_ALIASES)
    if date_col is None or level_col is None or point_col is None:
        raise ValueError(
            f'Colonnes détectées : {list(df_raw.columns)}\n\n'
            f"Date : {date_col or '❌'}   Niveau : {level_col or '❌'}   Point : {point_col or '❌'}"
        )
    cols  = [date_col, level_col, point_col] + ([masse_col] if masse_col else [])
    names = ['date', 'level', 'point'] + (['masse_eau'] if masse_col else [])
    df = df_raw[cols].copy()
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


def align_chronicle(df_source, target_dates):
    s = df_source.set_index('date')['level'].sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(target_dates))
    combined = s.index.union(idx)
    s_full = s.reindex(combined).astype(float).interpolate(method='time', limit_direction='both')
    return s_full.reindex(idx).values


def detect_frequency(dates):
    diffs = dates.diff().dropna().dt.days
    median_diff = diffs.median()
    if median_diff <= 1.5:   return 'D'
    elif median_diff <= 8:   return 'W'
    elif median_diff <= 35:  return 'MS'
    elif median_diff <= 100: return 'QS'
    else:                    return 'YS'


def freq_to_seasonal_periods(freq):
    return {'D': 365, 'W': 52, 'MS': 12, 'QS': 4, 'YS': 1}.get(freq, 12)


def future_steps(freq, years):
    return {'D': years * 365, 'W': years * 52, 'MS': years * 12,
            'QS': years * 4, 'YS': years}.get(freq, years * 12)


def make_features(dates):
    df = pd.DataFrame({'date': pd.to_datetime(dates)})
    df['t']         = (df['date'] - df['date'].min()).dt.days
    df['month']     = df['date'].dt.month
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['year']      = df['date'].dt.year
    df['quarter']   = df['date'].dt.quarter
    return df.drop(columns=['date'])


def compute_correlation_matrix(loaded):
    """loaded : dict {idx: {'df':..., 'name':...}}"""
    resampled = {}
    for i, c in loaded.items():
        s = c['df'].set_index('date')['level'].sort_index()
        resampled[c['name']] = s.resample('MS').mean()
    combined = pd.DataFrame(resampled).dropna()
    if len(combined) < 3:
        return None, 0
    return combined.corr(method='pearson'), len(combined)


def calculate_spatial_impact(Q, S, K, thickness, distance, time_days, Area):
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

def surface_to_png_overlay(GLon, GLat, GZ, cmap='Blues_r', alpha=0.75):
    """Convertit une grille interpolée en image PNG transparente,
    exploitable comme overlay Folium. Retourne (png_bytes, bounds)."""
    fig, ax = plt.subplots(figsize=(GLon.shape[1] / 40, GLon.shape[0] / 40), dpi=100)
    ax.contourf(GLon, GLat, GZ, levels=25, cmap=cmap, alpha=alpha)
    ax.axis('off')
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', transparent=True)
    plt.close(fig)
    buf.seek(0)

    bounds = [[GLat.min(), GLon.min()], [GLat.max(), GLon.max()]]
    return buf.getvalue(), bounds


# ─── Modèles (copiés tels quels depuis ton fichier Tkinter) ────────────────

class ETSModel:
    def __init__(self, ets_type, seasonal_periods, ci_level):
        self.ets_type = ets_type
        self.sp = seasonal_periods
        self.ci_level = ci_level
        self.fit_ = None

    def fit(self, y):
        t = self.ets_type
        sp = self.sp if self.sp > 1 else None
        if t == '1':
            m = ExponentialSmoothing(y, trend=None, seasonal=None)
        elif t == '2':
            m = ExponentialSmoothing(y, trend='add', seasonal=None)
        elif t == '3':
            m = ExponentialSmoothing(y, trend=None, seasonal='add' if sp else None, seasonal_periods=sp)
        else:
            m = ExponentialSmoothing(y, trend='add', seasonal='add' if sp else None, seasonal_periods=sp)
        self.fit_ = m.fit(optimized=True)
        return self

    def predict(self, steps):
        sim = self.fit_.simulate(steps, repetitions=500, error='mul')
        pred = self.fit_.forecast(steps)
        alpha = self.ci_level
        lo = np.quantile(sim, alpha / 2, axis=1)
        hi = np.quantile(sim, 1 - alpha / 2, axis=1)
        return pred, lo, hi


class ARIMAModel:
    CANDIDATES = [(1,1,1),(1,1,0),(0,1,1),(2,1,1),(1,1,2),(2,1,2),(0,1,2),(2,1,0)]

    def __init__(self, seasonal_periods, ci_level):
        self.sp = seasonal_periods
        self.ci_level = ci_level
        self.res_ = None
        self.order_ = None
        self.aux_cols_ = []
        self.origin_ = None
        self.exog_trend_ = {}

    def _is_stationary(self, y):
        try:
            return adfuller(y)[1] < 0.05
        except Exception:
            return False

    def fit(self, df, aux_cols=None):
        aux_cols = aux_cols or []
        self.aux_cols_ = aux_cols
        self.origin_ = df['date'].min()
        y = df['level'].values
        exog = None
        if aux_cols:
            exog = df[aux_cols].values
            t = (df['date'] - self.origin_).dt.days.values
            for c in aux_cols:
                vals = df[c].values
                mask = ~np.isnan(vals)
                if mask.sum() >= 2:
                    slope, intercept = np.polyfit(t[mask], vals[mask], 1)
                else:
                    slope, intercept = 0.0, float(vals[mask].mean()) if mask.any() else 0.0
                self.exog_trend_[c] = (slope, intercept)
        d = 0 if self._is_stationary(y) else 1
        sp = self.sp if self.sp > 1 else 0
        best_aic, best_res = np.inf, None
        for p, _, q in self.CANDIDATES:
            try:
                if sp > 1:
                    m = SARIMAX(y, exog=exog, order=(p,d,q), seasonal_order=(1,1,1,sp),
                               enforce_stationarity=False, enforce_invertibility=False)
                else:
                    m = SARIMAX(y, exog=exog, order=(p,d,q),
                               enforce_stationarity=False, enforce_invertibility=False)
                res = m.fit(disp=False, maxiter=200)
                if res.aic < best_aic:
                    best_aic, best_res, self.order_ = res.aic, res, (p,d,q)
            except Exception:
                continue
        if best_res is None:
            raise RuntimeError("ARIMA : impossible d'ajuster le modèle.")
        self.res_ = best_res
        return self

    def predict(self, steps, future_dates=None):
        exog_fut = None
        if self.aux_cols_:
            t_fut = (pd.to_datetime(pd.Series(future_dates)) - self.origin_).dt.days.values
            exog_fut = np.column_stack([
                self.exog_trend_[c][0] * t_fut + self.exog_trend_[c][1] for c in self.aux_cols_
            ])
        fc = self.res_.get_forecast(steps=steps, exog=exog_fut)
        pred = fc.predicted_mean
        ci = fc.conf_int(alpha=self.ci_level)
        return pred, ci.iloc[:, 0].values, ci.iloc[:, 1].values


class SklearnModel:
    def __init__(self, kind, ci_level, n_bootstraps):
        self.kind = kind
        self.ci_level = ci_level
        self.n_bootstraps = n_bootstraps
        self.models_ = []
        self.scaler_ = StandardScaler()
        self.train_origin_ = None
        self.aux_cols_ = []
        self.aux_trend_ = {}

    def _make_model(self):
        if self.kind == 'RandomForest':
            return RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
        return GradientBoostingRegressor(n_estimators=200, max_depth=4, learning_rate=0.05,
                                         subsample=0.8, random_state=42)

    def fit(self, df, aux_cols=None):
        aux_cols = aux_cols or []
        self.aux_cols_ = aux_cols
        self.train_origin_ = df['date'].min()
        X = make_features(df['date'])
        for c in aux_cols:
            X[c] = df[c].values
        y = df['level'].values
        t = (df['date'] - self.train_origin_).dt.days.values
        for c in aux_cols:
            vals = df[c].values
            mask = ~np.isnan(vals)
            if mask.sum() >= 2:
                slope, intercept = np.polyfit(t[mask], vals[mask], 1)
            else:
                slope, intercept = 0.0, float(vals[mask].mean()) if mask.any() else 0.0
            self.aux_trend_[c] = (slope, intercept)
        X_scaled = self.scaler_.fit_transform(X)
        n = len(y)
        for _ in range(self.n_bootstraps):
            idx = np.random.choice(n, int(n * 0.8), replace=True)
            m = self._make_model()
            m.fit(X_scaled[idx], y[idx])
            self.models_.append(m)
        return self

    def predict(self, future_dates):
        df_feat = pd.DataFrame({'date': pd.to_datetime(future_dates)})
        df_feat['t'] = (df_feat['date'] - self.train_origin_).dt.days
        df_feat['month'] = df_feat['date'].dt.month
        df_feat['month_sin'] = np.sin(2 * np.pi * df_feat['month'] / 12)
        df_feat['month_cos'] = np.cos(2 * np.pi * df_feat['month'] / 12)
        df_feat['year'] = df_feat['date'].dt.year
        df_feat['quarter'] = df_feat['date'].dt.quarter
        for c in self.aux_cols_:
            slope, intercept = self.aux_trend_[c]
            df_feat[c] = slope * df_feat['t'] + intercept
        X_fut = df_feat.drop(columns=['date'])
        X_scaled = self.scaler_.transform(X_fut)
        preds = np.array([m.predict(X_scaled) for m in self.models_])
        pred = preds.mean(axis=0)
        lo = np.percentile(preds, self.ci_level * 100, axis=0)
        hi = np.percentile(preds, (1 - self.ci_level) * 100, axis=0)
        lo = pd.Series(lo).rolling(3, min_periods=1).mean().values
        hi = pd.Series(hi).rolling(3, min_periods=1).mean().values
        return pred, lo, hi


def fit_predict(df_fit, steps, future_dates, model_name, freq, ci_level, ets_type='4', n_bootstraps=200):
    sp = freq_to_seasonal_periods(freq)
    aux_cols = [c for c in df_fit.columns if c.startswith('level_aux')]
    if model_name == 'ETS':
        m = ETSModel(ets_type, sp, ci_level)
        m.fit(df_fit['level'].values)
        pred, lo, hi = m.predict(steps)
    elif model_name == 'ARIMA':
        m = ARIMAModel(sp, ci_level)
        m.fit(df_fit, aux_cols)
        pred, lo, hi = m.predict(steps, future_dates)
    elif model_name in ('RandomForest', 'XGBoost'):
        m = SklearnModel(model_name, ci_level, n_bootstraps)
        m.fit(df_fit, aux_cols)
        pred, lo, hi = m.predict(future_dates)
    else:
        raise ValueError(f'Modèle inconnu : {model_name}')
    return np.array(pred), np.array(lo), np.array(hi)


def parse_descriptif(path):
    """Lit le fichier descriptif ADES (pipe-séparé) et retourne un dict
    {identifiant_bss: {'lon', 'lat', 'name', 'masse_eau'}}."""
    df = None
    last_error = None
    for encoding in ('utf-8', 'latin-1', 'cp1252'):
        try:
            df = pd.read_csv(path, sep='|', engine='python', encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
            continue
    if df is None:
        raise ValueError(f"Impossible de décoder le fichier (essayé utf-8/latin-1/cp1252) : {last_error}")

    df.columns = [c.strip() for c in df.columns]
    out = {}
    for _, row in df.iterrows():
        bss_id = str(row['Identifiant national BSS']).strip()
        try:
            lon = float(row['X_WGS84'])
            lat = float(row['Y_WGS84'])
        except (ValueError, TypeError):
            continue
        out[bss_id] = {
            'lon': lon,
            'lat': lat,
            'name': row.get('Dénomination', bss_id),
            'masse_eau': str(row.get("Masse(s) d'eau", '')).strip(),
        }
    return out

# def parse_descriptif(path):
#     """Lit le fichier descriptif ADES (pipe-séparé) et retourne un dict
#     {identifiant_bss: {'lon', 'lat', 'name', 'masse_eau'}}."""
#     df = pd.read_csv(path, sep='|', engine='python')
#     df.columns = [c.strip() for c in df.columns]
#     out = {}
#     for _, row in df.iterrows():
#         bss_id = str(row['Identifiant national BSS']).strip()
#         try:
#             lon = float(row['X_WGS84'])
#             lat = float(row['Y_WGS84'])
#         except (ValueError, TypeError):
#             continue
#         out[bss_id] = {
#             'lon': lon,
#             'lat': lat,
#             'name': row.get('Dénomination', bss_id),
#             'masse_eau': str(row.get("Masse(s) d'eau", '')).strip(),
#         }
#     return out


def value_at_date(df, date):
    """Valeur interpolée d'une chronique à une date donnée (méthode temporelle)."""
    s = df.set_index('date')['level'].sort_index()
    idx = pd.DatetimeIndex([pd.to_datetime(date)])
    combined = s.index.union(idx)
    s_full = s.reindex(combined).astype(float).interpolate(method='time', limit_direction='both')
    return float(s_full.reindex(idx).iloc[0])


def build_piezo_surface(coords, values, n=120, margin_ratio=0.3):
    """Interpole une surface piézométrique linéaire entre 3 points (ou plus).
    coords : liste de dicts avec 'lon'/'lat'. values : niveaux correspondants.
    Retourne (grille_lon, grille_lat, grille_niveaux) — NaN hors du triangle formé
    par les points (limite intrinsèque d'une interpolation à seulement 3 points)."""
    lons = np.array([c['lon'] for c in coords])
    lats = np.array([c['lat'] for c in coords])
    vals = np.array(values, dtype=float)

    span_lon = lons.max() - lons.min() or 0.01
    span_lat = lats.max() - lats.min() or 0.01
    grid_lon = np.linspace(lons.min() - span_lon * margin_ratio,
                           lons.max() + span_lon * margin_ratio, n)
    grid_lat = np.linspace(lats.min() - span_lat * margin_ratio,
                           lats.max() + span_lat * margin_ratio, n)
    GLon, GLat = np.meshgrid(grid_lon, grid_lat)
    GZ = griddata((lons, lats), vals, (GLon, GLat), method='linear')
    return GLon, GLat, GZ