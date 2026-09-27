from __future__ import annotations

import unittest

from media_downloader.formats import build_format_options


class FormatOptionsTest(unittest.TestCase):
    def test_groups_duplicate_resolutions_and_keeps_distinct_fps(self) -> None:
        info = {
            "formats": [
                {
                    "format_id": "18",
                    "height": 360,
                    "fps": 30,
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                    "ext": "mp4",
                    "filesize": 10,
                },
                {
                    "format_id": "137",
                    "height": 1080,
                    "fps": 30,
                    "vcodec": "avc1",
                    "acodec": "none",
                    "ext": "mp4",
                    "filesize": 100,
                },
                {
                    "format_id": "399",
                    "height": 1080,
                    "fps": 30,
                    "vcodec": "av01",
                    "acodec": "none",
                    "ext": "mp4",
                    "filesize": 90,
                },
                {
                    "format_id": "299",
                    "height": 1080,
                    "fps": 60,
                    "vcodec": "avc1",
                    "acodec": "none",
                    "ext": "mp4",
                    "filesize": 150,
                },
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a", "filesize": 20},
                {"format_id": "storyboard", "vcodec": "none", "acodec": "none", "ext": "mhtml"},
            ]
        }

        options = build_format_options(info)
        keys = [option.key for option in options]

        self.assertEqual(keys.count("video-1080p30"), 1)
        self.assertIn("video-1080p60", keys)
        self.assertIn("best", keys)
        self.assertIn("audio-mp3", keys)
        self.assertIn("audio-source", keys)
        self.assertNotIn("storyboard", " ".join(keys))

    def test_video_selector_pairs_video_only_format_with_audio(self) -> None:
        info = {
            "formats": [
                {
                    "format_id": "137",
                    "height": 1080,
                    "fps": 30,
                    "vcodec": "avc1",
                    "acodec": "none",
                    "ext": "mp4",
                    "filesize": 100,
                },
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a", "filesize": 20},
            ]
        }
        option = next(item for item in build_format_options(info) if item.key == "video-1080p30")
        self.assertEqual(option.selector, "137+ba[ext=m4a]/137+ba/b[height=1080]")
        self.assertEqual(option.filesize, 120)
        self.assertIn("видео со звуком", option.label)

    def test_combined_stream_offers_mp3_but_not_fake_source_audio(self) -> None:
        info = {
            "formats": [
                {"format_id": "hd", "height": 720, "fps": 30, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4"},
            ]
        }
        keys = [item.key for item in build_format_options(info)]
        self.assertIn("audio-mp3", keys)
        self.assertNotIn("audio-source", keys)

    def test_every_video_choice_is_explicitly_with_audio(self) -> None:
        info = {
            "formats": [
                {"format_id": "combined", "height": 720, "fps": 30, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4"},
                {"format_id": "video", "height": 1080, "fps": 60, "vcodec": "avc1", "acodec": "none", "ext": "mp4"},
                {"format_id": "audio", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"},
            ]
        }
        options = build_format_options(info)
        video_options = [item for item in options if item.media_type == "video"]

        self.assertTrue(video_options)
        self.assertTrue(all("видео со звуком" in item.label for item in video_options))
        self.assertTrue(all("без звука" not in item.label for item in options))
        self.assertEqual(
            next(item for item in options if item.key == "video-1080p60").selector,
            "video+ba[ext=m4a]/video+ba/b[height=1080]",
        )
        self.assertEqual(len([item for item in options if item.key == "video-1080p60"]), 1)


if __name__ == "__main__":
    unittest.main()

