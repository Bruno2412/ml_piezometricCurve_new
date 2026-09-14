# -*- coding: utf-8 -*-
"""
Tests unitaires pour piezo_core._read_ades_pipe_file().

Cette fonction est jusqu'ici seulement testée indirectement, via
parse_descriptif() / parse_chroniques_raw() / parse_masses_eau() dans
test_parsing.py, avec des fichiers en utf-8. On teste ici directement
sa logique propre : la boucle de fallback d'encodage (utf-8-sig ->
cp1252 -> latin-1), le nettoyage des noms de colonnes via _clean_str(),
et le cas où aucun encodage ne fonctionne.

Lancer avec :
    pytest tests/test_ades_pipe_file.py -v
"""

import pytest

import piezo_core as core


CONTENT_ASCII = "Identifiant national BSS|Côte NGF\nBSS001|100,5\n"


class TestReadAdesPipeFile:
    def test_reads_utf8_sig_file(self, tmp_path):
        p = tmp_path / "utf8.txt"
        p.write_bytes(CONTENT_ASCII.encode("utf-8-sig"))
        df = core._read_ades_pipe_file(str(p))
        assert list(df.columns) == ["Identifiant national BSS", "Côte NGF"]
        assert df.iloc[0]["Identifiant national BSS"] == "BSS001"

    def test_falls_back_to_cp1252_when_not_utf8(self, tmp_path):
        # Caractère accentué encodé en cp1252, invalide en utf-8-sig strict.
        content = "Identifiant national BSS|Dénomination\nBSS001|Piézomètre Nord\n"
        p = tmp_path / "cp1252.txt"
        p.write_bytes(content.encode("cp1252"))
        df = core._read_ades_pipe_file(str(p))
        assert df.iloc[0]["Dénomination"] == "Piézomètre Nord"

    def test_falls_back_to_latin1_as_last_resort(self, tmp_path, monkeypatch):
        # Force l'échec de cp1252 pour vérifier que latin-1 est bien
        # tenté en dernier recours (latin-1 ne lève jamais d'erreur de
        # décodage, quel que soit le contenu binaire).
        content = "Identifiant national BSS|Dénomination\nBSS001|Piezo\n"
        p = tmp_path / "latin1.txt"
        p.write_bytes(content.encode("latin-1"))

        import pandas as pd
        original_read_csv = pd.read_csv

        def _fake_read_csv(*args, **kwargs):
            if kwargs.get("encoding") == "cp1252":
                raise UnicodeDecodeError("cp1252", b"", 0, 1, "échec forcé")
            return original_read_csv(*args, **kwargs)

        monkeypatch.setattr(core.pd, "read_csv", _fake_read_csv)
        df = core._read_ades_pipe_file(str(p))
        assert df.iloc[0]["Identifiant national BSS"] == "BSS001"

    def test_raises_value_error_when_all_encodings_fail(self, tmp_path, monkeypatch):
        p = tmp_path / "unreadable.txt"
        p.write_text("peu importe le contenu", encoding="utf-8")

        def _always_fail(*args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "échec forcé")

        monkeypatch.setattr(core.pd, "read_csv", _always_fail)
        with pytest.raises(ValueError, match="Impossible de décoder"):
            core._read_ades_pipe_file(str(p))

    def test_strips_bom_from_column_names(self, tmp_path):
        p = tmp_path / "bom.txt"
        p.write_bytes(CONTENT_ASCII.encode("utf-8-sig"))
        df = core._read_ades_pipe_file(str(p))
        # _clean_str() doit avoir retiré le BOM du nom de la première colonne.
        assert not df.columns[0].startswith("\ufeff")

    def test_pipe_is_the_only_separator_quotes_are_literal(self, tmp_path):
        # quoting=csv.QUOTE_NONE : un guillemet dans une valeur doit être
        # conservé tel quel, pas interprété comme un délimiteur de champ.
        content = 'Identifiant national BSS|Dénomination\nBSS001|Piézo "Nord"\n'
        p = tmp_path / "quotes.txt"
        p.write_bytes(content.encode("utf-8-sig"))
        df = core._read_ades_pipe_file(str(p))
        assert df.iloc[0]["Dénomination"] == 'Piézo "Nord"'
