# -*- coding: utf-8 -*-
"""
Page « Cartographie » : carte piézométrique en plein écran (Folium).
"""

import base64
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from piezo_app.auth import permissions
from piezo_app.services import ign_carto
from piezo_app.services import projects
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

current_project = projects.require_current_project(user)

st.title("Cartographie piézométrique")

# ---------------------------------------------------------
# Récupération des données
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
# Localisation & Communes (IGN)
# ---------------------------------------------------------
commune_cible = None
communes_voisines = []
commune_note = None

if st.session_state.get("carto_search_center"):
    center = st.session_state["carto_search_center"]
    zoom_start = st.session_state.get("carto_search_zoom", 14)

    try:
        commune_cible = ign_carto.get_commune_at_point(lat=center[0], lon=center[1])
    except Exception as exc:
        commune_note = f"Erreur récupération commune cible : {exc}"

    if commune_cible:
        try:
            communes_voisines = ign_carto.get_neighboring_communes(commune_cible) or []
        except Exception as exc:
            commune_note = f"Erreur récupération communes limitrophes : {exc}"

elif points_with_coords:
    lats = [p["lat"] for p in points_with_coords.values()]
    lons = [p["lon"] for p in points_with_coords.values()]

    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    zoom_start = 14

    try:
        commune_cible = ign_carto.get_commune_at_point(lat=center[0], lon=center[1])
    except Exception as exc:
        commune_note = f"Erreur récupération commune cible : {exc}"

    if commune_cible:
        try:
            communes_voisines = ign_carto.get_neighboring_communes(commune_cible) or []
        except Exception as exc:
            commune_note = f"Erreur récupération communes limitrophes : {exc}"
else:
    center = [45.7640, 4.8357]  # Lyon par défaut
    zoom_start = 11


# ---------------------------------------------------------
# Recherche de lieu (géocodage Géoplateforme)
# ---------------------------------------------------------
search_col, button_col = st.columns([4, 1])

with search_col:
    search_query = st.text_input(
        "Rechercher un lieu",
        placeholder="Ex : Grenoble, 12 rue de la Paix Lyon...",
        label_visibility="collapsed",
        key="carto_search_query",
    )

with button_col:
    search_clicked = st.button("Rechercher", use_container_width=True)

if search_clicked and search_query:
    try:
        results = ign_carto.search_location(search_query)
        if results:
            best = results[0]
            props = best.get("properties", {})
            lon, lat = best["geometry"]["coordinates"]

            has_housenumber = bool(props.get("housenumber"))

            st.session_state["carto_search_center"] = [lat, lon]
            st.session_state["carto_search_zoom"] = 16 if has_housenumber else 13
            st.session_state["carto_search_label"] = ign_carto.location_label(best)
            st.session_state["carto_search_is_address"] = has_housenumber
            st.rerun()
        else:
            st.warning(f"Aucun résultat pour « {search_query} ».")
    except Exception as exc:
        st.warning(f"Recherche indisponible : {exc}")


if st.session_state.get("carto_search_label"):
    st.caption(f"📍 Centré sur : {st.session_state['carto_search_label']}")


# ---------------------------------------------------------
# Construction de la carte Folium
# ---------------------------------------------------------
m = folium.Map(
    location=center,
    zoom_start=zoom_start,
    control_scale=True,
    tiles="OpenStreetMap",
)

# Fond satellite Esri
folium.TileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    name="Satellite",
    attr="Esri",
).add_to(m)

# Fonds de carte IGN (Géoplateforme)
folium.TileLayer(
    tiles=ign_carto.wmts_tile_url("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"),
    name="Plan IGN",
    attr="IGN-F/Géoportail",
    overlay=False,
    control=True,
).add_to(m)

folium.TileLayer(
    tiles=ign_carto.wmts_tile_url("ORTHOIMAGERY.ORTHOPHOTOS"),
    name="Orthophotos IGN",
    attr="IGN-F/Géoportail",
    overlay=False,
    control=True,
).add_to(m)


# ---------------------------------------------------------
# Épingle sur le lieu recherché (uniquement si adresse précise)
# ---------------------------------------------------------
if st.session_state.get("carto_search_is_address") and st.session_state.get("carto_search_center"):
    search_lat, search_lon = st.session_state["carto_search_center"]
    folium.Marker(
        location=[search_lat, search_lon],
        popup=st.session_state.get("carto_search_label", "Lieu recherché"),
        tooltip=st.session_state.get("carto_search_label", "Lieu recherché"),
        icon=folium.Icon(color="green", icon="map-marker", prefix="fa"),
    ).add_to(m)


# ---------------------------------------------------------
# Affichage des communes (cible + voisines)
# ---------------------------------------------------------
if commune_cible:
    commune_group = folium.FeatureGroup(name="Commune cible", show=True)
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
    voisins_group = folium.FeatureGroup(name="Communes limitrophes", show=True)
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
# Cadastre (Modifié : show=True)
# ---------------------------------------------------------
cadastre_note = None

if commune_cible:
    try:
        # Fusion des communes pour interroger le cadastre
        communes_cadastre = [commune_cible, *communes_voisines]
        cadastre = ign_carto.get_cadastre_for_communes(communes_cadastre)

        if cadastre and cadastre.get("features"):
            folium.GeoJson(
                cadastre,
                name="Cadastre",
                show=True,  # <-- Poussé à True pour afficher les parcelles au chargement
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
                    fields=["section", "numero"],
                    aliases=["Section", "Parcelle"],
                    localize=True,
                    sticky=False,
                    labels=True,
                ),
            ).add_to(m)
        else:
            cadastre_note = "Aucune parcelle cadastrale trouvée pour la zone."
    except Exception as exc:
        cadastre_note = f"Cadastre indisponible : {exc}"

# ---------------------------------------------------------
# Piézomètres & Surface interpolée
# ---------------------------------------------------------
for name, info in points_with_coords.items():
    try:
        chron = next(
            c for c in chronicles.values() if c["name"] == name
        )
        last_row = chron["df"].loc[chron["df"]["date"].idxmax()]
        is_target = name == target_name

        popup_html = (
            f"<b>{name}</b><br>"
            f"Masse d'eau : {info.get('masse_eau') or 'non renseignée'}<br>"
            f"Dernier niveau : {last_row['level']:.2f} m<br>"
            f"({pd.Timestamp(last_row['date']).date()})"
        )

        folium.Marker(
            location=[info["lat"], info["lon"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=name,
            icon=folium.Icon(
                color="red" if is_target else "blue",
                icon="star" if is_target else "tint",
                prefix="fa",
            ),
        ).add_to(m)
    except Exception as exc:
        st.warning(f"Impossible d'afficher le point « {name} » : {exc}")

surface_note = None
if len(points_with_coords) >= 3:
    try:
        ref_date = min(
            c["df"]["date"].max()
            for c in chronicles.values()
            if c["name"] in points_with_coords
        )
        coords_list = list(points_with_coords.values())
        values = [
            core.value_at_date(
                next(
                    c["df"] for c in chronicles.values() if c["name"] == name
                ),
                ref_date,
            )
            for name in points_with_coords
        ]

        GLon, GLat, GZ = core.build_piezo_surface(coords_list, values)
        png_bytes, bounds = core.surface_to_png_overlay(GLon, GLat, GZ)
        b64 = base64.b64encode(png_bytes).decode("ascii")

        folium.raster_layers.ImageOverlay(
            image=f"data:image/png;base64,{b64}",
            bounds=bounds,
            opacity=0.6,
            name=f"Surface interpolée ({pd.Timestamp(ref_date).date()})",
        ).add_to(m)
    except Exception as exc:
        surface_note = f"Surface interpolée indisponible : {exc}"

# ---------------------------------------------------------
# Rendu & Contrôles
# ---------------------------------------------------------
folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, use_container_width=True, height=800, returned_objects=[])

# Notes d'information sous la carte
if points_with_coords:
    st.caption(
        f"{len(points_with_coords)} point(s) affiché(s) sur {len(chronicles)} chargé(s)."
    )

if commune_note:
    st.caption(f"⚠️ {commune_note}")
if cadastre_note:
    st.caption(f"ℹ️ {cadastre_note}")
if surface_note:
    st.caption(f"ℹ️ {surface_note}")

