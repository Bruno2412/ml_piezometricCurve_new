# -*- coding: utf-8 -*-
"""
Created on Wed Sep 23 13:21:10 2026

@author: bruno
"""

# -*- coding: utf-8 -*-

import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth as fb_auth


# ============================================================================
# 1. INITIALISATION FIREBASE ADMIN
# ============================================================================

try:
    cred_dict = dict(st.secrets["firebase_service_account"])

    if firebase_admin._apps:
        app = firebase_admin.get_app()
        print("✓ App Firebase déjà initialisée")
    else:
        cred = credentials.Certificate(cred_dict)
        app = firebase_admin.initialize_app(cred)
        print("✓ App Firebase initialisée")

except Exception as e:
    print(f"✗ Erreur initialisation Firebase : {e}")
    raise SystemExit


# ============================================================================
# 2. EMAIL DU COMPTE À TESTER
# ============================================================================

email = input("Email du compte Firebase à vérifier : ").strip()

if not email:
    print("✗ Aucun email fourni.")
    raise SystemExit


# ============================================================================
# 3. RÉCUPÉRATION DU COMPTE
# ============================================================================

try:
    user = fb_auth.get_user_by_email(email)

except fb_auth.UserNotFoundError:
    print()
    print("✗ Aucun compte Firebase trouvé avec cet email.")
    raise SystemExit

except Exception as e:
    print(f"✗ Erreur lors de la récupération du compte : {e}")
    raise SystemExit


# ============================================================================
# 4. AFFICHAGE DES INFORMATIONS
# ============================================================================

print()
print("=" * 70)
print("COMPTE FIREBASE")
print("=" * 70)

print(f"Email       : {user.email}")
print(f"UID         : {user.uid}")
print(f"Disabled    : {user.disabled}")
print(f"Email vérifié : {user.email_verified}")

print()
print("CUSTOM CLAIMS")
print("-" * 70)

claims = user.custom_claims or {}

if not claims:
    print("⚠ Aucun Custom Claim défini.")
else:
    for key, value in claims.items():
        print(f"{key} = {value}")

print()
print("=" * 70)
print("DIAGNOSTIC")
print("=" * 70)

# ---------------------------------------------------------------------------
# disabled
# ---------------------------------------------------------------------------

if user.disabled:
    print("✗ COMPTE DÉSACTIVÉ")
else:
    print("✓ COMPTE ACTIF")


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------

role = claims.get("role")

if role == "global_master":
    print("✓ ROLE = global_master")

elif role == "company_master":
    print("✓ ROLE = company_master")

elif role == "user":
    print("✓ ROLE = user")

elif role is None:
    print("✗ Aucun rôle défini")

else:
    print(f"⚠ Rôle inconnu : {role}")


# ---------------------------------------------------------------------------
# Informations société
# ---------------------------------------------------------------------------

if role in ("company_master", "user"):

    company_id = claims.get("company_id")
    company_name = claims.get("company_name")

    if company_id:
        print(f"✓ company_id = {company_id}")
    else:
        print("✗ company_id manquant")

    if company_name:
        print(f"✓ company_name = {company_name}")
    else:
        print("✗ company_name manquant")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

pages = claims.get("pages")

if pages is None:
    print("⚠ pages non définies")
else:
    print(f"✓ pages = {pages}")


print()
print("Fin du diagnostic.")