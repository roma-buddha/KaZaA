"""Persistent application settings (JSON)."""
import json
import os

APP_NAME = "VLoader"
ORG = "VLoader"

DEFAULTS = {
    "save_to": "",                      # download output directory ("" = <Videos>/VLoader)
    "download_quality": "best",         # best | 1080 | 720 | 480 | 360 | 240 | worst
    "spotify_format": "mp3",            # mp3 (320k) | flac (lossless) | wav
    "simultaneous_downloads": 3,
    "simultaneous_converts": 2,
    "auto_convert_to": "",              # "" = off, else target format e.g. "mp4"
    "conversion_quality": "normal",     # high | normal | low
    "delete_original_after_conversion": False,
    "open_folder_after_download": False,
    "after_done": "nothing",            # nothing | exit | shutdown | restart | logoff | hibernate | standby
    "language": "en",
    "yt_cookies": "",                   # "" off | chrome | edge | firefox —
                                        # sign-in cookies for YouTube bot checks
    "extensions_enabled": True,
    "recorder_audio": True,
    "recorder_framerate": 30,
    "window_geometry": "",
}


def config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def settings_path():
    return os.path.join(config_dir(), "settings.json")


class Settings:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(settings_path(), "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def save(self):
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self._data[key] = value

    def download_dir(self):
        d = self.get("save_to")
        if not d:
            d = os.path.join(os.path.expanduser("~"), "Videos", APP_NAME)
        os.makedirs(d, exist_ok=True)
        return d
