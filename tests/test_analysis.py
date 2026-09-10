# -*- coding: utf-8 -*-
"""
Tests unitaires pour components/tab_analyse.py.

tab_analyse.render() est une fonction d'orchestration fortement couplée à
Streamlit (st.error, st.stop, st.spinner, st.pyplot, ...). On ne teste pas
ici la qualité statistique des prévisions (déjà couvert par
test_models.py), mais :
  - le câblage correct (sélection de la chronique cible, construction des
    colonnes de covariables level_aux*, découpage entraînement/validation,
    calcul de ci_level, valeur de retour `freq`)
  - les chemins d'erreur (chronique cible introuvable, période de
    validation invalide ou trop grande) qui doivent stopper le script
    Streamlit via st.stop()

st.stop() est simulé par une exception dérivée de BaseException (comme le
fait réellement Streamlit), afin qu'elle ne soit PAS interceptée par les
blocs `except Exception` du code testé — reproduisant le comportement réel.

Lancer avec :
    pytest tests/test_analysis.py -v
"""

import contextlib

import matplotlib
matplotlib.use('Agg')  # pas d'affichage graphique pendant les tests

import numpy as np
import pandas as pd
import pytest

from components import tab_analyse


class StopRenderException(BaseException):
    """Simule st.stop() : dérive de BaseException, pas de Exception, pour
    ne pas être avalée par les `except Exception` du code testé."""
    pass


# ─────────────────────────────────────────────────────────────────────────
# Fixtures : données synthétiques + neutralisation des appels Streamlit
# ─────────────────────────────────────────────────────────────────────────

def _make_chronicles(n=48, freq='MS', keys=(1, 2, 3), seed=42):
    """Construit un dict `chronicles` compatible avec tab_analyse.render(),
    avec une clé par point (1, 2, 3 par convention app.py)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2020-01-01', periods=n, freq=freq)
    chronicles = {}
    names = {1: 'PZ1', 2: 'PZ2', 3: 'PZ3'}
    for k in keys:
        t = np.arange(n)
        level = 100.0 + k + 0.05 * t + 2.0 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 0.2, n)
        chronicles[k] = {
            'df': pd.DataFrame({'date': dates, 'level': level}),
            'name': names[k],
            'masse_eau': 'MASSE_TEST',
        }
    return chronicles


@pytest.fixture
def stubbed_st(monkeypatch):
    """Neutralise les appels Streamlit pour pouvoir exécuter render() hors
    contexte d'app Streamlit. Retourne un dict des messages capturés."""
    calls = {'error': [], 'warning': [], 'exception': []}

    def _record(bucket):
        def _fn(msg=None, *args, **kwargs):
            calls[bucket].append(msg)
        return _fn

    def _stop():
        raise StopRenderException()

    monkeypatch.setattr(tab_analyse.st, 'error', _record('error'))
    monkeypatch.setattr(tab_analyse.st, 'warning', _record('warning'))
    monkeypatch.setattr(tab_analyse.st, 'exception', _record('exception'))
    monkeypatch.setattr(tab_analyse.st, 'stop', _stop)
    monkeypatch.setattr(tab_analyse.st, 'spinner', lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(tab_analyse.st, 'pyplot', lambda *a, **k: None)
    return calls


def _fake_cached_fit_predict(record):
    """Remplace tab_analyse.cached_fit_predict par un stub rapide et
    déterministe, qui enregistre les arguments reçus pour inspection —
    ça isole les tests de l'orchestration de la logique de test_models.py."""
    def _fake(df_fit, steps, future_dates, model_name, freq, ci_level, n_bootstraps):
        record.append({
            'n_train': len(df_fit),
            'columns': list(df_fit.columns),
            'steps': steps,
            'model_name': model_name,
            'freq': freq,
            'ci_level': ci_level,
            'n_bootstraps': n_bootstraps,
        })
        pred = np.full(steps, 100.0)
        return pred, pred - 1.0, pred + 1.0
    return _fake


# ─────────────────────────────────────────────────────────────────────────
# Cas nominal
# ─────────────────────────────────────────────────────────────────────────

class TestRenderHappyPath:
    def test_returns_detected_frequency(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        freq = tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        assert freq == 'MS'

    def test_calls_fit_predict_twice_validation_then_future(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=2, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        assert len(record) == 2
        # Premier appel : validation (12 pas), second : prévision future (24 pas)
        assert record[0]['steps'] == 12
        assert record[1]['steps'] == 24

    def test_ci_level_derived_from_ci_pct(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        expected_ci_level = (100 - 68) / 200.0
        assert record[0]['ci_level'] == pytest.approx(expected_ci_level)

    def test_auxiliary_columns_added_for_non_target_chronicles(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        # PZ1 est la cible : les 2 autres chroniques doivent devenir
        # level_aux1 et level_aux2 dans le DataFrame passé au modèle.
        assert 'level_aux1' in record[0]['columns']
        assert 'level_aux2' in record[0]['columns']

    def test_target_in_middle_of_selection_resolves_correct_chronicle(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        # Cible = 2e élément de la sélection (PZ2 -> chronicles[2])
        freq = tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ2', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        assert freq == 'MS'
        assert record  # le fit a bien eu lieu, donc target_idx a été résolu

    def test_missing_third_aux_chronicle_degrades_gracefully(self, monkeypatch, stubbed_st):
        # Seulement 2 chroniques disponibles sur les 3 attendues : le code
        # doit avertir (st.warning) mais continuer, pas planter.
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS', keys=(1, 2))
        freq = tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        assert freq == 'MS'
        assert stubbed_st['warning']  # avertissement émis pour la chronique manquante
        assert 'level_aux1' in record[0]['columns']
        assert 'level_aux2' not in record[0]['columns']


# ─────────────────────────────────────────────────────────────────────────
# Chemins d'erreur (doivent lever via st.stop())
# ─────────────────────────────────────────────────────────────────────────

class TestRenderErrorHandling:
    def test_missing_target_chronicle_stops_and_reports_error(self, monkeypatch, stubbed_st):
        chronicles = _make_chronicles(n=48, freq='MS', keys=(1, 3))  # clé 2 absente
        with pytest.raises(StopRenderException):
            tab_analyse.render(
                chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ2', 'ETS',
                future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
            )
        assert stubbed_st['error']

    def test_zero_validation_years_stops_with_invalid_steps_error(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=48, freq='MS')
        with pytest.raises(StopRenderException):
            tab_analyse.render(
                chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
                future_years=1, validation_years=0, ci_pct=68, n_bootstraps=5,
            )
        assert any('invalide' in (msg or '') for msg in stubbed_st['error'])
        assert not record  # le fit n'a jamais dû être appelé

    def test_validation_period_larger_than_data_stops_with_clear_error(self, monkeypatch, stubbed_st):
        record = []
        monkeypatch.setattr(tab_analyse, 'cached_fit_predict', _fake_cached_fit_predict(record))
        chronicles = _make_chronicles(n=12, freq='MS')  # seulement 12 observations
        with pytest.raises(StopRenderException):
            tab_analyse.render(
                chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
                future_years=1, validation_years=5, ci_pct=68, n_bootstraps=5,
            )
        assert any('trop grande' in (msg or '') for msg in stubbed_st['error'])
        assert not record


# ─────────────────────────────────────────────────────────────────────────
# Test d'intégration léger (sans mock de cached_fit_predict)
# ─────────────────────────────────────────────────────────────────────────

class TestRenderIntegrationWithRealModel:
    def test_full_pipeline_runs_end_to_end_with_ets(self, stubbed_st):
        # Pas de mock de cached_fit_predict ici : vérifie que le vrai
        # câblage vers core.fit_predict (via le cache Streamlit) fonctionne,
        # avec un modèle rapide (ETS) pour garder le test court.
        chronicles = _make_chronicles(n=48, freq='MS')
        freq = tab_analyse.render(
            chronicles, ['PZ1', 'PZ2', 'PZ3'], 'PZ1', 'ETS',
            future_years=1, validation_years=1, ci_pct=68, n_bootstraps=5,
        )
        assert freq == 'MS'
        assert not stubbed_st['error']
