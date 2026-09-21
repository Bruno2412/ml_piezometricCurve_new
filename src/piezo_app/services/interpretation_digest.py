# -*- coding: utf-8 -*-
"""
services/interpretation_digest.py — Synthèse chiffrée de l'analyse, destinée à l'IA.

Logique pure : aucun appel Streamlit, aucun réseau. Tous les chiffres
(tendances, saisonnalité, corrélations, gradient, fiabilité de la
prévision, recharge) sont calculés ICI, de façon déterministe. L'IA ne
fait que rédiger à partir de ce dictionnaire : elle ne calcule rien.

Le sens physique (une hausse de valeur = remontée ou baisse de la nappe)
est aussi tranché ici, selon la convention choisie par l'utilisateur,
pour que l'IA n'ait jamais à deviner le signe.
"""

import math

import numpy as np
import pandas as pd

from piezo_app.services import piezo_core as core

CONVENTION_NGF = "ngf"
CONVENTION_PROFONDEUR = "profondeur"

CONVENTION_LABELS = {
    CONVENTION_NGF: "Cote piézométrique (NGF) : une hausse de la valeur = remontée de la nappe",
    CONVENTION_PROFONDEUR: (
        "Profondeur sous le repère : une hausse de la valeur = baisse de la nappe"
    ),
}

FREQ_LABELS = {
    "D": "journalière",
    "W": "hebdomadaire",
    "MS": "mensuelle",
    "QS": "trimestrielle",
    "YS": "annuelle",
}

_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
_SECTEURS = [
    "le nord", "le nord-est", "l'est", "le sud-est",
    "le sud", "le sud-ouest", "l'ouest", "le nord-ouest",
]

# Une variation totale inférieure à cette part de la plage historique est
# qualifiée de « stable ».
_STABLE_SHARE = 0.10


# ─── Utilitaires ─────────────────────────────────────────────────────────


def _round(x, nd=3):
    """Arrondi tolérant : None / NaN / inf deviennent None (JSON propre)."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return round(xf, nd) + 0.0 if math.isfinite(xf) else None


def _clean_name(name, max_len=60):
    """Nom de point nettoyé et tronqué : il est envoyé à l'IA comme donnée,
    jamais comme instruction."""
    return " ".join(str(name).split())[:max_len]


def _iso(ts):
    return pd.Timestamp(ts).date().isoformat()


def _slope_per_year(d):
    """Pente d'une régression linéaire niveau ~ temps (unités par an)."""
    years = (d["date"] - d["date"].min()).dt.days / 365.25
    if years.nunique() < 2:
        return None
    slope, _ = np.polyfit(years.to_numpy(dtype=float), d["level"].to_numpy(dtype=float), 1)
    return float(slope)


def _sens_nappe(delta_valeur, plage, convention):
    """Qualifie une variation de valeur en variation de la NAPPE, selon la
    convention : c'est ici, et pas dans l'IA, que le signe est interprété."""
    if plage is None or plage <= 0 or abs(delta_valeur) < _STABLE_SHARE * plage:
        return "stable"
    valeur_monte = delta_valeur > 0
    nappe_monte = valeur_monte if convention == CONVENTION_NGF else not valeur_monte
    return "hausse du niveau de la nappe" if nappe_monte else "baisse du niveau de la nappe"


# ─── Une chronique ───────────────────────────────────────────────────────


def summarize_chronicle(label, df, convention):
    """Résumé chiffré d'une chronique (df avec colonnes date / level)."""
    d = df[["date", "level"]].copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["level"] = pd.to_numeric(d["level"], errors="coerce")
    d = d.dropna().sort_values("date")

    if d.empty:
        return {"point": label, "n_observations": 0}

    first, last = d["date"].iloc[0], d["date"].iloc[-1]
    span_years = (last - first).days / 365.25
    lvl = d["level"]
    plage = float(lvl.max() - lvl.min())
    last_value = float(lvl.iloc[-1])

    out = {
        "point": label,
        "n_observations": int(len(d)),
        "periode": {
            "debut": _iso(first),
            "fin": _iso(last),
            "duree_annees": _round(span_years, 1),
        },
        "dernier_niveau": {"date": _iso(last), "valeur": _round(last_value, 2)},
        "minimum": {
            "valeur": _round(lvl.min(), 2),
            "date": _iso(d["date"].iloc[int(np.argmin(lvl.to_numpy()))]),
        },
        "maximum": {
            "valeur": _round(lvl.max(), 2),
            "date": _iso(d["date"].iloc[int(np.argmax(lvl.to_numpy()))]),
        },
        "moyenne": _round(lvl.mean(), 2),
        "plage_historique": _round(plage, 2),
    }

    # Tendance globale
    slope = _slope_per_year(d)
    if slope is not None and span_years > 0:
        total = slope * span_years
        out["tendance_globale"] = {
            "pente_par_an": _round(slope, 3),
            "variation_totale_sur_la_periode": _round(total, 2),
            "sens": _sens_nappe(total, plage, convention),
        }

    # Tendance récente (3 dernières années), si l'historique est assez long
    r = d[d["date"] >= last - pd.DateOffset(years=3)]
    span_r = (r["date"].iloc[-1] - r["date"].iloc[0]).days / 365.25 if len(r) > 1 else 0.0
    if span_years >= 5 and len(r) >= 6 and span_r >= 1:
        slope_r = _slope_per_year(r)
        if slope_r is not None:
            total_r = slope_r * span_r
            out["tendance_3_dernieres_annees"] = {
                "pente_par_an": _round(slope_r, 3),
                "variation_totale_sur_la_fenetre": _round(total_r, 2),
                "sens": _sens_nappe(total_r, plage, convention),
            }

    # Saisonnalité (moyennes mensuelles, au moins 2 ans)
    monthly = d.set_index("date")["level"].resample("MS").mean().dropna()
    if len(monthly) >= 24:
        clim = monthly.groupby(monthly.index.month).mean()
        if len(clim) == 12:
            mois_max, mois_min = int(clim.idxmax()), int(clim.idxmin())
            hautes, basses = (
                (mois_max, mois_min) if convention == CONVENTION_NGF else (mois_min, mois_max)
            )
            out["saisonnalite"] = {
                "amplitude_moyenne": _round(clim.max() - clim.min(), 2),
                "mois_hautes_eaux": _MOIS[hautes - 1],
                "mois_basses_eaux": _MOIS[basses - 1],
            }

    # Position du dernier niveau par rapport au même mois les autres années
    same = monthly[monthly.index.month == last.month]
    if len(same) >= 5:
        if convention == CONVENTION_NGF:
            rank = float((same <= last_value).mean() * 100.0)
        else:
            rank = float((same >= last_value).mean() * 100.0)
        out["rang_percentile_meme_mois"] = {
            "valeur": _round(rank, 0),
            "lecture": "100 = niveau de nappe le plus haut observé pour ce mois de l'année",
            "n_annees_comparees": int(len(same)),
        }

    return out


# ─── Cohérence entre points ──────────────────────────────────────────────


def _correlations(chronicles, labels):
    corr, n = core.compute_correlation_matrix(chronicles)
    if corr is None:
        return {
            "disponible": False,
            "raison": "moins de 3 mois communs entre les chroniques",
        }
    names = list(corr.columns)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs.append(
                {
                    "point_a": labels.get(names[i], _clean_name(names[i])),
                    "point_b": labels.get(names[j], _clean_name(names[j])),
                    "r_pearson": _round(corr.iloc[i, j], 2),
                }
            )
    return {
        "disponible": True,
        "methode": "Pearson sur moyennes mensuelles des niveaux, non détendancées",
        "n_mois_communs": int(n),
        "paires": pairs,
    }


def hydraulic_gradient(chronicles, coords_dict, convention):
    """Gradient hydraulique du plan passant par 3 points (à la dernière date
    commune), avec sa direction d'écoulement. Retourne None si non calculable
    (autre convention que la cote NGF, coordonnées absentes, points alignés)."""
    if convention != CONVENTION_NGF or not coords_dict or len(chronicles) != 3:
        return None

    pts = []
    for c in chronicles.values():
        info = coords_dict.get(c["name"])
        if not info or "lon" not in info or "lat" not in info:
            return None
        pts.append((info["lon"], info["lat"], c["df"]))

    lons = np.array([p[0] for p in pts], dtype=float)
    lats = np.array([p[1] for p in pts], dtype=float)
    lon0, lat0 = lons.mean(), lats.mean()
    x = (lons - lon0) * 111_320.0 * math.cos(math.radians(lat0))
    y = (lats - lat0) * 110_540.0

    ref = min(pd.to_datetime(p[2]["date"]).max() for p in pts)
    try:
        h = np.array([core.value_at_date(p[2], ref) for p in pts], dtype=float)
    except Exception:
        return None
    if not np.all(np.isfinite(h)):
        return None

    A = np.column_stack([x, y, np.ones(3)])
    det = float(np.linalg.det(A))
    if abs(det) < 1.0:  # points quasi alignés : plan indéterminé
        return None

    a, b, _c = np.linalg.solve(A, h)
    grad = float(math.hypot(a, b))
    out = {
        "date_reference": _iso(ref),
        "gradient_m_par_m": _round(grad, 5),
        "aire_triangle_m2": _round(abs(det) / 2.0, 0),
        "methode": "plan passant par les 3 points (nappe supposée homogène)",
    }
    if grad > 1e-6:
        azimut = math.degrees(math.atan2(-a, -b)) % 360.0  # écoulement vers les charges décroissantes
        out["sens_ecoulement_azimut_deg"] = _round(azimut, 0)
        out["sens_ecoulement"] = f"vers {_SECTEURS[int(round(azimut / 45.0)) % 8]}"
    else:
        out["sens_ecoulement"] = "gradient quasi nul"
    return out


# ─── Prévision ───────────────────────────────────────────────────────────


def summarize_forecast(
    *,
    model_name,
    ci_pct,
    validation_years,
    future_years,
    y_train,
    y_val,
    p_val,
    lo_val,
    hi_val,
    fut_dates,
    p_fut,
    lo_fut,
    hi_fut,
    convention,
):
    """Fiabilité (validation) et résultat (futur) de la prévision."""
    y_train = np.asarray(y_train, dtype=float)
    y_val = np.asarray(y_val, dtype=float)
    p_val = np.asarray(p_val, dtype=float)
    lo_val = np.asarray(lo_val, dtype=float)
    hi_val = np.asarray(hi_val, dtype=float)
    p_fut = np.asarray(p_fut, dtype=float)
    lo_fut = np.asarray(lo_fut, dtype=float)
    hi_fut = np.asarray(hi_fut, dtype=float)

    err = p_val - y_val
    mae = float(np.nanmean(np.abs(err)))
    rmse = float(np.sqrt(np.nanmean(err**2)))
    biais = float(np.nanmean(err))
    mae_persistance = float(np.nanmean(np.abs(y_val - y_train[-1])))
    couverture = float(np.nanmean((y_val >= lo_val) & (y_val <= hi_val)) * 100.0)

    hist_min = float(min(np.nanmin(y_train), np.nanmin(y_val)))
    hist_max = float(max(np.nanmax(y_train), np.nanmax(y_val)))
    plage = hist_max - hist_min
    dernier_obs = float(y_val[-1])
    delta = float(p_fut[-1] - dernier_obs)

    return {
        "modele": model_name,
        "validation": {
            "duree_annees": int(validation_years),
            "n_points": int(len(y_val)),
            "mae": _round(mae, 3),
            "rmse": _round(rmse, 3),
            "biais_moyen_prevu_moins_observe": _round(biais, 3),
            "mae_prevision_naive_dernier_niveau_constant": _round(mae_persistance, 3),
            "gain_mae_vs_naive_pct": (
                _round((1 - mae / mae_persistance) * 100.0, 0) if mae_persistance > 0 else None
            ),
            "couverture_intervalle_pct": _round(couverture, 0),
            "intervalle_nominal_pct": int(ci_pct),
        },
        "futur": {
            "horizon_annees": int(future_years),
            "date_debut": _iso(fut_dates[0]),
            "date_fin": _iso(fut_dates[-1]),
            "dernier_niveau_observe": _round(dernier_obs, 2),
            "valeur_prevue_a_la_fin": _round(p_fut[-1], 2),
            "intervalle_a_la_fin": [_round(lo_fut[-1], 2), _round(hi_fut[-1], 2)],
            "variation_prevue": _round(delta, 2),
            "sens": _sens_nappe(delta, plage, convention),
            "minimum_prevu": _round(np.nanmin(p_fut), 2),
            "maximum_prevu": _round(np.nanmax(p_fut), 2),
            "sort_de_la_plage_historique": bool(
                np.nanmin(p_fut) < hist_min or np.nanmax(p_fut) > hist_max
            ),
            "plage_historique": [_round(hist_min, 2), _round(hist_max, 2)],
        },
    }


# ─── Recharge maîtrisée (Digital Twin) ───────────────────────────────────


def summarize_recharge(df_target, freq, Q, S, K, thickness, distance, Area):
    if not Q or Q <= 0:
        return {"simulee": False, "raison": "débit injecté nul : aucune recharge simulée"}

    ind = core.compute_dashboard_indicators(df_target, freq, Q, S, K, thickness, distance, Area)
    temps = ind.get("temps_rech")
    return {
        "simulee": True,
        "parametres": {
            "debit_injecte_m3_par_jour": _round(Q, 2),
            "coefficient_emmagasinement": _round(S, 5),
            "permeabilite_K_m_par_s": _round(K, 8),
            "epaisseur_aquifere_m": _round(thickness, 1),
            "distance_piezometre_ouvrage_m": _round(distance, 1),
            "surface_ouvrage_m2": _round(Area, 1),
        },
        "impact_simule_au_piezometre_a_180_jours_m": _round(ind.get("impact_inj"), 3),
        "temps_pour_remontee_de_0_5_m_dans_l_ouvrage_jours": (
            _round(temps, 0) if temps is not None and temps < 9999 else None
        ),
    }


# ─── Assemblage ──────────────────────────────────────────────────────────


def _limits(chronicles, forecast, future_years):
    notes = []
    durees = []
    for c in chronicles.values():
        d = pd.to_datetime(c["df"]["date"]).dropna()
        if len(d) > 1:
            durees.append((d.max() - d.min()).days / 365.25)
    if durees and min(durees) < 5:
        notes.append("Au moins une chronique dure moins de 5 ans : tendance et saisonnalité peu robustes.")
    if durees and forecast is not None and future_years > 0.5 * min(durees):
        notes.append("L'horizon de prévision dépasse la moitié de la durée de la plus courte chronique.")
    if forecast is not None and forecast.get("modele") in ("RandomForest", "XGBoost"):
        notes.append(
            "Modèles à base d'arbres : ils n'extrapolent pas une tendance hors de la plage d'apprentissage."
        )
    return notes


def build_digest(
    *,
    chronicles,
    target_name,
    freq,
    convention,
    forecast=None,
    recharge=None,
    coords_dict=None,
    anonymize=False,
    future_years=0,
):
    """Assemble la synthèse envoyée à l'IA.

    Retourne (digest, alias_map). Si anonymize=True, les noms de points sont
    remplacés par « Piézomètre A/B/C » et alias_map permet de les restaurer
    dans le texte affiché à l'utilisateur.
    """
    alias_map = {}
    labels = {}
    for pos, key in enumerate(sorted(chronicles)):
        name = chronicles[key]["name"]
        if anonymize:
            alias = f"Piézomètre {chr(ord('A') + pos)}"
            alias_map[alias] = _clean_name(name)
            labels[name] = alias
        else:
            labels[name] = _clean_name(name)

    digest = {
        "contexte": {
            "convention_niveau": CONVENTION_LABELS[convention],
            "unite_niveau": "m",
            "frequence_des_donnees": FREQ_LABELS.get(freq, str(freq)),
            "nombre_de_points": len(chronicles),
            "piezometre_cible_de_la_prevision": labels.get(target_name, _clean_name(target_name)),
        },
        "chroniques": [
            summarize_chronicle(labels[c["name"]], c["df"], convention)
            for _, c in sorted(chronicles.items())
        ],
        "correlations_mensuelles": _correlations(chronicles, labels),
    }

    gradient = hydraulic_gradient(chronicles, coords_dict, convention)
    digest["gradient_hydraulique"] = gradient if gradient is not None else {
        "disponible": False,
        "raison": "coordonnées absentes, points alignés ou convention en profondeur",
    }

    digest["prevision"] = forecast if forecast is not None else {"disponible": False}
    digest["recharge_maitrisee"] = recharge if recharge is not None else {"simulee": False}
    digest["limites_identifiees"] = _limits(chronicles, forecast, future_years)

    return digest, alias_map
