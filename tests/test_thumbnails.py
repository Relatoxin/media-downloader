from __future__ import annotations

import unittest

from media_downloader.thumbnails import preferred_thumbnail, safe_thumbnail_headers


class ThumbnailHeadersTest(unittest.TestCase):
    def test_does_not_forward_credentials_to_thumbnail_host(self) -> None:
        headers = safe_thumbnail_headers(
            {
                "Cookie": "session=secret",
                "Authorization": "Bearer secret",
                "User-Agent": "Chrome",
                "Referer": "https://player.example/watch",
                "Accept-Language": "ru",
            }
        )
        self.assertEqual(headers["User-Agent"], "Chrome")
        self.assertEqual(headers["Referer"], "https://player.example/watch")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_extension_preview_has_priority_over_analyzed_thumbnail(self) -> None:
        extension_preview = "data:image/jpeg;base64,preview"
        analyzed = "https://img.example/thumb.jpg"
        self.assertEqual(preferred_thumbnail(extension_preview, analyzed), extension_preview)
        self.assertEqual(preferred_thumbnail("", analyzed), analyzed)


if __name__ == "__main__":
    unittest.main()

