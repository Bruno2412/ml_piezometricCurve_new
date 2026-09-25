# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 16:06:41 2026

@author: bruno

extract_carto.py — Extraction et export SIG.

Construit des FeatureCollection GeoJSON à partir des données déjà
chargées dans la page Cartographie (piézomètres, communes, cadastre),
et propose leur export.

Volontairement limité au GeoJSON pour l'instant : l'export Shapefile
nécessite geopandas/shapely, non installés à ce stade du projet. Ce
module est prévu pour accueillir cet export dès que ces dépendances
seront ajoutées.
"""

import json
from typing import Any

import pandas as pd
import streamlit as st


def build_piezometers_geojson(
    points_with_coords: dict[str, Any],
    chronicles: dict[str, Any],
    target_name: str | None,
) -> dict:
    """Construit une FeatureCollection des piézomètres affichés, avec
    leur dernier niveau connu en propriété."""
    features = []

    for name, info in points_with_coords.items():
        last_level = None
        last_date = None

        try:
            chron = next(c for c in chronicles.values() if c["name"] == name)
            last_row = chron["df"].loc[chron["df"]["date"].idxmax()]
            last_level = float(last_row["level"])
            last_date = str(pd.Timestamp(last_row["date"]).date())
        except Exception:
            pass

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [info["lon"], info["lat"]],
                },
                "properties": {
                    "name": name,
                    "masse_eau": info.get("masse_eau"),
                    "last_level": last_level,
                    "last_date": last_date,
                    "is_target": name == target_name,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def build_communes_geojson(
    commune_cible: dict | None,
    communes_voisines: list[dict] | None,
) -> dict:
    """Construit une FeatureCollection de la commune cible et de ses
    voisines, chacune taguée par son rôle."""
    features = []

    if commune_cible:
        feature = dict(commune_cible)
        feature["properties"] = {**feature.get("properties", {}), "role": "cible"}
        features.append(feature)

    for commune in communes_voisines or []:
        feature = dict(commune)
        feature["properties"] = {**feature.get("properties", {}), "role": "voisine"}
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def build_cadastre_geojson(cadastre: dict | None) -> dict:
    """Retourne les parcelles cadastrales déjà récupérées, telles
    quelles (déjà au format FeatureCollection GeoJSON)."""
    if not cadastre or not cadastre.get("features"):
        return {"type": "FeatureCollection", "features": []}
    return cadastre


def export_geojson(feature_collection: dict) -> bytes:
    """Sérialise une FeatureCollection en bytes GeoJSON, prêts pour
    st.download_button."""
    return json.dumps(feature_collection, ensure_ascii=False, indent=2).encode("utf-8")


def render_export_panel(
    *,
    points_with_coords: dict[str, Any],
    chronicles: dict[str, Any],
    target_name: str | None,
    commune_cible: dict | None,
    communes_voisines: list[dict] | None,
    cadastre: dict | None,
) -> None:
    """Affiche le panneau d'export SIG (sélection des couches + bouton
    de téléchargement GeoJSON)."""
    with st.expander("🗺️ Export SIG", expanded=False):
        st.caption(
            "Export au format GeoJSON. L'export Shapefile sera ajouté "
            "avec l'intégration de geopandas/shapely."
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            export_piezo = st.checkbox(
                "Piézomètres", value=True, key="export_piezo_chk"
            )
        with col2:
            export_communes = st.checkbox(
                "Communes", value=False, key="export_communes_chk"
            )
        with col3:
            export_cadastre = st.checkbox(
                "Parcelles cadastrales", value=False, key="export_cadastre_chk"
            )

        if st.button("Préparer l'export", key="export_prepare_btn"):
            payload: dict[str, Any] = {"type": "FeatureCollection", "features": []}

            if export_piezo and points_with_coords:
                payload["features"].extend(
                    build_piezometers_geojson(
                        points_with_coords, chronicles, target_name
                    )["features"]
                )

            if export_communes and (commune_cible or communes_voisines):
                payload["features"].extend(
                    build_communes_geojson(commune_cible, communes_voisines)["features"]
                )

            if export_cadastre and cadastre:
                payload["features"].extend(
                    build_cadastre_geojson(cadastre)["features"]
                )

            if not payload["features"]:
                st.warning(
                    "Aucune donnée sélectionnée ou disponible pour l'export."
                )
            else:
                st.download_button(
                    "📥 Télécharger le GeoJSON",
                    data=export_geojson(payload),
                    file_name="export_carto.geojson",
                    mime="application/geo+json",
                    key="export_download_btn",
                )