# -*- coding: utf-8 -*-
"""Persistance des fichiers de chroniques chargés pour un projet, dans
Firestore.

Le stockage se fait dans une sous-collection du document projet, pas dans
le document racine, pour ne pas être limité par sa taille (métadonnées,
droits...) et pour pouvoir gérer chaque fichier indépendamment (chroniques,
descriptif, MassesEau, Excel).

Aucun Firebase Storage n'est nécessaire : le contenu est encodé en base64
directement dans les documents Firestore. Limite pratique retenue : 700 Ko
par fichier brut (~950 Ko une fois encodé), sous la limite de 1 Mo par
document Firestore.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore

COLLECTION_NAME = "Projects"
FILES_SUBCOLLECTION = "files"
MAX_FILE_BYTES = 700 * 1024  # 700 Ko bruts par fichier

_ALL_SLOTS = ("excel", "chroniques", "descriptif", "masses_eau")


class ProjectFileTooLargeError(ValueError):
    """Fichier trop volumineux pour être stocké dans Firestore."""


class StoredFile(io.BytesIO):
    """BytesIO nommé, compatible avec l'API des ``UploadedFile`` de
    Streamlit (``.name``, ``.getvalue()``) telle qu'utilisée sans
    modification par le pipeline de parsing existant."""

    def __init__(self, content: bytes, name: str):
        super().__init__(content)
        self.name = name


def _db():
    return firestore.client()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slot_for(filename: str) -> str | None:
    name = filename.strip().lower()
    if name.endswith((".xlsx", ".xls")):
        return "excel"
    if name == "chroniques.txt":
        return "chroniques"
    if name == "descriptif.txt":
        return "descriptif"
    if name == "masseseau.txt":
        return "masses_eau"
    return None


def _files_collection(project_id: str):
    return (
        _db()
        .collection(COLLECTION_NAME)
        .document(project_id)
        .collection(FILES_SUBCOLLECTION)
    )


def save_uploaded_files(project_id: str, files: list[Any]) -> None:
    """Remplace le jeu de fichiers stocké pour ce projet par ``files``.

    Les emplacements (chroniques/descriptif/masses_eau/excel) absents de
    ``files`` sont supprimés : le stockage reflète toujours le dernier
    upload validé, jamais un mélange d'anciens et de nouveaux fichiers.
    """
    if not project_id:
        return

    collection = _files_collection(project_id)
    slots_present = set()

    for f in files or []:
        slot = _slot_for(f.name)
        if slot is None:
            continue

        content = f.getvalue()
        if len(content) > MAX_FILE_BYTES:
            raise ProjectFileTooLargeError(
                f"« {f.name} » dépasse la taille maximale acceptée "
                f"({MAX_FILE_BYTES // 1024} Ko)."
            )

        slots_present.add(slot)
        collection.document(slot).set(
            {
                "filename": f.name,
                "content_b64": base64.b64encode(content).decode("ascii"),
                "updated_at": _now_iso(),
            }
        )

    for slot in set(_ALL_SLOTS) - slots_present:
        collection.document(slot).delete()


def load_stored_files(project_id: str) -> dict[str, StoredFile]:
    """Retourne les fichiers enregistrés pour ce projet, prêts à être
    passés tels quels au pipeline de parsing existant. Dict vide si rien
    n'a encore été enregistré."""
    if not project_id:
        return {}

    result: dict[str, StoredFile] = {}
    for doc in _files_collection(project_id).stream():
        data = doc.to_dict() or {}
        content_b64 = data.get("content_b64")
        filename = data.get("filename")
        if not content_b64 or not filename:
            continue
        result[doc.id] = StoredFile(base64.b64decode(content_b64), filename)

    return result
