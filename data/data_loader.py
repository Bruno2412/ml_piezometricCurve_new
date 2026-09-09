# -*- coding: utf-8 -*-

"""
Chargements de données mis en cache pour Streamlit.
"""

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