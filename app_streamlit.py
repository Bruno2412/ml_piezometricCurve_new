import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import piezo_core as core

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
                tab_reseau, tab_analyse = st.tabs(["🌊 Réseau Piézo", "📊 Analyse"])

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

    except ValueError as e:
        st.sidebar.error(str(e))
else:
    st.info("Chargez un fichier Excel ADES (3 points minimum) pour commencer.")