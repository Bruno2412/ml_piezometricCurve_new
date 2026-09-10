# -*- coding: utf-8 -*-
"""
Created on Sat Sep  5 14:52:26 2026

@author: bruno

Module de logique métier pure (parsing, calculs, modèles).
Ne contient volontairement aucun appel Streamlit ni aucune lecture de
fichier "brute" mise en cache : ces deux responsabilités vivent dans
data/data_loader.py (voir séparation UI / data / logique demandée
par l'audit Roast My Streamlit).
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
from matplotlib.patches import Circle
from xgboost import XGBRegressor
import matplotlib.pyplot as plt
import unicodedata
import io
import base64
import csv


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


def _clean_str(s):
    """Supprime BOM, espaces insécables et espaces classiques en début/fin."""
    if s is None:
        return ''
    s = str(s)
    s = s.replace('\ufeff', '')       # BOM résiduel
    s = s.replace('\xa0', ' ')        # espace insécable -> espace normal
    return s.strip()


def _strip_accents(s):
    """Normalise en minuscules sans accents (ex. 'Interprété' -> 'interprete'),
    pour comparer des libellés ADES sans dépendre de leur orthographe exacte."""
    s = unicodedata.normalize('NFKD', _clean_str(s).lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def find_column(df, aliases):
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for alias in aliases:
        if alias in cols_lower:
            return cols_lower[alias]
    return None


def parse_multi_piezo_excel(df_raw, min_points=3):
    """df_raw : DataFrame brut lu depuis le fichier Excel (déjà chargé,
    idéalement via data_loader.load_excel() pour bénéficier du cache).
    min_points : nombre minimal de points distincts requis (3 par défaut)."""
    if df_raw.shape[1] < 3:
        raise ValueError("Le fichier doit contenir au moins 3 colonnes : date / niveau / nom du point.")
    date_col = find_column(df_raw, DATE_ALIASES)
    level_col = find_column(df_raw, LEVEL_ALIASES)
    point_col = find_column(df_raw, POINT_ALIASES)
    masse_col = find_column(df_raw, MASSE_EAU_ALIASES)
    if date_col is None or level_col is None or point_col is None:
        raise ValueError(
            f'Colonnes détectées : {list(df_raw.columns)}\n\n'
            f"Date : {date_col or '❌'}   Niveau : {level_col or '❌'}   Point : {point_col or '❌'}"
        )
    cols = [date_col, level_col, point_col] + ([masse_col] if masse_col else [])
    names = ['date', 'level', 'point'] + (['masse_eau'] if masse_col else [])
    df = df_raw[cols].copy()
    df.columns = names
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['level'] = pd.to_numeric(df['level'], errors='coerce')
    df['point'] = df['point'].astype(str).str.strip()
    if 'masse_eau' in df.columns:
        df['masse_eau'] = df['masse_eau'].astype(str).str.strip()
    else:
        df['masse_eau'] = ''

    df = df.dropna(subset=['date', 'level', 'point']).sort_values(['point', 'date']).reset_index(drop=True)

    # Sécurité : déduplique les dates identiques par point (moyenne des niveaux),
    # nécessaire car reindex() exige un index de dates unique dans align_chronicle().
    masse_lookup = df.groupby('point')['masse_eau'].first()
    df = (
        df.groupby(['point', 'date'], as_index=False)['level']
        .mean()
        .merge(masse_lookup.rename('masse_eau'), on='point', how='left')
    )

    points = sorted(df['point'].unique().tolist())
    if len(points) < min_points:
        raise ValueError(f"Seuls {len(points)} point(s) distinct(s) détecté(s) — {min_points} minimum requis.")
    return df, points, (masse_col is not None)


def align_chronicle(df_source, target_dates):
    s = df_source.set_index('date')['level'].sort_index()
    if s.index.duplicated().any():
        s = s.groupby(level=0).mean()

    idx = pd.DatetimeIndex(pd.to_datetime(target_dates))
    idx_unique = idx.unique()

    combined = s.index.union(idx_unique)
    s_full = s.reindex(combined).astype(float).interpolate(method='time', limit_direction='both')

    result_unique = s_full.reindex(idx_unique)

    return result_unique.loc[idx].values


def detect_frequency(dates):
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


def freq_to_seasonal_periods(freq):
    return {'D': 365, 'W': 52, 'MS': 12, 'QS': 4, 'YS': 1}.get(freq, 12)


def future_steps(freq, years):
    return {'D': years * 365, 'W': years * 52, 'MS': years * 12,
            'QS': years * 4, 'YS': years}.get(freq, years * 12)


def make_features(dates):
    df = pd.DataFrame({'date': pd.to_datetime(dates)})
    df['t'] = (df['date'] - df['date'].min()).dt.days
    df['month'] = df['date'].dt.month
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['year'] = df['date'].dt.year
    df['quarter'] = df['date'].dt.quarter
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


# ─── Digital Twin — carte Theis 2D ──────────────────────────────────────

def draw_nappe_2d_figure(Q, S, K, thickness, distance, time_days, Area, niveau_base=0.0):
    """Reconstruit la carte Theis 2D, retourne une figure matplotlib prête pour st.pyplot()."""
    fig, ax = plt.subplots(figsize=(7, 6))

    size = max(distance * 3, 200)
    nx, ny = 120, 120
    x = np.linspace(-size, size, nx)
    y = np.linspace(-size, size, ny)
    X, Y = np.meshgrid(x, y)
    R = np.maximum(np.sqrt(X**2 + Y**2), 1e-3)

    T = K * thickness
    impact_grid = np.zeros_like(R)
    if T > 0 and S > 0 and time_days > 0 and Q > 0:
        u = (R**2 * S) / (4 * T * time_days)
        mask = u < 5
        impact_grid[mask] = (Q / (4 * np.pi * T)) * exp1(u[mask])
        impact_grid = np.clip(impact_grid, 0, niveau_base + 10)

    niveau_field = niveau_base + impact_grid

    vmin, vmax = niveau_field.min(), niveau_field.max()
    if vmax - vmin < 1e-6:
        vmin -= 0.05
        vmax += 0.05
    levels_cmap = np.linspace(vmin, vmax, 60)

    cf = ax.contourf(X, Y, niveau_field, levels=levels_cmap, cmap='Blues_r', alpha=0.85)
    cs = ax.contour(X, Y, niveau_field, levels=12, colors='#0d6efd', linewidths=0.6, alpha=0.6)
    ax.clabel(cs, inline=True, fontsize=6, fmt='%.1f m')
    fig.colorbar(cf, ax=ax, fraction=0.04, pad=0.02, label='Niveau piézo. (m)')

    R_bassin = np.sqrt(Area / np.pi)
    ax.add_patch(Circle((0, 0), R_bassin, color='#e85d04', fill=True, alpha=0.5, zorder=6))
    ax.plot(0, 0, 'o', color='#e85d04', ms=8, zorder=7, label='Ouvrage injection')

    r_inf = None
    if T > 0 and S > 0 and time_days > 0 and Q > 0:
        r_inf = min(size * 0.95, np.sqrt(4 * T * time_days / S) * 2)
        ax.add_patch(Circle((0, 0), r_inf, color='#20c997', fill=False,
                             linestyle='--', linewidth=1.4, alpha=0.8, zorder=5,
                             label=f"R influence ≈{r_inf:.0f} m"))

    ax.plot(distance, 0, '^', color='#ffc107', ms=10, zorder=8, label=f'Piézomètre ({distance:.0f} m)')
    ax.annotate(f' Piézo\n {distance:.0f} m', (distance, 0), fontsize=7,
                xytext=(distance + size * 0.05, size * 0.08))

    ax.set_xlim(-size, size)
    ax.set_ylim(-size, size)
    ax.set_aspect('equal')
    ax.set_title(f'Simulation Theis — t={time_days:.0f}j  Q={Q:.1f} m³/j  K={K:.1e} m/s', fontsize=10)
    ax.set_xlabel('Distance Est (m)')
    ax.set_ylabel('Distance Nord (m)')
    ax.legend(fontsize=7, loc='upper right')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def response_curve_data(Q, S, K, thickness, distance, Area, t_max, niveau_base):
    """Calcule la réponse temporelle (spatial Theis + volumétrique cumulé)."""
    t_arr = np.linspace(1, t_max, 300)
    impact_t = np.array([calculate_spatial_impact(Q, S, K, thickness, distance, t, Area) for t in t_arr])
    days_step = t_arr[1] - t_arr[0]
    vol_rise = np.cumsum(np.full(len(t_arr), (Q * days_step) / (Area * S) if Area > 0 else 0))
    total_impact = impact_t + vol_rise
    return t_arr, impact_t + niveau_base, total_impact + niveau_base


def compute_dashboard_indicators(df, freq, Q, S, K, thickness, distance, Area):
    """Reconstruit les indicateurs du dashboard."""
    niveau_actuel = df['level'].iloc[-1]
    n_30 = min(30, len(df) - 1)
    variation_30j = df['level'].iloc[-1] - df['level'].iloc[-1 - n_30]

    n_trend = min(120, len(df))
    x_t = np.arange(n_trend)
    y_t = df['level'].values[-n_trend:]
    p = np.polyfit(x_t, y_t, 1)
    freq_factor = freq_to_seasonal_periods(freq)
    tendance = p[0] * freq_factor

    impact_inj = calculate_spatial_impact(Q, S, K, thickness, distance, 180, Area)

    if tendance < -0.5:
        risque = min(95, 60 + abs(tendance) * 10)
    elif tendance < 0:
        risque = min(60, 30 + abs(tendance) * 20)
    else:
        risque = max(5, 30 - tendance * 10)

    if Q > 0 and Area > 0 and S > 0:
        rise_rate = Q / (Area * S)
        temps_rech = max(1, 0.5 / rise_rate) if rise_rate > 0 else 9999
    else:
        temps_rech = 9999

    return {
        'niveau_actuel': niveau_actuel,
        'variation_30j': variation_30j,
        'tendance': tendance,
        'impact_inj': impact_inj,
        'risque': risque,
        'temps_rech': temps_rech,
    }


# ─── Modèles ─────────────────────────────────────────────────────────────

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
    CANDIDATES = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (2, 1, 1), (1, 1, 2), (2, 1, 2), (0, 1, 2), (2, 1, 0)]

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
                    m = SARIMAX(y, exog=exog, order=(p, d, q), seasonal_order=(1, 1, 1, sp),
                                enforce_stationarity=False, enforce_invertibility=False)
                else:
                    m = SARIMAX(y, exog=exog, order=(p, d, q),
                                enforce_stationarity=False, enforce_invertibility=False)
                res = m.fit(disp=False, maxiter=200)
                if res.aic < best_aic:
                    best_aic, best_res, self.order_ = res.aic, res, (p, d, q)
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
        ci = np.asarray(fc.conf_int(alpha=self.ci_level))
        return np.asarray(pred), ci[:, 0], ci[:, 1]
    
    # def predict(self, steps, future_dates=None):
    #     exog_fut = None
    #     if self.aux_cols_:
    #         t_fut = (pd.to_datetime(pd.Series(future_dates)) - self.origin_).dt.days.values
    #         exog_fut = np.column_stack([
    #             self.exog_trend_[c][0] * t_fut + self.exog_trend_[c][1] for c in self.aux_cols_
    #         ])
    #     fc = self.res_.get_forecast(steps=steps, exog=exog_fut)
    #     pred = fc.predicted_mean
    #     ci = fc.conf_int(alpha=self.ci_level)
    #     return pred, ci.iloc[:, 0].values, ci.iloc[:, 1].values


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
        if self.kind == 'XGBoost':
            return XGBRegressor(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                subsample=0.8, random_state=42, n_jobs=-1
            )
        raise ValueError(f"Modèle sklearn/boosting inconnu : {self.kind}")

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


def _read_ades_pipe_file(path):
    """Lit un fichier d'export ADES pipe-séparé (descriptif.txt, chroniques.txt,
    MassesEau.txt, ...) depuis un chemin local, en essayant plusieurs encodages
    usuels. Fonction pure, volontairement non mise en cache ici : le cache vit
    dans data_loader.py, calé sur le contenu du fichier uploadé plutôt que sur
    ce chemin temporaire (qui change à chaque exécution)."""
    df = None
    last_error = None
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            df = pd.read_csv(
                path, sep='|', engine='python', encoding=encoding,
                dtype=str,
                quoting=csv.QUOTE_NONE,   # le | est le seul séparateur, jamais le "
            )
            break
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
            continue
    if df is None:
        raise ValueError(f"Impossible de décoder le fichier : {last_error}")
    df.columns = [_clean_str(c) for c in df.columns]
    return df


def parse_descriptif(path):
    """Lit descriptif.txt (pipe-séparé) et retourne, par point,
    coordonnées + nom + code masse d'eau brut (ex. 'V5#DG240' — voir
    parse_masses_eau() pour le libellé complet et fiable)."""
    df = _read_ades_pipe_file(path)
    if 'Identifiant national BSS' not in df.columns:
        raise ValueError(f"Colonne ID introuvable. Colonnes lues : {list(df.columns)}")

    out = {}
    for _, row in df.iterrows():
        bss_id = _clean_str(row['Identifiant national BSS'])
        if not bss_id:
            continue
        try:
            lon = float(str(row['X_WGS84']).replace(',', '.'))
            lat = float(str(row['Y_WGS84']).replace(',', '.'))
        except (ValueError, TypeError):
            continue
        out[bss_id] = {
            'lon': lon, 'lat': lat,
            'name': _clean_str(row.get('Dénomination', bss_id)),
            'masse_eau': _clean_str(row.get("Masse(s) d'eau", '')),
        }
    return out


def parse_chroniques_raw(path):
    """Lit chroniques.txt (export ADES brut, pipe-séparé) et retourne le
    DataFrame brut avec ses colonnes d'origine (« Identifiant national BSS »,
    « Date de la mesure », « Côte NGF », ...), pour que
    parse_multi_piezo_excel() les identifie ensuite via find_column()."""
    return _read_ades_pipe_file(path)


_QUALITE_ASSOCIATION_RANK = {
    'bonne': 3,
    'interprete': 2,
    'incertaine': 1,
    '': 0,
}


def parse_masses_eau(path):
    """Lit MassesEau.txt (pipe-séparé) et retourne, pour chaque point
    (Identifiant national BSS), le libellé complet de la masse d'eau le plus
    fiable : la meilleure « Qualité association » disponible, puis
    l'association la plus récente en cas d'égalité. Un même point a souvent
    plusieurs lignes dans ce fichier (historique des associations)."""
    df = _read_ades_pipe_file(path)
    required = {'Identifiant national BSS', 'Masse eau'}
    if not required.issubset(df.columns):
        raise ValueError(
            f"Colonnes attendues introuvables ({required}). "
            f"Colonnes lues : {list(df.columns)}"
        )

    df = df.copy()
    df['_qualite_rank'] = df.get('Qualité association', '').map(
        lambda q: _QUALITE_ASSOCIATION_RANK.get(_strip_accents(q), 0)
    )
    df['_date_asso'] = pd.to_datetime(
        df.get('Date de début association'), format='%d/%m/%Y', errors='coerce'
    )

    out = {}
    for bss_id, group in df.groupby('Identifiant national BSS'):
        bss_id = _clean_str(bss_id)
        if not bss_id:
            continue
        best = group.sort_values(
            ['_qualite_rank', '_date_asso'], ascending=[False, False]
        ).iloc[0]
        label = _clean_str(best['Masse eau'])
        if label:
            out[bss_id] = label
    return out


def value_at_date(df, date):
    """Valeur interpolée d'une chronique à une date donnée (méthode temporelle)."""
    s = df.set_index('date')['level'].sort_index()
    idx = pd.DatetimeIndex([pd.to_datetime(date)])
    combined = s.index.union(idx)
    s_full = s.reindex(combined).astype(float).interpolate(method='time', limit_direction='both')
    return float(s_full.reindex(idx).iloc[0])


def build_piezo_surface(coords, values, n=120, margin_ratio=0.3):
    """Interpole une surface piézométrique linéaire entre 3 points (ou plus)."""
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