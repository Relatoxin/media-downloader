from __future__ import annotations

import unittest
from pathlib import Path

from media_downloader.controller import DownloadController
from media_downloader.engine import FormatUnavailableError
from media_downloader.formats import MediaAnalysis
from media_downloader.jobs import FormatOption, JobState


class FakeEngine:
    def __init__(self, analysis: MediaAnalysis) -> None:
        self.analysis = analysis
        self.analyzed = []
        self.downloaded = []
        self.download_result = Path("downloaded.mp4").resolve()

    def analyze(self, request):
        self.analyzed.append(request)
        return self.analysis

    def download(self, request):
        self.downloaded.append(request)
        return self.download_result


class FailingAnalysisEngine(FakeEngine):
    def analyze(self, request):
        raise RuntimeError("analysis failed")


class VanishedFormatEngine(FakeEngine):
    def download(self, request):
        raise FormatUnavailableError("format vanished")


class DownloadControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output_dir = Path.cwd() / ".tmp" / "controller-tests"
        self.analysis = MediaAnalysis(
            title="Social video",
            thumbnail="https://example.com/thumb.jpg",
            duration=120,
            platform="Youtube",
            formats=(
                FormatOption(key="best", label="Лучшее", selector="best"),
                FormatOption(key="video-720p30", label="720p", selector="22", height=720),
            ),
        )
        self.engine = FakeEngine(self.analysis)
        self.controller = DownloadController(
            engine_factory=lambda: self.engine,
            output_dir_provider=lambda: self.output_dir,
        )

    def test_confirmed_capture_becomes_ready_without_analysis_or_download(self) -> None:
        job = self.controller.prepare(
            {
                "jobId": "capture-1",
                "sourceType": "captured_stream",
                "url": "https://cdn.example/720/index.m3u8",
                "title": "Episode",
                "height": 720,
                "activeQualityConfirmed": True,
                "headers": {"Referer": "https://site.example/watch"},
            }
        )
        self.assertEqual(job.state, JobState.READY)
        self.assertEqual(len(job.formats), 1)
        self.assertEqual(job.formats[0].label, "720p · запущенный поток")
        self.assertEqual(self.engine.analyzed, [])
        self.assertEqual(self.engine.downloaded, [])

    def test_page_url_is_analyzed_but_not_downloaded(self) -> None:
        job = self.controller.prepare(
            {"jobId": "page-1", "sourceType": "page_url", "url": "https://youtube.com/watch?v=test", "title": "Page"}
        )
        self.assertEqual(job.state, JobState.READY)
        self.assertEqual(job.title, "Social video")
        self.assertEqual(len(job.formats), 2)
        self.assertEqual(self.engine.downloaded, [])

    def test_explicit_start_downloads_selected_format_only(self) -> None:
        job = self.controller.prepare(
            {"jobId": "page-2", "sourceType": "page_url", "url": "https://youtube.com/watch?v=test", "title": "Page"}
        )
        self.controller.start(job.job_id, "video-720p30")
        self.assertEqual(job.state, JobState.COMPLETED)
        self.assertEqual(self.engine.downloaded[0].format_selector_override, "22")
        self.assertEqual(job.output_path, self.engine.download_result)

    def test_failed_analysis_leaves_visible_failed_job(self) -> None:
        controller = DownloadController(
            engine_factory=lambda: FailingAnalysisEngine(self.analysis),
            output_dir_provider=lambda: self.output_dir,
        )
        with self.assertRaisesRegex(RuntimeError, "analysis failed"):
            controller.prepare({"jobId": "page-failed", "sourceType": "page_url", "url": "https://example.com/watch"})
        job = controller.store.get("page-failed")
        self.assertEqual(job.state, JobState.FAILED)
        self.assertEqual(job.message, "analysis failed")

    def test_vanished_format_reanalysis_returns_job_to_ready(self) -> None:
        engines = iter((self.engine, VanishedFormatEngine(self.analysis), self.engine))
        controller = DownloadController(
            engine_factory=lambda: next(engines), output_dir_provider=lambda: self.output_dir
        )
        job = controller.prepare({"jobId": "vanished", "sourceType": "page_url", "url": "https://example.com/watch"})
        with self.assertRaises(FormatUnavailableError):
            controller.start(job.job_id, "best")
        self.assertEqual(job.state, JobState.READY)
        self.assertIsNone(controller.store.active_job_id)
        self.assertIn("Выберите формат снова", job.message)

    def test_failed_reanalysis_releases_active_job(self) -> None:
        engines = iter((self.engine, VanishedFormatEngine(self.analysis), FailingAnalysisEngine(self.analysis)))
        controller = DownloadController(
            engine_factory=lambda: next(engines), output_dir_provider=lambda: self.output_dir
        )
        job = controller.prepare(
            {"jobId": "reanalyze-failed", "sourceType": "page_url", "url": "https://example.com/watch"}
        )
        with self.assertRaisesRegex(RuntimeError, "analysis failed"):
            controller.start(job.job_id, "best")
        self.assertEqual(job.state, JobState.FAILED)
        self.assertIsNone(controller.store.active_job_id)


if __name__ == "__main__":
    unittest.main()

