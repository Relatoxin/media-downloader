from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .engine import DownloadCancelled, DownloadRequest, FormatUnavailableError
from .formats import MediaAnalysis
from .job_store import JobStore
from .jobs import FormatOption, PreparedJob, SourceType
from .thumbnails import preferred_thumbnail


class EngineLike(Protocol):
    def analyze(self, request: DownloadRequest) -> MediaAnalysis: ...
    def download(self, request: DownloadRequest) -> Path: ...


class DownloadController:
    def __init__(
        self,
        engine_factory: Callable[[], EngineLike],
        output_dir_provider: Callable[[], Path],
        browser_provider: Callable[[], str | None] | None = None,
        on_change: Callable[[PreparedJob], None] | None = None,
        store: JobStore | None = None,
    ) -> None:
        self.engine_factory = engine_factory
        self.output_dir_provider = output_dir_provider
        self.browser_provider = browser_provider or (lambda: None)
        self.on_change = on_change or (lambda _job: None)
        self.store = store or JobStore()

    def prepare(self, payload: dict[str, Any]) -> PreparedJob:
        source_type = SourceType(str(payload.get("sourceType") or "captured_stream"))
        confirmed = source_type == SourceType.CAPTURED_STREAM and bool(payload.get("activeQualityConfirmed"))
        height = self._positive_int(payload.get("height"))
        formats: tuple[FormatOption, ...] = ()
        if confirmed:
            label = f"{height}p · запущенный поток" if height else "Запущенный поток"
            formats = (FormatOption(key="captured", label=label, selector="best", height=height),)
        job = PreparedJob(
            job_id=str(payload.get("jobId") or "").strip() or uuid4().hex,
            source_type=source_type,
            url=str(payload["url"]),
            page_url=str(payload.get("pageUrl") or ""),
            title=str(payload.get("title") or "Медиа"),
            thumbnail=str(payload.get("thumbnail") or ""),
            duration=self._positive_float(payload.get("duration")),
            headers=dict(payload.get("headers") or {}),
            browser=payload.get("browser"),
            formats=formats,
            active_quality_confirmed=confirmed,
        )
        self.store.add(job)
        self.on_change(job)
        try:
            if confirmed:
                job.mark_ready()
            else:
                analysis = self.engine_factory().analyze(self._analysis_request(job))
                job.title = analysis.title
                job.thumbnail = preferred_thumbnail(job.thumbnail, analysis.thumbnail)
                job.duration = analysis.duration or job.duration
                job.platform = analysis.platform
                job.mark_ready(analysis.formats)
                if any(option.key == "best" for option in job.formats):
                    job.select_format("best")
        except Exception as exc:
            job.mark_failed(str(exc))
            self.on_change(job)
            raise
        self.on_change(job)
        return job

    def start(self, job_id: str, format_key: str | None = None) -> None:
        job = self.store.start(job_id, format_key)
        self.on_change(job)
        try:
            job.output_path = self.engine_factory().download(self._download_request(job))
            self.store.finish(job_id)
        except DownloadCancelled:
            self.store.cancel(job_id)
            raise
        except FormatUnavailableError:
            try:
                analysis = self.engine_factory().analyze(self._analysis_request(job))
            except Exception as analysis_exc:
                self.store.fail(job_id, str(analysis_exc))
                raise
            self.store.retry_ready(job_id, analysis.formats, "Список форматов обновлён. Выберите формат снова.")
            raise
        except Exception as exc:
            self.store.fail(job_id, str(exc))
            raise
        finally:
            self.on_change(job)

    def cancel(self, job_id: str) -> None:
        job = self.store.cancel(job_id)
        self.on_change(job)

    def remove(self, job_id: str) -> None:
        self.store.remove(job_id)

    def _analysis_request(self, job: PreparedJob) -> DownloadRequest:
        return DownloadRequest(
            url=job.url,
            output_dir=self.output_dir_provider(),
            browser=job.browser or self.browser_provider(),
            headers=job.headers,
        )

    def _download_request(self, job: PreparedJob) -> DownloadRequest:
        option = job.selected_format
        if option is None:
            raise ValueError("Формат не выбран")
        return DownloadRequest(
            url=job.url,
            output_dir=self.output_dir_provider(),
            browser=job.browser or self.browser_provider(),
            headers=job.headers,
            filename_hint=job.title,
            filename_tag=datetime.now().strftime("%Y%m%d-%H%M%S"),
            expected_duration=job.duration,
            format_selector_override=option.selector,
            audio_output=option.audio_output,
        )

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            parsed = float(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None
