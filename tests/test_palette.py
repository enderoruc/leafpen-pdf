"""Command palette matching (no window needed)."""
from dataclasses import dataclass

from leafpen.ui.palette import Command, _clean, rank


@dataclass
class _Action:  # stands in for QAction; rank() only looks at titles and paths
    name: str


def _commands(*items):
    return [Command(title, path, "", _Action(title)) for title, path in items]


CMDS = _commands(
    ("Filigran ekle…", "Belge"),
    ("Sayfaları kırp", "Belge"),
    ("Kırpmayı kaldır (seçili sayfalar)", "Belge"),
    ("İmzaları doğrula", "İmzalar"),
    ("Aç…", "Dosya"),
    ("Profile", "Help"),
)


def titles(query):
    return [c.title for c in rank(CMDS, query)]


def test_every_word_must_match_and_case_and_dotless_i_are_ignored():
    assert titles("FİLİGRAN") == ["Filigran ekle…"]
    assert titles("imza") == ["İmzaları doğrula"]  # İ / i
    assert titles("kirp") == titles("kırp")  # typed without Turkish letters
    assert titles("imzalari dogrula") == ["İmzaları doğrula"]
    assert titles("sayfalari") == ["Sayfaları kırp"]  # "sayfalar" alone is not enough
    assert titles("kırp sayfa") == ["Sayfaları kırp", "Kırpmayı kaldır (seçili sayfalar)"]
    assert titles("belge") == ["Filigran ekle…", "Sayfaları kırp", "Kırpmayı kaldır (seçili sayfalar)"]
    assert titles("") == [c.title for c in CMDS]
    assert titles("yok böyle") == []


def test_title_prefix_ranks_first():
    # "kırp" starts "Kırpmayı…" but is only a later word in "Sayfaları kırp"
    assert titles("kırp")[0] == "Kırpmayı kaldır (seçili sayfalar)"


def test_clean_removes_accelerators():
    assert _clean("&Dosya") == "Dosya"
    assert _clean("A && B") == "A & B"
    assert _clean("Son &açılanlar") == "Son açılanlar"
