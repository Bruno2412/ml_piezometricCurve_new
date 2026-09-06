import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import piezo_core as core
import folium
from streamlit_folium import st_folium
import base64


st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")
st.title("Expert Piézométrie Pro — Digital Twin")

with st.sidebar:
    st.header("Chroniques ADES (3 points — même masse d'eau)")
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

    st.header("Injection Maîtrisée")
    thickness = st.number_input("Épaisseur Aquifère (m)", value=10.0)
    Q = st.number_input("Débit injecté (m³/jour)", value=0.0)
    S = st.number_input("Coeff. Emmagasinement (S)", value=0.05, format="%.4f")
    Area = st.number_input("Surface de l'ouvrage (m²)", value=100.0)
    distance = st.number_input("Distance piézo/ouvrage (m)", value=50.0)
    K = st.number_input("Perméabilité K (m/s)", value=0.0001, format="%.6f")

# ── Chargement + sélection des 3 points ─────────────────────────────────
if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file)
    try:
        source_df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
        st.sidebar.success(f"✓ {len(points)} points détectés"
                           + ("" if has_masse else " (⚠ pas de masse d'eau)"))

        col1, col2, col3 = st.sidebar.columns(3)
        p1 = col1.selectbox("Point 1", points, index=0)
        p2 = col2.selectbox("Point 2", points, index=min(1, len(points)-1))
        p3 = col3.selectbox("Point 3", points, index=min(2, len(points)-1))
        selection = [p1, p2, p3]

        target_name = st.sidebar.selectbox("Piézomètre à prévoir", selection)

        if len(set(selection)) < 3:
            st.sidebar.error("Sélectionnez 3 points distincts.")
        else:
            chronicles = {}
            ok = True
            for i, name in enumerate(selection, start=1):
                sub = source_df.loc[source_df['point'] == name, ['date', 'level']].reset_index(drop=True)
                if len(sub) < 24:
                    st.sidebar.error(f"Point « {name} » : {len(sub)} obs. (min 24).")
                    ok = False
                    break
                masse_vals = source_df.loc[source_df['point'] == name, 'masse_eau']
                chronicles[i] = {'df': sub, 'name': name,
                                 'masse_eau': masse_vals.iloc[0] if len(masse_vals) else ''}

            if ok:
                # Contrôle masse d'eau
                if has_masse:
                    masses = {c['masse_eau'].strip().lower() for c in chronicles.values()}
                    if len(masses) > 1:
                        st.sidebar.error("Points issus de masses d'eau différentes.")
                        ok = False
                    else:
                        st.sidebar.success(f"✓ Même masse d'eau : {list(chronicles.values())[0]['masse_eau']}")
                else:
                    st.sidebar.warning("Masse d'eau non renseignée — à vérifier manuellement.")

            if ok:
                # ── Onglets ──────────────────────────────────────────────
                #tab_reseau, tab_analyse = st.tabs(["🌊 Réseau Piézo", "📊 Analyse"])
                tab_reseau, tab_analyse, tab_carte, tab_twin = st.tabs(
                ["🌊 Réseau Piézo", "📊 Analyse", "🗺️ Carte piézométrique", "🌐 Digital Twin"])

                with tab_reseau:
                    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
                    colors = {1: '#2c7be5', 2: '#e85d04', 3: '#20c997'}
                    for i, c in chronicles.items():
                        ax1.plot(c['df']['date'], c['df']['level'], color=colors[i], label=c['name'])
                        z = (c['df']['level'] - c['df']['level'].mean()) / (c['df']['level'].std() or 1)
                        ax2.plot(c['df']['date'], z, color=colors[i], label=c['name'])
                    ax1.set_title("Chroniques brutes"); ax1.legend(); ax1.grid(alpha=0.25)
                    ax2.set_title("Comparaison normalisée (z-score)"); ax2.legend(); ax2.grid(alpha=0.25)
                    fig.tight_layout()
                    st.pyplot(fig)

                    corr, n_pts = core.compute_correlation_matrix(chronicles)
                    if corr is not None:
                        names = corr.columns.tolist()
                        st.write(f"**Corrélation (Pearson, base mensuelle, n={n_pts} mois communs)**")
                        st.dataframe(corr.style.format("{:.2f}"))

                with tab_analyse:
                    target_idx = selection.index(target_name) + 1
                    target_df = chronicles[target_idx]['df'].copy()
                    freq = core.detect_frequency(target_df['date'])
                    merged = target_df.copy()
                    j = 1
                    for i in (1, 2, 3):
                        if i == target_idx:
                            continue
                        merged[f'level_aux{j}'] = core.align_chronicle(chronicles[i]['df'], merged['date'])
                        j += 1

                    v_steps = core.future_steps(freq, validation_years)
                    if v_steps >= len(merged):
                        st.error(f"Période de validation trop grande ({len(merged)} obs. disponibles).")
                    else:
                        df_train = merged.iloc[:-v_steps].copy()
                        df_val = merged.iloc[-v_steps:].copy()
                        ci_level = (100 - ci_pct) / 200.0

                        with st.spinner("Calcul en cours…"):
                            p_val, lo_v, hi_v = core.fit_predict(
                                df_train, v_steps, df_val['date'], model_name, freq, ci_level,
                                n_bootstraps=n_bootstraps)

                            fut_s = core.future_steps(freq, future_years)
                            fut_dates = pd.date_range(merged['date'].max(), periods=fut_s + 1, freq=freq)[1:]
                            p_fut, lo_f, hi_f = core.fit_predict(
                                merged, fut_s, pd.Series(fut_dates), model_name, freq, ci_level,
                                n_bootstraps=n_bootstraps)

                        fig2, ax = plt.subplots(figsize=(11, 6))
                        ax.plot(df_train['date'], df_train['level'], color='#2c7be5', label='Historique')
                        ax.plot(df_val['date'], df_val['level'], color='#f6c90e', label='Réel (contrôle)')
                        ax.plot(df_val['date'], p_val, color='#e85d04', linestyle='--', label='Modèle (validation)')
                        ax.fill_between(df_val['date'], lo_v, hi_v, alpha=0.15, color='#e85d04')
                        ax.plot(fut_dates, p_fut, color='#20c997', linestyle='--', label='Prévision')
                        ax.fill_between(fut_dates, lo_f, hi_f, alpha=0.15, color='#20c997')
                        ax.set_title(f"Prévision — {target_name} ({model_name})")
                        ax.legend(); ax.grid(alpha=0.2)
                        st.pyplot(fig2)
                
                with tab_carte:
                    st.subheader("Carte piézométrique évolutive")
                
                    descriptif_path = st.text_input(
                        "Chemin du fichier descriptif ADES",
                        value=r"C:\Users\bruno.DESKTOP-I2NE6NI\OneDrive\Bureau\Projet_Courbes_piezo\chroniques_2\ades_export\Descriptif\descriptif.txt"
                    )
                
                    try:
                        coords_dict = core.parse_descriptif(descriptif_path)
                    except Exception as e:
                        st.error(f"Impossible de lire le fichier descriptif : {e}")
                        coords_dict = {}
                
                    st.write("len coords_dict:", len(coords_dict))
                    st.write("TPVW présent ?", 'BSS001TPVW' in coords_dict)
                    if 'BSS001TPVW' in coords_dict:
                        st.write("Valeur stockée :", coords_dict['BSS001TPVW'])
                
                    missing = [name for name in selection if name.strip() not in coords_dict]
                    available = [name for name in selection if name.strip() in coords_dict]
                
                    if missing:
                        st.warning(f"Coordonnées introuvables pour : {missing} — "
                                  "carte affichée avec les points disponibles seulement.")
                
                    if len(available) < 3:
                        st.error(
                            f"Seuls {len(available)} point(s) sur {len(selection)} ont des coordonnées "
                            "connues dans le fichier descriptif — au moins 3 sont nécessaires pour "
                            "interpoler une surface piézométrique."
                        )
                    else:
                        coords = [coords_dict[name] for name in available]
                        idx_available = [selection.index(name) + 1 for name in available]
                
                        min_date = max(chronicles[i]['df']['date'].min() for i in idx_available)
                        max_date = min(chronicles[i]['df']['date'].max() for i in idx_available)
                
                        if min_date >= max_date:
                            st.error("Aucune période commune entre les points disponibles.")
                        else:
                            selected_date = st.slider(
                                "Date de la carte",
                                min_value=min_date.to_pydatetime(),
                                max_value=max_date.to_pydatetime(),
                                value=max_date.to_pydatetime(),
                                format="DD/MM/YYYY"
                            )
                
                            values = [core.value_at_date(chronicles[i]['df'], selected_date) for i in idx_available]
                            GLon, GLat, GZ = core.build_piezo_surface(coords, values)
                
                            center_lat = sum(c['lat'] for c in coords) / len(coords)
                            center_lon = sum(c['lon'] for c in coords) / len(coords)
                
                            m = folium.Map(location=[center_lat, center_lon], zoom_start=13,
                                          tiles="OpenStreetMap")
                
                            png_bytes, bounds = core.surface_to_png_overlay(GLon, GLat, GZ)
                            img_data = f"data:image/png;base64,{base64.b64encode(png_bytes).decode()}"
                            folium.raster_layers.ImageOverlay(
                                image=img_data,
                                bounds=bounds,
                                opacity=0.7,
                                interactive=False,
                            ).add_to(m)
                
                            for c, name, val in zip(coords, available, values):
                                folium.Marker(
                                    location=[c['lat'], c['lon']],
                                    popup=f"<b>{name}</b><br>Niveau : {val:.2f} m<br>Masse d'eau : {c['masse_eau']}",
                                    tooltip=f"{name} — {val:.2f} m",
                                    icon=folium.Icon(color='orange', icon='tint', prefix='fa'),
                                ).add_to(m)
                
                            st_folium(m, width=900, height=600, returned_objects=[])
                
                            st.caption(
                                f"⚠️ Interpolation linéaire entre {len(available)} point(s) — la surface "
                                "colorée n'est valide qu'à l'intérieur du polygone formé par les points "
                                "disponibles, et reste une approximation grossière comparée à un krigeage "
                                "sur un réseau plus dense."
                            )
                            
                with tab_twin:
                    st.subheader("Jumeau numérique aquifère")
                
                    if not ok:
                        st.info("Chargez et sélectionnez les 3 chroniques pour activer le Digital Twin.")
                    else:
                        target_idx_dt = selection.index(target_name) + 1
                        df_dt = chronicles[target_idx_dt]['df']
                        niveau_base = df_dt['level'].iloc[-1]
                
                        col_sliders, col_plot = st.columns([1, 2])
                
                        with col_sliders:
                            st.markdown("**Paramètres de simulation**")
                            Q_dt = st.slider("Q — Débit injecté (m³/j)", 0.0, 500.0, float(Q), step=1.0)
                            S_dt = st.slider("S — Coeff. emmagasinement", 0.0001, 0.3, float(S), step=0.0001, format="%.4f")
                            K_dt = st.slider("K — Perméabilité (m/s)", 1e-7, 1e-2, float(K), step=1e-6, format="%.2e")
                            dist_dt = st.slider("r — Distance piézo/ouvrage (m)", 1.0, 500.0, float(distance), step=1.0)
                            thick_dt = st.slider("b — Épaisseur aquifère (m)", 1.0, 100.0, float(thickness), step=0.5)
                            t_max_dt = st.slider("t — Durée simulation (jours)", 1, 3650, 180, step=1)
                
                        with col_plot:
                            t_arr, impact_spatial, impact_total = core.response_curve_data(
                                Q_dt, S_dt, K_dt, thick_dt, dist_dt, Area, t_max_dt, niveau_base)
                
                            fig_resp, ax_resp = plt.subplots(figsize=(7, 4))
                            ax_resp.plot(t_arr, impact_spatial, color='#0d6efd', label='Impact Theis (spatial)')
                            ax_resp.plot(t_arr, impact_total, color='#20c997', linestyle='--',
                                        label='Impact total (spatial + volumétrique)')
                            ax_resp.axhline(niveau_base, color='#888', linestyle=':', label='Niveau de base')
                            ax_resp.set_title(f"Réponse piézométrique — Q={Q_dt:.0f} m³/j  K={K_dt:.1e} m/s  r={dist_dt:.0f} m",
                                             fontsize=9)
                            ax_resp.set_xlabel("Temps (jours)")
                            ax_resp.set_ylabel("Niveau NGF (m)")
                            ax_resp.legend(fontsize=8)
                            ax_resp.grid(alpha=0.3)
                            st.pyplot(fig_resp)
                
                        st.markdown("---")
                        st.markdown("**Carte 2D — zones d'influence**")
                        fig_map = core.draw_nappe_2d_figure(Q_dt, S_dt, K_dt, thick_dt, dist_dt, t_max_dt, Area, niveau_base)
                        st.pyplot(fig_map)
                
                        st.markdown("---")
                        st.markdown("**Tableau de bord**")
                        indicators = core.compute_dashboard_indicators(
                            df_dt, freq, Q_dt, S_dt, K_dt, thick_dt, dist_dt, Area)
                
                        c1, c2, c3, c4, c5, c6 = st.columns(6)
                        c1.metric("Niveau actuel", f"{indicators['niveau_actuel']:.2f} m")
                        c2.metric("Variation 30j", f"{indicators['variation_30j']:+.3f} m")
                        c3.metric("Tendance", f"{indicators['tendance']:+.3f} m/an")
                        c4.metric("Impact inj. (6 mois)", f"{indicators['impact_inj']:+.3f} m")
                        c5.metric("Risque nappe", f"{indicators['risque']:.0f} %")
                        c6.metric("Temps recharge", f"{indicators['temps_rech']:.0f} j")
                            

    except ValueError as e:
        st.sidebar.error(str(e))
else:
    st.info("Chargez un fichier Excel ADES (3 points minimum) pour commencer.")