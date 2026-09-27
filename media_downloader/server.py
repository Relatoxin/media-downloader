from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import urllib.request
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import imageio_ffmpeg
import yt_dlp

from .engine import validate_url

HOST = "127.0.0.1"
PORT = 17843
MAX_BODY = 128 * 1024
ALLOWED_HEADERS = {
    "accept",
    "accept-language",
    "accepts-controls",
    "authorization",
    "authorizations",
    "cache-control",
    "content-type",
    "cookie",
    "origin",
    "pragma",
    "referer",
    "user-agent",
}


PayloadCallback = Callable[[dict[str, Any]], None]
ProbeCallback = Callable[[dict[str, Any]], dict[str, Any]]


def sanitize_prepare_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Ожидался JSON-объект")
    url = validate_url(str(payload.get("url", "")))
    page_url = str(payload.get("pageUrl", "")).strip()
    if page_url:
        page_url = validate_url(page_url)
    title = str(payload.get("title", "Медиа из Chrome")).strip()[:200] or "Медиа из Chrome"
    source_type = str(payload.get("sourceType") or "captured_stream")
    if source_type not in {"captured_stream", "page_url"}:
        raise ValueError("Неизвестный тип источника")
    duration: float | None
    try:
        raw_duration = payload.get("duration")
        duration = float(raw_duration) if raw_duration is not None else None
        if duration is None:
            raise ValueError
        if not 0 < duration < 7 * 24 * 3600:
            duration = None
    except (TypeError, ValueError):
        duration = None

    raw_headers = payload.get("headers", {})
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        for name, value in raw_headers.items():
            lowered = str(name).lower().strip()
            is_extension_header = lowered.startswith("x-") or lowered.startswith("sec-fetch-")
            if (
                (lowered in ALLOWED_HEADERS or is_extension_header)
                and isinstance(value, str)
                and "\r" not in value
                and "\n" not in value
            ):
                headers[lowered.title()] = value[:16_384]
    if page_url and "Referer" not in headers:
        headers["Referer"] = page_url

    def dimension(name: str) -> int | None:
        try:
            raw_value = payload.get(name)
            if raw_value is None:
                return None
            value = int(raw_value)
            return value if 0 < value <= 16_384 else None
        except (TypeError, ValueError):
            return None

    thumbnail = str(payload.get("thumbnail") or "")
    if len(thumbnail) > 2 * 1024 * 1024 or (
        thumbnail and not thumbnail.startswith(("http://", "https://", "data:image/"))
    ):
        thumbnail = ""

    return {
        "jobId": uuid.uuid4().hex,
        "url": url,
        "pageUrl": page_url,
        "title": title,
        "kind": str(payload.get("kind", "media"))[:30],
        "sourceType": source_type,
        "activeQualityConfirmed": bool(payload.get("activeQualityConfirmed")),
        "width": dimension("width"),
        "height": dimension("height"),
        "thumbnail": thumbnail,
        "headers": headers,
        "duration": duration,
    }


sanitize_payload = sanitize_prepare_payload


def sanitize_start_payload(payload: Any) -> dict[str, str | None]:
    if not isinstance(payload, dict):
        raise ValueError("Ожидался JSON-объект")
    job_id = str(payload.get("jobId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise ValueError("Укажите корректный jobId")
    format_key = str(payload.get("formatKey") or "").strip() or None
    if format_key and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", format_key):
        raise ValueError("Некорректный formatKey")
    return {"jobId": job_id, "formatKey": format_key}


def probe_media(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(payload["url"], headers=payload["headers"])
    duration: float | None = None
    live = False
    width: int | None = None
    height: int | None = None
    thumbnail = ""
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            body = response.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        if "#EXTM3U" in body or "mpegurl" in content_type:
            fragments = [float(value) for value in re.findall(r"#EXTINF:([0-9]+(?:\.[0-9]+)?)", body)]
            if fragments:
                duration = sum(fragments)
                live = "#EXT-X-ENDLIST" not in body
            resolution = re.search(r"RESOLUTION=(\d+)x(\d+)", body, re.IGNORECASE)
            if resolution:
                width, height = int(resolution.group(1)), int(resolution.group(2))
        elif "dash+xml" in content_type or "<MPD" in body:
            iso_duration = re.search(
                r'mediaPresentationDuration="PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?"', body
            )
            if iso_duration:
                hours, minutes, seconds = (float(value or 0) for value in iso_duration.groups())
                duration = hours * 3600 + minutes * 60 + seconds
    except Exception:
        pass

    if duration is None:
        try:
            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 10,
                "extractor_retries": 1,
                "http_headers": payload["headers"],
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(payload["url"], download=False) or {}
            duration = info.get("duration")
            live = bool(info.get("is_live"))
            width = info.get("width")
            height = info.get("height")
            thumbnail = info.get("thumbnail") or ""
        except Exception:
            pass

    try:
        header_lines = []
        for name, value in payload["headers"].items():
            if name.lower() != "user-agent":
                header_lines.append(f"{name}: {value}")
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "info"]
        user_agent = payload["headers"].get("User-Agent")
        if user_agent:
            command.extend(["-user_agent", user_agent])
        if header_lines:
            command.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
        seek = min(10.0, max(1.0, float(duration or 5) * 0.2))
        command.extend(
            [
                "-ss",
                f"{seek:.2f}",
                "-i",
                payload["url"],
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
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0 and 1_000 < len(completed.stdout) < 2 * 1024 * 1024:
            thumbnail = "data:image/jpeg;base64," + base64.b64encode(completed.stdout).decode("ascii")
        if not width or not height:
            details = completed.stderr.decode("utf-8", errors="replace")
            dimensions = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", details, re.DOTALL)
            if dimensions:
                width, height = int(dimensions.group(1)), int(dimensions.group(2))
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    return {
        "duration": duration,
        "live": live,
        "width": width,
        "height": height,
        "thumbnail": thumbnail,
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class CompanionServer:
    def __init__(
        self,
        prepare_callback: PayloadCallback,
        start_callback: PayloadCallback | None = None,
        port: int = PORT,
        probe_callback: ProbeCallback = probe_media,
    ) -> None:
        self.prepare_callback = prepare_callback
        self.start_callback = start_callback or (lambda _payload: None)
        self.probe_callback = probe_callback
        self.port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        prepare_callback = self.prepare_callback
        start_callback = self.start_callback
        probe_callback = self.probe_callback

        class Handler(BaseHTTPRequestHandler):
            server_version = "MediaDownloaderCompanion/0.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _origin(self) -> str:
                return self.headers.get("Origin", "")

            def _cors_allowed(self) -> bool:
                origin = self._origin()
                return not origin or origin.startswith("chrome-extension://")

            def _send_json(self, status: int, data: dict[str, Any]) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                origin = self._origin()
                if origin.startswith("chrome-extension://"):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
                if not self._cors_allowed():
                    self._send_json(403, {"error": "Origin запрещён"})
                    return
                self.send_response(204)
                origin = self._origin()
                if origin.startswith("chrome-extension://"):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Media-Helper")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path == "/health":
                    self._send_json(200, {"ok": True, "service": "media-downloader", "version": 1})
                    return
                self._send_json(404, {"error": "Не найдено"})

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path not in {"/api/download", "/api/prepare", "/api/start", "/api/probe"}:
                    self._send_json(404, {"error": "Не найдено"})
                    return
                if not self._cors_allowed() or self.headers.get("X-Media-Helper") != "1":
                    self._send_json(403, {"error": "Запрос разрешён только расширению Chrome"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > MAX_BODY:
                        raise ValueError("Некорректный размер запроса")
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if self.path == "/api/download":
                        self._send_json(409, {"error": "Сначала добавьте задачу через /api/prepare"})
                        return
                    if self.path == "/api/start":
                        cleaned_start = sanitize_start_payload(payload)
                        start_callback(cleaned_start)
                        self._send_json(202, {"ok": True, **cleaned_start})
                        return
                    cleaned = sanitize_prepare_payload(payload)
                    if self.path == "/api/probe":
                        self._send_json(200, {"ok": True, **probe_callback(cleaned)})
                        return
                    prepare_callback(cleaned)
                    self._send_json(202, {"ok": True, "jobId": cleaned["jobId"]})
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._send_json(400, {"error": str(exc)})
                except Exception:
                    self._send_json(500, {"error": "Локальное приложение не приняло задачу"})

        self._server = _Server((HOST, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="companion-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

