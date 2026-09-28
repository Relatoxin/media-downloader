import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from media_downloader.engine import DownloadCancelled, DownloadEngine, DownloadRequest, format_selector, validate_url


def _locked_download_worker(request, messages) -> None:
    part = request.output_dir / "locked-video.mp4.part"
    sidecar = request.output_dir / "locked-video.mp4.ytdl"
    request.output_dir.mkdir(parents=True, exist_ok=True)
    sidecar.write_bytes(b"metadata")
    with part.open("wb") as stream:
        stream.write(b"partial media")
        stream.flush()
        messages.put(("progress", {"status": "downloading", "downloaded_bytes": 13}))
        while True:
            time.sleep(1)


class EngineHelpersTest(unittest.TestCase):
    def test_validate_url_accepts_http(self) -> None:
        self.assertEqual(validate_url(" https://example.com/video "), "https://example.com/video")

    def test_validate_url_rejects_local_paths_and_other_schemes(self) -> None:
        for value in ("", "example.com", "file:///tmp/video.mp4", "javascript:alert(1)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_url(value)

    def test_quality_selectors_are_bounded(self) -> None:
        self.assertIn("height<=720", format_selector("720"))
        self.assertEqual(format_selector("audio"), "bestaudio/best")
        with self.assertRaises(ValueError):
            format_selector("4k-ish")

    def test_options_do_not_expose_browser_cookies_by_default(self) -> None:
        request = DownloadRequest("https://example.com/v", Path.cwd())
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        options = engine._options(request)
        self.assertNotIn("cookiesfrombrowser", options)
        self.assertTrue(Path(options["ffmpeg_location"]).exists())
        self.assertEqual(options["concurrent_fragment_downloads"], 4)
        self.assertFalse(options["skip_unavailable_fragments"])
        self.assertEqual(options["impersonate"].client, "chrome")
        self.assertIn("node", options["js_runtimes"])

    def test_explicit_selector_and_audio_modes_override_legacy_quality(self) -> None:
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        source_request = DownloadRequest(
            url="https://example.com/watch",
            output_dir=Path("downloads"),
            format_selector_override="251",
            audio_output="source",
        )
        source_options = engine._options(source_request, simulate=True)
        self.assertEqual(source_options["format"], "251")
        self.assertNotIn("postprocessors", source_options)

        mp3_request = DownloadRequest(
            url="https://example.com/watch",
            output_dir=Path("downloads"),
            format_selector_override="bestaudio/best",
            audio_output="mp3",
        )
        mp3_options = engine._options(mp3_request, simulate=True)
        self.assertEqual(mp3_options["postprocessors"][0]["preferredcodec"], "mp3")

    def test_captured_headers_are_forwarded(self) -> None:
        request = DownloadRequest(
            "https://cdn.example/video.m3u8",
            Path.cwd(),
            headers={"Referer": "https://player.example/", "Origin": "https://player.example"},
        )
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        options = engine._options(request)
        self.assertEqual(options["http_headers"]["Referer"], "https://player.example/")

    def test_extension_filename_is_shortened(self) -> None:
        request = DownloadRequest(
            "https://cdn.example/video.m3u8",
            Path.cwd(),
            filename_hint="Название сериала — смотреть аниме онлайн бесплатно на сайте | лишний SEO-текст",
            filename_tag="20260920-031500",
        )
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        template = engine._options(request)["outtmpl"]
        self.assertIn("Название сериала", template)
        self.assertIn("20260920-031500", template)
        self.assertNotIn("смотреть аниме", template)

    def test_tiny_completed_video_is_rejected(self) -> None:
        output = Path.cwd() / ".tmp" / "tiny-result.mp4"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b"not-a-video")
        request = DownloadRequest("https://example.com/video", output.parent)
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        with self.assertRaisesRegex(RuntimeError, "пустой MP4"):
            engine._validate_completed_media(request, output)
        output.unlink()

    def test_resolves_postprocessed_output_path(self) -> None:
        output_dir = Path.cwd() / ".tmp" / "resolved-result"
        output_dir.mkdir(parents=True, exist_ok=True)
        intermediate = output_dir / "clip.webm"
        final = output_dir / "clip.mp4"
        final.write_bytes(b"media")
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        engine.completed_files = [intermediate]
        engine.final_files = [final]

        self.assertEqual(engine._resolve_completed_file({}, output_dir), final.resolve())
        final.unlink()

    def test_resolver_does_not_mistake_thumbnail_for_completed_media(self) -> None:
        output_dir = Path.cwd() / ".tmp" / "resolved-result"
        output_dir.mkdir(parents=True, exist_ok=True)
        missing_video = output_dir / "clip-missing.webm"
        thumbnail = output_dir / "clip-missing.jpg"
        thumbnail.write_bytes(b"thumbnail")
        engine = DownloadEngine(lambda _data: None, lambda _text: None)
        engine.completed_files = [missing_video]

        with self.assertRaisesRegex(RuntimeError, "итоговый файл не найден"):
            engine._resolve_completed_file({}, output_dir)
        thumbnail.unlink()

    def test_cancellation_removes_only_part_files_created_by_current_download(self) -> None:
        output_dir = Path.cwd() / ".tmp" / "cancel-cleanup"
        output_dir.mkdir(parents=True, exist_ok=True)
        existing = output_dir / "older-download.part"
        resumed = output_dir / "resumed-download.part"
        current = output_dir / "current-download.part"
        fragment = output_dir / "current-download.part-Frag12"
        sidecar = output_dir / "current-download.mp4.ytdl"
        existing_sidecar = output_dir / "older-download.mp4.ytdl"
        existing.write_bytes(b"keep")
        existing_sidecar.write_bytes(b"keep")
        resumed.write_bytes(b"old")
        current.unlink(missing_ok=True)
        fragment.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)

        class CancellingDownloader:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                self.assert_download = download
                current.write_bytes(b"partial")
                resumed.write_bytes(b"resumed-and-modified")
                fragment.write_bytes(b"fragment")
                sidecar.write_bytes(b"resume metadata")
                raise DownloadCancelled("cancelled")

        engine = DownloadEngine(lambda _data: None, lambda _text: None, isolate_download=False)
        request = DownloadRequest("https://example.com/video", output_dir)
        try:
            with patch("media_downloader.engine.yt_dlp.YoutubeDL", CancellingDownloader):
                with self.assertRaises(DownloadCancelled):
                    engine.download(request)
            self.assertFalse(current.exists())
            self.assertFalse(resumed.exists())
            self.assertFalse(fragment.exists())
            self.assertFalse(sidecar.exists())
            self.assertTrue(existing.exists())
            self.assertTrue(existing_sidecar.exists())
        finally:
            current.unlink(missing_ok=True)
            resumed.unlink(missing_ok=True)
            fragment.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            existing.unlink(missing_ok=True)
            existing_sidecar.unlink(missing_ok=True)

    def test_isolated_cancellation_releases_locked_files_before_cleanup(self) -> None:
        output_dir = Path.cwd() / ".tmp" / "isolated-cancel-cleanup"
        output_dir.mkdir(parents=True, exist_ok=True)
        part = output_dir / "locked-video.mp4.part"
        sidecar = output_dir / "locked-video.mp4.ytdl"
        part.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        cancelled = Event()
        engine = DownloadEngine(
            lambda _data: cancelled.set(),
            lambda _text: None,
            cancelled,
            worker_target=_locked_download_worker,
        )
        try:
            with self.assertRaises(DownloadCancelled):
                engine.download(DownloadRequest("https://example.com/video", output_dir))
            self.assertFalse(part.exists())
            self.assertFalse(sidecar.exists())
        finally:
            part.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
