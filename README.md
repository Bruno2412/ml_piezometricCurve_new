# Expert Piézométrie Pro — Digital Twin

Application Streamlit dédiée à l'analyse, la modélisation et la visualisation de chroniques piézométriques.

L'application permet d'explorer des données piézométriques, d'analyser les relations entre plusieurs points de mesure, de produire des cartes piézométriques et de réaliser des prévisions à l'aide de plusieurs modèles statistiques et de machine learning.

Ajout d'une authentification par user et par entreprise -- intégration de firebase

## Fonctionnalités

- Import de chroniques piézométriques au format Excel
- Détection et validation des points piézométriques
- Vérification de l'appartenance à une même masse d'eau
- Analyse statistique des chroniques
- Analyse des corrélations entre piézomètres
- Prévision des niveaux piézométriques
- Modèles disponibles :
  - ETS
  - ARIMA
  - Random Forest
  - XGBoost
- Intervalles de confiance et validation des modèles
- Cartographie piézométrique
- Analyse de l'influence spatiale
- Module de simulation de recharge maîtrisée
- Interface interactive Streamlit

## Architecture

```text
ml_piezometricCurve_new/
│
├── app_streamlit.py              ← point d'entrée
│
├── auth/
│   ├── __init__.py
│   ├── authentication.py         ← connexion / session
│   └── permissions.py             ← droits utilisateur
│
├── components/
│   ├── tab_reseau.py
│   ├── tab_analyse.py
│   ├── tab_carte.py
│   ├── tab_twin.py
│   ├── login.py
│   └── project_selector.py
│
├── data/
│   ├── data_loader.py
│   ├── validators.py
│   └── storage.py
│
├── database/
│   ├── models.py
│   ├── repository.py
│   └── connection.py
│
├── services/
│   ├── project_service.py
│   ├── chronology_service.py
│   └── analysis_service.py
│
├── tests/                        
│   ├── __init__.py
│   ├── test_data_loader.py
│   ├── test_parsing.py
│   ├── test_chronology.py
│   ├── test_analysis.py
│   ├── test_models.py
│   ├── test_validators.py
│   └── test_authentication.py
│
├── piezo_core.py
│
├── .streamlit/
│   └── config.toml
│
├── README.md
├── pyproject.toml
└── requirements.txt'
└── .gitignore
