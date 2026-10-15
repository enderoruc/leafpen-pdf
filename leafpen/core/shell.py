"""Windows Explorer integration: list the app under "Open with" for PDF files.

Only the current user's registry (HKCU) is written, so no administrator rights are
needed, and the default PDF program is never changed: Windows lets only the user
choose that. Everything written here is removed again by `unregister`.
"""
from __future__ import annotations

import os
import sys

PROGID = "LeafpenPDF.Document"
EXE_NAME = "LeafpenPDF.exe"
CLASSES = r"Software\Classes"


def supported() -> bool:
    return sys.platform == "win32"


def current_exe() -> str | None:
    """Path of the packaged executable, or None when running from source (python.exe)."""
    return os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else None


def entries(exe: str, app_name: str) -> list[tuple[str, str, str]]:
    """(subkey under the classes root, value name ("" = default), data) to write."""
    command = f'"{exe}" "%1"'
    icon = f'"{exe}",0'
    app = rf"Applications\{EXE_NAME}"
    return [
        (PROGID, "", f"{app_name} PDF"),
        (rf"{PROGID}\DefaultIcon", "", icon),
        (rf"{PROGID}\shell\open\command", "", command),
        (r".pdf\OpenWithProgids", PROGID, ""),
        (app, "FriendlyAppName", app_name),
        (rf"{app}\SupportedTypes", ".pdf", ""),
        (rf"{app}\DefaultIcon", "", icon),
        (rf"{app}\shell\open\command", "", command),
    ]


def _notify_explorer():
    try:
        import ctypes
        SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except (AttributeError, OSError):
        pass


def register(exe: str, app_name: str, root: str = CLASSES) -> None:
    import winreg
    for subkey, name, data in entries(exe, app_name):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{subkey}", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)
    if root == CLASSES:
        _notify_explorer()


def _delete_tree(path: str) -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def unregister(root: str = CLASSES) -> None:
    """Remove exactly what `register` wrote; .pdf's other "Open with" entries are left alone."""
    import winreg
    _delete_tree(rf"{root}\{PROGID}")
    _delete_tree(rf"{root}\Applications\{EXE_NAME}")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\.pdf\OpenWithProgids", 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, PROGID)
    except FileNotFoundError:
        pass
    if root == CLASSES:
        _notify_explorer()


def registered_exe(root: str = CLASSES) -> str | None:
    """The executable our "Open with" entry starts, or None if there is no entry."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{PROGID}\shell\open\command") as key:
            command, _type = winreg.QueryValueEx(key, "")
    except FileNotFoundError:
        return None
    return command.split('"')[1] if command.startswith('"') else command.split()[0]


def refresh_if_moved(exe: str, app_name: str, root: str = CLASSES) -> bool:
    """The portable folder was moved: point an existing entry at the new location. Returns True if updated."""
    old = registered_exe(root)
    if old is None or os.path.normcase(old) == os.path.normcase(exe) or os.path.exists(old):
        return False
    register(exe, app_name, root)
    return True
