# -*- coding: utf-8 -*-
"""Régénère requirements.txt à partir de pyproject.toml.

pyproject.toml est la seule source de vérité pour les dépendances.
requirements.txt n'existe que parce que Streamlit Cloud (et d'autres
plateformes de déploiement) l'exigent — il ne doit plus jamais être
édité à la main, seulement régénéré par ce script.

Workflow :
    1. Ajouter/modifier une dépendance dans pyproject.toml
    2. Lancer :  python scripts/generate_requirements.py
    3. Committer pyproject.toml ET requirements.txt ensemble

Nécessite Python 3.11+ (tomllib est dans la bibliothèque standard
depuis cette version — pas de dépendance supplémentaire à installer).
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = ROOT / "pyproject.toml"
REQUIREMENTS_PATH = ROOT / "requirements.txt"

HEADER = (
    "# Fichier généré automatiquement — NE PAS ÉDITER À LA MAIN.\n"
    "# Source de vérité : pyproject.toml.\n"
    "# Pour mettre à jour : modifier pyproject.toml, puis relancer\n"
    "# scripts/generate_requirements.py\n\n"
)


def main():
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    dependencies = data["project"]["dependencies"]

    content = HEADER + "\n".join(dependencies) + "\n"
    REQUIREMENTS_PATH.write_text(content, encoding="utf-8")

    print(f"✓ {len(dependencies)} dépendances écrites dans {REQUIREMENTS_PATH.name}")


if __name__ == "__main__":
    main()
