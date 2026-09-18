# -*- coding: utf-8 -*-
"""
Page « Analyse & Prévision » — le cœur de l'application.

Contenu identique à ce qui vivait auparavant directement dans
app_streamlit.py, avant l'introduction de la navigation multi-pages.
"""

import streamlit as st

from piezo_app import piezo_core as core
from piezo_app.auth import permissions
from piezo_app.components import tab_analyse, tab_carte, tab_reseau, tab_twin
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

# ── Paramètres (déplacés depuis la barre latérale vers la page) ──────────
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

# ── Extraction des fichiers uploadés (routage par nom, convention ADES) ──
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

# ── Traitement principal si des chroniques sont chargées ─────────────────
if chroniques_file is not None or excel_file is not None:
    # 1. Chargement des chroniques : export ADES brut en priorité,
    #    sinon Excel déjà préparé (compatibilité ascendante)
    uploaded_chroniques = chroniques_file if chroniques_file is not None else excel_file

    try:
        df_raw, _file_name = load_chroniques_auto(uploaded_chroniques)
    except Exception as e:
        st.error(f"Erreur lors de la lecture des chroniques : {e}")
        st.stop()

    coords_dict = {}
    if descriptif_file is not None:
        try:
            coords_dict = load_descriptif(descriptif_file.getvalue())
            st.success(f"✓ Descriptif chargé ({len(coords_dict)} points)")
        except Exception as e:
            st.error(f"Erreur lecture descriptif : {e}")
    else:
        st.info("Pas de descriptif.txt fourni — la carte sera limitée.")

    masses_eau_dict = {}
    if masses_eau_file is not None:
        try:
            masses_eau_dict = load_masses_eau(masses_eau_file.getvalue())
            st.success(f"✓ MassesEau.txt chargé ({len(masses_eau_dict)} points)")
        except Exception as e:
            st.warning(f"Impossible de lire MassesEau.txt : {e}")

    if masses_eau_dict:
        # Remplace le code brut ('V5#DG240') par le libellé complet et
        # fiable dans les infobulles de la carte.
        for bss_id, label in masses_eau_dict.items():
            if bss_id in coords_dict:
                coords_dict[bss_id]["masse_eau"] = label

    # 3. Parsing des chroniques
    try:
        source_df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
        if masses_eau_dict:
            # chroniques.txt seul ne contient pas la masse d'eau : on
            # l'injecte ici depuis MassesEau.txt, par point (BSS id).
            source_df["masse_eau"] = (
                source_df["point"].map(masses_eau_dict).fillna(source_df["masse_eau"])
            )
            has_masse = source_df["masse_eau"].str.len().gt(0).any()
        st.success(
            f"✓ {len(points)} points détectés" + ("" if has_masse else " (⚠ pas de masse d'eau)")
        )
    except Exception as e:
        st.error(f"Erreur parsing : {e}")
        points = []
        has_masse = False

    # 4. Sélection des points
    if points:
        selection = st.multiselect(
            "Points piézométriques (3 minimum)",
            options=points,
            default=points[: min(3, len(points))],
        )

        if len(selection) < 3:
            st.warning(
                f"Veuillez sélectionner au moins 3 points ({len(selection)} actuellement sélectionné(s))."
            )
        else:
            target_name = st.selectbox("Piézomètre à prévoir", selection)

            chronicles = {}
            ok = True
            for i, name in enumerate(selection, start=1):
                sub = source_df.loc[source_df["point"] == name, ["date", "level"]].reset_index(
                    drop=True
                )
                if len(sub) < 24:
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
                if has_masse:
                    masses = {c["masse_eau"].strip().lower() for c in chronicles.values()}
                    if len(masses) > 1:
                        st.error("Points issus de masses d'eau différentes.")
                        ok = False
                    else:
                        st.success(
                            f"✓ Même masse d'eau : {list(chronicles.values())[0]['masse_eau']}"
                        )
                else:
                    st.warning("Masse d'eau non renseignée — à vérifier")

                # 5. Affichage des Onglets — un utilisateur ne voit que les
                # onglets que son compte autorise (auth.permissions.
                # allowed_pages). Contrairement à un masquage côté client,
                # les onglets non autorisés ne sont ici même pas construits :
                # tab_reseau.render()/tab_analyse.render()/etc. ne sont
                # jamais appelées pour un onglet refusé, ce n'est donc pas
                # qu'une question d'affichage.

                tab_specs = [
                    spec
                    for spec in (
                        ("reseau", "Réseau"),
                        ("analyse", "Analyse & Prévision"),
                        ("carte", "Carte Piézométrique"),
                        ("twin", "Digital Twin"),
                    )
                    if spec[0] in allowed
                ]

                if not tab_specs:
                    st.warning(
                        "Aucun onglet ne vous est accessible. Contactez votre administrateur."
                    )
                else:
                    freq = None
                    tabs = st.tabs([label for _, label in tab_specs])
                    for (key, _label), tab in zip(tab_specs, tabs):
                        with tab:
                            if key == "reseau":
                                tab_reseau.render(chronicles)
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

else:
    st.info(
        "👋 Bienvenue. Charge chroniques.txt (+ descriptif.txt et "
        "MassesEau.txt si disponibles) pour démarrer "
        "l'analyse — ou un Excel de chroniques déjà préparé."
    )