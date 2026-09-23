# -*- coding: utf-8 -*-
"""
components/tab_global_overview.py — Tableau de contrôle transverse,
réservé au global_master.

Différence avec tab_admin.py : tab_admin.py affiche toujours UNE
société à la fois (celle "regardée" via project_selector, voir
auth.permissions.effective_company_id) et sert surtout à créer des
comptes. Ce panneau-ci donne une vue sur TOUTES les sociétés en même
temps — combien de company_master, combien de users, avec leur statut
— avec des filtres société / rôle / statut, comme demandé.

Les actions de bascule actif/inactif restent possibles ici pour éviter
un aller-retour vers l'autre page, mais passent par exactement les
mêmes fonctions sécurisées que tab_admin.py
(auth.authentication.set_user_active + auth.permissions.can_modify_target) :
aucune nouvelle règle de droits n'est introduite par ce fichier.

La gestion des rôles (_render_role_management) suit le même principe :
elle passe par auth.authentication.set_user_role, qui revalide
lui-même les droits (can_modify_target, can_assign_company_master,
can_create_user_for) indépendamment de ce que l'UI affiche.
"""

import streamlit as st

from piezo_app.auth import authentication, permissions


def render():
    user = st.session_state.user

    if not permissions.is_global_master(user):
        st.info("Cette section est réservée au global_master.")
        return

    try:
        all_users = authentication.list_users(user)
    except PermissionError:
        st.error("Impossible de charger les comptes.")
        return

    # Les sociétés sont déduites des comptes existants (pas de
    # collection "companies" séparée pour l'instant — même approche
    # que components/project_selector.py).
    companies = {}
    for u in all_users:
        if u["company_id"]:
            companies.setdefault(u["company_id"], u["company_name"])

    _render_summary(all_users, companies)
    st.divider()
    _render_per_company_table(all_users, companies)
    st.divider()
    _render_filterable_accounts(user, all_users, companies)
    _render_role_management(user, all_users, companies)
    _render_page_permissions(user, all_users)


def _render_summary(all_users, companies):
    company_masters = [u for u in all_users if u["role"] == "company_master"]
    standard_users = [u for u in all_users if u["role"] == "user"]
    disabled_count = sum(1 for u in all_users if u["disabled"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sociétés", len(companies))
    c2.metric("Company masters", len(company_masters))
    c3.metric("Utilisateurs", len(standard_users))
    c4.metric("Comptes désactivés", disabled_count)


def _render_per_company_table(all_users, companies):
    st.subheader("Par société")

    if not companies:
        st.info("Aucune société créée pour l'instant.")
        return

    rows = []
    for cid, cname in sorted(companies.items(), key=lambda kv: kv[1] or kv[0]):
        company_users = [u for u in all_users if u["company_id"] == cid]
        cm_email = next((u["email"] for u in company_users if u["role"] == "company_master"), "—")
        n_users = sum(1 for u in company_users if u["role"] == "user")
        n_active = sum(1 for u in company_users if not u["disabled"])
        rows.append(
            {
                "Société": cname or cid,
                "Company master": cm_email,
                "Utilisateurs": n_users,
                "Actifs": n_active,
                "Désactivés": len(company_users) - n_active,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_filterable_accounts(user, all_users, companies):
    st.subheader("Tous les comptes")

    f1, f2, f3 = st.columns(3)
    company_labels = ["Toutes"] + [companies[cid] or cid for cid in companies]
    company_choice = f1.selectbox("Société", company_labels)
    role_choice = f2.selectbox("Rôle", ["Tous", "company_master", "user"])
    status_choice = f3.selectbox("Statut", ["Tous", "Actifs", "Désactivés"])

    filtered = all_users
    if company_choice != "Toutes":
        target_cid = next(cid for cid, name in companies.items() if (name or cid) == company_choice)
        filtered = [u for u in filtered if u["company_id"] == target_cid]
    if role_choice != "Tous":
        filtered = [u for u in filtered if u["role"] == role_choice]
    if status_choice == "Actifs":
        filtered = [u for u in filtered if not u["disabled"]]
    elif status_choice == "Désactivés":
        filtered = [u for u in filtered if u["disabled"]]

    if not filtered:
        st.info("Aucun compte ne correspond à ces filtres.")
        return

    for u in filtered:
        col_email, col_company, col_role, col_status, col_action = st.columns([3, 2, 2, 2, 2])
        col_email.write(u["email"])
        col_company.write(u["company_name"] or "—")
        col_role.write(u["role"])
        col_status.write("🔴 Désactivé" if u["disabled"] else "🟢 Actif")

        # Même garde-fou que tab_admin.py : pas de bouton sur son
        # propre compte ni sur un autre global_master.
        if permissions.can_modify_target(user, u):
            action_label = "Réactiver" if u["disabled"] else "Désactiver"
            if col_action.button(action_label, key=f"global_toggle_{u['uid']}"):
                try:
                    authentication.set_user_active(user, u, is_active=u["disabled"])
                    st.rerun()
                except PermissionError as e:
                    st.error(str(e))


def _render_role_management(user, all_users, companies):
    st.divider()
    st.subheader("Gestion des rôles")

    editable_users = [u for u in all_users if permissions.can_modify_target(user, u)]

    if not editable_users:
        st.info("Aucun compte ne peut être modifié.")
        return

    user_labels = {
        u["uid"]: f"{u['email']} — {u['role']} ({u['company_name'] or 'Sans société'})"
        for u in editable_users
    }

    selected_uid = st.selectbox(
        "Utilisateur",
        options=list(user_labels.keys()),
        format_func=lambda uid: user_labels[uid],
        key="role_management_user_select",
    )

    target = next(u for u in editable_users if u["uid"] == selected_uid)

    role_options = ["user", "company_master"]
    current_role_index = role_options.index(target["role"]) if target["role"] in role_options else 0

    col_role, col_company = st.columns(2)

    new_role = col_role.selectbox(
        "Nouveau rôle",
        options=role_options,
        index=current_role_index,
        key=f"new_role_{target['uid']}",
    )

    company_ids = list(companies.keys())
    company_display = {cid: (companies[cid] or cid) for cid in company_ids}

    current_company_index = (
        company_ids.index(target["company_id"]) if target["company_id"] in company_ids else 0
    )

    new_company_id = None
    new_company_name = None
    if company_ids:
        new_company_id = col_company.selectbox(
            "Société",
            options=company_ids,
            index=current_company_index,
            format_func=lambda cid: company_display[cid],
            key=f"new_company_{target['uid']}",
        )
        new_company_name = companies[new_company_id]
    else:
        col_company.info("Aucune société existante.")

    if st.button(
        "Enregistrer le rôle",
        type="primary",
        key=f"save_role_{target['uid']}",
    ):
        try:
            authentication.set_user_role(
                current_user=user,
                target=target,
                new_role=new_role,
                new_company_id=new_company_id,
                new_company_name=new_company_name,
            )

            st.success(f"Le rôle de {target['email']} a été mis à jour en '{new_role}'.")

            st.rerun()

        except PermissionError as e:
            st.error(str(e))
        except ValueError as e:
            st.error(str(e))


def _render_page_permissions(user, all_users):
    st.divider()
    st.subheader("Gestion des accès aux pages")

    editable_users = [u for u in all_users if permissions.can_modify_target(user, u)]
    grantable = permissions.assignable_pages(user)

    if not editable_users:
        st.info("Aucun compte ne peut être modifié.")
        return

    user_labels = {
        u["uid"]: f"{u['email']} — {u['company_name'] or 'Sans société'}" for u in editable_users
    }

    selected_uid = st.selectbox(
        "Utilisateur",
        options=list(user_labels.keys()),
        format_func=lambda uid: user_labels[uid],
        key="page_permissions_user_select",
    )

    target = next(u for u in editable_users if u["uid"] == selected_uid)

    current_pages = permissions.allowed_pages(target)

    st.markdown("**Pages accessibles**")

    selected_pages = {}

    for page_key in permissions.PAGE_KEYS:
        can_grant = page_key in grantable
        selected_pages[page_key] = st.checkbox(
            permissions.PAGE_LABELS[page_key],
            value=page_key in current_pages,
            disabled=not can_grant,
            key=f"page_permission_{target['uid']}_{page_key}",
        )
        if not can_grant:
            st.caption(f"↳ Vous n'avez pas accès à '{permissions.PAGE_LABELS[page_key]}'.")

    if st.button(
        "Enregistrer les permissions",
        type="primary",
        key=f"save_page_permissions_{target['uid']}",
    ):
        try:
            authentication.set_user_pages(
                user,
                target,
                selected_pages,
            )

            st.success(f"Les permissions de {target['email']} ont été enregistrées.")

            st.rerun()

        except PermissionError as e:
            st.error(str(e))
