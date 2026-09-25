# -*- coding: utf-8 -*-
"""Onglet « Analyse & Prévision » : détection de fréquence, alignement des
chroniques auxiliaires, validation puis prévision future du modèle
sélectionné."""

import pandas as pd
import streamlit as st
from matplotlib.figure import Figure

from piezo_app.services import piezo_core as core

# Nombre minimal d'observations conservées pour l'entraînement une fois
# la période de validation retirée (même seuil que le chargement des
# chroniques dans app_pages/analyse.py).
MIN_TRAIN_OBS = 24


@st.cache_data(show_spinner=False)
def cached_fit_predict(df_fit, steps, future_dates, model_name, freq, ci_level, n_bootstraps):
    return core.fit_predict(
        df_fit, steps, future_dates, model_name, freq, ci_level, n_bootstraps=n_bootstraps
    )


def _fail(message, exc=None):
    """Affiche l'erreur DANS l'onglet et rend la main (retourne None).

    On n'utilise jamais st.stop() ici : il interrompt tout le script, donc
    les onglets suivants (carte, twin, interprétation) ne seraient plus
    dessinés dès que l'analyse échoue."""
    st.error(message)
    if exc is not None:
        st.exception(exc)
    return None


def render(
    chronicles,
    selection,
    target_name,
    model_name,
    future_years,
    validation_years,
    ci_pct,
    n_bootstraps,
):
    """Retourne `freq` (fréquence détectée) pour être réutilisée par les
    onglets Digital Twin et Interprétation, évitant de la recalculer.
    Retourne None si l'analyse n'a pas pu aboutir (l'erreur est alors
    affichée dans l'onglet)."""

    # Les résultats d'une exécution précédente ne doivent jamais servir à
    # l'onglet Interprétation si celle-ci échoue.
    st.session_state.pop("analysis_raw", None)

    # --- 1. Identification de la chronique cible ---
    if target_name not in selection:
        return _fail(f"❌ Le piézomètre « {target_name} » ne fait pas partie de la sélection.")

    target_idx = selection.index(target_name) + 1
    if target_idx not in chronicles:
        return _fail(
            f"❌ target_idx = {target_idx}, mais chronicles ne contient pas cette clé "
            f"(clés disponibles : {list(chronicles.keys())})"
        )

    try:
        target_df = chronicles[target_idx]["df"].copy()
    except Exception as e:
        return _fail(f"❌ Erreur lors de la récupération de la chronique cible : {e}", e)

    # --- 2. Détection de la fréquence ---
    try:
        freq = core.detect_frequency(target_df["date"])
    except Exception as e:
        return _fail(f"❌ Erreur dans detect_frequency() : {e}", e)

    # --- 3. Construction du DataFrame merged ---
    try:
        merged = target_df.copy()
        
        expected_indices = set(range(1, len(selection) + 1))
        available_indices = set(chronicles.keys())
        
        missing_aux = sorted(
            expected_indices - available_indices - {target_idx}
        )
        
        if missing_aux:
            missing_names = [
                selection[i - 1]
                for i in missing_aux
                if 1 <= i <= len(selection)
            ]
        
            st.warning(
                "⚠️ Certaines chroniques auxiliaires sont absentes "
                f"et seront ignorées : {', '.join(missing_names)}."
            )
        
        j = 1
        for i in sorted(chronicles):
            if i == target_idx:
                continue
            merged[f"level_aux{j}"] = core.align_chronicle(chronicles[i]["df"], merged["date"])
            j += 1
    except Exception as e:
        return _fail(f"❌ Erreur lors de la construction de merged : {e}", e)

    # --- 4. Nombre de pas pour la validation ---
    try:
        v_steps = core.future_steps(freq, validation_years)
    except Exception as e:
        return _fail(f"❌ Erreur dans future_steps() : {e}", e)

    # --- 5. Vérification de la période de validation ---
    if v_steps <= 0:
        return _fail(f"❌ Nombre de pas de validation invalide : {v_steps}")

    if v_steps >= len(merged):
        return _fail(
            f"Période de validation trop grande "
            f"({len(merged)} observations disponibles, {v_steps} demandées)."
        )

    n_train = len(merged) - v_steps
    if n_train < MIN_TRAIN_OBS:
        return _fail(
            f"Période de validation trop grande : il ne resterait que {n_train} "
            f"observations pour l'entraînement (minimum {MIN_TRAIN_OBS}). "
            f"Réduisez le nombre d'années de validation."
        )

    # --- 6. Séparation entraînement / validation ---
    try:
        df_train = merged.iloc[:-v_steps].copy()
        df_val = merged.iloc[-v_steps:].copy()
    except Exception as e:
        return _fail(f"❌ Erreur lors de la séparation train / validation : {e}", e)

    # --- 7. Intervalle de confiance ---
    ci_level = (100 - ci_pct) / 200.0

    # --- 8. Fit + predict sur la période de validation ---
    try:
        with st.spinner("Calcul de la validation en cours…"):
            p_val, lo_v, hi_v = cached_fit_predict(
                df_train, v_steps, df_val["date"], model_name, freq, ci_level, n_bootstraps
            )
    except Exception as e:
        return _fail(f"❌ Erreur dans fit_predict() pendant la validation : {e}", e)

    # --- 9. Prévisions futures : dates ---
    try:
        fut_s = core.future_steps(freq, future_years)
        fut_dates = pd.date_range(merged["date"].max(), periods=fut_s + 1, freq=freq)[1:]
    except Exception as e:
        return _fail(f"❌ Erreur lors de la construction des dates futures : {e}", e)

    # --- 10. Fit + predict sur la période future ---
    try:
        with st.spinner("Calcul des prévisions futures en cours…"):
            p_fut, lo_f, hi_f = cached_fit_predict(
                merged, fut_s, pd.Series(fut_dates), model_name, freq, ci_level, n_bootstraps
            )
    except Exception as e:
        return _fail(f"❌ Erreur dans fit_predict() pour les prévisions futures : {e}", e)

    # --- Résultats bruts pour l'onglet Interprétation (synthèse par l'IA) ---
    st.session_state["analysis_raw"] = {
        "target": target_name,
        "model_name": model_name,
        "ci_pct": ci_pct,
        "validation_years": validation_years,
        "future_years": future_years,
        "y_train": df_train["level"].to_numpy(dtype=float),
        "y_val": df_val["level"].to_numpy(dtype=float),
        "p_val": p_val,
        "lo_val": lo_v,
        "hi_val": hi_v,
        "fut_dates": fut_dates,
        "p_fut": p_fut,
        "lo_fut": lo_f,
        "hi_fut": hi_f,
    }

    # --- 11. Construction du graphique ---
    # Figure() plutôt que plt.subplots() : pas d'état global pyplot partagé
    # entre les sessions, et plus besoin de plt.close().
    try:
        fig = Figure(figsize=(11, 6))
        ax = fig.subplots()

        ax.plot(df_train["date"], df_train["level"], color="#2c7be5", label="Historique")
        ax.plot(df_val["date"], df_val["level"], color="#f6c90e", label="Réel (contrôle)")
        ax.plot(df_val["date"], p_val, color="#e85d04", linestyle="--", label="Modèle (validation)")
        ax.fill_between(df_val["date"], lo_v, hi_v, alpha=0.15, color="#e85d04")

        ax.plot(fut_dates, p_fut, color="#20c997", linestyle="--", label="Prévision")
        ax.fill_between(fut_dates, lo_f, hi_f, alpha=0.15, color="#20c997")

        ax.set_title(f"Prévision — {target_name} ({model_name})")
        ax.set_xlabel("Date")
        ax.set_ylabel("Niveau piézométrique")
        ax.legend()
        ax.grid(alpha=0.2)
        fig.tight_layout()

        st.pyplot(fig)

    except Exception as e:
        # Le calcul a abouti : on rend quand même freq aux onglets suivants.
        st.error(f"❌ Erreur lors de la construction du graphique : {e}")
        st.exception(e)

    return freq
