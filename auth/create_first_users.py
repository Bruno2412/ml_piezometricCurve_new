# -*- coding: utf-8 -*-
"""
Script à lancer une seule fois en local pour créer les 2 comptes
global_master, et éventuellement une première société + son
company_master.

Usage :
    python create_first_users.py /chemin/vers/ta-cle-service-account.json

Le fichier JSON est celui téléchargé depuis Firebase Console
(Paramètres du projet > Comptes de service > Générer une nouvelle clé
privée). Ne le commite jamais dans Git.
"""

import getpass
import sys

import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_admin import credentials


def init_firebase(json_path):
    cred = credentials.Certificate(json_path)
    firebase_admin.initialize_app(cred)


def create_user(email, password, role, company_id=None, company_name=None):
    user_record = fb_auth.create_user(email=email, password=password)
    claims = {"role": role}
    if company_id is not None:
        claims["company_id"] = company_id
        claims["company_name"] = company_name
    fb_auth.set_custom_user_claims(user_record.uid, claims)
    print(f"  ✓ Utilisateur '{email}' créé (rôle : {role}, uid={user_record.uid})")
    return user_record.uid


def main():
    if len(sys.argv) != 2:
        print("Usage : python create_first_users.py chemin/vers/cle.json")
        sys.exit(1)

    init_firebase(sys.argv[1])

    if input("\nCréer les 2 comptes global_master ? (o/n) : ").strip().lower() == "o":
        for i in (1, 2):
            print(f"\nGlobal master n°{i} :")
            email = input("  Email : ").strip()
            password = getpass.getpass("  Mot de passe (8 caractères min.) : ")
            create_user(email, password, role="global_master")

    if input("\nCréer une première société maintenant ? (o/n) : ").strip().lower() == "o":
        company_id = input("  Identifiant de société (court, ex: 'edf', 'brgm') : ").strip()
        company_name = input("  Nom complet de la société : ").strip()

        print("\nCompte company_master pour cette société :")
        email = input("  Email : ").strip()
        password = getpass.getpass("  Mot de passe : ")
        create_user(email, password, role="company_master",
                    company_id=company_id, company_name=company_name)

    print("\nTerminé.")


if __name__ == "__main__":
    main()
