# -*- coding: utf-8 -*-
"""
Tests unitaires pour les fonctions de parsing de piezo_core.py.

Portée : uniquement la logique pure de parsing (lecture et structuration
des fichiers ADES/Excel). Pas de Streamlit, pas de data_loader.py — ce
dernier n'étant qu'un wrapper de cache autour de piezo_core, il n'a pas
de logique propre à tester ici. L'alignement temporel et les fréquences
(align_chronicle, detect_frequency, value_at_date, ...) sont testés dans
test_chronology.py, pas ici.

Lancer avec :
    pytest tests/test_parsing.py -v
"""

import textwrap

import pandas as pd
import pytest

import piezo_core as core


# ─────────────────────────────────────────────────────────────────────────
# Helpers internes : _clean_str / _strip_accents
# ─────────────────────────────────────────────────────────────────────────

class TestCleanStr:
    def test_none_returns_empty_string(self):
        assert core._clean_str(None) == ''

    def test_strips_bom(self):
        assert core._clean_str('\ufeffValeur') == 'Valeur'

    def test_replaces_nbsp_with_normal_space(self):
        assert core._clean_str('10\xa0000') == '10 000'

    def test_strips_leading_trailing_whitespace(self):
        assert core._clean_str('  valeur  ') == 'valeur'

    def test_casts_non_string_input(self):
        assert core._clean_str(42) == '42'


class TestStripAccents:
    def test_removes_accents_and_lowercases(self):
        assert core._strip_accents('Interprété') == 'interprete'

    def test_handles_already_clean_string(self):
        assert core._strip_accents('bonne') == 'bonne'

    def test_handles_empty_string(self):
        assert core._strip_accents('') == ''


# ─────────────────────────────────────────────────────────────────────────
# find_column
# ─────────────────────────────────────────────────────────────────────────

class TestFindColumn:
    def test_matches_known_alias_case_insensitive(self):
        df = pd.DataFrame(columns=['Date de la mesure', 'Côte NGF', 'Nom Point'])
        assert core.find_column(df, core.DATE_ALIASES) == 'Date de la mesure'

    def test_matches_alias_with_surrounding_whitespace(self):
        df = pd.DataFrame(columns=[' Date ', 'level'])
        assert core.find_column(df, ['date']) == ' Date '

    def test_returns_none_when_no_alias_matches(self):
        df = pd.DataFrame(columns=['colonne_inconnue'])
        assert core.find_column(df, core.DATE_ALIASES) is None


# ─────────────────────────────────────────────────────────────────────────
# parse_multi_piezo_excel
# ─────────────────────────────────────────────────────────────────────────

def _make_raw_df(n_points=3, n_obs=5, with_masse_eau=True):
    """Construit un df_raw minimal valide pour parse_multi_piezo_excel."""
    rows = []
    for p in range(n_points):
        point_name = f'PZ{p+1}'
        for d in range(n_obs):
            rows.append({
                'date': pd.Timestamp('2024-01-01') + pd.Timedelta(days=30 * d),
                'level': 100.0 + p + d * 0.1,
                'point': point_name,
                "masse d'eau": f'MASSE_{p}' if with_masse_eau else None,
            })
    df = pd.DataFrame(rows)
    if not with_masse_eau:
        df = df.drop(columns=["masse d'eau"])
    return df


class TestParseMultiPiezoExcel:
    def test_happy_path_returns_expected_points(self):
        df_raw = _make_raw_df(n_points=3)
        df, points, has_masse = core.parse_multi_piezo_excel(df_raw)
        assert points == ['PZ1', 'PZ2', 'PZ3']
        assert has_masse is True
        assert list(df.columns) >= ['date', 'level', 'point']
        assert set(df['point'].unique()) == {'PZ1', 'PZ2', 'PZ3'}

    def test_raises_if_fewer_than_three_columns(self):
        df_raw = pd.DataFrame({'date': [1], 'level': [2]})
        with pytest.raises(ValueError, match='au moins 3 colonnes'):
            core.parse_multi_piezo_excel(df_raw)

    def test_raises_if_required_column_missing(self):
        df_raw = pd.DataFrame({
            'date': [pd.Timestamp('2024-01-01')],
            'foo': [1],
            'bar': [2],
        })
        with pytest.raises(ValueError, match='Colonnes détectées'):
            core.parse_multi_piezo_excel(df_raw)

    def test_raises_if_fewer_points_than_min_points(self):
        df_raw = _make_raw_df(n_points=2)
        with pytest.raises(ValueError, match='minimum requis'):
            core.parse_multi_piezo_excel(df_raw, min_points=3)

    def test_accepts_custom_min_points(self):
        df_raw = _make_raw_df(n_points=2)
        df, points, _ = core.parse_multi_piezo_excel(df_raw, min_points=2)
        assert points == ['PZ1', 'PZ2']

    def test_drops_rows_with_invalid_date_or_level(self):
        df_raw = _make_raw_df(n_points=3)
        # Repasse la colonne en dtype 'object' avant d'y injecter une
        # chaîne : les versions récentes de pandas refusent d'insérer une
        # str directement dans une colonne float64 typée.
        df_raw['level'] = df_raw['level'].astype(object)
        df_raw.loc[0, 'level'] = 'texte_invalide'
        df, points, _ = core.parse_multi_piezo_excel(df_raw)
        # La ligne invalide doit avoir été supprimée, pas plantée le parsing
        assert not df['level'].isna().any()

    def test_duplicate_point_date_pairs_are_averaged(self):
        df_raw = _make_raw_df(n_points=3, n_obs=1)
        duplicate_row = df_raw.iloc[[0]].copy()
        duplicate_row['level'] = df_raw.iloc[0]['level'] + 10
        df_raw = pd.concat([df_raw, duplicate_row], ignore_index=True)
        df, _, _ = core.parse_multi_piezo_excel(df_raw)
        pz1_rows = df[df['point'] == 'PZ1']
        assert len(pz1_rows) == 1
        expected_mean = (100.0 + 100.0 + 10) / 2
        assert pz1_rows['level'].iloc[0] == pytest.approx(expected_mean)

    def test_masse_eau_defaults_to_empty_when_column_absent(self):
        df_raw = _make_raw_df(n_points=3, with_masse_eau=False)
        df, _, has_masse = core.parse_multi_piezo_excel(df_raw)
        assert has_masse is False
        assert (df['masse_eau'] == '').all()

    def test_points_are_sorted_alphabetically(self):
        df_raw = _make_raw_df(n_points=3)
        df_raw['point'] = df_raw['point'].replace({'PZ1': 'PZC', 'PZ2': 'PZA', 'PZ3': 'PZB'})
        _, points, _ = core.parse_multi_piezo_excel(df_raw)
        assert points == ['PZA', 'PZB', 'PZC']


# ─────────────────────────────────────────────────────────────────────────
# Parsing des fichiers ADES pipe-séparés : descriptif / chroniques / masses eau
# (align_chronicle, detect_frequency, freq_to_seasonal_periods, future_steps
#  et value_at_date sont testés dans test_chronology.py)
# ─────────────────────────────────────────────────────────────────────────

DESCRIPTIF_CONTENT = textwrap.dedent("""\
    Identifiant national BSS|Dénomination|X_WGS84|Y_WGS84|Masse(s) d'eau
    BSS001|Piezo Un|4,8|45,7|V5#DG240
    BSS002|Piezo Deux|4,9|45,8|V5#DG241
""")

CHRONIQUES_CONTENT = textwrap.dedent("""\
    Identifiant national BSS|Date de la mesure|Côte NGF
    BSS001|01/01/2024|100,5
    BSS001|01/02/2024|101,2
""")

MASSES_EAU_CONTENT = textwrap.dedent("""\
    Identifiant national BSS|Masse eau|Qualité association|Date de début association
    BSS001|Nappe alluviale ancienne|Incertaine|01/01/2010
    BSS001|Nappe alluviale confirmee|Bonne|01/01/2020
    BSS002|Autre nappe|Interprete|01/01/2015
""")


@pytest.fixture
def descriptif_file(tmp_path):
    p = tmp_path / 'descriptif.txt'
    p.write_text(DESCRIPTIF_CONTENT, encoding='utf-8')
    return str(p)


@pytest.fixture
def chroniques_file(tmp_path):
    p = tmp_path / 'chroniques.txt'
    p.write_text(CHRONIQUES_CONTENT, encoding='utf-8')
    return str(p)


@pytest.fixture
def masses_eau_file(tmp_path):
    p = tmp_path / 'MassesEau.txt'
    p.write_text(MASSES_EAU_CONTENT, encoding='utf-8')
    return str(p)


class TestParseDescriptif:
    def test_parses_coordinates_with_comma_decimal(self, descriptif_file):
        result = core.parse_descriptif(descriptif_file)
        assert result['BSS001']['lon'] == pytest.approx(4.8)
        assert result['BSS001']['lat'] == pytest.approx(45.7)

    def test_parses_name_and_raw_masse_eau(self, descriptif_file):
        result = core.parse_descriptif(descriptif_file)
        assert result['BSS002']['name'] == 'Piezo Deux'
        assert result['BSS002']['masse_eau'] == 'V5#DG241'

    def test_raises_if_id_column_missing(self, tmp_path):
        p = tmp_path / 'bad_descriptif.txt'
        p.write_text('Foo|Bar\n1|2\n', encoding='utf-8')
        with pytest.raises(ValueError, match='Colonne ID introuvable'):
            core.parse_descriptif(str(p))


class TestParseChroniquesRaw:
    def test_returns_dataframe_with_original_columns(self, chroniques_file):
        df = core.parse_chroniques_raw(chroniques_file)
        assert 'Identifiant national BSS' in df.columns
        assert 'Date de la mesure' in df.columns
        assert len(df) == 2

    def test_feeds_correctly_into_parse_multi_piezo_excel(self, chroniques_file):
        # Vérifie l'intégration : le format brut lu doit bien être
        # exploitable par find_column() / parse_multi_piezo_excel(), même
        # si ici on n'a qu'un seul point (donc on doit lever ValueError).
        df_raw = core.parse_chroniques_raw(chroniques_file)
        with pytest.raises(ValueError, match='minimum requis'):
            core.parse_multi_piezo_excel(df_raw)


class TestParseMassesEau:
    def test_picks_best_quality_association_per_point(self, masses_eau_file):
        result = core.parse_masses_eau(masses_eau_file)
        # BSS001 a deux lignes : 'Bonne' doit l'emporter sur 'Incertaine'
        assert result['BSS001'] == 'Nappe alluviale confirmee'

    def test_single_row_point_is_kept(self, masses_eau_file):
        result = core.parse_masses_eau(masses_eau_file)
        assert result['BSS002'] == 'Autre nappe'

    def test_raises_if_required_columns_missing(self, tmp_path):
        p = tmp_path / 'bad_masses.txt'
        p.write_text('Foo|Bar\n1|2\n', encoding='utf-8')
        with pytest.raises(ValueError, match='Colonnes attendues introuvables'):
            core.parse_masses_eau(str(p))

