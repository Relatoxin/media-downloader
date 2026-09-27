from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import imageio_ffmpeg
from PIL import Image

MEDIA_HEADER_NAMES = {
    "accept",
    "accept-language",
    "authorization",
    "cookie",
    "origin",
    "referer",
    "user-agent",
}
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


def safe_media_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() in MEDIA_HEADER_NAMES and isinstance(value, str) and "\r" not in value and "\n" not in value
    }


def build_frame_command(source_url: str, headers: dict[str, str], *, seek: float = 3.0) -> list[str]:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Preview source must be an HTTP URL")
    filtered = safe_media_headers(headers)
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    user_agent = next((value for name, value in filtered.items() if name.lower() == "user-agent"), "")
    if user_agent:
        command.extend(["-user_agent", user_agent])
    header_lines = [f"{name}: {value}" for name, value in filtered.items() if name.lower() != "user-agent"]
    if header_lines:
        command.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    command.extend(
        [
            "-ss",
            f"{max(0.0, seek):.2f}",
            "-i",
            source_url,
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
    )
    return command


def extract_video_frame(
    source_url: str,
    headers: dict[str, str],
    *,
    timeout: float = 15.0,
    runner: Callable[..., Any] = subprocess.run,
) -> bytes | None:
    try:
        completed = runner(
            build_frame_command(source_url, headers),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        raw = bytes(completed.stdout or b"")
        if completed.returncode != 0 or not 16 <= len(raw) <= MAX_PREVIEW_BYTES:
            return None
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        return raw
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

