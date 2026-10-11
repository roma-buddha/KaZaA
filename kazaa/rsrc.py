"""Resource paths that work from source and from the PyInstaller bundle."""
import os
import sys

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ui", "assets")


def asset(name):
    """Absolute path to a bundled UI asset (logo, icon, ...)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "kazaa", "ui", "assets", name)
        if os.path.exists(p):
            return p
    return os.path.join(_ASSETS, name)
