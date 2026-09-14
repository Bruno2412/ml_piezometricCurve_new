# -*- coding: utf-8 -*-
"""
Tests unitaires pour piezo_app.components.mpl_theme.

Lancer avec :
    pytest tests/test_mpl_theme.py -v
"""

from unittest import mock

import matplotlib.pyplot as plt

from piezo_app.components import mpl_theme


class TestThemeColors:
    def test_returns_palette_from_streamlit_option_when_set(self):
        with mock.patch.object(mpl_theme.st, "get_option", return_value=["#111111", "#222222"]):
            assert mpl_theme.theme_colors() == ["#111111", "#222222"]

    def test_falls_back_to_default_palette_when_option_is_none(self):
        with mock.patch.object(mpl_theme.st, "get_option", return_value=None):
            colors = mpl_theme.theme_colors()
            assert colors == mpl_theme._FALLBACK_COLORS

    def test_returns_a_new_list_not_a_reference_to_the_option(self):
        # theme_colors() ne doit pas renvoyer l'objet de config.toml tel
        # quel : un appelant qui muterait la liste renvoyée ne doit pas
        # affecter les appels suivants.
        source = ["#aaaaaa", "#bbbbbb"]
        with mock.patch.object(mpl_theme.st, "get_option", return_value=source):
            colors = mpl_theme.theme_colors()
            colors.append("#ffffff")
            assert source == ["#aaaaaa", "#bbbbbb"]


class TestApplyMplTheme:
    def _fake_get_option(self, key):
        return {
            "theme.textColor": "#123456",
            "theme.backgroundColor": "#fefefe",
            "theme.font": "'Inter':https://fonts.googleapis.com/css2?family=Inter",
            "theme.chartCategoricalColors": ["#0d6efd", "#fd7e14"],
        }.get(key)

    def test_sets_expected_rcparams_from_theme_options(self):
        with mock.patch.object(mpl_theme.st, "get_option", side_effect=self._fake_get_option):
            mpl_theme.apply_mpl_theme()
        assert plt.rcParams["axes.edgecolor"] == "#123456"
        assert plt.rcParams["text.color"] == "#123456"
        assert plt.rcParams["figure.facecolor"] == "#fefefe"
        assert plt.rcParams["axes.facecolor"] == "#fefefe"
        assert plt.rcParams["axes.spines.top"] is False
        assert plt.rcParams["axes.spines.right"] is False

    def test_extracts_font_family_name_from_google_fonts_syntax(self):
        with mock.patch.object(mpl_theme.st, "get_option", side_effect=self._fake_get_option):
            mpl_theme.apply_mpl_theme()
        assert plt.rcParams["font.family"][0] == "Inter"

    def test_uses_sensible_defaults_when_theme_options_are_unset(self):
        with mock.patch.object(mpl_theme.st, "get_option", return_value=None):
            mpl_theme.apply_mpl_theme()
        assert plt.rcParams["text.color"] == "#1c2733"
        assert plt.rcParams["figure.facecolor"] == "#ffffff"
        assert plt.rcParams["font.family"][0] == "sans-serif"

    def test_new_figures_pick_up_the_categorical_color_cycle(self):
        with mock.patch.object(mpl_theme.st, "get_option", side_effect=self._fake_get_option):
            mpl_theme.apply_mpl_theme()
        fig, ax = plt.subplots()
        (line1,) = ax.plot([0, 1], [0, 1])
        (line2,) = ax.plot([0, 1], [1, 0])
        assert line1.get_color() == "#0d6efd"
        assert line2.get_color() == "#fd7e14"
        plt.close(fig)
