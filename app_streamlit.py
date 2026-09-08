# -*- coding: utf-8 -*-
"""
Expert Piézométrie Pro — Digital Twin

Point d'entrée Streamlit. Ce fichier orchestre uniquement :
  - la barre latérale (paramètres),
  - le chargement des données (via data/data_loader.py, mis en cache),
  - la sélection/validation des points,
  - le dispatch vers les 4 onglets (components/tab_*.py).

Toute la logique métier vit dans piezo_core.py, et chaque onglet dans son
propre module — cf. rapport d'audit "fichier Streamlit monolithique".
"""

import streamlit as st

import piezo_core as core
from data.data_loader import load_excel
from components import tab_reseau, tab_analyse, tab_carte, tab_twin


st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")
st.title("Expert Piézométrie Pro — Digital Twin")

with st.sidebar:
    st.header("Chroniques (3 points — même masse d'eau)")
    uploaded_file = st.file_uploader("Charger fichier ADES", type=["xlsx", "xls"])
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

# ── Chargement + sélection des points ───────────────────────────────────
if uploaded_file is None:
    st.info("Chargez un fichier Excel ADES (3 points minimum) pour commencer.")
    st.stop()

df_raw = load_excel(uploaded_file)  # mis en cache : plus de rechargement à chaque interaction

try:
    source_df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
except ValueError as e:
    st.sidebar.error(str(e))
    st.stop()

st.sidebar.success(
    f"✓ {len(points)} points détectés"
    + ("" if has_masse else " (⚠ pas de masse d'eau)")
)

selection = st.sidebar.multiselect(
    "Points piézométriques (3 minimum)",
    options=points,
    default=points[:min(3, len(points))]
)

target_name = st.sidebar.selectbox("Piézomètre à prévoir", selection)

if len(selection) < 3:
    st.sidebar.error(f"Sélectionnez au moins 3 points ({len(selection)} sélectionné(s)).")
    st.stop()

chronicles = {}
ok = True
for i, name in enumerate(selection, start=1):
    sub = source_df.loc[
        source_df['point'] == name, ['date', 'level']
    ].reset_index(drop=True)
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

if ok and has_masse:
    masses = {c['masse_eau'].strip().lower() for c in chronicles.values()}
    if len(masses) > 1:
        st.sidebar.error("Points issus de masses d'eau différentes.")
        ok = False
    else:
        st.sidebar.success(
            f"✓ Même masse d'eau : {list(chronicles.values())[0]['masse_eau']}"
        )
elif ok:
    st.sidebar.warning("Masse d'eau non renseignée — à vérifier manuellement.")

if not ok:
    st.stop()

# ── Onglets ──────────────────────────────────────────────────────────────
tab_reseau_ui, tab_analyse_ui, tab_carte_ui, tab_twin_ui = st.tabs(
    ["🌊 Réseau Piézo", "📊 Analyse", "🗺️ Carte piézométrique", "🌐 Digital Twin"]
)

with tab_reseau_ui:
    tab_reseau.render(chronicles)

with tab_analyse_ui:
    freq = tab_analyse.render(
        chronicles, selection, target_name, model_name,
        future_years, validation_years, ci_pct, n_bootstraps
    )

with tab_carte_ui:
    tab_carte.render(selection, chronicles)

with tab_twin_ui:
    tab_twin.render(chronicles, selection, target_name, freq, ok,
                     Q, S, K, thickness, distance, Area)
