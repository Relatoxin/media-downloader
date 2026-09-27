from __future__ import annotations

import base64
import queue
import threading
import tkinter as tk
import urllib.request
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
from media_downloader.jobs import JobState, PreparedJob
from media_downloader.previews import extract_video_frame
from media_downloader.server import PORT, CompanionServer
from media_downloader.settings import AppSettings, SettingsStore
from media_downloader.thumbnails import safe_thumbnail_headers

APP_BG, CARD_BG, TEXT, MUTED, ACCENT = "#0f172a", "#172033", "#e5e7eb", "#94a3b8", "#38bdf8"
APP_VERSION = "0.5.3"


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
        self.output_var = tk.StringVar(value=str(self.settings_store.load(default_output).output_dir))
        self.browser_var = tk.StringVar(value="Не использовать")
        self.status_var = tk.StringVar(value="Готово")
        self.helper_status_var = tk.StringVar(value="Расширение: запуск локальной связи…")
        self.progress_var = tk.DoubleVar(value=0)
        self.controller = DownloadController(
            engine_factory=self._engine,
            output_dir_provider=self._output_dir,
            browser_provider=self._browser,
            on_change=lambda job: self.events.put(("job_change", job.job_id)),
        )
        self._build_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_companion()
        self.after(100, self._drain_events)

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
        ttk.Label(root, text="Media Downloader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            root, text="Добавьте поток из Chrome или ссылку на YouTube, TikTok и другие сайты.", style="Muted.TLabel"
        ).pack(anchor="w", pady=(3, 14))
        card = ttk.Frame(root, style="Card.TFrame", padding=16)
        card.pack(fill="x")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Ссылка на страницу", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(card, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(5, 10))
        ttk.Label(card, text="Папка сохранения", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.output_var).grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(card, text="Обзор…", command=self._choose_output).grid(row=3, column=1, padx=(8, 0), pady=(5, 0))
        ttk.Combobox(
            card,
            textvariable=self.browser_var,
            values=["Не использовать", "Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi"],
            state="readonly",
            width=18,
        ).grid(row=3, column=2, padx=(8, 0), pady=(5, 0))
        self.add_url_button = ttk.Button(
            card, text="Добавить ссылку", style="Accent.TButton", command=self._prepare_url
        )
        self.add_url_button.grid(row=3, column=3, padx=(8, 0), pady=(5, 0))
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(14, 6))
        ttk.Label(header, text="Подготовленные задачи", font=("Segoe UI Semibold", 13)).pack(side="left")
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
        selected = filedialog.askdirectory(initialdir=self.output_var.get(), title="Выберите папку")
        if selected:
            self.output_var.set(selected)
            self._persist_output_dir()

    def _persist_output_dir(self) -> None:
        try:
            output_dir = self._output_dir().expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            self.settings_store.save(AppSettings(output_dir=output_dir))
        except (OSError, ValueError) as exc:
            self._append_log(f"Предупреждение: не удалось сохранить папку загрузки: {exc}")

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
            raise ValueError("Выберите папку сохранения")
        return Path(value)

    def _browser(self) -> str | None:
        label = self.browser_var.get()
        return None if label == "Не использовать" else label.lower()

    def _engine(self) -> DownloadEngine:
        return DownloadEngine(
            lambda data: self.events.put(("progress", data)),
            lambda text: self.events.put(("log", text)),
            self.cancel_event,
        )

    def _start_companion(self) -> None:
        try:
            self.companion = CompanionServer(
                prepare_callback=lambda payload: self.events.put(("prepare_payload", payload)),
                start_callback=lambda payload: self.events.put(("start_payload", payload)),
            )
            self.companion.start()
            self.helper_status_var.set(f"Расширение подключено · {APP_VERSION} · порт {PORT}")
            self._append_log(f"Media Downloader {APP_VERSION}\nЛокальная связь: http://127.0.0.1:{PORT}")
        except OSError as exc:
            self.helper_status_var.set("Расширение: порт недоступен")
            self._append_log(f"Не удалось запустить связь с расширением: {exc}")

    def _prepare_url(self) -> None:
        try:
            url = validate_url(self.url_var.get())
        except ValueError as exc:
            messagebox.showerror("Некорректная ссылка", str(exc), parent=self)
            return
        self._launch_prepare(
            {"sourceType": "page_url", "url": url, "pageUrl": url, "title": "Анализ ссылки", "browser": self._browser()}
        )

    def _launch_prepare(self, payload: dict[str, Any]) -> None:
        self.add_url_button.configure(state="disabled")
        self.status_var.set("Анализирую доступные форматы…")
        threading.Thread(target=self._run_prepare, args=(payload,), daemon=True).start()

    def _run_prepare(self, payload: dict[str, Any]) -> None:
        try:
            job = self.controller.prepare(payload)
            self.events.put(("prepare_done", job.job_id))
        except Exception as exc:
            self.events.put(("prepare_error", friendly_error(exc)))

    def _start_job(self, job_id: str) -> None:
        if self.controller.store.active_job_id is not None:
            messagebox.showinfo("Загрузка уже идёт", "Дождитесь завершения или отмените текущую загрузку.", parent=self)
            return
        job = self.controller.store.get(job_id)
        key = job.selected_format_key
        if variable := self.format_vars.get(job_id):
            option = next((item for item in job.formats if item.label == variable.get()), None)
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
            self.events.put(("download_error", friendly_error(exc)))

    def _remove_job(self, job_id: str) -> None:
        try:
            self.controller.remove(job_id)
            self.format_vars.pop(job_id, None)
            self.thumbnail_images.pop(job_id, None)
            self._render_jobs()
        except RuntimeError as exc:
            messagebox.showerror("Нельзя удалить задачу", str(exc), parent=self)

    def _open_job_file(self, job_id: str) -> None:
        job = self.controller.store.get(job_id)
        if job.output_path is None:
            messagebox.showinfo("Файл недоступен", "У задачи нет сохранённого пути к файлу.", parent=self)
            return
        result = show_in_explorer(job.output_path)
        if result.status == ExplorerStatus.SELECTED:
            return
        if result.status == ExplorerStatus.MISSING:
            if result.folder.is_dir() and messagebox.askyesno(
                "Файл перемещён",
                "Скачанный файл не найден по сохранённому пути. Открыть папку загрузки?",
                parent=self,
            ):
                folder_result = open_folder(result.folder)
                if folder_result.status == ExplorerStatus.FAILED:
                    messagebox.showerror("Не удалось открыть папку", folder_result.error, parent=self)
            else:
                messagebox.showinfo("Файл не найден", "Файл был перемещён или удалён.", parent=self)
            return
        messagebox.showerror("Не удалось открыть Проводник", result.error, parent=self)

    def _render_jobs(self) -> None:
        for child in self.tasks_frame.winfo_children():
            child.destroy()
        jobs = self.controller.store.list()
        if not jobs:
            ttk.Label(
                self.tasks_frame,
                text="Задач пока нет. Добавьте поток из расширения или вставьте ссылку выше.",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=18)
            return
        for job in jobs:
            self._render_job(job)

    def _render_job(self, job: PreparedJob) -> None:
        card = ttk.Frame(self.tasks_frame, style="Card.TFrame", padding=12)
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(1, weight=1)
        preview = ttk.Label(card, text="Превью\nнедоступно", style="CardMuted.TLabel", anchor="center", width=22)
        preview.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=(0, 12))
        if job.job_id in self.thumbnail_images:
            preview.configure(image=self.thumbnail_images[job.job_id], text="")
        elif job.state != JobState.ANALYZING:
            preview.configure(text="Загрузка\nпревью…")
            self._request_thumbnail(job)
        ttk.Label(card, text=job.title, style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(
            row=0, column=1, sticky="w"
        )
        source = job.platform or ("Обнаруженный поток" if job.active_quality_confirmed else "Анализ ссылки")
        ttk.Label(
            card,
            text=f"{source} · {self._duration(job.duration)} · {self._state_label(job.state)}",
            style="CardMuted.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(3, 6))
        if len(job.formats) > 1:
            labels = [item.label for item in job.formats]
            selected = job.selected_format.label if job.selected_format else labels[0]
            variable = self.format_vars.setdefault(job.job_id, tk.StringVar(value=selected))
            ttk.Combobox(card, textvariable=variable, values=labels, state="readonly").grid(
                row=2, column=1, sticky="ew"
            )
        elif job.formats:
            ttk.Label(card, text=job.formats[0].label, style="Card.TLabel").grid(row=2, column=1, sticky="w")
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=1, sticky="w", pady=(8, 0))
        can_start = job.state == JobState.READY and self.controller.store.active_job_id is None
        ttk.Button(
            actions,
            text="Начать загрузку",
            style="Accent.TButton",
            command=partial(self._start_job, job.job_id),
            state="normal" if can_start else "disabled",
        ).pack(side="left")
        if job.state == JobState.DOWNLOADING:
            ttk.Button(actions, text="Отменить", command=self._cancel).pack(side="left", padx=(7, 0))
        elif job.state == JobState.COMPLETED and job.output_path is not None:
            ttk.Button(actions, text="Открыть в проводнике", command=partial(self._open_job_file, job.job_id)).pack(
                side="left", padx=(7, 0)
            )
            ttk.Button(actions, text="Удалить", command=partial(self._remove_job, job.job_id)).pack(
                side="left", padx=(7, 0)
            )
        elif can_remove_job(job.state):
            ttk.Button(actions, text="Удалить", command=partial(self._remove_job, job.job_id)).pack(
                side="left", padx=(7, 0)
            )
        if job.message:
            ttk.Label(card, text=job.message, style="CardMuted.TLabel", wraplength=580).grid(
                row=4, column=1, sticky="w", pady=(6, 0)
            )

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
                raise ValueError("Превью недоступно")
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Превью слишком большое")
            image = Image.open(BytesIO(raw)).convert("RGB")
            image.thumbnail((176, 99), Image.Resampling.LANCZOS)
            self.events.put(("thumbnail", (job_id, image)))
        except Exception:
            self.events.put(("thumbnail_failed", job_id))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Отмена после завершения текущего фрагмента…")

    @staticmethod
    def _duration(seconds: float | None) -> str:
        if not seconds:
            return "длительность неизвестна"
        total = round(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    @staticmethod
    def _state_label(state: JobState) -> str:
        return {
            JobState.ANALYZING: "анализ",
            JobState.READY: "готово к загрузке",
            JobState.DOWNLOADING: "загружается",
            JobState.COMPLETED: "завершено",
            JobState.FAILED: "ошибка",
            JobState.CANCELLED: "отменено",
        }[state]

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
                self.status_var.set(f"Загрузка: {percent:.1f}% — {data.get('_speed_str', '').strip()}")
            else:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.status_var.set("Загрузка…")
        elif data.get("status") == "finished":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(100)
            self.status_var.set("Обработка файла…")

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
                    self.status_var.set("Задача подготовлена. Нажмите «Начать загрузку».")
                    self._render_jobs()
                elif kind == "prepare_error":
                    self.add_url_button.configure(state="normal")
                    self.status_var.set("Ошибка анализа")
                    self._append_log(f"Ошибка: {payload}")
                    messagebox.showerror("Не удалось подготовить задачу", str(payload), parent=self)
                elif kind == "download_done":
                    self.progress.stop()
                    self.progress_var.set(100)
                    self.status_var.set(f"Готово. Файл сохранён в {self.output_var.get()}")
                    self._render_jobs()
                elif kind == "download_cancelled":
                    self.progress.stop()
                    self.status_var.set("Загрузка отменена")
                    self._render_jobs()
                elif kind == "download_error":
                    self.progress.stop()
                    self.status_var.set("Ошибка загрузки")
                    self._append_log(f"Ошибка: {payload}")
                    self._render_jobs()
                    messagebox.showerror("Не удалось скачать медиа", str(payload), parent=self)
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


if __name__ == "__main__":
    MediaDownloaderApp().mainloop()

