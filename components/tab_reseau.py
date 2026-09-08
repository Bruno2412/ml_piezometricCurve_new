# -*- coding: utf-8 -*-
"""Onglet 1 — Réseau Piézo : chroniques brutes + comparaison normalisée."""

import matplotlib.pyplot as plt
import streamlit as st

import piezo_core as core


def render(chronicles):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
    cmap = plt.get_cmap('tab10')
    colors = {i: cmap((i - 1) % 10) for i in chronicles.keys()}
    for i, c in chronicles.items():
        ax1.plot(c['df']['date'], c['df']['level'], color=colors[i], label=c['name'])
        z = (c['df']['level'] - c['df']['level'].mean()) / (c['df']['level'].std() or 1)
        ax2.plot(c['df']['date'], z, color=colors[i], label=c['name'])
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
