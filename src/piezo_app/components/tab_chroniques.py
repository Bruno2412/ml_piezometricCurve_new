# -*- coding: utf-8 -*-
"""Onglet « Chroniques » : chroniques brutes + comparaison normalisée."""

import numpy as np
import streamlit as st
from matplotlib.figure import Figure

from piezo_app.services import piezo_core as core
from piezo_app.components.mpl_theme import theme_colors


def _zscore(series):
    """Centre-réduit une série ; si l'écart-type est nul, absent ou NaN
    (série constante, une seule valeur…), on ne divise pas."""
    std = series.std()
    if not np.isfinite(std) or std == 0:
        return series - series.mean()
    return (series - series.mean()) / std


def render(chronicles):
    if not chronicles:
        st.info("Aucune chronique à afficher.")
        return

    # Figure() plutôt que plt.subplots() : pas d'état global pyplot, donc
    # pas de mélange de figures entre sessions simultanées, et plus besoin
    # de plt.close().
    fig = Figure(figsize=(12, 8))
    ax1, ax2 = fig.subplots(2, 1, sharex=True)

    palette = theme_colors()
    colors = {i: palette[(i - 1) % len(palette)] for i in chronicles.keys()}

    for i, c in chronicles.items():
        ax1.plot(c["df"]["date"], c["df"]["level"], color=colors[i], label=c["name"])
        ax2.plot(c["df"]["date"], _zscore(c["df"]["level"]), color=colors[i], label=c["name"])

    ax1.set_title("Chroniques brutes")
    ax1.legend()
    ax1.grid(alpha=0.25)
    ax2.set_title("Comparaison normalisée (z-score)")
    ax2.legend()
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    st.pyplot(fig)

    corr, n_pts = core.compute_correlation_matrix(chronicles)
    if corr is None:
        st.info("Matrice de corrélation indisponible pour ces chroniques.")
    else:
        st.caption(f"Matrice de corrélation (n = {n_pts})")
        # round() plutôt que .style.format() : évite la dépendance à jinja2.
        st.dataframe(corr.round(2))
