"""Tiny file logger for diagnosing the frozen app (no console)."""
import os
import time
from .settings import config_dir

_path = os.path.join(config_dir(), "debug.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass
