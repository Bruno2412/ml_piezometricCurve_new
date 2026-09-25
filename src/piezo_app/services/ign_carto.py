# -*- coding: utf-8 -*-
"""
Created on Tue Sep 22 14:46:45 2026

@author: bruno
"""


# -*- coding: utf-8 -*-
"""
Services cartographiques IGN / API Carto.

Fonctions :
- retrouver la commune contenant un point ;
- récupérer les communes limitrophes ;
- récupérer les parcelles cadastrales des communes concernées.

Les géométries sont manipulées en WGS84 / EPSG:4326,
conformément à l'API Carto IGN.
"""

import json
from typing import Any

from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_CARTO = "https://apicarto.ign.fr/api"
GEOPLATEFORME_WMTS = "https://data.geopf.fr/wmts"


def _get_json(endpoint: str, params: dict[str, Any]) -> dict:
    """
    Effectue une requête GET vers API Carto et retourne le JSON.
    """
    url = f"{API_CARTO}/{endpoint}?{urlencode(params)}"

    request = Request(
        url,
        headers={
            "User-Agent": "Expert-Piezometrie-Pro/1.0",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def wmts_tile_url(layer: str, style: str = "normal") -> str:
    """
    Construit le gabarit d'URL WMTS (format XYZ) pour une couche de la
    Géoplateforme, directement utilisable par folium.TileLayer.

    Les couches usuelles :
      - "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2" : plan IGN
      - "ORTHOIMAGERY.ORTHOPHOTOS"          : orthophotos
    """
    return (
        f"{GEOPLATEFORME_WMTS}?"
        "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
        f"&LAYER={layer}&STYLE={style}&FORMAT=image/png"
    )


def get_commune_at_point(
    lat: float,
    lon: float,
) -> dict | None:
    """
    Recherche la commune contenant le point fourni.

    Retourne la Feature GeoJSON de la commune ou None.
    """

    geom = json.dumps(
        {
            "type": "Point",
            "coordinates": [float(lon), float(lat)],
        },
        separators=(",", ":"),
    )

    data = _get_json(
        "limites-administratives/commune",
        {
            "geom": geom,
            "_limit": 10,
        },
    )

    features = data.get("features", [])

    if not features:
        return None

    # Le premier résultat est normalement la commune contenant le point.
    return features[0]


def get_neighboring_communes(
    commune_feature: dict,
) -> list[dict]:
    """
    Recherche les communes qui intersectent la géométrie
    de la commune cible.

    La commune cible elle-même est retirée du résultat.

    Retourne une liste de Features GeoJSON.
    """

    geometry = commune_feature.get("geometry")

    if not geometry:
        return []

    geom = json.dumps(
        geometry,
        separators=(",", ":"),
    )

    data = _get_json(
        "limites-administratives/commune",
        {
            "geom": geom,
            "_limit": 1000,
        },
    )

    target_properties = commune_feature.get("properties", {})

    target_insee = (
        target_properties.get("code")
        or target_properties.get("code_insee")
        or target_properties.get("insee")
        or target_properties.get("CODE_INSEE")
    )

    neighbors = []

    for feature in data.get("features", []):

        properties = feature.get("properties", {})

        feature_insee = (
            properties.get("code")
            or properties.get("code_insee")
            or properties.get("insee")
            or properties.get("CODE_INSEE")
        )

        if target_insee and feature_insee == target_insee:
            continue

        neighbors.append(feature)

    return neighbors


def get_cadastre_for_commune(
    insee_code: str,
) -> dict | None:
    """
    Récupère les parcelles cadastrales d'une commune.

    L'API Carto limite le nombre d'objets retournés par requête.
    Pour une première version, on récupère jusqu'à 1000 parcelles.

    Retourne une FeatureCollection GeoJSON.
    """

    if not insee_code:
        return None

    data = _get_json(
        "cadastre/parcelle",
        {
            "code_insee": str(insee_code),
            "_start": 0,
            "_limit": 1000,
        },
    )

    return data


def get_cadastre_for_communes(
    communes: list[dict],
) -> dict:
    """
    Récupère et fusionne les parcelles cadastrales
    de plusieurs communes.

    L'API Carto ne permet pas de demander plusieurs communes
    cadastrales dans une seule requête : on effectue donc
    une requête par commune puis on regroupe les résultats.
    """

    all_features = []

    for commune in communes:

        properties = commune.get("properties", {})

        insee_code = (
            properties.get("code")
            or properties.get("code_insee")
            or properties.get("insee")
            or properties.get("CODE_INSEE")
        )

        if not insee_code:
            continue

        data = get_cadastre_for_commune(
            str(insee_code)
        )

        if not data:
            continue

        all_features.extend(
            data.get("features", [])
        )

    return {
        "type": "FeatureCollection",
        "features": all_features,
    }


def commune_label(
    commune_feature: dict,
) -> str:
    """
    Retourne le nom de commune disponible dans les propriétés IGN.
    """

    properties = commune_feature.get(
        "properties",
        {},
    )

    return (
        properties.get("nom")
        or properties.get("NOM")
        or properties.get("nom_com")
        or properties.get("NOM_COM")
        or "Commune inconnue"
    )

