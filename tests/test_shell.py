"""Explorer integration: "Open with" against a private test key (never the real file associations),
and shortcuts in temporary folders (never the real desktop or Start menu)."""
import sys
import uuid

import pytest

from leafpen.core import shell

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")


@pytest.fixture
def root():
    import winreg
    base = rf"Software\LeafpenTest-{uuid.uuid4().hex}"
    yield rf"{base}\Classes"
    shell._delete_tree(base)
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)


def _value(path, name=""):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        return winreg.QueryValueEx(key, name)[0]


def test_register_and_unregister(root):
    import winreg
    exe = r"C:\Apps\Leafpen PDF\LeafpenPDF.exe"
    # another program's "Open with" entry must survive our unregister
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\.pdf\OpenWithProgids") as key:
        winreg.SetValueEx(key, "Other.Reader", 0, winreg.REG_SZ, "")

    assert shell.registered_exe(root) is None
    shell.register(exe, "Leafpen PDF", root)
    assert shell.registered_exe(root) == exe
    assert _value(rf"{root}\{shell.PROGID}\shell\open\command") == f'"{exe}" "%1"'
    assert _value(rf"{root}\.pdf\OpenWithProgids", shell.PROGID) == ""
    assert _value(rf"{root}\Applications\LeafpenPDF.exe", "FriendlyAppName") == "Leafpen PDF"

    shell.unregister(root)
    assert shell.registered_exe(root) is None
    assert _value(rf"{root}\.pdf\OpenWithProgids", "Other.Reader") == ""
    with pytest.raises(FileNotFoundError):
        _value(rf"{root}\.pdf\OpenWithProgids", shell.PROGID)
    shell.unregister(root)  # unregistering twice is harmless


def test_moved_folder_is_followed(root, tmp_path):
    old = str(tmp_path / "old" / "LeafpenPDF.exe")  # no longer exists
    new = str(tmp_path / "new" / "LeafpenPDF.exe")
    assert not shell.refresh_if_moved(new, "Leafpen PDF", root)  # nothing registered: nothing to do
    shell.register(old, "Leafpen PDF", root)
    assert shell.refresh_if_moved(new, "Leafpen PDF", root)
    assert shell.registered_exe(root) == new
    # an entry for another copy that still exists is not taken over
    other = tmp_path / "other.exe"
    other.write_bytes(b"")
    shell.register(str(other), "Leafpen PDF", root)
    assert not shell.refresh_if_moved(new, "Leafpen PDF", root)
    assert shell.registered_exe(root) == str(other)


def test_shortcut_create_read_remove(tmp_path):
    lnk = str(tmp_path / "Start Menu" / "Leafpen PDF.lnk")  # missing folder is created
    exe = str(tmp_path / "Leafpen PDF" / "LeafpenPDF.exe")
    assert shell.shortcut_target(lnk) is None
    shell.create_shortcut(lnk, exe, "Leafpen PDF")
    assert shell.shortcut_target(lnk) == exe
    assert shell.shortcut_is_ours(lnk, exe)
    assert not shell.shortcut_is_ours(lnk, str(tmp_path / "other" / "LeafpenPDF.exe"))
    shell.remove_shortcut(lnk)
    assert shell.shortcut_target(lnk) is None
    shell.remove_shortcut(lnk)  # removing twice is harmless


def test_shortcut_follows_moved_folder(tmp_path):
    lnk = str(tmp_path / "Leafpen PDF.lnk")
    old = str(tmp_path / "old" / "LeafpenPDF.exe")  # no longer exists
    new = str(tmp_path / "new" / "LeafpenPDF.exe")
    assert not shell.refresh_shortcut_if_moved(lnk, new, "Leafpen PDF")  # no shortcut: nothing to do
    shell.create_shortcut(lnk, old, "Leafpen PDF")
    assert shell.refresh_shortcut_if_moved(lnk, new, "Leafpen PDF")
    assert shell.shortcut_target(lnk) == new
    # a same-named shortcut to another program is left alone
    shell.create_shortcut(lnk, str(tmp_path / "gone" / "Other.exe"), "Other")
    assert not shell.refresh_shortcut_if_moved(lnk, new, "Leafpen PDF")


def test_shortcut_folders_are_the_users():
    import os
    for place in shell.SHORTCUT_PLACES:
        path = shell.shortcut_path(place, "Leafpen PDF")
        assert path.endswith(r"\Leafpen PDF.lnk") and os.path.isdir(os.path.dirname(path))
