# -*- coding: utf-8 -*-
"""
Tests unitaires pour les modèles de prévision (ETS/ARIMA/RandomForest/
XGBoost) et les fonctions de calcul (Theis, indicateurs dashboard,
corrélation) de piezo_core.py.

Portée volontairement pragmatique : on ne vérifie pas la précision
statistique des modèles (ce n'est pas le rôle de tests unitaires), mais
qu'ils s'entraînent sans erreur, renvoient des sorties de la bonne forme,
et respectent les invariants attendus (bornes de confiance cohérentes,
longueurs de sortie correctes, cas limites gérés).

Les jeux de données synthétiques sont volontairement petits (quelques
dizaines de points) pour garder la suite rapide — les modèles ARIMA
notamment testent plusieurs ordres candidats à chaque fit().

Lancer avec :
    pytest tests/test_models.py -v
"""

import numpy as np
import pandas as pd
import pytest

import piezo_core as core


# ─────────────────────────────────────────────────────────────────────────
# Fixtures : séries synthétiques
# ─────────────────────────────────────────────────────────────────────────

def _make_series_df(n=48, freq='MS', with_aux=False, seed=42):
    """Série mensuelle avec tendance + saisonnalité + bruit léger,
    reproductible (seed fixe)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2020-01-01', periods=n, freq=freq)
    t = np.arange(n)
    seasonal = 2.0 * np.sin(2 * np.pi * t / 12)
    trend = 0.05 * t
    noise = rng.normal(0, 0.2, n)
    level = 100.0 + trend + seasonal + noise
    df = pd.DataFrame({'date': dates, 'level': level})
    if with_aux:
        # Covariable corrélée à la tendance, avec son propre bruit.
        df['level_aux1'] = 50.0 + 0.03 * t + rng.normal(0, 0.3, n)
    return df


# ─────────────────────────────────────────────────────────────────────────
# make_features
# ─────────────────────────────────────────────────────────────────────────

class TestMakeFeatures:
    def test_returns_expected_columns(self):
        dates = pd.date_range('2024-01-01', periods=12, freq='MS')
        feats = core.make_features(dates)
        assert set(feats.columns) == {'t', 'month', 'month_sin', 'month_cos', 'year', 'quarter'}

    def test_t_starts_at_zero(self):
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        feats = core.make_features(dates)
        assert feats['t'].iloc[0] == 0
        assert feats['t'].iloc[-1] == 4

    def test_month_sin_cos_are_bounded(self):
        dates = pd.date_range('2024-01-01', periods=24, freq='MS')
        feats = core.make_features(dates)
        assert feats['month_sin'].between(-1, 1).all()
        assert feats['month_cos'].between(-1, 1).all()


# ─────────────────────────────────────────────────────────────────────────
# ETSModel
# ─────────────────────────────────────────────────────────────────────────

class TestETSModel:
    @pytest.mark.parametrize('ets_type', ['1', '2', '3', '4'])
    def test_fit_predict_returns_correct_shapes(self, ets_type):
        df = _make_series_df(n=48)
        model = core.ETSModel(ets_type, seasonal_periods=12, ci_level=0.32)
        model.fit(df['level'].values)
        steps = 6
        pred, lo, hi = model.predict(steps)
        assert len(pred) == steps
        assert len(lo) == steps
        assert len(hi) == steps

    def test_confidence_bounds_are_ordered(self):
        df = _make_series_df(n=48)
        model = core.ETSModel('4', seasonal_periods=12, ci_level=0.32)
        model.fit(df['level'].values)
        pred, lo, hi = model.predict(6)
        # La borne basse ne doit jamais dépasser la borne haute.
        assert (lo <= hi).all()

    def test_non_seasonal_type_ignores_seasonal_periods(self):
        # ets_type '1' et '2' n'utilisent pas la saisonnalité : doit
        # fonctionner même avec une série courte (< seasonal_periods).
        df = _make_series_df(n=15)
        model = core.ETSModel('1', seasonal_periods=12, ci_level=0.32)
        model.fit(df['level'].values)
        pred, lo, hi = model.predict(3)
        assert len(pred) == 3


# ─────────────────────────────────────────────────────────────────────────
# ARIMAModel
# ─────────────────────────────────────────────────────────────────────────

class TestARIMAModel:
    def test_fit_predict_without_covariates(self):
        df = _make_series_df(n=36)
        model = core.ARIMAModel(seasonal_periods=1, ci_level=0.32)
        model.fit(df)
        steps = 6
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=steps, freq='MS')
        pred, lo, hi = model.predict(steps, future_dates)
        assert len(pred) == steps
        assert (lo <= hi).all()

    def test_order_is_selected_among_candidates(self):
        df = _make_series_df(n=36)
        model = core.ARIMAModel(seasonal_periods=1, ci_level=0.32)
        model.fit(df)
        assert model.order_ in core.ARIMAModel.CANDIDATES

    def test_fit_predict_with_covariates(self):
        df = _make_series_df(n=36, with_aux=True)
        model = core.ARIMAModel(seasonal_periods=1, ci_level=0.32)
        model.fit(df, aux_cols=['level_aux1'])
        steps = 4
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=steps, freq='MS')
        pred, lo, hi = model.predict(steps, future_dates)
        assert len(pred) == steps
        assert 'level_aux1' in model.exog_trend_

    def test_raises_runtime_error_when_all_candidates_fail(self, monkeypatch):
        df = _make_series_df(n=36)
        model = core.ARIMAModel(seasonal_periods=1, ci_level=0.32)

        def _always_fail(*args, **kwargs):
            raise ValueError('échec forcé pour le test')

        monkeypatch.setattr(core, 'SARIMAX', _always_fail)
        with pytest.raises(RuntimeError, match='impossible d.ajuster'):
            model.fit(df)


# ─────────────────────────────────────────────────────────────────────────
# SklearnModel (RandomForest / XGBoost)
# ─────────────────────────────────────────────────────────────────────────

class TestSklearnModel:
    @pytest.mark.parametrize('kind', ['RandomForest', 'XGBoost'])
    def test_fit_predict_returns_correct_shapes(self, kind):
        df = _make_series_df(n=48)
        model = core.SklearnModel(kind, ci_level=0.32, n_bootstraps=5)
        model.fit(df)
        steps = 6
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=steps, freq='MS')
        pred, lo, hi = model.predict(future_dates)
        assert len(pred) == steps
        assert len(lo) == steps
        assert len(hi) == steps

    def test_trains_n_bootstraps_models(self):
        df = _make_series_df(n=48)
        n_bootstraps = 7
        model = core.SklearnModel('RandomForest', ci_level=0.32, n_bootstraps=n_bootstraps)
        model.fit(df)
        assert len(model.models_) == n_bootstraps

    def test_unknown_kind_raises_value_error(self):
        model = core.SklearnModel('UnknownModel', ci_level=0.32, n_bootstraps=5)
        with pytest.raises(ValueError, match='inconnu'):
            model._make_model()

    def test_fit_predict_with_covariates(self):
        df = _make_series_df(n=48, with_aux=True)
        model = core.SklearnModel('RandomForest', ci_level=0.32, n_bootstraps=5)
        model.fit(df, aux_cols=['level_aux1'])
        steps = 3
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=steps, freq='MS')
        pred, lo, hi = model.predict(future_dates)
        assert len(pred) == steps
        assert 'level_aux1' in model.aux_trend_


# ─────────────────────────────────────────────────────────────────────────
# fit_predict (dispatcher)
# ─────────────────────────────────────────────────────────────────────────

class TestFitPredict:
    @pytest.mark.parametrize('model_name', ['ETS', 'ARIMA', 'RandomForest', 'XGBoost'])
    def test_dispatches_to_correct_model_and_returns_arrays(self, model_name):
        df = _make_series_df(n=36)
        steps = 5
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=steps, freq='MS')
        pred, lo, hi = core.fit_predict(
            df, steps, future_dates, model_name, freq='MS',
            ci_level=0.32, ets_type='4', n_bootstraps=5,
        )
        assert isinstance(pred, np.ndarray)
        assert len(pred) == steps
        assert len(lo) == steps
        assert len(hi) == steps

    def test_unknown_model_name_raises_value_error(self):
        df = _make_series_df(n=36)
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=3, freq='MS')
        with pytest.raises(ValueError, match='Modèle inconnu'):
            core.fit_predict(df, 3, future_dates, 'ModeleBidon', freq='MS', ci_level=0.32)

    def test_auto_detects_aux_columns_from_dataframe(self):
        df = _make_series_df(n=36, with_aux=True)
        future_dates = pd.date_range(df['date'].iloc[-1] + pd.DateOffset(months=1),
                                      periods=4, freq='MS')
        # Ne doit pas lever d'erreur : fit_predict doit détecter
        # automatiquement 'level_aux1' comme colonne de covariable.
        pred, lo, hi = core.fit_predict(
            df, 4, future_dates, 'RandomForest', freq='MS',
            ci_level=0.32, n_bootstraps=5,
        )
        assert len(pred) == 4


# ─────────────────────────────────────────────────────────────────────────
# calculate_spatial_impact
# ─────────────────────────────────────────────────────────────────────────

class TestCalculateSpatialImpact:
    @pytest.mark.parametrize('kwargs', [
        dict(Q=10, S=0.05, K=1e-4, thickness=10, distance=50, time_days=0, Area=100),
        dict(Q=10, S=0, K=1e-4, thickness=10, distance=50, time_days=180, Area=100),
        dict(Q=10, S=0.05, K=0, thickness=10, distance=50, time_days=180, Area=100),
        dict(Q=10, S=0.05, K=1e-4, thickness=0, distance=50, time_days=180, Area=100),
    ])
    def test_returns_zero_for_degenerate_inputs(self, kwargs):
        assert core.calculate_spatial_impact(**kwargs) == 0

    def test_returns_non_negative_for_valid_inputs(self):
        impact = core.calculate_spatial_impact(
            Q=10, S=0.05, K=1e-4, thickness=10, distance=50, time_days=180, Area=100,
        )
        assert impact >= 0

    def test_distance_within_bassin_radius_uses_linear_formula(self):
        # R_bassin = sqrt(Area/pi) ; on choisit une distance très inférieure.
        impact = core.calculate_spatial_impact(
            Q=10, S=0.05, K=1e-4, thickness=10, distance=1, time_days=180, Area=1000,
        )
        expected = (10 / (1000 * 0.05)) * (1 - np.exp(-180 / 10))
        assert impact == pytest.approx(expected)

    def test_far_distance_with_large_u_returns_zero(self):
        # Distance très grande + temps très court => u > 5 => impact nul.
        impact = core.calculate_spatial_impact(
            Q=10, S=0.05, K=1e-6, thickness=10, distance=5000, time_days=1, Area=100,
        )
        assert impact == 0

    def test_impact_increases_with_time(self):
        kwargs = dict(Q=10, S=0.05, K=1e-4, thickness=10, distance=100, Area=100)
        impact_early = core.calculate_spatial_impact(time_days=30, **kwargs)
        impact_late = core.calculate_spatial_impact(time_days=300, **kwargs)
        assert impact_late >= impact_early


# ─────────────────────────────────────────────────────────────────────────
# compute_correlation_matrix
# ─────────────────────────────────────────────────────────────────────────

class TestComputeCorrelationMatrix:
    def test_returns_matrix_and_count_for_sufficient_data(self):
        df = _make_series_df(n=24)
        loaded = {
            1: {'df': df[['date', 'level']], 'name': 'PZ1'},
            2: {'df': df[['date', 'level']].assign(level=lambda d: d['level'] * 1.5), 'name': 'PZ2'},
            3: {'df': df[['date', 'level']].assign(level=lambda d: d['level'] + 5), 'name': 'PZ3'},
        }
        corr, n = core.compute_correlation_matrix(loaded)
        assert corr is not None
        assert list(corr.columns) == ['PZ1', 'PZ2', 'PZ3']
        assert n > 0
        # PZ1/PZ2 sont une transformation affine l'une de l'autre : corrélation ~1.
        assert corr.loc['PZ1', 'PZ2'] == pytest.approx(1.0, abs=1e-6)

    def test_returns_none_when_insufficient_overlap(self):
        df1 = pd.DataFrame({'date': pd.date_range('2024-01-01', periods=1, freq='MS'), 'level': [1.0]})
        df2 = pd.DataFrame({'date': pd.date_range('2024-01-01', periods=1, freq='MS'), 'level': [2.0]})
        loaded = {1: {'df': df1, 'name': 'PZ1'}, 2: {'df': df2, 'name': 'PZ2'}}
        corr, n = core.compute_correlation_matrix(loaded)
        assert corr is None
        assert n == 0


# ─────────────────────────────────────────────────────────────────────────
# compute_dashboard_indicators
# ─────────────────────────────────────────────────────────────────────────

class TestComputeDashboardIndicators:
    def test_returns_expected_keys(self):
        df = _make_series_df(n=48)
        indicators = core.compute_dashboard_indicators(
            df, freq='MS', Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
        )
        assert set(indicators) == {
            'niveau_actuel', 'variation_30j', 'tendance',
            'impact_inj', 'risque', 'temps_rech',
        }

    def test_niveau_actuel_is_last_value(self):
        df = _make_series_df(n=48)
        indicators = core.compute_dashboard_indicators(
            df, freq='MS', Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
        )
        assert indicators['niveau_actuel'] == pytest.approx(df['level'].iloc[-1])

    def test_rising_trend_detected_on_strictly_increasing_series(self):
        n = 60
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=n, freq='MS'),
            'level': np.linspace(100, 130, n),
        })
        indicators = core.compute_dashboard_indicators(
            df, freq='MS', Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
        )
        assert indicators['tendance'] > 0
        # Tendance positive => risque de baisse faible.
        assert indicators['risque'] < 50

    def test_falling_trend_increases_risk(self):
        n = 60
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=n, freq='MS'),
            'level': np.linspace(130, 100, n),
        })
        indicators = core.compute_dashboard_indicators(
            df, freq='MS', Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
        )
        assert indicators['tendance'] < 0
        assert indicators['risque'] > 50

    def test_no_injection_gives_default_temps_rech(self):
        df = _make_series_df(n=48)
        indicators = core.compute_dashboard_indicators(
            df, freq='MS', Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
        )
        assert indicators['temps_rech'] == 9999


# ─────────────────────────────────────────────────────────────────────────
# response_curve_data
# ─────────────────────────────────────────────────────────────────────────

class TestResponseCurveData:
    def test_returns_arrays_of_matching_length(self):
        t_max = 365
        t_arr, impact_curve, total_curve = core.response_curve_data(
            Q=10, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
            t_max=t_max, niveau_base=100.0,
        )
        assert len(t_arr) == len(impact_curve) == len(total_curve) == 300

    def test_total_curve_is_at_or_above_impact_curve(self):
        # total_impact cumule aussi la remontée volumétrique : il doit être
        # au moins égal à l'impact spatial seul (remontée volumétrique >= 0
        # quand Q >= 0).
        t_arr, impact_curve, total_curve = core.response_curve_data(
            Q=10, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
            t_max=365, niveau_base=100.0,
        )
        assert (total_curve >= impact_curve - 1e-9).all()

    def test_zero_injection_gives_flat_total_curve_at_baseline(self):
        _, impact_curve, total_curve = core.response_curve_data(
            Q=0, S=0.05, K=1e-4, thickness=10, distance=50, Area=100,
            t_max=100, niveau_base=100.0,
        )
        np.testing.assert_allclose(impact_curve, 100.0)
        np.testing.assert_allclose(total_curve, 100.0)
