# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 16:06:58 2026

@author: bruno

outils_carto.py — Outils cartographiques interactifs (SIG).

Espace réservé pour les futurs outils de manipulation/analyse
directement sur la carte : mesure de distance, mesure de surface,
lecture de coordonnées, buffer, dessin de zone, sélection spatiale,
identification d'objet.

Aucun outil n'est encore implémenté : le dessin de zone (et les outils
qui en dépendent) nécessite le plugin folium.plugins.Draw combiné à la
lecture du retour de st_folium, traité dans une itération ultérieure.
"""

import streamlit as st


def render_tools() -> None:
    """Affiche l'emplacement des futurs outils cartographiques."""
    with st.expander("🛠️ Outils cartographiques", expanded=False):
        st.caption(
            "Mesure de distance, mesure de surface, coordonnées, "
            "buffer, dessin de zone... arriveront ici."
        )