# -*- coding: utf-8 -*-
"""
auth/registration.py — Gestion des inscriptions publiques.

Flux :
    1. L'utilisateur s'inscrit.
    2. Le compte Firebase est créé désactivé.
    3. Le rôle est obligatoirement "user".
    4. approved = False.
    5. Toutes les pages sont désactivées.
    6. Un email de vérification est envoyé à l'utilisateur.
    7. L'utilisateur confirme son adresse email.
    8. L'application vérifie email_verified auprès de Firebase.
    9. Le global_master est alors notifié.
   10. Le global_master pourra ensuite approuver et activer le compte.
"""

from urllib.parse import quote

from firebase_admin import auth as fb_auth
from firebase_admin.auth import ActionCodeSettings
import streamlit as st

from piezo_app.auth import permissions
from piezo_app.services.email_service import (
    send_verification_email,
    send_admin_notification_email,
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

    Un email de vérification Firebase est ensuite envoyé
    à l'utilisateur.

    Aucun email n'est envoyé au global_master à ce stade.
    """

    email = email.strip().lower()
    company_id = company_id.strip()
    company_name = company_name.strip()

    # ---------------------------------------------------------
    # Validation des données
    # ---------------------------------------------------------

    if not email:
        raise ValueError(
            "L'adresse email est obligatoire."
        )

    if not password:
        raise ValueError(
            "Le mot de passe est obligatoire."
        )

    if len(password) < 8:
        raise ValueError(
            "Le mot de passe doit contenir au moins 8 caractères."
        )

    if not company_id:
        raise ValueError(
            "L'identifiant de la société est obligatoire."
        )

    if not company_name:
        raise ValueError(
            "Le nom de la société est obligatoire."
        )

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
        # Attribution des custom claims
        # -----------------------------------------------------
        #
        # Une inscription publique crée TOUJOURS un user.
        #
        # Le compte n'est pas encore approuvé.
        #
        # Aucun accès aux fonctionnalités métier par défaut.
        #

        claims = {
            "role": permissions.USER,
            "company_id": company_id,
            "company_name": company_name,
            "approved": False,
            "pages": {
                key: False
                for key in permissions.PAGE_KEYS
            },
        }

        fb_auth.set_custom_user_claims(
            user_record.uid,
            claims,
        )

    except Exception:
        # -----------------------------------------------------
        # Nettoyage en cas d'échec
        # -----------------------------------------------------
        #
        # Si l'attribution des claims échoue, on supprime
        # le compte afin d'éviter un compte Firebase orphelin.
        #

        try:
            fb_auth.delete_user(
                user_record.uid
            )
        except Exception:
            pass

        raise

    # ---------------------------------------------------------
    # Génération et envoi du mail de vérification
    # ---------------------------------------------------------
    #
    # Firebase génère un lien à usage unique.
    #
    # Après validation, Firebase positionnera :
    #
    #     email_verified = True
    #
    # Le global_master n'est PAS notifié ici.
    #

    try:
        app_url = (
            st.secrets
            .get("app", {})
            .get(
                "base_url",
                "http://localhost:8501",
            )
        )

        action_code_settings = ActionCodeSettings(
            url=(
                f"{app_url}/"
                f"?action=email_verified"
                f"&email={quote(email)}"
            ),
            handle_code_in_app=False,
        )

        link = fb_auth.generate_email_verification_link(
            email,
            action_code_settings,
        )

        send_verification_email(
            email,
            link,
        )

    except Exception as e:
        # L'inscription reste créée.
        # Le compte reste cependant désactivé.
        print(
            "Échec d'envoi de l'email de confirmation "
            f"pour {email} : {e}"
        )

    return user_record.uid


def notify_admins_of_email_confirmation(
    email: str,
) -> None:
    """
    Notifie les global_master lorsqu'un utilisateur a effectivement
    confirmé son adresse email.

    IMPORTANT :
    cette fonction ne doit être appelée qu'après le retour de Firebase
    indiquant que l'adresse email est vérifiée.

    Une vérification supplémentaire de email_verified est effectuée
    directement auprès de Firebase avant l'envoi du mail.
    """

    email = email.strip().lower()

    if not email:
        return

    # ---------------------------------------------------------
    # Récupération du compte Firebase
    # ---------------------------------------------------------

    try:
        user_record = fb_auth.get_user_by_email(
            email
        )
    except Exception:
        return

    # ---------------------------------------------------------
    # Sécurité :
    # on ne notifie que si Firebase confirme réellement
    # la vérification de l'adresse email.
    # ---------------------------------------------------------

    if not user_record.email_verified:
        return

    # ---------------------------------------------------------
    # Récupération des informations d'inscription
    # ---------------------------------------------------------

    claims = user_record.custom_claims or {}

    company_name = claims.get(
        "company_name",
        "",
    )

    # ---------------------------------------------------------
    # Recherche des global_master
    # ---------------------------------------------------------

    admin_emails = [
        u.email
        for u in fb_auth.list_users().iterate_all()
        if (
            u.email
            and (u.custom_claims or {}).get("role")
            == permissions.GLOBAL_MASTER
        )
    ]

    if not admin_emails:
        return

    # ---------------------------------------------------------
    # Notification
    # ---------------------------------------------------------

    send_admin_notification_email(
        admin_emails,
        new_user_email=email,
        company_name=company_name,
    )