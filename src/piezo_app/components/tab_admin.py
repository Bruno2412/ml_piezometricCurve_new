# -*- coding: utf-8 -*-
"""
Created on Sun Sep 13 16:35:58 2026

@author: bruno
"""

# -*- coding: utf-8 -*-
"""Panneau d'administration des comptes utilisateurs.

C'est le "consommateur" de components/project_selector.py : c'est ici
que st.session_state['viewing_company_id'] (choisi par un global_master
via le sélecteur de société) est effectivement utilisé, via
auth.permissions.effective_company_id(), pour filtrer la liste des
comptes affichés.

Visible uniquement pour global_master et company_master (voir
auth.permissions.can_administer_users) :
  - un global_master voit et gère les comptes de la société actuellement
    sélectionnée dans la sidebar (ou tous les comptes si aucune société
    n'est encore sélectionnée) ; il peut créer des company_master et
    des user pour n'importe quelle société
  - un company_master ne voit et ne gère que les comptes de sa propre
    société ; il ne peut créer que des user rattachés à celle-ci

La délégation des pages (popover "Pages") est elle aussi bornée : un
company_master ne peut cocher pour un de ses users que les onglets
auxquels il a lui-même accès (voir auth.permissions.assignable_pages).
Il ne peut donc jamais donner plus de droits qu'il n'en a lui-même.

À appeler depuis app_streamlit.py, par exemple :

    from components import tab_admin
    if permissions.can_administer_users(st.session_state.user):
        with st.expander("🔧 Administration des comptes"):
            tab_admin.render()
"""

import streamlit as st

from piezo_app.auth import authentication, permissions


def _render_page_permissions_form(current_user, target: dict):
    """Contenu du popover "Pages" d'une ligne utilisateur : une case à
    cocher par onglet (auth.permissions.PAGE_KEYS), pré-remplies avec
    l'état actuel, et un bouton Enregistrer qui appelle
    auth.authentication.set_user_pages (qui revérifie les droits de
    son côté, ce popover n'est qu'un raccourci d'affichage).

    Un company_master ne peut cocher que les pages auxquelles il a
    lui-même accès (voir permissions.assignable_pages) : impossible
    de déléguer un droit qu'on ne possède pas soi-même. Pour un
    global_master, toutes les pages restent cochables."""
    current = permissions.allowed_pages(target)
    grantable = permissions.assignable_pages(current_user)

    with st.form(f"pages_form_{target['uid']}"):
        st.caption(f"Onglets accessibles pour {target['email']}")
        choices = {}
        for key in permissions.PAGE_KEYS:
            label = permissions.PAGE_LABELS[key]
            can_grant = key in grantable

            if key == "twin":
                help_text = "Nécessite aussi « Analyse & Prévision »"
            else:
                help_text = None

            if not can_grant:
                help_text = "Vous n'avez pas vous-même accès à cet onglet."

            choices[key] = st.checkbox(
                label,
                value=key in current,
                disabled=not can_grant,
                help=help_text,
            )

        if st.form_submit_button("Enregistrer"):
            try:
                authentication.set_user_pages(current_user, target, choices)
                st.success("Permissions mises à jour.")
                st.rerun()
            except PermissionError as e:
                st.error(str(e))


def render():
    user = st.session_state.user

    if not permissions.can_administer_users(user):
        st.info("Cette section est réservée aux administrateurs.")
        return

    try:
        all_users = authentication.list_users(user)
    except PermissionError:
        st.error("Droits insuffisants pour lister les utilisateurs.")
        return

    # C'est ici que le choix fait dans project_selector prend effet :
    # un global_master ne voit que la société qu'il "regarde" ; un
    # company_master voit toujours la sienne, quel que soit le contenu
    # de viewing_company_id (effective_company_id l'ignore pour lui).
    company_filter = permissions.effective_company_id(
        user, st.session_state.get("viewing_company_id")
    )
    visible_users = (
        [u for u in all_users if u["company_id"] == company_filter]
        if company_filter is not None
        else all_users
    )

    st.subheader("Utilisateurs")
    if not visible_users:
        st.info("Aucun utilisateur à afficher pour cette société.")
    else:
        for u in visible_users:
            col_email, col_role, col_status, col_action, col_pages = st.columns([3, 2, 2, 2, 2])
            col_email.write(u["email"])
            col_role.write(u["role"])
            col_status.write("🔴 Désactivé" if u["disabled"] else "🟢 Actif")

            # Le bouton n'est même pas affiché sur son propre compte ou
            # sur un global_master : ce n'est pas qu'une question de
            # cosmétique, authentication.set_user_active() refuserait de
            # toute façon l'action (auth.permissions.can_modify_target),
            # mais autant ne pas présenter une action vouée à échouer.
            if permissions.can_modify_target(user, u):
                action_label = "Réactiver" if u["disabled"] else "Désactiver"
                if col_action.button(action_label, key=f"toggle_{u['uid']}"):
                    try:
                        authentication.set_user_active(user, u, is_active=u["disabled"])
                        st.rerun()
                    except PermissionError as e:
                        st.error(str(e))

                with col_pages.popover("Pages"):
                    _render_page_permissions_form(user, u)

    st.divider()
    st.subheader("Créer un nouvel utilisateur")

    is_global = permissions.is_global_master(user)

    with st.form("create_user_form", clear_on_submit=True):
        new_email = st.text_input("Email")
        new_password = st.text_input("Mot de passe temporaire", type="password")

        if is_global:
            # Un global_master choisit le rôle et la société.
            new_role = st.selectbox("Rôle", ["company_master", "user"])
            new_company_id = st.text_input("Identifiant société (company_id)")
            new_company_name = st.text_input("Nom de la société")
        else:
            # Un company_master ne peut créer que des "user" dans SA
            # propre société — pas de champ, pas de choix possible.
            new_role = "user"
            new_company_id = user["company_id"]
            new_company_name = user["company_name"]
            st.caption(f"Société : {new_company_name} (fixée à la vôtre)")

        submitted = st.form_submit_button("Créer le compte")

        if submitted:
            if not new_email or not new_password:
                st.error("Email et mot de passe sont obligatoires.")
            else:
                try:
                    authentication.create_user(
                        current_user=user,
                        email=new_email,
                        password=new_password,
                        role=new_role,
                        company_id=new_company_id or None,
                        company_name=new_company_name or None,
                    )
                    st.success(f"Compte {new_email} créé avec succès.")
                    st.rerun()
                except PermissionError as e:
                    st.error(str(e))
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Erreur lors de la création du compte : {e}")