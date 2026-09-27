from __future__ import annotations

import unittest

from media_downloader.errors import friendly_error


class FriendlyErrorTest(unittest.TestCase):
    def test_maps_common_failures_to_distinct_russian_guidance(self) -> None:
        cases = {
            "HTTP Error 403: Forbidden": "подпись CDN устарела",
            "Sign in to confirm your age; cookies required": "требует вход",
            "This video is unavailable in your country": "недоступно или ограничено",
            "This video is DRM protected": "DRM",
            "ffmpeg executable is missing": "FFmpeg",
            "Выбранный формат больше недоступен": "Список форматов обновлён",
            "Скачанный файл неполный": "повреждён или скачан не полностью",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertIn(expected, friendly_error(RuntimeError(raw)))


if __name__ == "__main__":
    unittest.main()

