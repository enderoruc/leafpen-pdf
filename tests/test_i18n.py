import ast
from pathlib import Path

import pytest

from leafpen import i18n
from leafpen.lang import tr as turkish

SRC = Path(__file__).resolve().parents[1] / "leafpen"


def _literal(node) -> str | None:
    """Value of a string literal, including implicit concatenation and conditional parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _source_keys() -> set[str]:
    keys = set()
    for path in SRC.rglob("*.py"):
        if "lang" in path.parts or path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args):
                value = _literal(node.args[0])
                assert value is not None, f"{path.name}:{node.lineno}: tr() needs a string literal"
                keys.add(value)
    return keys


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    i18n.set_language("en")


def test_every_source_string_has_a_turkish_translation():
    missing = sorted(_source_keys() - set(turkish.MESSAGES))
    assert not missing, f"untranslated strings: {missing}"


def test_catalog_has_no_unused_entries():
    unused = sorted(set(turkish.MESSAGES) - _source_keys())
    assert not unused, f"unused catalog entries: {unused}"


def test_placeholders_match_between_languages():
    import string

    def fields(text):
        return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}

    for source, translated in turkish.MESSAGES.items():
        assert fields(source) == fields(translated), source


def test_translation_and_fallback():
    i18n.set_language("tr")
    assert i18n.tr("Save") == "Kaydet"
    assert i18n.tr("Page {page} / {total}", page=2, total=5) == "Sayfa 2 / 5"
    assert i18n.tr("not in the catalog") == "not in the catalog"  # falls back to the source text
    i18n.set_language("en")
    assert i18n.tr("Save") == "Save"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("xx")
    assert i18n.language() == "en"


@pytest.mark.parametrize("preference, system, expected", [
    ("system", ["tr-TR", "en-US"], "tr"),
    ("system", ["en-US"], "en"),
    ("system", ["de-DE", "tr-TR"], "en"),  # only the first UI language counts
    ("system", [], "en"),
    ("tr", ["en-US"], "tr"),
    ("en", ["tr-TR"], "en"),
    ("garbage", ["tr_TR"], "tr"),
])
def test_resolve(preference, system, expected):
    assert i18n.resolve(preference, system) == expected


def test_errors_follow_the_active_language(pdf_bytes):
    from leafpen.core.document import PdfDocument, PdfError

    doc = PdfDocument(pdf_bytes)
    with pytest.raises(PdfError) as en:
        doc.delete_pages([0])
    i18n.set_language("tr")
    with pytest.raises(PdfError) as tr_:
        doc.delete_pages([0])
    assert str(en.value) != str(tr_.value)
    assert "silinemez" in str(tr_.value)
