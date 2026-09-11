# -*- coding: utf-8 -*-
"""
Package auth — authentification Firebase + gestion des rôles.

Ce fichier réexpose les fonctions les plus utilisées pour que le reste
de l'app puisse écrire `import auth` puis `auth.authenticate(...)`,
`auth.require_role(...)`, etc., sans se soucier de savoir dans quel
sous-module elles vivent réellement.
"""

from auth.authentication import (
    authenticate,
    create_user,
    list_users,
    set_user_active,
)
from auth.permissions import (
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
    "authenticate", "create_user", "list_users", "set_user_active",
    "GLOBAL_MASTER", "COMPANY_MASTER", "USER", "ADMIN_ROLES",
    "is_global_master", "is_company_master", "can_administer_users",
    "can_switch_company", "require_role", "effective_company_id",
]
