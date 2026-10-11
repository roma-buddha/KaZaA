"""Offline checks for the project rename and existing application data."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kazaa import VERSION, __main__, i18n
from kazaa.settings import Settings, config_dir


class BrandingTests(unittest.TestCase):
    def test_existing_data_is_copied_and_preserved(self):
        with tempfile.TemporaryDirectory() as base:
            legacy = Path(base, "VLoader")
            legacy.mkdir()
            data = {
                "settings.json": {"language": "es", "save_to": "existing-output"},
                "history.json": [{"name": "existing download"}],
                "live_registry.json": {"existing.part": {}},
            }
            for name, value in data.items():
                (legacy / name).write_text(json.dumps(value), encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": base}):
                settings = Settings()
                self.assertEqual(settings.get("language"), "es")
                self.assertEqual(settings.get("save_to"), "existing-output")
                migrated = Path(config_dir())
                self.assertEqual(migrated.name, "KazaA")
                for name in data:
                    self.assertEqual((legacy / name).read_bytes(),
                                     (migrated / name).read_bytes())

    def test_existing_new_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as base:
            for name, language in [("VLoader", "es"), ("KazaA", "de")]:
                directory = Path(base, name)
                directory.mkdir()
                (directory / "settings.json").write_text(
                    json.dumps({"language": language}), encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": base}):
                self.assertEqual(Settings().get("language"), "de")

    def test_fresh_download_folder_uses_new_name(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.dict(os.environ, {"APPDATA": str(Path(base, "config"))}), \
                    patch("kazaa.settings.os.path.expanduser", return_value=base):
                self.assertEqual(Settings().download_dir(),
                                 str(Path(base, "Videos", "KazaA")))

    def test_every_language_has_new_title_and_about_name(self):
        try:
            for language in i18n.languages():
                i18n.set_language(language)
                self.assertTrue(i18n.tr("app_title").startswith("KazaA v2. revival"))
                self.assertIn("KazaA v2. revival", i18n.tr("m_about"))
        finally:
            i18n.set_language("en")

    def test_cli_version_does_not_require_gui_dependencies(self):
        output = io.StringIO()
        with patch.object(__main__, "_redirect_stderr"), \
                contextlib.redirect_stdout(output):
            self.assertEqual(__main__.main(["--version"]), 0)
        self.assertEqual(output.getvalue().strip(), f"KazaA v2. revival {VERSION}")

    def test_plugin_instructions_point_to_repository(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(__main__._plugin_instructions(), 0)
            self.assertEqual(__main__._plugin_instructions(install=False), 0)
        text = output.getvalue()
        self.assertIn(str(Path(__file__).resolve().parent.parent) + "\\extensions", text)
        self.assertIn("KazaA v2. revival Helper", text)

    def test_extensions_use_new_name_and_version(self):
        root = Path(__file__).resolve().parent.parent
        for browser in ("chrome", "firefox"):
            manifest = json.loads((root / "extensions" / browser / "manifest.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "KazaA v2. revival Helper")
            self.assertEqual(manifest["version"], VERSION)


if __name__ == "__main__":
    unittest.main()
