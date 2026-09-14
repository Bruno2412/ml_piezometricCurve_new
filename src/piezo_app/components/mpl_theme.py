# -*- coding: utf-8 -*-
"""
Applique le thème défini dans .streamlit/config.toml aux figures matplotlib
de l'application (tab_analyse, tab_reseau, tab_twin, piezo_core), pour que
les graphiques suivent la même charte que les widgets natifs Streamlit
(couleurs, police) au lieu du style par défaut de matplotlib.

Usage : appeler apply_mpl_theme() une seule fois, tôt dans app_streamlit.py,
avant que la moindre figure ne soit créée. Les rcParams modifiés s'appliquent
ensuite à tous les plt.subplots() de l'application pour le reste de la
session — aucune autre modification n'est nécessaire dans les composants.

Pour une figure qui a besoin de plusieurs couleurs distinctes (courbes
multiples, barres par catégorie...), utiliser theme_colors() plutôt que de
coder une couleur en dur, afin de rester aligné avec la palette du thème
si celle-ci change dans config.toml.
"""

import matplotlib.pyplot as plt
import streamlit as st

# Repli utilisé si le thème ne définit pas de palette catégorielle
# (ex. si quelqu'un supprime chartCategoricalColors de config.toml).
_FALLBACK_COLORS = ["#0d6efd", "#fd7e14", "#20c997", "#6f42c1", "#dc3545", "#adb5bd"]


def theme_colors() -> list[str]:
    """Palette catégorielle du thème (theme.chartCategoricalColors dans
    config.toml). À utiliser pour toute série/couleur codée en dur dans un
    graphique matplotlib, afin que l'app entière partage une seule palette.
    """
    colors = st.get_option("theme.chartCategoricalColors")
    return list(colors) if colors else list(_FALLBACK_COLORS)


def apply_mpl_theme() -> None:
    """Configure matplotlib pour suivre le thème Streamlit courant.

    Modifie les rcParams globaux : cycle de couleurs par défaut (donc
    ax.plot() sans couleur explicite suit déjà la palette du thème),
    police, couleur du texte/axes, et un style de grille plus discret
    que le défaut matplotlib.
    """
    text_color = st.get_option("theme.textColor") or "#1c2733"
    bg_color = st.get_option("theme.backgroundColor") or "#ffffff"
    font_option = st.get_option("theme.font") or "sans-serif"
    # theme.font peut être au format "'Inter':https://..." (Google Fonts) :
    # on n'a besoin que du nom de famille pour matplotlib.
    font_family = font_option.split(":")[0].strip("'\"") if font_option else "sans-serif"

    plt.rcParams.update(
        {
            "font.family": [font_family, "DejaVu Sans", "sans-serif"],
            "axes.prop_cycle": plt.cycler(color=theme_colors()),
            "axes.edgecolor": text_color,
            "axes.labelcolor": text_color,
            "text.color": text_color,
            "xtick.color": text_color,
            "ytick.color": text_color,
            "figure.facecolor": bg_color,
            "axes.facecolor": bg_color,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.color": text_color,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
