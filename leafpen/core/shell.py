"""Windows Explorer integration: "Open with" for PDF files, plus desktop and Start menu shortcuts.

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


# ---- shortcuts (.lnk) on the desktop and in the Start menu -------------------------
# Written through the Windows Shell's own IShellLink COM object via ctypes, so no pywin32
# is needed. Only the current user's folders are used: no administrator rights.

SHORTCUT_PLACES = {"desktop": 0x0010, "start_menu": 0x0002}  # CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS
_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
# vtable slots (IUnknown takes 0-2)
_GET_PATH, _SET_DESCRIPTION, _SET_WORKING_DIR, _SET_ICON, _SET_PATH = 3, 7, 9, 17, 20
_QUERY_INTERFACE, _RELEASE, _LOAD, _SAVE = 0, 2, 5, 6


def shortcut_path(place: str, app_name: str) -> str:
    """Where our shortcut lives for `place` ("desktop" or "start_menu"): the folder plus "<app_name>.lnk"."""
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.oledll.shell32.SHGetFolderPathW(None, SHORTCUT_PLACES[place], None, 0, buf)
    return os.path.join(buf.value, f"{app_name}.lnk")


class _Com:
    """A raw COM interface pointer: call its vtable slots, release it when done."""

    def __init__(self, ptr):
        self.ptr = ptr

    def call(self, slot, *args, argtypes=()):
        import ctypes
        vtable = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])(self.ptr, *args)

    def query(self, iid: str) -> _Com:
        import ctypes
        out = ctypes.c_void_p()
        self.call(_QUERY_INTERFACE, ctypes.byref(_guid(iid)), ctypes.byref(out),
                  argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        return _Com(out)

    def release(self):
        import ctypes
        vtable = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])(self.ptr)


def _guid(text: str):
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _with_shell_link(work):
    """Run work(shell_link, persist_file) on a fresh ShellLink object, with COM initialised."""
    import ctypes
    ole32 = ctypes.windll.ole32
    initialised = ole32.CoInitializeEx(None, 0x2) >= 0  # STA; already initialised by Qt is fine too
    link = persist = None
    try:
        ptr = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_SHELL_LINK)), None, 1,  # in-process
                                             ctypes.byref(_guid(_IID_SHELL_LINK_W)), ctypes.byref(ptr))
        link = _Com(ptr)
        persist = link.query(_IID_PERSIST_FILE)
        return work(link, persist)
    finally:
        for obj in (persist, link):
            if obj is not None:
                obj.release()
        if initialised:
            ole32.CoUninitialize()


def create_shortcut(lnk: str, exe: str, description: str) -> None:
    """Write (or overwrite) a shortcut at `lnk` that starts `exe` with its own icon."""
    import ctypes
    wstr = (ctypes.c_wchar_p,)

    def work(link, persist):
        link.call(_SET_PATH, exe, argtypes=wstr)
        link.call(_SET_WORKING_DIR, os.path.dirname(exe), argtypes=wstr)
        link.call(_SET_ICON, exe, 0, argtypes=(ctypes.c_wchar_p, ctypes.c_int))
        link.call(_SET_DESCRIPTION, description, argtypes=wstr)
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        persist.call(_SAVE, lnk, True, argtypes=(ctypes.c_wchar_p, ctypes.c_int))
    _with_shell_link(work)


def shortcut_target(lnk: str) -> str | None:
    """The program a shortcut starts, or None if there is no shortcut at `lnk`."""
    if not os.path.isfile(lnk):
        return None
    import ctypes

    def work(link, persist):
        persist.call(_LOAD, lnk, 0, argtypes=(ctypes.c_wchar_p, ctypes.c_ulong))  # STGM_READ
        buf = ctypes.create_unicode_buffer(32768)
        link.call(_GET_PATH, buf, len(buf), None, 0x4,  # SLGP_RAWPATH: as stored, no searching
                  argtypes=(ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong))
        return buf.value or None
    return _with_shell_link(work)


def remove_shortcut(lnk: str) -> None:
    try:
        os.remove(lnk)
    except FileNotFoundError:
        pass


def same_path(a: str, b: str) -> bool:
    """Same file, even when one is spelled with short 8.3 names (PROGRA~1) or different case."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def shortcut_is_ours(lnk: str, exe: str) -> bool:
    target = shortcut_target(lnk)
    return target is not None and same_path(target, exe)


def refresh_shortcut_if_moved(lnk: str, exe: str, description: str) -> bool:
    """Like `refresh_if_moved`, for a shortcut: re-point it only if its old target is gone. True if updated."""
    old = shortcut_target(lnk)
    if old is None or same_path(old, exe) or os.path.exists(old):
        return False
    if os.path.basename(old).lower() != EXE_NAME.lower():
        return False  # a shortcut of the same name to some other program: not ours to change
    create_shortcut(lnk, exe, description)
    return True
