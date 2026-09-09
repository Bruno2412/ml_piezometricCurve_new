# -*- coding: utf-8 -*-
"""Onglet 3 — Carte piézométrique évolutive (interpolation + Folium)."""

import base64

import folium
import streamlit as st
from streamlit_folium import st_folium

import piezo_core as core


def render(selection, chronicles, coords_dict):
    st.subheader("Carte piézométrique évolutive")

    if not coords_dict:
        st.info(
            "Aucun fichier descriptif chargé — charge-le en même temps "
            "que le fichier Excel, dans la barre latérale."
        )
        return

    missing = [name for name in selection if name.strip() not in coords_dict]
    available = [name for name in selection if name.strip() in coords_dict]

    if missing:
        st.warning(
            f"Coordonnées introuvables pour : {missing} — "
            "carte affichée avec les points disponibles seulement."
        )

    if len(available) < 3:
        st.error(
            f"Seuls {len(available)} point(s) sur {len(selection)} "
            "ont des coordonnées connues dans le fichier descriptif — "
            "au moins 3 sont nécessaires pour interpoler une surface "
            "piézométrique."
        )
        return

    coords = [coords_dict[name] for name in available]
    idx_available = [selection.index(name) + 1 for name in available]

    min_date = max(chronicles[i]['df']['date'].min() for i in idx_available)
    max_date = min(chronicles[i]['df']['date'].max() for i in idx_available)

    if min_date >= max_date:
        st.error("Aucune période commune entre les points disponibles.")
        return

    selected_date = st.slider(
        "Date de la carte",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=max_date.to_pydatetime(),
        format="DD/MM/YYYY"
    )

    values = [
        core.value_at_date(chronicles[i]['df'], selected_date)
        for i in idx_available
    ]

    GLon, GLat, GZ = core.build_piezo_surface(coords, values)

    center_lat = sum(c['lat'] for c in coords) / len(coords)
    center_lon = sum(c['lon'] for c in coords) / len(coords)

    m = folium.Map(
        location=[center_lat, center_lon], zoom_start=13,
        tiles="OpenStreetMap"
    )

    png_bytes, bounds = core.surface_to_png_overlay(GLon, GLat, GZ)
    img_data = f"data:image/png;base64,{base64.b64encode(png_bytes).decode()}"

    folium.raster_layers.ImageOverlay(
        image=img_data, bounds=bounds, opacity=0.7, interactive=False,
    ).add_to(m)

    for c, name, val in zip(coords, available, values):
        folium.Marker(
            location=[c['lat'], c['lon']],
            popup=(
                f"<b>{name}</b><br>"
                f"Niveau : {val:.2f} m<br>"
                f"Masse d'eau : {c['masse_eau']}"
            ),
            tooltip=f"{name} — {val:.2f} m",
            icon=folium.Icon(color='orange', icon='tint', prefix='fa'),
        ).add_to(m)

    st_folium(m, width=900, height=600, returned_objects=[])

    st.caption(
        f"⚠️ Interpolation linéaire entre {len(available)} point(s) — "
        "la surface colorée n'est valide qu'à l'intérieur du polygone "
        "formé par les points disponibles, et reste une approximation "
        "grossière")