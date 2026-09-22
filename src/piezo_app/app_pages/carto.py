# -*- coding: utf-8 -*-
"""
Page « Cartographie » : carte piézométrique en plein écran (Folium).

La carte est toujours affichée, même lorsqu'aucune donnée n'a encore été
transmise par « Analyse & Prévision ».

Lorsque des chroniques et coordonnées sont disponibles dans
st.session_state["shared_map_data"], les piézomètres sont ajoutés à la carte
et une surface interpolée peut être calculée à partir d'au moins 3 points.
"""

import base64


import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from piezo_app.services import ign_carto
from piezo_app.auth import permissions
from piezo_app.services import piezo_core as core


# ---------------------------------------------------------
# Pleine largeur
# ---------------------------------------------------------
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Connexion et droits
# ---------------------------------------------------------
user = st.session_state.get("user")

if user is None:
    st.error("Connexion requise.")
    st.stop()

if "carte" not in permissions.allowed_pages(user):
    st.warning(
        "Vous n'avez pas accès à la cartographie. Contactez votre "
        "administrateur pour demander l'attribution de ce droit."
    )
    st.stop()


st.title("Cartographie piézométrique")


# ---------------------------------------------------------
# Récupération éventuelle des données
# ---------------------------------------------------------
data = st.session_state.get("shared_map_data")

chronicles = {}
coords_dict = {}
target_name = None

if data:
    chronicles = data.get("chronicles", {})
    coords_dict = data.get("coords_dict", {})
    target_name = data.get("target_name")


# ---------------------------------------------------------
# Points disposant de coordonnées
# ---------------------------------------------------------
points_with_coords = {}

if chronicles and coords_dict:
    points_with_coords = {
        c["name"]: coords_dict[c["name"]]
        for c in chronicles.values()
        if c["name"] in coords_dict
    }


# ---------------------------------------------------------
# Position initiale de la carte
# ---------------------------------------------------------
# Initialisation des variables pour éviter l'erreur si points_with_coords est vide
commune_cible = None
communes_voisines = []
commune_note = None

if points_with_coords:
    lats = [p["lat"] for p in points_with_coords.values()]
    lons = [p["lon"] for p in points_with_coords.values()]

    center = [
        sum(lats) / len(lats),
        sum(lons) / len(lons),
    ]

    zoom_start = 14
    
    try:
        commune_cible = ign_carto.get_commune_at_point(
            lat=center[0],
            lon=center[1],
        )
    
        if commune_cible:
            communes_voisines = ign_carto.get_neighboring_communes(
                commune_cible
            )
    
    except Exception as exc:
        commune_note = (
            f"Informations communales IGN indisponibles : {exc}"
        )

else:
    # Position par défaut : Lyon
    center = [45.7640, 4.8357]
    zoom_start = 11


# ---------------------------------------------------------
# Construction de la carte
# ---------------------------------------------------------
m = folium.Map(
    location=center,
    zoom_start=zoom_start,
    control_scale=True,
    tiles="OpenStreetMap",
)


# ---------------------------------------------------------
# Fond satellite
# ---------------------------------------------------------
folium.TileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}",
    name="Satellite",
    attr="Esri",
).add_to(m)

# ---------------------------------------------------------
# Limites communales
# ---------------------------------------------------------
if commune_cible:

    commune_group = folium.FeatureGroup(
        name="Commune cible",
        show=True,
    )

    folium.GeoJson(
        commune_cible,
        name=ign_carto.commune_label(commune_cible),
        style_function=lambda feature: {
            "color": "#d62728",
            "weight": 3,
            "fillOpacity": 0.05,
        },
        tooltip=ign_carto.commune_label(commune_cible),
    ).add_to(commune_group)

    commune_group.add_to(m)


if communes_voisines:

    voisins_group = folium.FeatureGroup(
        name="Communes limitrophes",
        show=True,
    )

    for commune in communes_voisines:

        folium.GeoJson(
            commune,
            style_function=lambda feature: {
                "color": "#555555",
                "weight": 1.5,
                "fillOpacity": 0.02,
            },
            tooltip=ign_carto.commune_label(commune),
        ).add_to(voisins_group)

    voisins_group.add_to(m)


# ---------------------------------------------------------
# Ajout des piézomètres
# ---------------------------------------------------------
for name, info in points_with_coords.items():

    try:
        chron = next(
            c for c in chronicles.values()
            if c["name"] == name
        )

        last_row = chron["df"].loc[
            chron["df"]["date"].idxmax()
        ]

        is_target = name == target_name

        popup_html = (
            f"<b>{name}</b><br>"
            f"Masse d'eau : "
            f"{info.get('masse_eau') or 'non renseignée'}<br>"
            f"Dernier niveau : "
            f"{last_row['level']:.2f} m<br>"
            f"({pd.Timestamp(last_row['date']).date()})"
        )

        folium.Marker(
            location=[
                info["lat"],
                info["lon"],
            ],
            popup=folium.Popup(
                popup_html,
                max_width=250,
            ),
            tooltip=name,
            icon=folium.Icon(
                color="red" if is_target else "blue",
                icon="star" if is_target else "tint",
                prefix="fa",
            ),
        ).add_to(m)

    except Exception as exc:
        st.warning(
            f"Impossible d'afficher le point « {name} » : {exc}"
        )


# ---------------------------------------------------------
# Surface interpolée
# ---------------------------------------------------------
surface_note = None

if len(points_with_coords) >= 3:

    try:

        ref_date = min(
            c["df"]["date"].max()
            for c in chronicles.values()
            if c["name"] in points_with_coords
        )

        coords_list = list(
            points_with_coords.values()
        )

        values = [
            core.value_at_date(
                next(
                    c["df"]
                    for c in chronicles.values()
                    if c["name"] == name
                ),
                ref_date,
            )
            for name in points_with_coords
        ]

        GLon, GLat, GZ = core.build_piezo_surface(
            coords_list,
            values,
        )

        png_bytes, bounds = core.surface_to_png_overlay(
            GLon,
            GLat,
            GZ,
        )

        b64 = base64.b64encode(
            png_bytes
        ).decode("ascii")

        folium.raster_layers.ImageOverlay(
            image=f"data:image/png;base64,{b64}",
            bounds=bounds,
            opacity=0.6,
            name=(
                "Surface interpolée "
                f"({pd.Timestamp(ref_date).date()})"
            ),
        ).add_to(m)

    except Exception as exc:
        surface_note = (
            f"Surface interpolée indisponible : {exc}"
        )

# ---------------------------------------------------------
# Cadastre
# ---------------------------------------------------------
cadastre_note = None

if commune_cible:

    try:

        communes_cadastre = [
            commune_cible,
            *communes_voisines,
        ]

        cadastre = ign_carto.get_cadastre_for_communes(
            communes_cadastre
        )

        if cadastre.get("features"):

            folium.GeoJson(
                cadastre,
                name="Cadastre",
                show=False,
                style_function=lambda feature: {
                    "color": "#666666",
                    "weight": 0.6,
                    "fillColor": "#ffffff",
                    "fillOpacity": 0.02,
                },
                highlight_function=lambda feature: {
                    "weight": 2,
                    "fillOpacity": 0.10,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=[
                        "section",
                        "numero",
                    ],
                    aliases=[
                        "Section",
                        "Parcelle",
                    ],
                    localize=True,
                    sticky=False,
                    labels=True,
                ),
            ).add_to(m)

    except Exception as exc:
        cadastre_note = (
            f"Cadastre indisponible : {exc}"
        )


# ---------------------------------------------------------
# Contrôle des couches
# ---------------------------------------------------------
folium.LayerControl(
    collapsed=False
).add_to(m)


# ---------------------------------------------------------
# Affichage de la carte
# ---------------------------------------------------------
st_folium(
    m,
    use_container_width=True,
    height=800,
    returned_objects=[],
)


# ---------------------------------------------------------
# Informations sous la carte
# ---------------------------------------------------------
if points_with_coords:

    st.caption(
        f"{len(points_with_coords)} point(s) affiché(s) "
        f"sur {len(chronicles)} chargé(s). "
        "Étoile rouge : piézomètre cible de la prévision."
    )

else:

    st.caption(
        "Aucune chronique ni coordonnée n'est actuellement "
        "disponible. La carte est prête à recevoir les données "
        "piézométriques."
    )


if surface_note:
    st.caption(surface_note)

