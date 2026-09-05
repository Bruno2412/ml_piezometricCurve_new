# -*- coding: utf-8 -*-
"""
Created on Sat Sep  5 14:28:03 2026

@author: bruno
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="Expert Piézométrie Pro", layout="wide")

st.title("Expert Piézométrie Pro — Digital Twin")

# ── Sidebar (équivalent de ton `sidebar` Tkinter) ──────────────────────
with st.sidebar:
    st.header("Chroniques ADES (3 points)")
    uploaded_file = st.file_uploader("Charger fichier ADES", type=["xlsx", "xls"])

    model = st.selectbox("Modèle", ["ETS", "ARIMA", "RandomForest", "XGBoost"])
    future_years = st.number_input("Années futures", value=5, min_value=1)
    validation_years = st.number_input("Années validation", value=5, min_value=1)

# ── Corps principal ──────────────────────────────────────────────────
if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.write("Aperçu des données :", df.head())

    fig, ax = plt.subplots()
    ax.plot(df.iloc[:, 0], df.iloc[:, 1])
    st.pyplot(fig)
else:
    st.info("Chargez un fichier pour commencer.")