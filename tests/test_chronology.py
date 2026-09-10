# -*- coding: utf-8 -*-
"""
Tests unitaires pour la logique de chronologie de piezo_core.py :
alignement temporel des chroniques, détection et conversion de fréquence,
valeur interpolée à une date donnée.

Lancer avec :
    pytest tests/test_chronology.py -v
"""

import pandas as pd
import pytest

import piezo_core as core


# ─────────────────────────────────────────────────────────────────────────
# align_chronicle
# ─────────────────────────────────────────────────────────────────────────

class TestAlignChronicle:
    def test_returns_exact_values_at_known_dates(self):
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=5, freq='D'),
            'level': [1.0, 2.0, 3.0, 4.0, 5.0],
        })
        target_dates = df['date']
        result = core.align_chronicle(df, target_dates)
        pd.testing.assert_series_equal(
            pd.Series(result), pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]),
            check_names=False,
        )

    def test_interpolates_between_known_points(self):
        df = pd.DataFrame({
            'date': [pd.Timestamp('2024-01-01'), pd.Timestamp('2024-01-03')],
            'level': [10.0, 20.0],
        })
        target_dates = [pd.Timestamp('2024-01-02')]
        result = core.align_chronicle(df, target_dates)
        assert result[0] == pytest.approx(15.0)

    def test_handles_duplicate_dates_by_averaging(self):
        df = pd.DataFrame({
            'date': [pd.Timestamp('2024-01-01'), pd.Timestamp('2024-01-01')],
            'level': [10.0, 20.0],
        })
        result = core.align_chronicle(df, [pd.Timestamp('2024-01-01')])
        assert result[0] == pytest.approx(15.0)

    def test_output_length_matches_target_dates(self):
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=3, freq='D'),
            'level': [1.0, 2.0, 3.0],
        })
        target_dates = pd.date_range('2024-01-01', periods=6, freq='D')
        result = core.align_chronicle(df, target_dates)
        assert len(result) == 6


# ─────────────────────────────────────────────────────────────────────────
# detect_frequency / freq_to_seasonal_periods / future_steps
# ─────────────────────────────────────────────────────────────────────────

class TestDetectFrequency:
    @pytest.mark.parametrize('freq_str, expected', [
        ('D', 'D'),
        ('7D', 'W'),
        ('30D', 'MS'),
        ('90D', 'QS'),
        ('365D', 'YS'),
    ])
    def test_detects_expected_frequency(self, freq_str, expected):
        dates = pd.Series(pd.date_range('2024-01-01', periods=6, freq=freq_str))
        assert core.detect_frequency(dates) == expected


class TestFreqToSeasonalPeriods:
    @pytest.mark.parametrize('freq, expected', [
        ('D', 365), ('W', 52), ('MS', 12), ('QS', 4), ('YS', 1),
    ])
    def test_known_frequencies(self, freq, expected):
        assert core.freq_to_seasonal_periods(freq) == expected

    def test_unknown_frequency_defaults_to_monthly(self):
        assert core.freq_to_seasonal_periods('XYZ') == 12


class TestFutureSteps:
    def test_monthly_steps_over_two_years(self):
        assert core.future_steps('MS', years=2) == 24

    def test_daily_steps_over_one_year(self):
        assert core.future_steps('D', years=1) == 365


# ─────────────────────────────────────────────────────────────────────────
# value_at_date
# ─────────────────────────────────────────────────────────────────────────

class TestValueAtDate:
    def test_exact_match_returns_known_value(self):
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=3, freq='D'),
            'level': [1.0, 2.0, 3.0],
        })
        assert core.value_at_date(df, '2024-01-02') == pytest.approx(2.0)

    def test_interpolates_between_known_values(self):
        df = pd.DataFrame({
            'date': [pd.Timestamp('2024-01-01'), pd.Timestamp('2024-01-03')],
            'level': [10.0, 30.0],
        })
        assert core.value_at_date(df, '2024-01-02') == pytest.approx(20.0)
