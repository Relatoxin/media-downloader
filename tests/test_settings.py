from __future__ import annotations

import json
import unittest
from pathlib import Path

from media_downloader.settings import AppSettings, SettingsStore


class SettingsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".tmp" / "settings-tests"
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = self.root / "settings.json"
        self.config.unlink(missing_ok=True)
        (self.root / "settings.json.tmp").unlink(missing_ok=True)
        self.output = self.root / "downloads"
        self.output.mkdir(exist_ok=True)
        self.default = self.root.resolve()
        self.store = SettingsStore(self.config)

    def test_missing_config_uses_default(self) -> None:
        self.assertEqual(self.store.load(self.default).output_dir, self.default)

    def test_round_trip_writes_output_directory_and_language_atomically(self) -> None:
        self.store.save(AppSettings(output_dir=self.output, language="en"))
        payload = json.loads(self.config.read_text(encoding="utf-8"))

        self.assertEqual(payload, {"outputDir": str(self.output.resolve()), "language": "en"})
        loaded = self.store.load(self.default)
        self.assertEqual(loaded.output_dir, self.output.resolve())
        self.assertEqual(loaded.language, "en")
        self.assertFalse((self.root / "settings.json.tmp").exists())

    def test_legacy_config_without_language_stays_russian(self) -> None:
        self.config.write_text(json.dumps({"outputDir": str(self.output.resolve())}), encoding="utf-8")

        self.assertEqual(self.store.load(self.default, default_language="en").language, "ru")

    def test_malformed_wrong_type_and_nonexistent_directory_fall_back(self) -> None:
        cases = [
            "{not json",
            json.dumps({"outputDir": 42}),
            json.dumps({"outputDir": str(self.root / "missing")}),
            json.dumps({"outputDir": "relative/path"}),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.config.write_text(raw, encoding="utf-8")
                self.assertEqual(self.store.load(self.default).output_dir, self.default)


if __name__ == "__main__":
    unittest.main()
