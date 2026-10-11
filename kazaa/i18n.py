"""Minimal i18n: JSON dictionaries per language, English fallback."""
import json
import os

_LANGS = {
    "en": "English", "ar": "العربية", "bg": "Български", "zh_CN": "简体中文",
    "zh_TW": "繁體中文", "cz": "Čeština", "de": "Deutsch", "es": "Español",
    "fi": "Suomi", "it": "Italiano", "ku": "Kurdî", "nl": "Nederlands",
    "pl": "Polski", "pt": "Português", "ru": "Русский", "tr": "Türkçe",
}

_cache = {}
_current = "en"


def languages():
    return dict(_LANGS)


def set_language(code):
    global _current
    _current = code if code in _LANGS else "en"


def _load(code):
    if code in _cache:
        return _cache[code]
    path = os.path.join(os.path.dirname(__file__), "i18n", f"{code}.json")
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    _cache[code] = data
    return data


def tr(key, **kwargs):
    """Translate key; fall back to English, then to the key itself."""
    text = _load(_current).get(key) or _load("en").get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
