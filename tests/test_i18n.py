from __future__ import annotations

import unittest

from media_downloader.i18n import TRANSLATIONS, normalize_language, translate


class InternationalizationTest(unittest.TestCase):
    def test_russian_and_english_catalogs_have_the_same_keys(self) -> None:
        self.assertEqual(set(TRANSLATIONS["ru"]), set(TRANSLATIONS["en"]))

    def test_language_is_normalized_and_unknown_values_fall_back(self) -> None:
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("ru_RU"), "ru")
        self.assertEqual(normalize_language("de-DE"), "en")

    def test_translation_supports_named_values(self) -> None:
        self.assertEqual(translate("status.download", "en", percent=12.5, speed="1 MiB/s"), "Download: 12.5% — 1 MiB/s")


if __name__ == "__main__":
    unittest.main()
