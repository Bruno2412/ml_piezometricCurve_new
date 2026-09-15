# -*- coding: utf-8 -*-
"""
auth/registration.py — Inscription publique des utilisateurs.

Une inscription publique :
- crée uniquement un compte 'user' ;
- rattache le compte à une société ;
- crée le compte Firebase désactivé ;
- attribue les custom claims nécessaires.

L'activation est ensuite réalisée par un administrateur.
"""

from firebase_admin import auth as fb_auth

from piezo_app.auth import permissions


def register_user(
    email: str,
    password: str,
    company_id: str,
    company_name: str,
) -> str:
    """
    Crée un utilisateur depuis l'inscription publique.

    Le rôle est toujours USER.
    Un utilisateur ne peut jamais choisir son rôle.
    Le compte est créé désactivé.

    Les droits d'accès aux pages sont initialisés à False.
    Ils devront être attribués explicitement par un administrateur.
    """

    email = email.strip().lower()
    company_id = company_id.strip()
    company_name = company_name.strip()

    if not email:
        raise ValueError("L'adresse email est obligatoire.")

    if not password:
        raise ValueError("Le mot de passe est obligatoire.")

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
    )

    try:
        # -----------------------------------------------------
        # Attribution des droits
        # -----------------------------------------------------
        #
        # Une inscription publique crée TOUJOURS un user.
        #
        # Sécurité stricte :
        # aucun accès aux fonctionnalités métier par défaut.
        #
        claims = {
            "role": permissions.USER,
            "company_id": company_id,
            "company_name": company_name,
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
        # Évite de laisser un compte Firebase orphelin si
        # l'attribution des claims échoue.
        try:
            fb_auth.delete_user(user_record.uid)
        except Exception:
            pass

        raise

    return user_record.uid