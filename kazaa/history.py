"""Download / conversion history, persisted as JSON."""
import json
import os
import time

from .settings import config_dir


class History:
    def __init__(self, limit=500):
        self.path = os.path.join(config_dir(), "history.json")
        self.limit = limit
        self.items = []
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.items = json.load(f)
        except (OSError, ValueError):
            self.items = []

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.items[-self.limit:], f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def add(self, kind, name, url="", output="", status="started", size=0):
        self.items.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind, "name": name, "url": url,
            "output": output, "status": status, "size": size,
        })
        self.save()

    def update_last(self, **fields):
        if self.items:
            self.items[-1].update(fields)
            self.save()
