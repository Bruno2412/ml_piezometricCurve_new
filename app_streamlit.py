# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin
"""

import os
import streamlit as st

import piezo_core as core
from data.data_loader import load_excel, load_descriptif
from components import tab_reseau, tab_analyse, tab_carte, tab_twin

st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")
st.title("Expert Piézométrie Pro — Digital Twin")

# ── Barre latérale (Paramètres) ──────────────────────────────────────────
with st.sidebar:
    st.header("Chroniques (3 points — même masse d'eau)")
    uploaded_files = st.file_uploader(
        "Charger fichiers ADES (chronique Excel + descriptif .txt)",
        type=["xlsx", "xls", "txt"],
        accept_multiple_files=True,
    )
    model_name = st.selectbox("Modèle", ["ETS", "ARIMA", "RandomForest", "XGBoost"])
    if model_name == "ETS":
        st.caption("ETS = univarié (chronique cible seule).")
    else:
        st.caption("Exploite les 3 chroniques (covariables).")

    future_years = st.number_input("Années futures", value=5, min_value=1)
    validation_years = st.number_input("Années validation", value=5, min_value=1)
    ci_pct = st.slider("Intervalle de confiance (%)", 50, 99, 68)
    n_bootstraps = st.number_input("Bootstraps (RF/XGB)", value=200, min_value=10)

    st.header("Recharge Maîtrisée")
    thickness = st.number_input("Épaisseur Aquifère (m)", value=10.0)
    Q = st.number_input("Débit injecté (m³/jour)", value=0.0)
    S = st.number_input("Coeff. Emmagasinement (S)", value=0.05, format="%.4f")
    Area = st.number_input("Surface de l'ouvrage (m²)", value=100.0)
    distance = st.number_input("Distance piézo/ouvrage (m)", value=50.0)
    K = st.number_input("Perméabilité K (m/s)", value=0.0001, format="%.6f")

# ── Extraction des fichiers uploadés ─────────────────────────────────────
excel_file, descriptif_file = None, None
for f in uploaded_files or []:
    ext = f.name.rsplit('.', 1)[-1].lower()
    if ext in ('xlsx', 'xls'):
        excel_file = f
    elif ext == 'txt':
        descriptif_file = f

# ── Traitement principal si un fichier Excel est chargé ──────────────────
if excel_file is not None:
    # 1. Chargement du fichier Excel
    try:
        df_raw = load_excel(excel_file)
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier Excel : {e}")
        st.stop()

    # 2. Chargement du descriptif (Upload prioritaire > Fichier Local/Relative)
    coords_dict = {}
    if descriptif_file is not None:
        try:
            coords_dict = load_descriptif(descriptif_file.getvalue())
            st.sidebar.success(f"✓ Descriptif chargé via navigateur ({len(coords_dict)} points)")
        except Exception as e:
            st.sidebar.error(f"Erreur lecture descriptif chargé : {e}")

    if not coords_dict:
        local_default = r"C:\Users\bruno.DESKTOP-I2NE6NI\OneDrive\Bureau\Projet_Courbes_piezo\chroniques_2\ades_export\Descriptif\descriptif.txt"
        relative_default = os.path.join("data", "descriptif.txt")
        
        target = local_default if os.path.exists(local_default) else (relative_default if os.path.exists(relative_default) else None)
        if target:
            try:
                with open(target, "rb") as f:
                    coords_dict = load_descriptif(f.read())
                st.sidebar.success(f"✓ Descriptif chargé automatiquement ({len(coords_dict)} points)")
            except Exception as e:
                st.sidebar.warning(f"Impossible de lire le descriptif par défaut : {e}")
        else:
            st.sidebar.info("Pas de fichier descriptif fourni — la carte sera limitée.")

    # 3. Parsing du fichier Excel
    try:
        source_df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
        st.sidebar.success(f"✓ {len(points)} points détectés" + ("" if has_masse else " (⚠ pas de masse d'eau)"))
    except Exception as e:
        st.sidebar.error(f"Erreur parsing : {e}")
        points = []
        has_masse = False

    # 4. Sélection des points
    if points:
        selection = st.sidebar.multiselect(
            "Points piézométriques (3 minimum)",
            options=points,
            default=points[:min(3, len(points))]
        )

        if len(selection) < 3:
            st.warning(f"Veuillez sélectionner au moins 3 points dans le menu latéral ({len(selection)} actuellement sélectionné(s)).")
        else:
            target_name = st.sidebar.selectbox("Piézomètre à prévoir", selection)

            chronicles = {}
            ok = True
            for i, name in enumerate(selection, start=1):
                sub = source_df.loc[source_df['point'] == name, ['date', 'level']].reset_index(drop=True)
                if len(sub) < 24:
                    st.sidebar.error(f"Point « {name} » : {len(sub)} obs. (min 24).")
                    ok = False
                    break
                masse_vals = source_df.loc[source_df['point'] == name, 'masse_eau']
                chronicles[i] = {
                    'df': sub,
                    'name': name,
                    'masse_eau': masse_vals.iloc[0] if len(masse_vals) else '',
                }

            if ok:
                if has_masse:
                    masses = {c['masse_eau'].strip().lower() for c in chronicles.values()}
                    if len(masses) > 1:
                        st.sidebar.error("Points issus de masses d'eau différentes.")
                        ok = False
                    else:
                        st.sidebar.success(f"✓ Même masse d'eau : {list(chronicles.values())[0]['masse_eau']}")
                else:
                    st.sidebar.warning("Masse d'eau non renseignée — à vérifier")

                # 5. Affichage des Onglets
                tab1, tab2, tab3, tab4 = st.tabs(["Réseau", "Analyse & Prévision", "Carte Piézométrique", "Digital Twin"])
                
                with tab1:
                    tab_reseau.render(chronicles)
                with tab2:
                    tab_analyse.render(chronicles, target_name, model_name, future_years, validation_years, ci_pct, n_bootstraps)
                with tab3:
                    tab_carte.render(chronicles, coords_dict)
                with tab4:
                    tab_twin.render(chronicles, target_name, thickness, Q, S, Area, distance, K)

else:
    st.info("👋 Bienvenue. Veuillez charger un fichier Excel ADES dans le menu latéral pour démarrer l'analyse.")