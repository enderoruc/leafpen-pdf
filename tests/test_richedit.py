"""The on-page text box: formatting with nothing selected applies to the whole text."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leafpen.core.richtext import TextStyle  # noqa: E402
from leafpen.ui.richedit import InlineTextEditor  # noqa: E402


@pytest.fixture(scope="module")
def page():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    w = QWidget(host)
    w.resize(800, 600)
    yield w
    host.deleteLater()
    app.processEvents()


def editor(page, zoom=1.0):
    return InlineTextEditor(page, zoom, 10, 10, 300, [], TextStyle(size=12), paragraph=True,
                            on_commit=lambda r: None)


@pytest.mark.parametrize("zoom", [1.0, 0.2])
def test_size_without_selection_applies_to_typed_text(page, zoom):
    ed = editor(page, zoom)
    ed.box.insertPlainText("Merhaba")
    ed.apply(size=60)
    ed.box.insertPlainText(" dünya")
    sizes = {r.style.size for r in ed.result().runs}
    assert sizes == {60}
    ed.cancel()


def test_size_set_before_typing_survives(page):
    ed = editor(page)
    ed.apply(size=40)
    ed.box.setTextCursor(ed.box.cursorForPosition(ed.box.rect().center()))  # like clicking into the box
    ed.box.insertPlainText("Test")
    assert {r.style.size for r in ed.result().runs} == {40}
    ed.cancel()


def test_size_with_selection_changes_only_selection(page):
    ed = editor(page)
    ed.box.insertPlainText("ab")
    c = ed.box.textCursor()
    c.setPosition(0)
    c.setPosition(1, c.MoveMode.KeepAnchor)
    ed.box.setTextCursor(c)
    ed.apply(size=30)
    assert [(r.text, r.style.size) for r in ed.result().runs] == [("a", 30), ("b", 12)]
    ed.cancel()
