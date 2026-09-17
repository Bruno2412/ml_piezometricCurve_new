# -*- coding: utf-8 -*-
"""
auth/registration.py — Gestion des inscriptions publiques.

Flux :
    1. L'utilisateur crée son compte.
    2. Le compte Firebase est créé désactivé (disabled=True,
       email_verified=False, approved=False).
    3. Le rôle est obligatoirement "user".
    4. Toutes les pages sont désactivées.
    5. Un email de vérification est envoyé à l'utilisateur. Le lien
       pointe vers notre propre appli (handle_code_in_app=True) et
       n'affiche qu'un bouton "Confirmer mon email" : la validation
       Firebase (oobCode) n'est déclenchée qu'au clic, jamais au
       simple chargement de la page — ce qui évite qu'un pré-scan de
       sécurité côté messagerie (ex. Outlook Safe Links) ne consomme
       le lien avant l'utilisateur.
    6. Une fois l'email confirmé, les administrateurs (global_master)
       sont notifiés qu'un compte est prêt à être activé.
    7. Le global_master valide ensuite le compte (activate_user) :
       approved=True, disabled=False, pages autorisées enregistrées.
    8. Un email de confirmation d'activation est envoyé à
       l'utilisateur.
"""

from urllib.parse import quote

import streamlit as st
from firebase_admin import auth as fb_auth
from firebase_admin.auth import ActionCodeSettings

from piezo_app.auth import permissions
from piezo_app.services.email_service import (
    send_account_activation_email,
    send_admin_notification_email,
    send_verification_email,
)


def register_user(
    email: str,
    password: str,
    company_id: str,
    company_name: str,
) -> str:
    """
    Crée un utilisateur depuis l'inscription publique.

    Le rôle est toujours USER.
    L'utilisateur ne peut jamais choisir son rôle.

    Le compte est créé :
        - disabled = True
        - email_verified = False
        - approved = False
        - toutes les pages = False

    Un email de vérification est envoyé en best-effort : un échec
    d'envoi n'empêche pas la création du compte, qui reste de toute
    façon bloqué (disabled=True) jusqu'à validation manuelle par un
    administrateur.
    """

    email = email.strip().lower()
    company_id = company_id.strip()
    company_name = company_name.strip()

    if not email:
        raise ValueError("L'adresse email est obligatoire.")

    if not password:
        raise ValueError("Le mot de passe est obligatoire.")

    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")

    if not company_id:
        raise ValueError("L'identifiant de la société est obligatoire.")

    if not company_name:
        raise ValueError("Le nom de la société est obligatoire.")

    # ---------------------------------------------------------
    # Création du compte Firebase
    # ---------------------------------------------------------

    user_record = fb_auth.create_user(
        email=email,
        password=password,
        disabled=True,
        email_verified=False,
    )

    try:
        # -----------------------------------------------------
        # Attribution des droits initiaux
        # -----------------------------------------------------

        claims = {
            "role": permissions.USER,
            "company_id": company_id,
            "company_name": company_name,
            "approved": False,
            "pages": {key: False for key in permissions.PAGE_KEYS},
        }

        fb_auth.set_custom_user_claims(
            user_record.uid,
            claims,
        )

    except Exception:
        # -----------------------------------------------------
        # Nettoyage en cas d'échec
        # -----------------------------------------------------

        try:
            fb_auth.delete_user(user_record.uid)
        except Exception:
            pass

        raise

    # ---------------------------------------------------------
    # Envoi de l'email de vérification
    # ---------------------------------------------------------
    #
    # handle_code_in_app=True : Firebase redirige vers notre propre
    # appli avec le oobCode en paramètre, plutôt que de valider
    # l'email dès le chargement de sa page générique. La validation
    # elle-même n'a lieu qu'au clic sur le bouton "Confirmer mon
    # email" côté app_streamlit.py (voir le bloc `action ==
    # "email_verified"` qui appelle l'API accounts:update avec ce
    # code).
    #
    try:
        app_url = st.secrets.get("app", {}).get("base_url", "http://localhost:8501")
        action_code_settings = ActionCodeSettings(
            url=f"{app_url}/?action=email_verified&email={quote(email)}",
            handle_code_in_app=True,
        )
        link = fb_auth.generate_email_verification_link(email, action_code_settings)
        send_verification_email(email, link)
    except Exception as e:
        print(f"Échec d'envoi de l'email de vérification pour {email} : {e}")

    return user_record.uid


def notify_admins_of_email_confirmation(email: str) -> None:
    """
    Envoie une notification aux administrateurs (global_master) lorsque
    l'email d'un utilisateur inscrit vient d'être confirmé (après clic
    réel sur le bouton "Confirmer mon email", voir app_streamlit.py).

    Idempotent : un custom claim `admin_notified` est posé sur le compte
    après le premier envoi, pour ne jamais notifier deux fois pour le
    même compte (ex. si la page est rechargée après confirmation).
    """
    try:
        user_record = fb_auth.get_user_by_email(email)
    except Exception:
        return

    claims = user_record.custom_claims or {}

    if claims.get("admin_notified"):
        return

    admin_emails = [
        u.email
        for u in fb_auth.list_users().iterate_all()
        if (u.custom_claims or {}).get("role") == permissions.GLOBAL_MASTER
    ]

    if admin_emails:
        send_admin_notification_email(
            admin_emails,
            new_user_email=email,
            company_name=claims.get("company_name", ""),
        )

    claims["admin_notified"] = True
    fb_auth.set_custom_user_claims(user_record.uid, claims)


def activate_user(
    current_user: dict,
    target: dict,
    pages: dict,
) -> None:
    """
    Valide et active un utilisateur.

    Seul un global_master peut effectuer cette opération.

    Lors de l'activation :
        - approved = True
        - disabled = False
        - les pages sélectionnées sont enregistrées
        - un email de confirmation est envoyé à l'utilisateur
    """

    # ---------------------------------------------------------
    # Vérification des droits
    # ---------------------------------------------------------

    if current_user["role"] != permissions.GLOBAL_MASTER:
        raise PermissionError("Seul un global_master peut activer un compte.")

    if not permissions.can_modify_target(
        current_user,
        target,
    ):
        raise PermissionError("Droits insuffisants pour modifier ce compte.")

    # ---------------------------------------------------------
    # Récupération du compte Firebase
    # ---------------------------------------------------------

    user_record = fb_auth.get_user(target["uid"])

    # ---------------------------------------------------------
    # Conservation des claims existantes
    # ---------------------------------------------------------

    claims = user_record.custom_claims or {}

    # Sécurité : le compte doit rester un utilisateur standard.
    if claims.get("role") != permissions.USER:
        raise ValueError("Seuls les comptes utilisateur peuvent être activés avec cette fonction.")

    # ---------------------------------------------------------
    # Approbation
    # ---------------------------------------------------------

    claims["approved"] = True

    # ---------------------------------------------------------
    # Attribution des pages
    # ---------------------------------------------------------

    claims["pages"] = {key: bool(pages.get(key, False)) for key in permissions.PAGE_KEYS}

    # ---------------------------------------------------------
    # Enregistrement des claims
    # ---------------------------------------------------------

    fb_auth.set_custom_user_claims(
        user_record.uid,
        claims,
    )

    # ---------------------------------------------------------
    # Activation du compte
    # ---------------------------------------------------------

    fb_auth.update_user(
        user_record.uid,
        disabled=False,
    )

    # ---------------------------------------------------------
    # Notification de l'utilisateur
    # ---------------------------------------------------------

    send_account_activation_email(
        user_record.email,
        claims["pages"],
    )
