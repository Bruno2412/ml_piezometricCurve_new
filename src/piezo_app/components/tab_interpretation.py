# -*- coding: utf-8 -*-
"""
Created on Fri Sep 18 15:10:38 2026

@author: bruno
"""

# -*- coding: utf-8 -*-
"""Onglet 1 — Réseau Piézo : chroniques brutes + comparaison normalisée."""

import matplotlib.pyplot as plt
import streamlit as st

from piezo_app import piezo_core as core
from piezo_app.components.mpl_theme import theme_colors


def render(chronicles):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 6.5))
    palette = theme_colors()
    colors = {i: palette[(i - 1) % len(palette)] for i in chronicles.keys()}
    for i, c in chronicles.items():
        ax1.plot(c["df"]["date"], c["df"]["level"], color=colors[i], label=c["name"])
        z = (c["df"]["level"] - c["df"]["level"].mean()) / (c["df"]["level"].std() or 1)
        ax2.plot(c["df"]["date"], z, color=colors[i], label=c["name"])
    ax1.set_title("Chroniques brutes")
    ax1.legend()
    ax1.grid(alpha=0.25)
    ax2.set_title("Comparaison normalisée (z-score)")
    ax2.legend()
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    corr, n_pts = core.compute_correlation_matrix(chronicles)
    if corr is not None:
        st.dataframe(corr.style.format("{:.2f}"))