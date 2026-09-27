from __future__ import annotations

import unittest
from pathlib import Path

from media_downloader.job_store import JobStore
from media_downloader.jobs import FormatOption, JobState, PreparedJob, SourceType


class PreparedJobTest(unittest.TestCase):
    def test_ready_job_can_select_format_and_start(self) -> None:
        option = FormatOption(key="video-720p", label="720p", selector="22", height=720)
        job = PreparedJob(source_type=SourceType.PAGE_URL, url="https://example.com/watch", formats=(option,))

        job.mark_ready()
        job.select_format("video-720p")
        job.mark_started()
        job.output_path = Path("downloaded.mp4")
        job.mark_finished()

        self.assertEqual(job.state, JobState.COMPLETED)
        self.assertEqual(job.selected_format_key, "video-720p")
        self.assertEqual(job.output_path, Path("downloaded.mp4"))

    def test_invalid_transition_is_rejected(self) -> None:
        job = PreparedJob(source_type=SourceType.PAGE_URL, url="https://example.com/watch")
        with self.assertRaises(ValueError):
            job.mark_started()

    def test_confirmed_capture_requires_one_fixed_option(self) -> None:
        option = FormatOption(key="captured", label="1080p", selector="https://cdn.example/video.m3u8", height=1080)
        job = PreparedJob(
            source_type=SourceType.CAPTURED_STREAM,
            url="https://cdn.example/video.m3u8",
            formats=(option,),
            active_quality_confirmed=True,
        )
        job.mark_ready()

        self.assertEqual(job.selected_format_key, "captured")
        self.assertEqual(job.formats, (option,))


class JobStoreTest(unittest.TestCase):
    @staticmethod
    def ready_job(url: str) -> PreparedJob:
        option = FormatOption(key="best", label="Лучшее", selector="best")
        job = PreparedJob(source_type=SourceType.PAGE_URL, url=url, formats=(option,))
        job.mark_ready()
        job.select_format("best")
        return job

    def test_add_does_not_start_job(self) -> None:
        store = JobStore()
        job = store.add(self.ready_job("https://example.com/one"))
        self.assertEqual(job.state, JobState.READY)
        self.assertIsNone(store.active_job_id)

    def test_start_is_explicit_and_only_one_job_can_be_active(self) -> None:
        store = JobStore()
        first = store.add(self.ready_job("https://example.com/one"))
        second = store.add(self.ready_job("https://example.com/two"))

        store.start(first.job_id)
        with self.assertRaises(RuntimeError):
            store.start(second.job_id)

        store.finish(first.job_id)
        self.assertEqual(second.state, JobState.READY)
        self.assertIsNone(store.active_job_id)

    def test_active_job_cannot_be_removed(self) -> None:
        store = JobStore()
        job = store.add(self.ready_job("https://example.com/one"))
        store.start(job.job_id)
        with self.assertRaises(RuntimeError):
            store.remove(job.job_id)

    def test_newest_jobs_are_listed_first_without_changing_active_job(self) -> None:
        store = JobStore()
        first = store.add(self.ready_job("https://example.com/one"))
        second = store.add(self.ready_job("https://example.com/two"))
        store.start(first.job_id)
        third = store.add(self.ready_job("https://example.com/three"))

        self.assertEqual([job.job_id for job in store.list()], [third.job_id, second.job_id, first.job_id])
        self.assertEqual(store.active_job_id, first.job_id)
        self.assertEqual(first.state, JobState.DOWNLOADING)


if __name__ == "__main__":
    unittest.main()

