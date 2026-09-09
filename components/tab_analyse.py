# -*- coding: utf-8 -*-
"""Onglet 2 — Analyse : détection de fréquence, alignement des chroniques
auxiliaires, validation puis prévision future du modèle sélectionné."""

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import piezo_core as core

@st.cache_data(show_spinner="Calcul de la validation en cours…")
def cached_fit_predict(df_fit, steps, future_dates, model_name, freq, ci_level, n_bootstraps):
    return core.fit_predict(df_fit, steps, future_dates, model_name, freq, ci_level, n_bootstraps=n_bootstraps)

def render(chronicles, selection, target_name, model_name,
           future_years, validation_years, ci_pct, n_bootstraps):
    """Retourne `freq` (fréquence détectée) pour être réutilisée par
    l'onglet Digital Twin, évitant de la recalculer deux fois."""

    # --- 1. Identification de la chronique cible ---
    try:
        target_idx = selection.index(target_name) + 1
        if target_idx not in chronicles:
            st.error(
                f"❌ target_idx = {target_idx}, "
                f"mais chronicles ne contient pas cette clé "
                f"(clés disponibles : {list(chronicles.keys())})"
            )
            st.stop()
        target_df = chronicles[target_idx]['df'].copy()
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération de la chronique cible : {e}")
        st.exception(e)
        st.stop()

    # --- 2. Détection de la fréquence ---
    try:
        freq = core.detect_frequency(target_df['date'])
        st.write(f"✅ fréquence détectée : {freq}")
    except Exception as e:
        st.error(f"❌ Erreur dans detect_frequency() : {e}")
        st.exception(e)
        st.stop()

    # --- 3. Construction du DataFrame merged ---
    try:
        merged = target_df.copy()
        j = 1
        for i in (1, 2, 3):
            if i == target_idx:
                continue
            if i not in chronicles:
                st.warning(f"⚠️ La chronique chronicles[{i}] n'existe pas.")
                continue
            merged[f'level_aux{j}'] = core.align_chronicle(
                chronicles[i]['df'], merged['date']
            )
            j += 1
    except Exception as e:
        st.error(f"❌ Erreur lors de la construction de merged : {e}")
        st.exception(e)
        st.stop()

    # --- 4. Nombre de pas pour la validation ---
    try:
        v_steps = core.future_steps(freq, validation_years)
    except Exception as e:
        st.error(f"❌ Erreur dans future_steps() : {e}")
        st.exception(e)
        st.stop()

    # --- 5. Vérification de la période de validation ---
    if v_steps <= 0:
        st.error(f"❌ Nombre de pas de validation invalide : {v_steps}")
        st.stop()

    if v_steps >= len(merged):
        st.error(
            f"Période de validation trop grande "
            f"({len(merged)} observations disponibles, {v_steps} demandées)."
        )
        st.stop()

    # --- 6. Séparation entraînement / validation ---
    try:
        df_train = merged.iloc[:-v_steps].copy()
        df_val = merged.iloc[-v_steps:].copy()
    except Exception as e:
        st.error(f"❌ Erreur lors de la séparation train / validation : {e}")
        st.exception(e)
        st.stop()

    # --- 7. Intervalle de confiance ---
    ci_level = (100 - ci_pct) / 200.0

    # --- 8. Fit + predict sur la période de validation ---
    try:
        with st.spinner("Calcul de la validation en cours…"):
            p_val, lo_v, hi_v = cached_fit_predict(
                df_train, v_steps, df_val['date'], model_name, freq, ci_level, n_bootstraps
            )
    except Exception as e:
        st.error(f"❌ Erreur dans fit_predict() pendant la validation : {e}")
        st.exception(e)
        st.stop()

    # --- 9. Prévisions futures : dates ---
    try:
        fut_s = core.future_steps(freq, future_years)
        fut_dates = pd.date_range(
            merged['date'].max(), periods=fut_s + 1, freq=freq
        )[1:]
    except Exception as e:
        st.error(f"❌ Erreur lors de la construction des dates futures : {e}")
        st.exception(e)
        st.stop()

    # --- 10. Fit + predict sur la période future ---
    try:
        with st.spinner("Calcul des prévisions futures en cours…"):
            p_fut, lo_f, hi_f = cached_fit_predict(
                merged, fut_s, pd.Series(fut_dates), model_name, freq, ci_level, n_bootstraps
            )
    except Exception as e:
        st.error(f"❌ Erreur dans fit_predict() pour les prévisions futures : {e}")
        st.exception(e)
        st.stop()

    # --- 11. Construction du graphique ---
    try:
        fig2, ax = plt.subplots(figsize=(11, 6))

        ax.plot(df_train['date'], df_train['level'], color='#2c7be5', label='Historique')
        ax.plot(df_val['date'], df_val['level'], color='#f6c90e', label='Réel (contrôle)')
        ax.plot(
            df_val['date'], p_val, color='#e85d04', linestyle='--',
            label='Modèle (validation)'
        )
        ax.fill_between(df_val['date'], lo_v, hi_v, alpha=0.15, color='#e85d04')

        ax.plot(fut_dates, p_fut, color='#20c997', linestyle='--', label='Prévision')
        ax.fill_between(fut_dates, lo_f, hi_f, alpha=0.15, color='#20c997')

        ax.set_title(f"Prévision — {target_name} ({model_name})")
        ax.set_xlabel("Date")
        ax.set_ylabel("Niveau piézométrique")
        ax.legend()
        ax.grid(alpha=0.2)
        fig2.tight_layout()

        st.pyplot(fig2)
        plt.close(fig2)

    except Exception as e:
        st.error(f"❌ Erreur lors de la construction du graphique : {e}")
        st.exception(e)
        st.stop()

    return freq
