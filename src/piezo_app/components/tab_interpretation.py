# -*- coding: utf-8 -*-
"""Onglet « Interprétation » : description assistée par IA de l'ensemble de
l'analyse (chroniques, cohérence entre points, prévision, recharge).

Principe : les chiffres sont calculés par l'application
(services/interpretation_digest.py) ; le LLM (services/llm_client.py) ne fait
que les rédiger. Seule la synthèse chiffrée affichée dans l'expandeur est
envoyée au service d'IA.

Configuration (Secrets Streamlit) :

    [mistral]
    api_key = "..."
    model = "mistral-small-latest"   # facultatif
    max_calls_per_session = 10       # facultatif
"""

import hashlib
import json
import re
from datetime import datetime

import streamlit as st

from piezo_app.services import interpretation_digest as digest_lib
from piezo_app.services import llm_client

_DEFAULT_MODEL = "mistral-small-latest"
_DEFAULT_MAX_CALLS = 10


def _llm_config():
    """Clé et modèle depuis les secrets ; None si la clé n'est pas configurée."""
    try:
        cfg = st.secrets["mistral"]
        return {
            "api_key": cfg["api_key"],
            "model": cfg.get("model", _DEFAULT_MODEL),
            "max_calls": int(cfg.get("max_calls_per_session", _DEFAULT_MAX_CALLS)),
        }
    except Exception:
        return None


def _restore_names(text, alias_map):
    """Remet les vrais noms de points à la place des alias « Piézomètre A »."""
    for alias, real in alias_map.items():
        text = text.replace(alias, real)
    return text


def render(
    chronicles,
    selection,
    target_name,
    freq,
    coords_dict=None,
    Q=0.0,
    S=0.05,
    K=1e-4,
    thickness=10.0,
    distance=50.0,
    Area=100.0,
):
    """Appelée par app_pages/analyse.py, après l'onglet Analyse & Prévision
    (qui fournit `freq` et enregistre ses résultats dans la session)."""

    if not chronicles:
        st.info("Aucune chronique à interpréter.")
        return

    st.subheader("Interprétation assistée par IA")
    st.caption(
        "Les chiffres sont calculés par l'application ; l'IA se contente de les "
        "rédiger. Seule la synthèse chiffrée ci-dessous est envoyée à l'API "
        "de Mistral AI : ni les fichiers bruts, ni votre identité, ni celle de "
        "votre société. L'anonymisation des noms de points est recommandée."
    )

    # ── Options ───────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        convention = st.radio(
            "Nature des valeurs de niveau",
            options=list(digest_lib.CONVENTION_LABELS),
            format_func=lambda k: digest_lib.CONVENTION_LABELS[k],
            key="interp_convention",
            help=(
                "Détermine le sens d'une variation : avec des profondeurs, "
                "une valeur qui augmente signifie que la nappe baisse."
            ),
        )
    with col2:
        anonymize = st.checkbox(
            "Anonymiser les noms de points (Piézomètre A, B, C)",
            value=True,
            key="interp_anonymize",
        )

    # ── Synthèse chiffrée ─────────────────────────────────────────────────
    raw = st.session_state.get("analysis_raw")
    forecast = None
    recharge = None
    future_years = 0

    target_df = next((c["df"] for c in chronicles.values() if c["name"] == target_name), None)

    if raw is not None and raw.get("target") == target_name:
        future_years = raw["future_years"]
        try:
            forecast = digest_lib.summarize_forecast(
                model_name=raw["model_name"],
                ci_pct=raw["ci_pct"],
                validation_years=raw["validation_years"],
                future_years=raw["future_years"],
                y_train=raw["y_train"],
                y_val=raw["y_val"],
                p_val=raw["p_val"],
                lo_val=raw["lo_val"],
                hi_val=raw["hi_val"],
                fut_dates=raw["fut_dates"],
                p_fut=raw["p_fut"],
                lo_fut=raw["lo_fut"],
                hi_fut=raw["hi_fut"],
                convention=convention,
            )
        except Exception as e:
            st.warning(f"Synthèse de la prévision indisponible : {e}")

    if target_df is not None:
        try:
            recharge = digest_lib.summarize_recharge(
                target_df, freq, Q, S, K, thickness, distance, Area
            )
        except Exception as e:
            st.warning(f"Synthèse de la recharge indisponible : {e}")

    digest, alias_map = digest_lib.build_digest(
        chronicles=chronicles,
        target_name=target_name,
        freq=freq,
        convention=convention,
        forecast=forecast,
        recharge=recharge,
        coords_dict=coords_dict,
        anonymize=anonymize,
        future_years=future_years,
    )

    with st.expander("Données transmises à l'IA (synthèse chiffrée)", expanded=False):
        st.json(digest, expanded=2)

    # ── Configuration de l'IA ─────────────────────────────────────────────
    config = _llm_config()
    if config is None:
        st.info(
            "L'interprétation par IA n'est pas activée : aucune clé n'est "
            "configurée. L'administrateur de l'application doit renseigner la "
            "section [mistral] des secrets (api_key)."
        )
        return

    consent = st.checkbox(
        "J'autorise l'envoi de cette synthèse chiffrée à un service d'IA externe.",
        key="interp_consent",
    )

    digest_key = hashlib.sha256(
        (config["model"] + json.dumps(digest, sort_keys=True, ensure_ascii=False)).encode("utf-8")
    ).hexdigest()[:16]

    results = st.session_state.setdefault("_interp_results", {})
    calls = st.session_state.get("_interp_calls", 0)
    remaining = config["max_calls"] - calls

    if st.button(
        "Générer l'interprétation",
        type="primary",
        disabled=not consent or remaining <= 0,
        key="interp_generate",
    ):
        with st.spinner("Rédaction en cours…"):
            try:
                text = llm_client.generate_interpretation(
                    digest, api_key=config["api_key"], model=config["model"]
                )
            except Exception as e:
                st.error(f"Échec de l'appel à l'IA ({type(e).__name__}) : {e}")
            else:
                results[digest_key] = {
                    "text": _restore_names(text, alias_map),
                    "model": config["model"],
                    "when": datetime.now().strftime("%d/%m/%Y %H:%M"),
                }
                st.session_state["_interp_calls"] = calls + 1
                remaining -= 1

    if remaining <= 0:
        st.warning("Limite de générations atteinte pour cette session.")
    else:
        st.caption(f"{remaining} génération(s) restante(s) pour cette session.")

    # ── Résultat ──────────────────────────────────────────────────────────
    result = results.get(digest_key)
    if result is None:
        st.info("Aucune interprétation générée pour ces données et ces options.")
        return

    st.markdown(result["text"])
    st.caption(
        f"Texte généré par IA ({result['model']}) le {result['when']} à partir de la synthèse "
        "chiffrée ci-dessus. À relire et valider avant tout usage : il ne remplace pas "
        "l'avis d'un hydrogéologue."
    )
    safe_target = re.sub(r"[^A-Za-z0-9_-]+", "_", str(target_name))[:40] or "point"
    st.download_button(
        "Télécharger (Markdown)",
        result["text"].encode("utf-8"),
        file_name=f"interpretation_{safe_target}.md",
        mime="text/markdown",
        key="interp_download",
    )
