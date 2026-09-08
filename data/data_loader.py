# -*- coding: utf-8 -*-
"""
Chargements de données mis en cache pour Streamlit.

Corrige les points majeurs du rapport d'audit :
- "Chargement de données au niveau module" (app_streamlit.py:39)
- "Fonctions de chargement sans cache" (pd.read_excel / pd.read_csv)

Chaque fonction de lecture est décorée avec @st.cache_data : Streamlit
la ré-exécute uniquement quand le contenu du fichier change, et non à
chaque rerun (clic sur un widget, changement de slider, etc.).
"""

import os
import tempfile

import pandas as pd
import streamlit as st

import piezo_core as core


@st.cache_data(show_spinner="Lecture du fichier Excel ADES…")
def load_excel(uploaded_file) -> pd.DataFrame:
    """Charge un fichier Excel ADES en DataFrame brut.
    Mis en cache par le contenu du fichier uploadé (Streamlit hash le flux
    d'octets d'un UploadedFile), donc un même fichier n'est relu qu'une fois
    même si l'utilisateur change un slider ailleurs dans l'app."""
    return pd.read_excel(uploaded_file)


@st.cache_data(show_spinner="Lecture du fichier descriptif ADES…")
def load_descriptif(file_bytes: bytes) -> dict:
    """Parse le fichier descriptif ADES (pipe-séparé) à partir de ses octets.
    On met en cache sur `file_bytes` plutôt que sur un chemin temporaire :
    tempfile.NamedTemporaryFile génère un nom différent à chaque exécution,
    ce qui invaliderait le cache à chaque rerun si on cachait sur le chemin."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        return core.parse_descriptif(tmp_path)
    finally:
        os.remove(tmp_path)
