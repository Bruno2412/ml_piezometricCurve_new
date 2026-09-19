# -*- coding: utf-8 -*-
"""Onglet « Interprétation ».

ATTENTION — version de remplacement : le fichier reçu était une copie de
tab_chroniques.py (même en-tête Spyder, même code, et une signature
render(chronicles) incompatible avec l'appel fait par app_pages/analyse.py).
Si tu as une ancienne version de l'interprétation (sauvegarde Spyder,
git…), garde-la et n'adapte que la signature de render() ci-dessous.

Cette version se contente d'un tableau descriptif par chronique (période,
dernier niveau, min/max, tendance linéaire) pour que l'onglet fonctionne.
"""

import numpy as np
import pandas as pd
import streamlit as st


def _linear_trend_per_year(df):
    """Pente d'une régression linéaire niveau ~ temps, en unités de
    niveau par an. Retourne NaN si elle n'est pas calculable."""
    d = df[["date", "level"]].dropna()
    if len(d) < 2:
        return np.nan

    years = (pd.to_datetime(d["date"]) - pd.to_datetime(d["date"]).min()).dt.days / 365.25
    if years.nunique() < 2:
        return np.nan

    slope, _intercept = np.polyfit(years.to_numpy(), d["level"].to_numpy(), 1)
    return float(slope)


def render(
    chronicles,
    selection,
    target_name,
    freq,
    ok=True,
    Q=0.0,
    S=0.05,
    K=1e-4,
    thickness=10.0,
    distance=50.0,
    Area=100.0,
):
    """Même signature que tab_twin.render : c'est l'appel commun fait par
    app_pages/analyse.py (twin et interpretation partagent les mêmes
    arguments). `freq` est la fréquence détectée par l'onglet Analyse."""

    if not chronicles:
        st.info("Aucune chronique à interpréter.")
        return

    st.caption(f"Piézomètre cible : {target_name} — fréquence détectée : {freq}")

    rows = []
    for _i, c in chronicles.items():
        df = c["df"].dropna(subset=["level"])
        if df.empty:
            continue
        rows.append(
            {
                "Point": c["name"],
                "Début": pd.to_datetime(df["date"]).min().date(),
                "Fin": pd.to_datetime(df["date"]).max().date(),
                "Observations": len(df),
                "Dernier niveau": round(float(df["level"].iloc[-1]), 2),
                "Min": round(float(df["level"].min()), 2),
                "Max": round(float(df["level"].max()), 2),
                "Tendance (par an)": round(_linear_trend_per_year(df), 3),
            }
        )

    if not rows:
        st.info("Aucune donnée exploitable.")
        return

    st.dataframe(pd.DataFrame(rows).set_index("Point"))
