# -*- coding: utf-8 -*-

"""
Chargements de données mis en cache pour Streamlit.
"""

import io
import os
import tempfile

import pandas as pd
import streamlit as st

import piezo_core as core


def _parse_from_bytes(file_bytes: bytes, parse_fn):
    """Écrit `file_bytes` dans un fichier temporaire .txt puis appelle
    `parse_fn(tmp_path)`. Helper partagé car core.parse_descriptif(),
    core.parse_chroniques_raw() et core.parse_masses_eau() attendent
    toutes un chemin de fichier plutôt que des octets bruts."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        return parse_fn(tmp_path)
    finally:
        os.remove(tmp_path)

@st.cache_data(show_spinner="Lecture des chroniques...")
def load_chroniques_auto(uploaded_file):
    file_name = getattr(uploaded_file, "name", str(uploaded_file))
    extension = os.path.splitext(file_name)[1].lower()

    if extension == ".txt":
        raw_bytes = uploaded_file.getvalue()

        # Essai d'encodage utf-8 puis latin-1 (très fréquent sur les fichiers ADES/BRGM)
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(raw_bytes),
                    sep="\t",  # Séparateur tabulation
                    decimal=",",  # <--- Gère directement les virgules comme séparateur décimal
                    encoding=enc,
                )
                # Si les colonnes ont bien été découpées, on valide la lecture
                if len(df.columns) > 1:
                    break
            except Exception:
                continue

    elif extension in (".xlsx", ".xls"):
        df = pd.read_excel(uploaded_file)

    else:
        raise ValueError(f"Format non supporté : {extension}")

    # 1. Nettoyage des entêtes de colonnes
    df.columns = df.columns.astype(str).str.strip()

    # 2. Nettoyage explicite des virgules vers points sur les colonnes numériques (au cas où)
    cols_numeriques = [
        "Côte NGF",
        "Profondeur relative/repère de mesure",
        "X_WGS84",
        "Y_WGS84",
    ]
    for col in cols_numeriques:
        if col in df.columns:
            if df[col].dtype == "object":
                # Remplacement explicite des virgules par des points
                df[col] = df[col].astype(str).str.replace(",", ".")
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 3. Conversion de la date (dayfirst=True pour le format français JJ/MM/AAAA)
    if "Date de la mesure" in df.columns:
        df["Date de la mesure"] = pd.to_datetime(
            df["Date de la mesure"], dayfirst=True, errors="coerce"
        )
        # Supprime les lignes où la date n'a pas pu être lue et trie chronologiquement
        df = df.dropna(subset=["Date de la mesure"]).sort_values(
            "Date de la mesure"
        )

    return df, file_name

# @st.cache_data(show_spinner="Lecture des chroniques...")
# def load_chroniques_auto(uploaded_file):
#     file_name = getattr(uploaded_file, "name", str(uploaded_file))
#     extension = os.path.splitext(file_name)[1].lower()

#     if extension == ".txt":
#         df = _parse_from_bytes(
#             uploaded_file.getvalue(),
#             core.parse_chroniques_raw
#         )

#     elif extension in (".xlsx", ".xls"):
#         df = pd.read_excel(uploaded_file)

#     else:
#         raise ValueError(f"Format non supporté : {extension}")

#     return df, file_name


@st.cache_data(show_spinner="Lecture du fichier Excel ...")
def load_excel(uploaded_file) -> tuple[pd.DataFrame, str]:
    """Charge un fichier Excel de chroniques préparé manuellement et retourne
    le DataFrame ainsi que le nom du fichier. Conservé pour compatibilité —
    load_chroniques() ci-dessous permet de lire chroniques.txt directement,
    sans conversion Excel préalable."""
    df = pd.read_excel(uploaded_file)
    file_name = getattr(uploaded_file, "name", str(uploaded_file))
    return df, file_name


@st.cache_data(show_spinner="Lecture de chroniques.txt (export ADES)...")
def load_chroniques(uploaded_file) -> tuple[pd.DataFrame, str]:
    """Charge chroniques.txt (export ADES brut, pipe-séparé) et retourne un
    DataFrame prêt pour core.parse_multi_piezo_excel(), avec ses colonnes
    d'origine intactes, ainsi que le nom du fichier."""
    file_name = getattr(uploaded_file, "name", str(uploaded_file))
    df = _parse_from_bytes(uploaded_file.getvalue(), core.parse_chroniques_raw)
    return df, file_name


@st.cache_data(show_spinner="Lecture du fichier descriptif...")
def load_descriptif(file_bytes: bytes) -> dict:
    """Parse descriptif.txt à partir de ses octets : coordonnées, nom et code
    masse d'eau brut par point."""
    return _parse_from_bytes(file_bytes, core.parse_descriptif)


@st.cache_data(show_spinner="Lecture de MassesEau.txt...")
def load_masses_eau(file_bytes: bytes) -> dict:
    """Parse MassesEau.txt à partir de ses octets : libellé complet et
    fiable de la masse d'eau par point (voir core.parse_masses_eau)."""
    return _parse_from_bytes(file_bytes, core.parse_masses_eau)