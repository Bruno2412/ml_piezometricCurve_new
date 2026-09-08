# -*- coding: utf-8 -*-
"""Onglet 4 — Digital Twin : simulation Theis interactive + tableau de bord."""

import matplotlib.pyplot as plt
import streamlit as st

import piezo_core as core


def render(chronicles, selection, target_name, freq, ok,
           Q, S, K, thickness, distance, Area):
    st.subheader("Jumeau numérique aquifère")

    if not ok:
        st.info("Chargez et sélectionnez les 3 chroniques pour activer le Digital Twin.")
        return

    target_idx_dt = selection.index(target_name) + 1
    df_dt = chronicles[target_idx_dt]['df']
    niveau_base = df_dt['level'].iloc[-1]

    col_sliders, col_plot = st.columns([1, 2])

    with col_sliders:
        st.markdown("**Paramètres de simulation**")
        Q_dt = st.slider("Q — Débit injecté (m³/j)", 0.0, 500.0, float(Q), step=1.0)
        S_dt = st.slider(
            "S — Coeff. emmagasinement", 0.0001, 0.3, float(S),
            step=0.0001, format="%.4f"
        )
        K_dt = st.slider(
            "K — Perméabilité (m/s)", 1e-7, 1e-2, float(K),
            step=1e-6, format="%.2e"
        )
        dist_dt = st.slider(
            "r — Distance piézo/ouvrage (m)", 1.0, 500.0, float(distance), step=1.0
        )
        thick_dt = st.slider(
            "b — Épaisseur aquifère (m)", 1.0, 100.0, float(thickness), step=0.5
        )
        t_max_dt = st.slider(
            "t — Durée simulation (jours)", 1, 3650, 180, step=1
        )

    with col_plot:
        t_arr, impact_spatial, impact_total = core.response_curve_data(
            Q_dt, S_dt, K_dt, thick_dt, dist_dt, Area, t_max_dt, niveau_base
        )

        fig_resp, ax_resp = plt.subplots(figsize=(7, 4))
        ax_resp.plot(t_arr, impact_spatial, color='#0d6efd', label='Impact Theis (spatial)')
        ax_resp.plot(
            t_arr, impact_total, color='#20c997', linestyle='--',
            label='Impact total (spatial + volumétrique)'
        )
        ax_resp.axhline(niveau_base, color='#888', linestyle=':', label='Niveau de base')
        ax_resp.set_title(
            f"Réponse piézométrique — Q={Q_dt:.0f} m³/j  "
            f"K={K_dt:.1e} m/s  r={dist_dt:.0f} m",
            fontsize=9
        )
        ax_resp.set_xlabel("Temps (jours)")
        ax_resp.set_ylabel("Niveau NGF (m)")
        ax_resp.legend(fontsize=8)
        ax_resp.grid(alpha=0.3)
        st.pyplot(fig_resp)
        plt.close(fig_resp)

    st.markdown("---")
    st.markdown("**Carte 2D — zones d'influence**")
    fig_map = core.draw_nappe_2d_figure(
        Q_dt, S_dt, K_dt, thick_dt, dist_dt, t_max_dt, Area, niveau_base
    )
    st.pyplot(fig_map)
    plt.close(fig_map)

    st.markdown("---")
    st.markdown("**Tableau de bord**")
    indicators = core.compute_dashboard_indicators(
        df_dt, freq, Q_dt, S_dt, K_dt, thick_dt, dist_dt, Area
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Niveau actuel", f"{indicators['niveau_actuel']:.2f} m")
    c2.metric("Variation 30j", f"{indicators['variation_30j']:+.3f} m")
    c3.metric("Tendance", f"{indicators['tendance']:+.3f} m/an")
    c4.metric("Impact inj. (6 mois)", f"{indicators['impact_inj']:+.3f} m")
    c5.metric("Risque nappe", f"{indicators['risque']:.0f} %")
    c6.metric("Temps recharge", f"{indicators['temps_rech']:.0f} j")
