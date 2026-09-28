from __future__ import annotations

import subprocess
import unittest

from media_downloader.jobs import JobState, PreparedJob, SourceType
from media_downloader.previews import build_frame_command, extract_video_frame, safe_media_headers


class PreviewExtractionTest(unittest.TestCase):
    def test_frame_command_scopes_headers_to_media_request(self) -> None:
        command = build_frame_command(
            "https://cdn.example/video.m3u8",
            {
                "User-Agent": "Chrome",
                "Referer": "https://player.example/watch",
                "Cookie": "session=secret",
                "Authorization": "Bearer token",
                "X-Debug-Secret": "drop-me",
            },
        )
        rendered = " ".join(command)

        self.assertIn("https://cdn.example/video.m3u8", command)
        self.assertIn("Chrome", command)
        self.assertIn("Cookie: session=secret", rendered)
        self.assertIn("Authorization: Bearer token", rendered)
        self.assertNotIn("X-Debug-Secret", rendered)
        self.assertEqual(command[-1], "pipe:1")

    def test_media_header_filter_rejects_line_injection_and_unneeded_headers(self) -> None:
        headers = safe_media_headers(
            {
                "Origin": "https://player.example",
                "Accept": "*/*",
                "Sec-Fetch-Dest": "video",
                "X-Test": "value",
                "Cookie": "safe=value",
                "Referer": "ok\r\nInjected: yes",
            }
        )
        self.assertEqual(headers["Origin"], "https://player.example")
        self.assertEqual(headers["Cookie"], "safe=value")
        self.assertNotIn("Sec-Fetch-Dest", headers)
        self.assertNotIn("X-Test", headers)
        self.assertNotIn("Referer", headers)

    def test_timeout_is_nonfatal_and_does_not_change_job_state(self) -> None:
        job = PreparedJob(source_type=SourceType.CAPTURED_STREAM, url="https://cdn.example/video.m3u8")

        def timeout_runner(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

        result = extract_video_frame(job.url, {}, timeout=1, runner=timeout_runner)

        self.assertIsNone(result)
        self.assertEqual(job.state, JobState.ANALYZING)


if __name__ == "__main__":
    unittest.main()
