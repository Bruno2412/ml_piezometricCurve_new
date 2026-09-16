from firebase_admin import auth as fb_auth

from piezo_app.auth import permissions
from piezo_app.services.email_service import send_verification_email


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
    Le compte est créé désactivé (email non vérifié en plus, à titre
    informatif pour l'administrateur qui validera le compte).

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
        email_verified=False,
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

    # ---------------------------------------------------------
    # Envoi de l'email de confirmation
    # ---------------------------------------------------------
    #
    # Best-effort : un échec d'envoi ne doit pas empêcher la création
    # du compte, qui reste de toute façon bloqué (disabled=True)
    # jusqu'à validation manuelle par un administrateur. On journalise
    # simplement l'échec pour investigation.
    #
    try:
        link = fb_auth.generate_email_verification_link(email)
        send_verification_email(email, link)
    except Exception as e:
        print(f"Échec d'envoi de l'email de confirmation pour {email} : {e}")

    return user_record.uid