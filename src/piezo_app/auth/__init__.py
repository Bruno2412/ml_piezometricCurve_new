# -*- coding: utf-8 -*-
"""
Package auth — authentification Firebase + gestion des rôles.

Ce fichier réexpose les fonctions les plus utilisées pour que le reste
de l'app puisse écrire `from piezo_app import auth` puis
`auth.authenticate(...)`, `auth.require_role(...)`, etc., sans se
soucier de savoir dans quel sous-module elles vivent réellement.
"""

# from piezo_app.auth.authentication import (
#     authenticate,
#     create_user,
#     list_users,
#     set_user_active,
# )

from piezo_app.auth.authentication import (
    authenticate,
    create_user,
    list_companies,
    list_users,
    set_user_active,
)

from piezo_app.auth.permissions import (
    ADMIN_ROLES,
    COMPANY_MASTER,
    GLOBAL_MASTER,
    USER,
    can_administer_users,
    can_switch_company,
    effective_company_id,
    is_company_master,
    is_global_master,
    require_role,
)

__all__ = [
    "authenticate",
    "list_companies",
    "create_user",
    "list_users",
    "set_user_active",
    "GLOBAL_MASTER",
    "COMPANY_MASTER",
    "USER",
    "ADMIN_ROLES",
    "is_global_master",
    "is_company_master",
    "can_administer_users",
    "can_switch_company",
    "require_role",
    "effective_company_id",
]
# -*- coding: utf-8 -*-
"""
Created on Thu Sep 10 16:41:44 2026

@author: bruno
"""
