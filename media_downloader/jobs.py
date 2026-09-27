from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import uuid4


class JobState(str, Enum):
    ANALYZING = "analyzing"
    READY = "ready"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceType(str, Enum):
    CAPTURED_STREAM = "captured_stream"
    PAGE_URL = "page_url"


@dataclass(frozen=True, slots=True)
class FormatOption:
    key: str
    label: str
    selector: str
    height: int | None = None
    fps: float | None = None
    media_type: Literal["video", "audio"] = "video"
    extension: str | None = None
    filesize: int | None = None
    audio_output: Literal["mp3", "source"] | None = None


@dataclass(slots=True)
class PreparedJob:
    source_type: SourceType
    url: str
    job_id: str = field(default_factory=lambda: uuid4().hex)
    page_url: str = ""
    title: str = "Медиа"
    platform: str = ""
    thumbnail: str = ""
    duration: float | None = None
    headers: dict[str, str] = field(default_factory=dict)
    browser: str | None = None
    formats: tuple[FormatOption, ...] = ()
    selected_format_key: str | None = None
    active_quality_confirmed: bool = False
    state: JobState = JobState.ANALYZING
    message: str = ""
    output_path: Path | None = None

    def __post_init__(self) -> None:
        if self.active_quality_confirmed:
            if len(self.formats) != 1:
                raise ValueError("Подтверждённый поток должен содержать ровно один формат")
            self.selected_format_key = self.formats[0].key

    @property
    def selected_format(self) -> FormatOption | None:
        return next((option for option in self.formats if option.key == self.selected_format_key), None)

    def mark_ready(self, formats: tuple[FormatOption, ...] | None = None) -> None:
        if self.state not in {JobState.ANALYZING, JobState.FAILED, JobState.READY}:
            raise ValueError(f"Нельзя подготовить задачу из состояния {self.state.value}")
        if formats is not None:
            self.formats = formats
        if not self.formats:
            raise ValueError("У задачи нет доступных форматов")
        if self.active_quality_confirmed:
            if len(self.formats) != 1:
                raise ValueError("Подтверждённый поток должен содержать ровно один формат")
            self.selected_format_key = self.formats[0].key
        self.state = JobState.READY
        self.message = ""

    def select_format(self, key: str) -> FormatOption:
        if self.state != JobState.READY:
            raise ValueError("Формат можно выбрать только для готовой задачи")
        option = next((item for item in self.formats if item.key == key), None)
        if option is None:
            raise ValueError("Выбранный формат недоступен")
        self.selected_format_key = key
        return option

    def mark_started(self) -> None:
        if self.state != JobState.READY or self.selected_format is None:
            raise ValueError("Сначала подготовьте задачу и выберите формат")
        self.state = JobState.DOWNLOADING

    def mark_finished(self) -> None:
        if self.state != JobState.DOWNLOADING:
            raise ValueError("Завершить можно только активную загрузку")
        self.state = JobState.COMPLETED

    def mark_failed(self, message: str) -> None:
        if self.state not in {JobState.ANALYZING, JobState.DOWNLOADING}:
            raise ValueError("Ошибка допустима только при анализе или загрузке")
        self.state = JobState.FAILED
        self.message = message

    def mark_cancelled(self) -> None:
        if self.state != JobState.DOWNLOADING:
            raise ValueError("Отменить можно только активную загрузку")
        self.state = JobState.CANCELLED

