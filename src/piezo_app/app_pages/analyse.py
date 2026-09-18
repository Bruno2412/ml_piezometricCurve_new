# -*- coding: utf-8 -*-
"""
Page « Analyse & Prévision » — le cœur de l'application.
"""

import streamlit as st

from piezo_app import piezo_core as core
from piezo_app.auth import permissions
from piezo_app.components import tab_analyse, tab_carte, tab_chroniques, tab_twin, tab_interpretation
from piezo_app.data.data_loader import load_chroniques_auto, load_descriptif, load_masses_eau

st.title("Piézométrie - Digital Twin - ...")

# ---------------------------------------------------------
# Permissions de l'utilisateur
# ---------------------------------------------------------
allowed = permissions.allowed_pages(st.session_state.user)

if not allowed:
    st.warning(
        "Aucune fonctionnalité ne vous est actuellement accessible. "
        "Contactez votre administrateur pour demander l'attribution "
        "de vos droits."
    )
    st.stop()

# ---------------------------------------------------------
# Onglets métier : ils ne sont construits que si les chroniques ont
# été chargées et validées avec succès (data_ready), et filtrés selon
# les permissions de l'utilisateur (allowed). Tant que ce n'est pas le
# cas, seul "Paramètres" est affiché.
# ---------------------------------------------------------
if "data_ready" not in st.session_state:
    st.session_state.data_ready = False

if st.session_state.data_ready:
    tab_specs = [("parametres", "Paramètres")] + [
        spec
        for spec in (
            ("chroniques", "Chroniques"),
            ("analyse", "Analyse & Prévision"),
            ("carte", "Carte Piézométrique"),
            ("twin", "Digital Twin"),
            ("interpretation", "Interprétation"),
        )
        if spec[0] in allowed
    ]
else:
    tab_specs = [("parametres", "Paramètres")]

tabs = st.tabs([label for _, label in tab_specs])
tab_by_key = dict(zip((key for key, _ in tab_specs), tabs))

# ── Paramètres ────────────────────────────────────────────────────────
with tab_by_key["parametres"]:
    st.header("Chroniques (3 points — même masse d'eau)")
    uploaded_files = st.file_uploader(
        "Charger l'export ADES : chroniques.txt, descriptif.txt, "
        "MassesEau.txt (ou un Excel de chroniques déjà préparé)",
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

# ── Extraction des fichiers uploadés ──────────────────────────────────
excel_file, chroniques_file, descriptif_file, masses_eau_file = None, None, None, None
for f in uploaded_files or []:
    fname = f.name.strip().lower()
    if fname.endswith((".xlsx", ".xls")):
        excel_file = f
    elif fname == "chroniques.txt":
        chroniques_file = f
    elif fname == "descriptif.txt":
        descriptif_file = f
    elif fname == "masseseau.txt":
        masses_eau_file = f

ok = False  # devient True seulement si tout le pipeline réussit

# ── Traitement principal si des chroniques sont chargées ─────────────────
if chroniques_file is not None or excel_file is not None:
    uploaded_chroniques = chroniques_file if chroniques_file is not None else excel_file

    try:
        df_raw, _file_name = load_chroniques_auto(uploaded_chroniques)
    except Exception as e:
        with tab_by_key["parametres"]:
            st.error(f"Erreur lors de la lecture des chroniques : {e}")
        df_raw = None

    if df_raw is not None:
        coords_dict = {}
        if descriptif_file is not None:
            try:
                coords_dict = load_descriptif(descriptif_file.getvalue())
                with tab_by_key["parametres"]:
                    st.success(f"✓ Descriptif chargé ({len(coords_dict)} points)")
            except Exception as e:
                with tab_by_key["parametres"]:
                    st.error(f"Erreur lecture descriptif : {e}")
        else:
            with tab_by_key["parametres"]:
                st.info("Pas de descriptif.txt fourni — la carte sera limitée.")

        masses_eau_dict = {}
        if masses_eau_file is not None:
            try:
                masses_eau_dict = load_masses_eau(masses_eau_file.getvalue())
                with tab_by_key["parametres"]:
                    st.success(f"✓ MassesEau.txt chargé ({len(masses_eau_dict)} points)")
            except Exception as e:
                with tab_by_key["parametres"]:
                    st.warning(f"Impossible de lire MassesEau.txt : {e}")

        if masses_eau_dict:
            for bss_id, label in masses_eau_dict.items():
                if bss_id in coords_dict:
                    coords_dict[bss_id]["masse_eau"] = label

        # Parsing des chroniques
        try:
            source_df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
            if masses_eau_dict:
                source_df["masse_eau"] = (
                    source_df["point"].map(masses_eau_dict).fillna(source_df["masse_eau"])
                )
                has_masse = source_df["masse_eau"].str.len().gt(0).any()
            with tab_by_key["parametres"]:
                st.success(
                    f"✓ {len(points)} points détectés"
                    + ("" if has_masse else " (⚠ pas de masse d'eau)")
                )
        except Exception as e:
            with tab_by_key["parametres"]:
                st.error(f"Erreur parsing : {e}")
            points = []
            has_masse = False

        # Sélection des points
        if points:
            with tab_by_key["parametres"]:
                selection = st.multiselect(
                    "Points piézométriques (3 minimum)",
                    options=points,
                    default=points[: min(3, len(points))],
                )
                if len(selection) < 3:
                    st.warning(
                        f"Veuillez sélectionner au moins 3 points "
                        f"({len(selection)} actuellement sélectionné(s))."
                    )

            if len(selection) >= 3:
                with tab_by_key["parametres"]:
                    target_name = st.selectbox("Piézomètre à prévoir", selection)

                chronicles = {}
                ok = True
                for i, name in enumerate(selection, start=1):
                    sub = source_df.loc[
                        source_df["point"] == name, ["date", "level"]
                    ].reset_index(drop=True)
                    if len(sub) < 24:
                        with tab_by_key["parametres"]:
                            st.error(f"Point « {name} » : {len(sub)} obs. (min 24).")
                        ok = False
                        break
                    masse_vals = source_df.loc[source_df["point"] == name, "masse_eau"]
                    chronicles[i] = {
                        "df": sub,
                        "name": name,
                        "masse_eau": masse_vals.iloc[0] if len(masse_vals) else "",
                    }

                if ok:
                    with tab_by_key["parametres"]:
                        if has_masse:
                            masses = {c["masse_eau"].strip().lower() for c in chronicles.values()}
                            if len(masses) > 1:
                                st.error("Points issus de masses d'eau différentes.")
                                ok = False
                            else:
                                st.success(
                                    f"✓ Même masse d'eau : "
                                    f"{list(chronicles.values())[0]['masse_eau']}"
                                )
                        else:
                            st.warning("Masse d'eau non renseignée — à vérifier")
else:
    with tab_by_key["parametres"]:
        st.info(
            "👋 Bienvenue. Charge chroniques.txt (+ descriptif.txt et "
            "MassesEau.txt si disponibles) pour démarrer "
            "l'analyse — ou un Excel de chroniques déjà préparé."
        )

# ---------------------------------------------------------
# Mise à jour de l'état "données prêtes" — si l'état change par
# rapport au run précédent, on force un rerun pour que la barre
# d'onglets se reconstruise immédiatement avec les bons onglets.
# ---------------------------------------------------------
previous_ready = st.session_state.data_ready
st.session_state.data_ready = ok

if ok != previous_ready:
    st.rerun()

# ── Affichage du contenu des onglets métier ───────────────────────────
if ok:
    freq = None
    for key, _label in tab_specs:
        if key == "parametres":
            continue
        with tab_by_key[key]:
            if key == "chroniques":
                tab_chroniques.render(chronicles)
            elif key == "analyse":
                freq = tab_analyse.render(
                    chronicles=chronicles,
                    selection=selection,
                    target_name=target_name,
                    model_name=model_name,
                    future_years=future_years,
                    validation_years=validation_years,
                    ci_pct=ci_pct,
                    n_bootstraps=n_bootstraps,
                )
            elif key == "carte":
                tab_carte.render(
                    selection=selection,
                    chronicles=chronicles,
                    coords_dict=coords_dict,
                )
            elif key == "twin":
                tab_twin.render(
                    chronicles=chronicles,
                    selection=selection,
                    target_name=target_name,
                    freq=freq,
                    ok=ok,
                    Q=Q,
                    S=S,
                    K=K,
                    thickness=thickness,
                    distance=distance,
                    Area=Area,
                )
            elif key == "interpretation":
                tab_interpretation.render(
                        
                    )