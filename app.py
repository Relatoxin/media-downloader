from __future__ import annotations

import base64
import multiprocessing
import queue
import sys
import threading
import tkinter as tk
import urllib.request
from collections.abc import Callable
from functools import partial
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from PIL import Image, ImageTk

from media_downloader.controller import DownloadController
from media_downloader.engine import DownloadCancelled, DownloadEngine, validate_url
from media_downloader.errors import friendly_error
from media_downloader.explorer import ExplorerStatus, open_folder, show_in_explorer
from media_downloader.i18n import system_language, translate
from media_downloader.jobs import JobState, PreparedJob
from media_downloader.previews import extract_video_frame
from media_downloader.server import PORT, CompanionServer
from media_downloader.settings import AppSettings, SettingsStore
from media_downloader.thumbnails import safe_thumbnail_headers

APP_BG, CARD_BG, TEXT, MUTED, ACCENT = "#0f172a", "#172033", "#e5e7eb", "#94a3b8", "#38bdf8"
APP_VERSION = "0.6.0"
LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def set_window_icon(window: Any, icon_path: Path) -> None:
    try:
        window.iconbitmap(default=str(icon_path))
    except (OSError, tk.TclError):
        pass


def can_remove_job(state: JobState) -> bool:
    return state != JobState.DOWNLOADING


def wheel_units(delta: int) -> int:
    if delta == 0:
        return 0
    magnitude = max(1, abs(delta) // 120)
    return -magnitude if delta > 0 else magnitude


def can_scroll_region(bbox: tuple[int, int, int, int] | None, viewport_height: int) -> bool:
    return bool(bbox and bbox[3] - bbox[1] > viewport_height)


def restore_window(window: Any) -> None:
    try:
        window.deiconify()
        window.lift()
        window.after_idle(window.focus_force)
    except tk.TclError:
        pass


class MediaDownloaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Media Downloader {APP_VERSION}")
        set_window_icon(self, resource_path("assets/app-icon.ico"))
        self.geometry("940x760")
        self.minsize(760, 620)
        self.configure(bg=APP_BG)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.companion: CompanionServer | None = None
        self.format_vars: dict[str, tk.StringVar] = {}
        self.thumbnail_images: dict[str, ImageTk.PhotoImage] = {}
        self.thumbnail_loading: set[str] = set()
        self.url_var = tk.StringVar()
        self.settings_store = SettingsStore()
        default_output = Path.home() / "Downloads" / "Media Downloader"
        settings = self.settings_store.load(default_output, default_language=system_language())
        self.language = settings.language
        self.language_var = tk.StringVar(value=LANGUAGE_NAMES[self.language])
        self.output_var = tk.StringVar(value=str(settings.output_dir))
        self.browser_var = tk.StringVar(value=self._t("browser.none"))
        self.status_var = tk.StringVar(value=self._t("status.ready"))
        self.helper_status_var = tk.StringVar(value=self._t("companion.starting"))
        self.progress_var = tk.DoubleVar(value=0)
        self.controller = DownloadController(
            engine_factory=self._engine,
            output_dir_provider=self._output_dir,
            browser_provider=self._browser,
            language_provider=lambda: self.language,
            on_change=lambda job: self.events.put(("job_change", job.job_id)),
        )
        self._build_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_companion()
        self.after(100, self._drain_events)

    def _t(self, key: str, **values: Any) -> str:
        return translate(key, self.language, **values)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=APP_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabel", background=APP_BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 24), foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT)
        style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED)
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Accent.TButton", background=ACCENT, foreground="#082f49")
        style.map("Accent.TButton", background=[("active", "#7dd3fc"), ("disabled", "#334155")])
        style.configure("TEntry", fieldbackground="#0b1220", foreground=TEXT, insertcolor=TEXT, padding=8)
        style.configure("TCombobox", fieldbackground="#0b1220", foreground=TEXT, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", "#0b1220")], foreground=[("readonly", TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor="#0b1220", background=ACCENT)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        title_row = ttk.Frame(root)
        title_row.pack(fill="x")
        ttk.Label(title_row, text="Media Downloader", style="Title.TLabel").pack(side="left")
        language = ttk.Combobox(
            title_row,
            textvariable=self.language_var,
            values=list(LANGUAGE_NAMES.values()),
            state="readonly",
            width=10,
        )
        language.pack(side="right")
        language.bind("<<ComboboxSelected>>", self._change_language)
        ttk.Label(root, text=self._t("app.tagline"), style="Muted.TLabel").pack(anchor="w", pady=(3, 14))
        card = ttk.Frame(root, style="Card.TFrame", padding=16)
        card.pack(fill="x")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=self._t("label.page_url"), style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(card, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(5, 10))
        ttk.Label(card, text=self._t("label.output_dir"), style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.output_var).grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(card, text=self._t("button.browse"), command=self._choose_output).grid(
            row=3, column=1, padx=(8, 0), pady=(5, 0)
        )
        ttk.Combobox(
            card,
            textvariable=self.browser_var,
            values=[self._t("browser.none"), "Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi"],
            state="readonly",
            width=18,
        ).grid(row=3, column=2, padx=(8, 0), pady=(5, 0))
        self.add_url_button = ttk.Button(
            card, text=self._t("button.add_url"), style="Accent.TButton", command=self._prepare_url
        )
        self.add_url_button.grid(row=3, column=3, padx=(8, 0), pady=(5, 0))
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(14, 6))
        ttk.Label(header, text=self._t("header.tasks"), font=("Segoe UI Semibold", 13)).pack(side="left")
        ttk.Label(header, textvariable=self.helper_status_var, style="Muted.TLabel").pack(side="right")
        host = ttk.Frame(root)
        host.pack(fill="both", expand=True)
        self.task_canvas = tk.Canvas(host, bg=APP_BG, highlightthickness=0, height=260)
        scroll = ttk.Scrollbar(host, orient="vertical", command=self.task_canvas.yview)
        self.tasks_frame = ttk.Frame(self.task_canvas)
        self.tasks_window = self.task_canvas.create_window((0, 0), window=self.tasks_frame, anchor="nw")
        self.task_canvas.configure(yscrollcommand=scroll.set)
        self.tasks_frame.bind(
            "<Configure>", lambda _e: self.task_canvas.configure(scrollregion=self.task_canvas.bbox("all"))
        )
        self.task_canvas.bind("<Configure>", lambda e: self.task_canvas.itemconfigure(self.tasks_window, width=e.width))
        self.task_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._on_mouse_wheel, add="+")
        ttk.Label(root, textvariable=self.status_var).pack(anchor="w", pady=(10, 0))
        self.progress = ttk.Progressbar(root, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x", pady=(5, 8))
        self.log = tk.Text(
            root,
            height=7,
            bg="#0b1220",
            fg="#cbd5e1",
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            font=("Cascadia Mono", 9),
            state="disabled",
        )
        self.log.pack(fill="x")
        self._render_jobs()
        self.url_entry.focus_set()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get(), title=self._t("dialog.choose_folder"))
        if selected:
            self.output_var.set(selected)
            self._persist_output_dir()

    def _persist_output_dir(self) -> None:
        language = getattr(self, "language", "ru")
        try:
            output_dir = self._output_dir().expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            self.settings_store.save(AppSettings(output_dir=output_dir, language=language))
        except (OSError, ValueError) as exc:
            self._append_log(translate("warning.save_output", language, error=exc))

    def _change_language(self, _event: tk.Event | None = None) -> None:
        selected = self.language_var.get()
        language = next((code for code, name in LANGUAGE_NAMES.items() if name == selected), self.language)
        if language == self.language:
            return
        current_browser = self.browser_var.get()
        browser_was_disabled = current_browser in {translate("browser.none", "ru"), translate("browser.none", "en")}
        self.language = language
        if browser_was_disabled:
            self.browser_var.set(self._t("browser.none"))
        self.status_var.set(self._t("status.ready"))
        self.helper_status_var.set(
            self._t("companion.connected", version=APP_VERSION, port=PORT)
            if self.companion is not None
            else self._t("companion.unavailable")
        )
        self._persist_output_dir()
        self.unbind_all("<MouseWheel>")
        for child in self.winfo_children():
            child.destroy()
        self.format_vars.clear()
        self._build_style()
        self._build_ui()

    def _on_mouse_wheel(self, event: tk.Event) -> str | None:
        widget: Any = event.widget
        while widget is not None and widget not in {self.task_canvas, self.tasks_frame}:
            widget = getattr(widget, "master", None)
        if widget is None or not can_scroll_region(self.task_canvas.bbox("all"), self.task_canvas.winfo_height()):
            return None
        units = wheel_units(int(getattr(event, "delta", 0)))
        if units:
            self.task_canvas.yview_scroll(units, "units")
            return "break"
        return None

    def _output_dir(self) -> Path:
        value = self.output_var.get().strip()
        if not value:
            raise ValueError(translate("error.output_required", getattr(self, "language", "ru")))
        return Path(value)

    def _browser(self) -> str | None:
        label = self.browser_var.get()
        disabled_labels = {translate("browser.none", "ru"), translate("browser.none", "en")}
        return None if label in disabled_labels else label.lower()

    def _engine(self) -> DownloadEngine:
        return DownloadEngine(
            lambda data: self.events.put(("progress", data)),
            lambda text: self.events.put(("log", text)),
            self.cancel_event,
            language=self.language,
        )

    def _start_companion(self) -> None:
        try:
            self.companion = CompanionServer(
                prepare_callback=lambda payload: self.events.put(("prepare_payload", payload)),
                start_callback=lambda payload: self.events.put(("start_payload", payload)),
            )
            self.companion.start()
            self.helper_status_var.set(self._t("companion.connected", version=APP_VERSION, port=PORT))
            self._append_log(self._t("companion.log_ready", version=APP_VERSION, port=PORT))
        except OSError as exc:
            self.helper_status_var.set(self._t("companion.unavailable"))
            self._append_log(self._t("companion.log_failed", error=exc))

    def _prepare_url(self) -> None:
        try:
            url = validate_url(self.url_var.get(), self.language)
        except ValueError as exc:
            messagebox.showerror(self._t("dialog.invalid_url"), str(exc), parent=self)
            return
        self._launch_prepare(
            {
                "sourceType": "page_url",
                "url": url,
                "pageUrl": url,
                "title": self._t("job.analysis_title"),
                "browser": self._browser(),
            }
        )

    def _launch_prepare(self, payload: dict[str, Any]) -> None:
        self.add_url_button.configure(state="disabled")
        self.status_var.set(self._t("status.analyzing"))
        threading.Thread(target=self._run_prepare, args=(payload,), daemon=True).start()

    def _run_prepare(self, payload: dict[str, Any]) -> None:
        try:
            job = self.controller.prepare(payload)
            self.events.put(("prepare_done", job.job_id))
        except Exception as exc:
            self.events.put(("prepare_error", friendly_error(exc, language=self.language)))

    def _start_job(self, job_id: str) -> None:
        if self.controller.store.active_job_id is not None:
            messagebox.showinfo(
                self._t("dialog.download_active_title"),
                self._t("dialog.download_active_body"),
                parent=self,
            )
            return
        job = self.controller.store.get(job_id)
        key = job.selected_format_key
        if variable := self.format_vars.get(job_id):
            option = next((item for item in job.formats if self._format_label(item) == variable.get()), None)
            key = option.key if option else None
        self.cancel_event.clear()
        self.progress_var.set(0)
        self._persist_output_dir()
        threading.Thread(target=self._run_start, args=(job_id, key), daemon=True).start()

    def _run_start(self, job_id: str, key: str | None) -> None:
        try:
            self.controller.start(job_id, key)
            self.events.put(("download_done", job_id))
        except DownloadCancelled:
            self.events.put(("download_cancelled", job_id))
        except Exception as exc:
            self.events.put(("download_error", friendly_error(exc, language=self.language)))

    def _remove_job(self, job_id: str) -> None:
        try:
            self.controller.remove(job_id)
            self.format_vars.pop(job_id, None)
            self.thumbnail_images.pop(job_id, None)
            self._render_jobs()
        except RuntimeError as exc:
            messagebox.showerror(self._t("dialog.remove_failed"), str(exc), parent=self)

    def _open_job_file(self, job_id: str) -> None:
        job = self.controller.store.get(job_id)
        if job.output_path is None:
            messagebox.showinfo(
                self._t("dialog.file_unavailable_title"),
                self._t("dialog.file_unavailable_body"),
                parent=self,
            )
            return
        result = show_in_explorer(job.output_path)
        if result.status == ExplorerStatus.SELECTED:
            return
        if result.status == ExplorerStatus.MISSING:
            if result.folder.is_dir() and messagebox.askyesno(
                self._t("dialog.file_moved_title"),
                self._t("dialog.file_moved_body"),
                parent=self,
            ):
                folder_result = open_folder(result.folder)
                if folder_result.status == ExplorerStatus.FAILED:
                    messagebox.showerror(self._t("dialog.open_folder_failed"), folder_result.error, parent=self)
            else:
                messagebox.showinfo(
                    self._t("dialog.file_missing_title"), self._t("dialog.file_missing_body"), parent=self
                )
            return
        messagebox.showerror(self._t("dialog.explorer_failed"), result.error, parent=self)

    def _render_jobs(self) -> None:
        for child in self.tasks_frame.winfo_children():
            child.destroy()
        jobs = self.controller.store.list()
        if not jobs:
            ttk.Label(
                self.tasks_frame,
                text=self._t("empty.jobs"),
                style="Muted.TLabel",
            ).pack(anchor="w", pady=18)
            return
        for job in jobs:
            self._render_job(job)

    def _render_job(self, job: PreparedJob) -> None:
        card = ttk.Frame(self.tasks_frame, style="Card.TFrame", padding=12)
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(1, weight=1)
        preview = ttk.Label(
            card, text=self._t("preview.unavailable"), style="CardMuted.TLabel", anchor="center", width=22
        )
        preview.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=(0, 12))
        if job.job_id in self.thumbnail_images:
            preview.configure(image=self.thumbnail_images[job.job_id], text="")
        elif job.state != JobState.ANALYZING:
            preview.configure(text=self._t("preview.loading"))
            self._request_thumbnail(job)
        ttk.Label(card, text=job.title, style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(
            row=0, column=1, sticky="w"
        )
        source = job.platform or (
            self._t("source.detected") if job.active_quality_confirmed else self._t("source.analysis")
        )
        ttk.Label(
            card,
            text=f"{source} · {self._duration(job.duration)} · {self._state_label(job.state)}",
            style="CardMuted.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(3, 6))
        if len(job.formats) > 1:
            labels = [self._format_label(item) for item in job.formats]
            selected = self._format_label(job.selected_format) if job.selected_format else labels[0]
            variable = self.format_vars.setdefault(job.job_id, tk.StringVar(value=selected))
            ttk.Combobox(card, textvariable=variable, values=labels, state="readonly").grid(
                row=2, column=1, sticky="ew"
            )
        elif job.formats:
            ttk.Label(card, text=self._format_label(job.formats[0]), style="Card.TLabel").grid(
                row=2, column=1, sticky="w"
            )
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=1, sticky="w", pady=(8, 0))
        can_start = job.state == JobState.READY and self.controller.store.active_job_id is None
        ttk.Button(
            actions,
            text=self._t("button.start"),
            style="Accent.TButton",
            command=partial(self._start_job, job.job_id),
            state="normal" if can_start else "disabled",
        ).pack(side="left")
        if job.state == JobState.DOWNLOADING:
            ttk.Button(actions, text=self._t("button.cancel"), command=self._cancel).pack(side="left", padx=(7, 0))
        elif job.state == JobState.COMPLETED and job.output_path is not None:
            ttk.Button(
                actions,
                text=self._t("button.open_explorer"),
                command=partial(self._open_job_file, job.job_id),
            ).pack(side="left", padx=(7, 0))
            ttk.Button(actions, text=self._t("button.remove"), command=partial(self._remove_job, job.job_id)).pack(
                side="left", padx=(7, 0)
            )
        elif can_remove_job(job.state):
            ttk.Button(actions, text=self._t("button.remove"), command=partial(self._remove_job, job.job_id)).pack(
                side="left", padx=(7, 0)
            )
        if job.message:
            ttk.Label(card, text=job.message, style="CardMuted.TLabel", wraplength=580).grid(
                row=4, column=1, sticky="w", pady=(6, 0)
            )

    def _format_label(self, option: Any) -> str:
        if option.key == "best":
            return self._t("format.best")
        if option.key == "audio-mp3":
            return self._t("format.audio_mp3")
        if option.key == "audio-source":
            return self._t("format.audio_source")
        if option.key == "captured":
            if option.height:
                return self._t("format.captured_height", height=option.height)
            return self._t("format.captured")
        if option.key.startswith("video-") and option.height:
            fps = f" · {int(option.fps)} FPS" if option.fps and option.fps > 30 else ""
            return self._t("format.video", height=option.height, fps=fps)
        return option.label

    def _request_thumbnail(self, job: PreparedJob) -> None:
        if job.job_id in self.thumbnail_loading:
            return
        self.thumbnail_loading.add(job.job_id)
        threading.Thread(
            target=self._load_thumbnail,
            args=(job.job_id, job.thumbnail, job.url, job.headers),
            daemon=True,
        ).start()

    def _load_thumbnail(self, job_id: str, value: str, source_url: str, headers: dict[str, str]) -> None:
        try:
            raw: bytes | None = None
            if value:
                try:
                    if value.startswith("data:image/"):
                        raw = base64.b64decode(value.split(",", 1)[1])
                    else:
                        request = urllib.request.Request(value, headers=safe_thumbnail_headers(headers))
                        with urllib.request.urlopen(request, timeout=10) as response:
                            raw = response.read(2 * 1024 * 1024 + 1)
                except Exception:
                    raw = None
            if raw is None:
                raw = extract_video_frame(source_url, headers)
            if raw is None:
                raise ValueError(self._t("error.preview_unavailable"))
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError(self._t("error.preview_too_large"))
            image = Image.open(BytesIO(raw)).convert("RGB")
            image.thumbnail((176, 99), Image.Resampling.LANCZOS)
            self.events.put(("thumbnail", (job_id, image)))
        except Exception:
            self.events.put(("thumbnail_failed", job_id))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set(self._t("status.cancelling"))

    def _duration(self, seconds: float | None) -> str:
        if not seconds:
            return self._t("duration.unknown")
        total = round(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    def _state_label(self, state: JobState) -> str:
        return self._t(f"state.{state.value}")

    def _append_log(self, text: str) -> None:
        if text.strip():
            self.log.configure(state="normal")
            self.log.insert("end", text.rstrip() + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

    def _update_progress(self, data: dict[str, Any]) -> None:
        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            if total:
                percent = min(downloaded / total * 100, 100)
                self.progress.configure(mode="determinate")
                self.progress_var.set(percent)
                self.status_var.set(
                    self._t("status.download", percent=percent, speed=data.get("_speed_str", "").strip())
                )
            else:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.status_var.set(self._t("status.downloading"))
        elif data.get("status") == "finished":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(100)
            self.status_var.set(self._t("status.processing"))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self._update_progress(payload)
                elif kind == "log":
                    self._append_log(str(payload))
                elif kind == "prepare_payload":
                    restore_window(self)
                    self._launch_prepare(payload)
                elif kind == "start_payload":
                    self._start_job(str(payload["jobId"]))
                elif kind == "job_change":
                    self._render_jobs()
                elif kind == "prepare_done":
                    self.add_url_button.configure(state="normal")
                    self.status_var.set(self._t("status.prepared"))
                    self._render_jobs()
                elif kind == "prepare_error":
                    self.add_url_button.configure(state="normal")
                    self.status_var.set(self._t("status.analysis_error"))
                    self._append_log(self._t("log.error", error=payload))
                    messagebox.showerror(self._t("dialog.prepare_failed"), str(payload), parent=self)
                elif kind == "download_done":
                    self.progress.stop()
                    self.progress_var.set(100)
                    self.status_var.set(self._t("status.done", directory=self.output_var.get()))
                    self._render_jobs()
                elif kind == "download_cancelled":
                    self.progress.stop()
                    self.status_var.set(self._t("status.cancelled"))
                    self._render_jobs()
                elif kind == "download_error":
                    self.progress.stop()
                    self.status_var.set(self._t("status.download_error"))
                    self._append_log(self._t("log.error", error=payload))
                    self._render_jobs()
                    messagebox.showerror(self._t("dialog.download_failed"), str(payload), parent=self)
                elif kind == "thumbnail":
                    job_id, image = payload
                    self.thumbnail_loading.discard(job_id)
                    self.thumbnail_images[job_id] = ImageTk.PhotoImage(image)
                    self._render_jobs()
                elif kind == "thumbnail_failed":
                    self.thumbnail_loading.discard(str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _on_close(self) -> None:
        self.cancel_event.set()
        self.unbind_all("<MouseWheel>")
        if self.companion:
            self.companion.stop()
        self.destroy()


def main(
    *,
    app_factory: Callable[[], Any] = MediaDownloaderApp,
    freeze_support: Callable[[], None] = multiprocessing.freeze_support,
) -> None:
    freeze_support()
    app_factory().mainloop()


if __name__ == "__main__":
    main()
