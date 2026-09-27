from __future__ import annotations

import multiprocessing
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty
from threading import Event
from typing import Any, Literal
from urllib.parse import urlparse

import imageio_ffmpeg
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

from .formats import MediaAnalysis, build_format_options

ProgressCallback = Callable[[dict[str, Any]], None]
LogCallback = Callable[[str], None]
COMPLETED_MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac"}


class DownloadCancelled(Exception):
    """Raised from a yt-dlp progress hook when the user cancels."""


class FormatUnavailableError(RuntimeError):
    """The format selected during analysis is no longer available."""


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    url: str
    output_dir: Path
    quality: str = "best"
    browser: str | None = None
    playlist: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    filename_hint: str | None = None
    filename_tag: str | None = None
    expected_duration: float | None = None
    format_selector_override: str | None = None
    audio_output: Literal["mp3", "source"] | None = None


QUALITY_LABELS = {
    "Лучшее качество (MP4)": "best",
    "До 1080p (MP4)": "1080",
    "До 720p (MP4)": "720",
    "До 480p (MP4)": "480",
    "Только аудио (MP3)": "audio",
}


def validate_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Введите полную ссылку, начинающуюся с http:// или https://")
    return url


def format_selector(quality: str) -> str:
    if quality == "audio":
        return "bestaudio/best"
    if quality == "best":
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    if quality in {"1080", "720", "480"}:
        return (
            f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/"
            f"b[height<={quality}][ext=mp4]/"
            f"bv*[height<={quality}]+ba/b[height<={quality}]"
        )
    raise ValueError(f"Неизвестный режим качества: {quality}")


class _Logger:
    def __init__(self, callback: LogCallback) -> None:
        self.callback = callback

    def debug(self, message: str) -> None:
        if not message.startswith("[debug]"):
            self.callback(message)

    def info(self, message: str) -> None:
        self.callback(message)

    def warning(self, message: str) -> None:
        self.callback(f"Предупреждение: {message}")

    def error(self, message: str) -> None:
        self.callback(f"Ошибка: {message}")


class DownloadEngine:
    def __init__(
        self,
        progress_callback: ProgressCallback,
        log_callback: LogCallback,
        cancel_event: Event | None = None,
        *,
        isolate_download: bool = True,
        worker_target: Callable[[DownloadRequest, Any], None] | None = None,
    ) -> None:
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.cancel_event = cancel_event or Event()
        self.isolate_download = isolate_download
        self.worker_target = worker_target or _download_worker
        self.completed_files: list[Path] = []
        self.final_files: list[Path] = []

    def _progress_hook(self, status: dict[str, Any]) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled("Загрузка отменена пользователем")
        if status.get("status") == "finished" and status.get("filename"):
            self.completed_files.append(Path(status["filename"]))
        self.progress_callback(status)

    def _postprocessor_hook(self, status: dict[str, Any]) -> None:
        if status.get("status") != "finished":
            return
        info = status.get("info") or {}
        value = info.get("filepath") or status.get("filename") or info.get("_filename")
        if value:
            self.final_files.append(Path(value))

    def _options(self, request: DownloadRequest, *, simulate: bool = False) -> dict[str, Any]:
        output_dir = request.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        output_template = "%(title).180B [%(id)s].%(ext)s"
        if request.filename_hint:
            short_hint = request.filename_hint
            for separator in (" — смотреть", " - смотреть", " | ", " ｜ "):
                short_hint = short_hint.split(separator, 1)[0]
            safe_hint = yt_dlp.utils.sanitize_filename(short_hint.strip(), restricted=False)[:80]
            if safe_hint:
                safe_tag = yt_dlp.utils.sanitize_filename(request.filename_tag or "", restricted=True)[:24]
                tag_part = f" [{safe_tag}]" if safe_tag else ""
                output_template = f"{safe_hint}{tag_part} [%(id).32B].%(ext)s"

        options: dict[str, Any] = {
            "format": request.format_selector_override or format_selector(request.quality),
            "outtmpl": str(output_dir / output_template),
            "windowsfilenames": True,
            "noplaylist": not request.playlist,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
            # Signed CDN paths used by embedded players can expire quickly.
            # Four workers were the reliable balance in real YummyAnime tests:
            # fast enough to finish before expiry without overloading the CDN.
            "concurrent_fragment_downloads": 4,
            "skip_unavailable_fragments": False,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "logger": _Logger(self.log_callback),
            "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
            "merge_output_format": "mp4",
            "impersonate": ImpersonateTarget(client="chrome"),
            "js_runtimes": {"node": {}, "deno": {}},
            "quiet": True,
            "no_warnings": False,
            "simulate": simulate,
        }
        if request.browser:
            options["cookiesfrombrowser"] = (request.browser,)
        if request.headers:
            options["http_headers"] = dict(request.headers)
        if request.audio_output == "mp3" or (request.audio_output is None and request.quality == "audio"):
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        return options

    @staticmethod
    def media_duration(path: Path) -> float | None:
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-progress",
            "pipe:1",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "null",
            os.devnull,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        timestamps = re.findall(rb"out_time_us=(\d+)", completed.stdout)
        if not timestamps:
            return None
        return int(timestamps[-1]) / 1_000_000

    @staticmethod
    def _info_paths(info: dict[str, Any]) -> list[Path]:
        values: list[Path] = []
        for key in ("filepath", "_filename"):
            if info.get(key):
                values.append(Path(info[key]))
        for item in info.get("requested_downloads") or ():
            if isinstance(item, dict):
                for key in ("filepath", "filename"):
                    if item.get(key):
                        values.append(Path(item[key]))
        return values

    def _resolve_completed_file(self, info: dict[str, Any], output_dir: Path) -> Path:
        root = output_dir.expanduser().resolve()
        candidates = [*reversed(self.final_files), *reversed(self._info_paths(info)), *reversed(self.completed_files)]
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved.is_file() and resolved.is_relative_to(root):
                return resolved
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if not resolved.is_relative_to(root):
                continue
            siblings = sorted(
                (
                    path
                    for path in resolved.parent.glob(f"{resolved.stem}.*")
                    if path.is_file() and path.suffix.lower() in COMPLETED_MEDIA_EXTENSIONS
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if siblings:
                return siblings[0].resolve()
        raise RuntimeError("yt-dlp завершил загрузку, но итоговый файл не найден")

    @staticmethod
    def _partial_file_state(output_dir: Path) -> dict[Path, tuple[int, int]]:
        root = output_dir.expanduser().resolve()
        if not root.is_dir():
            return {}
        state: dict[Path, tuple[int, int]] = {}
        for path in root.rglob("*"):
            lowered = path.name.lower()
            if not (lowered.endswith((".part", ".ytdl")) or ".part-frag" in lowered):
                continue
            try:
                if path.is_file():
                    stat = path.stat()
                    state[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                # The downloader can rename a fragment while the directory is scanned.
                continue
        return state

    def _cleanup_changed_partial_files(
        self,
        output_dir: Path,
        existing: dict[Path, tuple[int, int]],
    ) -> None:
        removed = 0
        current = self._partial_file_state(output_dir)
        targets = [path for path, signature in current.items() if existing.get(path) != signature]
        for path in targets:
            last_error: OSError | None = None
            for attempt in range(5):
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    if attempt < 4:
                        time.sleep(0.1)
            if last_error is not None:
                self.log_callback(f"Предупреждение: не удалось удалить временный файл {path.name}: {last_error}")
        if removed:
            self.log_callback(f"Удалены временные файлы отменённой загрузки: {removed}")

    def _validate_completed_media(self, request: DownloadRequest, final_file: Path) -> None:
        if request.audio_output or final_file.suffix.lower() not in {".mp4", ".mkv", ".webm", ".mov"}:
            return
        if final_file.stat().st_size < 4 * 1024:
            raise RuntimeError(
                "Поток вернул только служебный или пустой MP4-файл. Выберите HLS/DASH-кандидат вместо init/blank MP4."
            )
        if request.expected_duration and request.expected_duration > 30:
            actual_duration = self.media_duration(final_file)
            if actual_duration is None:
                raise RuntimeError("Не удалось проверить целостность готового видеофайла.")
            if actual_duration < request.expected_duration * 0.9:
                raise RuntimeError(
                    "Скачанный файл неполный: фактически доступно "
                    f"{actual_duration / 60:.1f} мин из ожидаемых {request.expected_duration / 60:.1f} мин. "
                    "Файл оставлен на диске для диагностики."
                )

    def inspect(self, request: DownloadRequest) -> dict[str, Any]:
        url = validate_url(request.url)
        with yt_dlp.YoutubeDL(self._options(request, simulate=True)) as downloader:
            info = downloader.extract_info(url, download=False)
        if not info:
            raise RuntimeError("Не удалось получить сведения о медиа")
        return info

    def analyze(self, request: DownloadRequest) -> MediaAnalysis:
        info = self.inspect(request)
        return MediaAnalysis(
            title=str(info.get("title") or "Без названия"),
            thumbnail=str(info.get("thumbnail") or ""),
            duration=float(info["duration"]) if info.get("duration") else None,
            platform=str(info.get("extractor_key") or info.get("extractor") or "Generic"),
            formats=build_format_options(info),
        )

    @staticmethod
    def _stop_process(process: Any) -> None:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=5)

    def _download_isolated(self, request: DownloadRequest) -> Path:
        partial_files_before = self._partial_file_state(request.output_dir)
        context = multiprocessing.get_context("spawn")
        messages = context.Queue()
        process = context.Process(target=self.worker_target, args=(request, messages), daemon=True)
        process.start()
        result: Path | None = None
        error: tuple[str, str] | None = None

        def handle_message(message: tuple[str, Any]) -> None:
            nonlocal result, error
            kind, payload = message
            if kind == "progress":
                self.progress_callback(payload)
            elif kind == "log":
                self.log_callback(str(payload))
            elif kind == "result":
                result = Path(str(payload))
            elif kind == "error":
                error = (str(payload[0]), str(payload[1]))

        try:
            while process.is_alive():
                if self.cancel_event.is_set():
                    self._stop_process(process)
                    self._cleanup_changed_partial_files(request.output_dir, partial_files_before)
                    raise DownloadCancelled("Загрузка отменена пользователем")
                try:
                    handle_message(messages.get(timeout=0.1))
                except Empty:
                    continue
            process.join(timeout=1)
            while True:
                try:
                    handle_message(messages.get_nowait())
                except Empty:
                    break
            if self.cancel_event.is_set():
                self._cleanup_changed_partial_files(request.output_dir, partial_files_before)
                raise DownloadCancelled("Загрузка отменена пользователем")
            if error:
                error_type, message = error
                if error_type == "format":
                    raise FormatUnavailableError(message)
                if error_type == "download":
                    raise yt_dlp.utils.DownloadError(message)
                raise RuntimeError(message)
            if result is None:
                raise RuntimeError(f"Процесс загрузки завершился без результата (код {process.exitcode})")
            return result
        finally:
            self._stop_process(process)
            process.close()
            messages.close()
            messages.join_thread()

    def download(self, request: DownloadRequest) -> Path:
        if self.isolate_download:
            return self._download_isolated(request)
        return self._download_direct(request)

    def _download_direct(self, request: DownloadRequest) -> Path:
        url = validate_url(request.url)
        self.completed_files.clear()
        self.final_files.clear()
        options = self._options(request)
        partial_files_before = self._partial_file_state(request.output_dir)
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
        except DownloadCancelled:
            self._cleanup_changed_partial_files(request.output_dir, partial_files_before)
            raise
        except yt_dlp.utils.DownloadError as exc:
            if self.cancel_event.is_set():
                self._cleanup_changed_partial_files(request.output_dir, partial_files_before)
                raise DownloadCancelled("Загрузка отменена пользователем") from exc
            lowered = str(exc).lower()
            if "requested format" in lowered and ("not available" in lowered or "unavailable" in lowered):
                raise FormatUnavailableError("Выбранный формат больше недоступен") from exc
            raise
        if self.cancel_event.is_set():
            self._cleanup_changed_partial_files(request.output_dir, partial_files_before)
            raise DownloadCancelled("Загрузка отменена пользователем")
        if not info:
            raise RuntimeError("yt-dlp не вернул сведения об итоговом файле")
        final_file = self._resolve_completed_file(info, request.output_dir)
        self._validate_completed_media(request, final_file)
        return final_file


def _serializable_progress(status: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "filename",
        "downloaded_bytes",
        "total_bytes",
        "total_bytes_estimate",
        "_speed_str",
        "_percent_str",
        "_eta_str",
    )
    return {key: status[key] for key in keys if key in status}


def _download_worker(request: DownloadRequest, messages: Any) -> None:
    engine = DownloadEngine(
        lambda status: messages.put(("progress", _serializable_progress(status))),
        lambda message: messages.put(("log", message)),
        isolate_download=False,
    )
    try:
        result = engine.download(request)
        messages.put(("result", str(result)))
    except FormatUnavailableError as exc:
        messages.put(("error", ("format", str(exc))))
    except yt_dlp.utils.DownloadError as exc:
        messages.put(("error", ("download", str(exc))))
    except Exception as exc:
        messages.put(("error", ("runtime", str(exc))))

