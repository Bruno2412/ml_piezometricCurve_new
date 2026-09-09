# -*- coding: utf-8 -*-

"""
Chargements de données mis en cache pour Streamlit.
"""

import os
import tempfile

import pandas as pd
import streamlit as st

import piezo_core as core


@st.cache_data(show_spinner="Lecture du fichier Excel ADES…")
def load_excel(uploaded_file) -> pd.DataFrame:
    """
    Charge le fichier Excel des chroniques.
    """

    return pd.read_excel(uploaded_file)


@st.cache_data(show_spinner="Lecture du fichier descriptif ADES…")
def load_descriptif(file_bytes: bytes) -> dict:
    """
    Parse le fichier descriptif ADES à partir de ses octets.

    Le fichier est temporairement écrit sur disque car
    core.parse_descriptif() attend actuellement un chemin de fichier.
    """

    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".txt",
        delete=False
    ) as tmp:

        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:

        return core.parse_descriptif(tmp_path)

    finally:

        os.remove(tmp_path)