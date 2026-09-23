# -*- coding: utf-8 -*-
"""
Created on Wed Sep 23 13:40:27 2026

@author: bruno
"""

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore


st.title("Test Firestore — Projects")

try:
    # Initialisation Firebase
    if not firebase_admin._apps:
        cred_dict = dict(st.secrets["firebase_service_account"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    st.success("✓ Firebase / Firestore initialisé")

    st.write("Lecture de la collection `Projects`...")

    docs = list(db.collection("Projects").stream())

    st.success(f"✓ Lecture réussie — {len(docs)} projet(s) trouvé(s)")

    for doc in docs:
        st.write({
            "id": doc.id,
            "data": doc.to_dict(),
        })

except Exception as e:
    st.error("❌ Erreur Firestore")
    st.exception(e)