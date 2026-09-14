# Commandes du projet Expert Piézométrie Pro.
# Installation de `just` : https://github.com/casey/just#installation
# Lister toutes les commandes : just --list  (ou juste `just`)

# Sous Windows, `just` cherche `sh` par défaut (absent sans Git Bash/WSL) :
# on utilise cmd.exe à la place. Sans effet sous macOS/Linux (sh y est natif).
set windows-shell := ["cmd.exe", "/c"]

default:
    @just --list

# Crée le venv et installe toutes les dépendances (prod + dev).
setup:
    pip install -e .[dev] || pip install -r requirements.txt
    pip install ruff pytest

# Lance l'application Streamlit.
run:
    streamlit run app_streamlit.py

# Lance les tests.
test:
    pytest -v

# Lance les tests avec rapport de couverture (nécessite pytest-cov).
test-cov:
    pytest --cov=. --cov-report=term-missing

# Formate le code avec ruff.
format:
    ruff format .

# Vérifie le lint avec ruff (sans modifier les fichiers).
lint:
    ruff check .

# Corrige automatiquement ce qui peut l'être, puis formate.
fix:
    ruff check --fix .
    ruff format .

# Formate + lint + tests, à lancer avant un commit.
check: format lint test

# Régénère requirements.txt à partir de pyproject.toml (source de vérité).
requirements:
    python scripts/generate_requirements.py

# Crée le premier compte admin Firebase (voir auth/create_first_users.py).
create-first-user:
    python auth/create_first_users.py
