"""Minimal translation layer.

Source strings are English. `tr()` returns the translation for the active
language and falls back to the English text, so a missing entry is never fatal.
Catalogs live in `leafpen.lang`; add a language by adding a module there and
registering it in `LANGUAGES` and `_CATALOGS`.
"""
from __future__ import annotations

import datetime

from .lang import tr as _tr

# code -> name shown in the language menu (always written in the language itself)
LANGUAGES = {"en": "English", "tr": "Türkçe"}
_CATALOGS = {"tr": _tr.MESSAGES}

_current = "en"


def resolve(preference: str, system_languages: list[str]) -> str:
    """Pick a language code: an explicit choice, else the system UI language, else English."""
    if preference in LANGUAGES:
        return preference
    if system_languages:
        code = system_languages[0].replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def language() -> str:
    return _current


def tr(text: str, **kwargs) -> str:
    """Translate `text`; `{name}` placeholders are filled from `kwargs`."""
    out = _CATALOGS.get(_current, {}).get(text, text)
    return out.format(**kwargs) if kwargs else out


def fmt_date(value: datetime.date) -> str:
    return f"{value:%d.%m.%Y}" if _current == "tr" else f"{value:%Y-%m-%d}"


def fmt_datetime(value: datetime.datetime) -> str:
    return f"{value:%d.%m.%Y %H:%M}" if _current == "tr" else f"{value:%Y-%m-%d %H:%M}"
