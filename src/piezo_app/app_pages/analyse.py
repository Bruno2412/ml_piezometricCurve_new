# -*- coding: utf-8 -*-
"""
Page « Analyse & Prévision » — le cœur de l'application.
"""

import streamlit as st

# ---------------------------------------------------------
# Imports de l'application — protégés pour que la cause d'un échec
# (module déplacé, fichier manquant, erreur de syntaxe dans un onglet)
# s'affiche à l'écran au lieu d'une page blanche.
#
# piezo_core doit être importé depuis le MÊME chemin dans tous les
# fichiers (analyse.py, tab_*.py, carto.py, rapport.py) : sinon Python
# charge deux modules distincts, ou l'un des imports échoue.
# ---------------------------------------------------------
try:
    from piezo_app.services import piezo_core as core
    from piezo_app.auth import permissions
    from piezo_app.components import (
        tab_analyse,
        tab_carte,
        tab_chroniques,
        tab_interpretation,
        tab_twin,
    )
    from piezo_app.data.data_loader import (
        load_chroniques_auto,
        load_descriptif,
        load_masses_eau,
    )
except Exception as exc:
    st.error("Échec d'import d'un module de l'application.")
    st.exception(exc)
    st.stop()


def _safe(label, fn, *args, **kwargs):
    """Exécute le rendu d'un onglet ; en cas d'exception, affiche l'erreur
    dans cet onglet sans empêcher le rendu des suivants. Retourne le
    résultat de fn, ou None en cas d'erreur."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        st.error(f"L'onglet « {label} » a rencontré une erreur.")
        st.exception(exc)
        return None


st.title("Piézométrie — Digital Twin")

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
#
# Clés, libellés et ordre viennent de permissions.PAGE_KEYS / PAGE_LABELS
# (source unique de vérité) : un nouvel onglet s'y déclare une seule fois.
# ---------------------------------------------------------
if "data_ready" not in st.session_state:
    st.session_state.data_ready = False

tab_specs = [("parametres", "Paramètres")]

if st.session_state.data_ready:
    tab_specs += [
        (key, permissions.PAGE_LABELS[key])
        for key in permissions.PAGE_KEYS
        if key in allowed
    ]

tabs = st.tabs([label for _, label in tab_specs])
tab_by_key = dict(zip((key for key, _ in tab_specs), tabs))

# ── Paramètres ────────────────────────────────────────────────────────
# Chaque widget a une key explicite : son état ne dépend plus de sa
# position dans la page, ce qui évite les réinitialisations lorsque la
# barre d'onglets est reconstruite (data_ready qui change).
with tab_by_key["parametres"]:
    st.header("Chroniques (3 points — même masse d'eau)")
    uploaded_files = st.file_uploader(
        "Charger l'export ADES : chroniques.txt, descriptif.txt, "
        "MassesEau.txt (ou un Excel de chroniques déjà préparé)",
        type=["xlsx", "xls", "txt"],
        accept_multiple_files=True,
        key="upl_files",
    )
    model_name = st.selectbox(
        "Modèle", ["ETS", "ARIMA", "RandomForest", "XGBoost"], key="model_name"
    )
    if model_name == "ETS":
        st.caption("ETS = univarié (chronique cible seule).")
    else:
        st.caption("Exploite les 3 chroniques (covariables).")

    future_years = st.number_input(
        "Années futures", value=5, min_value=1, key="future_years"
    )
    validation_years = st.number_input(
        "Années validation", value=5, min_value=1, key="validation_years"
    )
    ci_pct = st.slider("Intervalle de confiance (%)", 50, 99, 68, key="ci_pct")
    n_bootstraps = st.number_input(
        "Bootstraps (RF/XGB)", value=200, min_value=10, key="n_bootstraps"
    )

    st.header("Recharge Maîtrisée")
    thickness = st.number_input("Épaisseur Aquifère (m)", value=10.0, key="thickness")
    Q = st.number_input("Débit injecté (m³/jour)", value=0.0, key="Q")
    S = st.number_input("Coeff. Emmagasinement (S)", value=0.05, format="%.4f", key="S")
    Area = st.number_input("Surface de l'ouvrage (m²)", value=100.0, key="Area")
    distance = st.number_input("Distance piézo/ouvrage (m)", value=50.0, key="distance")
    K = st.number_input("Perméabilité K (m/s)", value=0.0001, format="%.6f", key="K")

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
                    "Points piézométriques (3 points)",
                    options=points,
                    default=points[: min(3, len(points))],
                    max_selections=3,
                    key="selection",
                )
                if len(selection) < 3:
                    st.warning(
                        f"Veuillez sélectionner 3 points "
                        f"({len(selection)} actuellement sélectionné(s))."
                    )

            if len(selection) >= 3:
                with tab_by_key["parametres"]:
                    target_name = st.selectbox(
                        "Piézomètre à prévoir", selection, key="target_name"
                    )

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

# ---------------------------------------------------------
# Partage avec la page « Cartographie » (app_pages/carto.py), qui s'exécute
# indépendamment de cette page : sans cet enregistrement dans la session,
# elle n'aurait aucun moyen de connaître les chroniques et coordonnées
# chargées ici. Le partage lui-même est décidé par la case à cocher de
# l'onglet « Carte Piézométrique » (voir components/tab_carte.py,
# clé "share_with_cartography") : décochée par défaut, donc rien n'est
# partagé tant que l'utilisateur ne l'a pas explicitement demandé.
# ---------------------------------------------------------
# share_with_cartography = st.session_state.get(
#     "share_with_cartography", 
#     False)

# if ok and share_with_cartography:
#     st.session_state["shared_map_data"] = {
#         "chronicles": chronicles,
#         "coords_dict": coords_dict,
#         "selection": selection,
#         "target_name": target_name,
#     }
# elif not share_with_cartography:
#     # Si l'utilisateur décoche (ou n'a jamais coché), aucune donnée d'une
#     # précédente analyse ne doit rester accessible depuis la page
#     # Cartographie : on retire ce qui aurait pu y être laissé.
#     st.session_state.pop("shared_map_data", None)

# ── Affichage du contenu des onglets métier ───────────────────────────
# Chaque onglet est isolé par _safe : une erreur dans l'un n'empêche plus
# le rendu des suivants. L'ordre d'exécution suit permissions.PAGE_KEYS,
# donc "analyse" (qui produit freq) s'exécute toujours avant "twin" et
# "interpretation" (qui le consomment).
if ok:
    freq = None

    for key, label in tab_specs:
        if key == "parametres":
            continue

        with tab_by_key[key]:
            if key == "chroniques":
                _safe(label, tab_chroniques.render, chronicles)

            elif key == "analyse":
                freq = _safe(
                    label,
                    tab_analyse.render,
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
                _safe(
                    label,
                    tab_carte.render,
                    selection=selection,
                    chronicles=chronicles,
                    coords_dict=coords_dict,
                )
                
                share_with_cartography = st.session_state.get(
                    "share_with_cartography",
                    False,
                )
                if ok and share_with_cartography:
                    st.session_state["shared_map_data"] = {
                        "chronicles": chronicles,
                        "coords_dict": coords_dict,
                        "selection": selection,
                        "target_name": target_name,
                    }
                else:
                    st.session_state.pop(
                        "shared_map_data",
                        None,
                    )
                
                
                
                
                

            elif key in ("twin", "interpretation"):
                if freq is None:
                    st.info(
                        "Cet onglet nécessite le résultat de « "
                        f"{permissions.PAGE_LABELS['analyse']} » : "
                        "vérifiez que cet onglet s'est exécuté sans erreur."
                    )
                    continue

                if key == "twin":
                    _safe(
                        label,
                        tab_twin.render,
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
                    _safe(
                        label,
                        tab_interpretation.render,
                        chronicles=chronicles,
                        selection=selection,
                        target_name=target_name,
                        freq=freq,
                        coords_dict=coords_dict,
                        Q=Q,
                        S=S,
                        K=K,
                        thickness=thickness,
                        distance=distance,
                        Area=Area,
                    )
