from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .jobs import FormatOption


@dataclass(frozen=True, slots=True)
class MediaAnalysis:
    title: str
    thumbnail: str
    duration: float | None
    platform: str
    formats: tuple[FormatOption, ...]


def _number(value: Any) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _preference(item: dict[str, Any]) -> tuple[int, int, int]:
    codec = str(item.get("vcodec") or "")
    return (
        1 if item.get("ext") == "mp4" else 0,
        1 if codec.startswith(("avc", "h264")) else 0,
        _number(item.get("filesize") or item.get("filesize_approx")) or 0,
    )


def build_format_options(info: dict[str, Any]) -> tuple[FormatOption, ...]:
    formats = [item for item in info.get("formats") or () if isinstance(item, dict)]
    audio_formats = [
        item for item in formats if item.get("acodec") not in {None, "none"} and item.get("vcodec") in {None, "none"}
    ]
    best_audio = max(
        audio_formats, key=lambda item: _number(item.get("filesize") or item.get("filesize_approx")) or 0, default=None
    )

    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for item in formats:
        height = _number(item.get("height"))
        if not height or item.get("vcodec") in {None, "none"}:
            continue
        fps = int(float(item.get("fps") or 0)) or 30
        key = (height, fps)
        if key not in grouped or _preference(item) > _preference(grouped[key]):
            grouped[key] = item

    options: list[FormatOption] = [
        FormatOption(
            key="best",
            label="Лучшее качество · видео со звуком",
            selector="bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        )
    ]
    for (height, fps), item in sorted(grouped.items(), reverse=True):
        format_id = str(item.get("format_id") or "")
        if not format_id:
            continue
        has_audio = item.get("acodec") not in {None, "none"}
        selector = format_id if has_audio else f"{format_id}+ba[ext=m4a]/{format_id}+ba/b[height={height}]"
        size = _number(item.get("filesize") or item.get("filesize_approx"))
        if not has_audio and size and best_audio:
            audio_size = _number(best_audio.get("filesize") or best_audio.get("filesize_approx"))
            size = size + audio_size if audio_size else size
        label = f"{height}p" + (f" · {fps} FPS" if fps > 30 else "") + " · видео со звуком"
        options.append(
            FormatOption(
                key=f"video-{height}p{fps}",
                label=label,
                selector=selector,
                height=height,
                fps=fps,
                extension=str(item.get("ext") or "") or None,
                filesize=size,
            )
        )

    has_any_audio = any(item.get("acodec") not in {None, "none"} for item in formats)
    if has_any_audio:
        options.append(
            FormatOption(
                key="audio-mp3",
                label="Только аудио · MP3 192 кбит/с",
                selector="bestaudio/best",
                media_type="audio",
                extension="mp3",
                audio_output="mp3",
            )
        )
    if audio_formats:
        options.append(
            FormatOption(
                key="audio-source",
                label="Только аудио · исходный формат",
                selector="bestaudio/best",
                media_type="audio",
                extension=str(best_audio.get("ext") or "") if best_audio else None,
                filesize=_number((best_audio or {}).get("filesize") or (best_audio or {}).get("filesize_approx")),
                audio_output="source",
            )
        )
    return tuple(options)
