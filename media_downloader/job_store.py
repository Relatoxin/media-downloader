from __future__ import annotations

from collections import OrderedDict

from .jobs import FormatOption, JobState, PreparedJob


class JobStore:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, PreparedJob] = OrderedDict()
        self.active_job_id: str | None = None

    def add(self, job: PreparedJob) -> PreparedJob:
        if job.job_id in self._jobs:
            raise ValueError("Задача с таким идентификатором уже существует")
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> PreparedJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("Задача не найдена") from exc

    def list(self) -> tuple[PreparedJob, ...]:
        return tuple(reversed(self._jobs.values()))

    def start(self, job_id: str, format_key: str | None = None) -> PreparedJob:
        if self.active_job_id is not None:
            raise RuntimeError("Другая загрузка уже выполняется")
        job = self.get(job_id)
        if format_key is not None:
            job.select_format(format_key)
        job.mark_started()
        self.active_job_id = job_id
        return job

    def finish(self, job_id: str) -> PreparedJob:
        job = self._require_active(job_id)
        job.mark_finished()
        self.active_job_id = None
        return job

    def fail(self, job_id: str, message: str) -> PreparedJob:
        job = self._require_active(job_id)
        job.mark_failed(message)
        self.active_job_id = None
        return job

    def cancel(self, job_id: str) -> PreparedJob:
        job = self._require_active(job_id)
        job.mark_cancelled()
        self.active_job_id = None
        return job

    def retry_ready(
        self,
        job_id: str,
        formats: tuple[FormatOption, ...] | None = None,
        message: str = "",
    ) -> PreparedJob:
        job = self._require_active(job_id)
        job.state = JobState.ANALYZING
        job.mark_ready(formats)
        job.message = message
        self.active_job_id = None
        return job

    def remove(self, job_id: str) -> None:
        if job_id == self.active_job_id:
            raise RuntimeError("Нельзя удалить активную загрузку")
        self._jobs.pop(job_id, None)

    def _require_active(self, job_id: str) -> PreparedJob:
        if self.active_job_id != job_id:
            raise ValueError("Задача не является активной")
        return self.get(job_id)
