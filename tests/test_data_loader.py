# -*- coding: utf-8 -*-
"""
Tests unitaires pour data/data_loader.py.

Point clé : les fonctions publiques (load_excel, load_chroniques,
load_chroniques_auto, load_descriptif, load_masses_eau) sont décorées
avec @st.cache_data. Pour les tester sans dépendre du système de cache
de Streamlit (qui peut échouer à hasher un faux fichier uploadé "maison"),
on appelle directement l'attribut `.__wrapped__` que Streamlit conserve
automatiquement (via functools.wraps) pour accéder à la fonction
originale, non mise en cache.

Lancer depuis la racine du repo :
    pytest tests/test_data_loader.py -v

Dépendance de test à ajouter (pas dans requirements.txt de l'app) :
    pip install pytest
"""

import io
import os

import pandas as pd
import pytest

from data import data_loader as dl


# ─────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────

class FakeUploadedFile(io.BytesIO):
    """Imite l'objet UploadedFile de Streamlit : un flux d'octets doté
    d'un attribut `.name` et de `.getvalue()` (déjà fourni par BytesIO).
    Suffisant pour pd.read_excel() et pour le code de data_loader.py qui
    accède à `.name` et `.getvalue()`."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def make_excel_bytes(df: pd.DataFrame) -> bytes:
    """Sérialise un DataFrame en octets .xlsx, comme le ferait un vrai
    upload utilisateur."""
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _isolate_tempdir(tmp_path, monkeypatch):
    """Force tempfile.NamedTemporaryFile (utilisé par _parse_from_bytes)
    à écrire dans un dossier temporaire propre à chaque test, pour ne
    jamais dépendre ni polluer le /tmp réel de la machine qui exécute
    les tests."""
    monkeypatch.setattr(dl.tempfile, "tempdir", str(tmp_path))
    yield


# ─────────────────────────────────────────────────────────────────────────
# _parse_from_bytes — le helper interne partagé
# ─────────────────────────────────────────────────────────────────────────

class TestParseFromBytes:

    def test_calls_parse_fn_with_a_readable_temp_path(self):
        """Le chemin passé à parse_fn doit exister et contenir exactement
        les octets fournis, tant que parse_fn s'exécute."""
        captured = {}

        def fake_parse_fn(path):
            captured["path_existed"] = os.path.exists(path)
            with open(path, "rb") as f:
                captured["content"] = f.read()
            return "résultat"

        result = dl._parse_from_bytes(b"contenu de test", fake_parse_fn)

        assert result == "résultat"
        assert captured["path_existed"] is True
        assert captured["content"] == b"contenu de test"

    def test_removes_temp_file_after_success(self):
        captured_path = {}

        def fake_parse_fn(path):
            captured_path["path"] = path
            return None

        dl._parse_from_bytes(b"peu importe", fake_parse_fn)

        assert not os.path.exists(captured_path["path"])

    def test_removes_temp_file_even_if_parse_fn_raises(self):
        """Le `finally` doit nettoyer le fichier temporaire même en cas
        d'exception dans parse_fn, et l'exception doit toujours se
        propager à l'appelant."""
        captured_path = {}

        def failing_parse_fn(path):
            captured_path["path"] = path
            raise ValueError("format invalide")

        with pytest.raises(ValueError, match="format invalide"):
            dl._parse_from_bytes(b"peu importe", failing_parse_fn)

        assert not os.path.exists(captured_path["path"])


# ─────────────────────────────────────────────────────────────────────────
# load_excel
# ─────────────────────────────────────────────────────────────────────────

class TestLoadExcel:

    def test_returns_dataframe_and_filename(self):
        original = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        fake_file = FakeUploadedFile(make_excel_bytes(original), "chroniques.xlsx")

        df, file_name = dl.load_excel.__wrapped__(fake_file)

        pd.testing.assert_frame_equal(df, original)
        assert file_name == "chroniques.xlsx"

    def test_filename_falls_back_to_str_when_no_name_attribute(self):
        """`getattr(uploaded_file, "name", str(uploaded_file))` : sans
        attribut .name, on retombe sur str(objet)."""
        original = pd.DataFrame({"a": [1]})
        plain_bytesio = io.BytesIO(make_excel_bytes(original))  # pas de .name

        _, file_name = dl.load_excel.__wrapped__(plain_bytesio)

        assert file_name == str(plain_bytesio)


# ─────────────────────────────────────────────────────────────────────────
# load_chroniques — export ADES brut (chroniques.txt), pipe-séparé
# ─────────────────────────────────────────────────────────────────────────

class TestLoadChroniques:

    def test_delegates_to_core_parse_chroniques_raw(self, monkeypatch):
        expected_df = pd.DataFrame({"point": ["P1"], "level": [12.3]})
        captured = {}

        def fake_parse_chroniques_raw(path):
            captured["content"] = open(path, "rb").read()
            return expected_df

        monkeypatch.setattr(dl.core, "parse_chroniques_raw", fake_parse_chroniques_raw)

        fake_file = FakeUploadedFile(b"donnees|pipe|separees", "chroniques.txt")
        df, file_name = dl.load_chroniques.__wrapped__(fake_file)

        pd.testing.assert_frame_equal(df, expected_df)
        assert file_name == "chroniques.txt"
        assert captured["content"] == b"donnees|pipe|separees"


# ─────────────────────────────────────────────────────────────────────────
# load_descriptif — coordonnées / nom / masse d'eau par point
# ─────────────────────────────────────────────────────────────────────────

class TestLoadDescriptif:

    def test_delegates_to_core_parse_descriptif(self, monkeypatch):
        expected = {"P1": {"lat": 45.7, "lon": 4.8, "masse_eau": "FRDG123"}}

        def fake_parse_descriptif(path):
            return expected

        monkeypatch.setattr(dl.core, "parse_descriptif", fake_parse_descriptif)

        result = dl.load_descriptif.__wrapped__(b"peu importe le contenu")

        assert result == expected


# ─────────────────────────────────────────────────────────────────────────
# load_masses_eau — libellés fiables des masses d'eau
# ─────────────────────────────────────────────────────────────────────────

class TestLoadMassesEau:

    def test_delegates_to_core_parse_masses_eau(self, monkeypatch):
        expected = {"P1": "Alluvions du Rhône"}

        def fake_parse_masses_eau(path):
            return expected

        monkeypatch.setattr(dl.core, "parse_masses_eau", fake_parse_masses_eau)

        result = dl.load_masses_eau.__wrapped__(b"peu importe le contenu")

        assert result == expected


# ─────────────────────────────────────────────────────────────────────────
# load_chroniques_auto — détection auto de format + nettoyage
# ─────────────────────────────────────────────────────────────────────────

class TestLoadChroniquesAutoExcel:

    def test_reads_xlsx_and_returns_filename(self):
        raw = pd.DataFrame({
            "Côte NGF": ["123,45", "124,10"],
            "Date de la mesure": ["01/03/2020", "02/03/2020"],
        })
        fake_file = FakeUploadedFile(make_excel_bytes(raw), "export.xlsx")

        df, file_name = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert file_name == "export.xlsx"
        assert len(df) == 2

    def test_strips_whitespace_from_column_headers(self):
        raw = pd.DataFrame({"  Côte NGF  ": ["123,45"]})
        fake_file = FakeUploadedFile(make_excel_bytes(raw), "export.xlsx")

        df, _ = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert "Côte NGF" in df.columns
        assert "  Côte NGF  " not in df.columns

    def test_converts_comma_decimal_numeric_columns_to_float(self):
        raw = pd.DataFrame({
            "Côte NGF": ["123,45", "124,10"],
            "X_WGS84": ["4,8357", "4,8360"],
        })
        fake_file = FakeUploadedFile(make_excel_bytes(raw), "export.xlsx")

        df, _ = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert df["Côte NGF"].tolist() == pytest.approx([123.45, 124.10])
        assert df["X_WGS84"].tolist() == pytest.approx([4.8357, 4.8360])
        assert pd.api.types.is_numeric_dtype(df["Côte NGF"])

    def test_parses_french_dates_and_sorts_chronologically(self):
        raw = pd.DataFrame({
            "Date de la mesure": ["15/03/2021", "01/01/2021", "20/06/2021"],
            "Côte NGF": ["100,0", "101,0", "102,0"],
        })
        fake_file = FakeUploadedFile(make_excel_bytes(raw), "export.xlsx")

        df, _ = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert pd.api.types.is_datetime64_any_dtype(df["Date de la mesure"])
        assert df["Date de la mesure"].is_monotonic_increasing
        # La ligne la plus ancienne (01/01/2021, Côte NGF=101,0) doit être
        # passée en tête après le tri chronologique.
        assert df.iloc[0]["Côte NGF"] == pytest.approx(101.0)

    def test_drops_rows_with_unparseable_date(self):
        raw = pd.DataFrame({
            "Date de la mesure": ["15/03/2021", "date-invalide", "01/01/2021"],
            "Côte NGF": ["100,0", "999,0", "101,0"],
        })
        fake_file = FakeUploadedFile(make_excel_bytes(raw), "export.xlsx")

        df, _ = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert len(df) == 2
        assert 999.0 not in df["Côte NGF"].values


class TestLoadChroniquesAutoTxt:

    def test_reads_tab_separated_utf8_txt(self):
        content = "Côte NGF\tDate de la mesure\n123,45\t01/03/2020\n".encode("utf-8")
        fake_file = FakeUploadedFile(content, "export.txt")

        df, file_name = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert file_name == "export.txt"
        assert len(df) == 1
        assert df.iloc[0]["Côte NGF"] == pytest.approx(123.45)

    def test_falls_back_to_latin1_when_utf8_decoding_fails(self):
        # "é" encodé en latin-1 (0xE9) n'est pas un octet UTF-8 valide en
        # position isolée : la tentative utf-8 doit échouer, puis
        # latin-1 doit réussir et lire correctement l'en-tête accentué.
        header = "Côte NGF\tPoint\n"
        row = "123,45\tPiézomètre\n"
        content = (header + row).encode("latin-1")
        fake_file = FakeUploadedFile(content, "export_latin1.txt")

        df, _ = dl.load_chroniques_auto.__wrapped__(fake_file)

        assert "Côte NGF" in df.columns
        assert len(df) == 1

    def test_raises_value_error_for_unsupported_extension(self):
        fake_file = FakeUploadedFile(b"peu importe", "export.csv")

        with pytest.raises(ValueError, match="Format non supporté"):
            dl.load_chroniques_auto.__wrapped__(fake_file)

    def test_filename_fallback_without_name_attribute_raises_value_error(self):
        """Sans attribut .name, file_name devient str(objet) : son
        extension est vide, donc ValueError attendu (comportement
        actuel du code, pas un bug — juste à documenter par un test)."""
        plain_bytesio = io.BytesIO(b"peu importe")

        with pytest.raises(ValueError, match="Format non supporté"):
            dl.load_chroniques_auto.__wrapped__(plain_bytesio)

