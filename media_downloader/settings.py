from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .i18n import normalize_language


@dataclass(frozen=True, slots=True)
class AppSettings:
    output_dir: Path
    language: str = "ru"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            path = local_app_data / "MediaDownloader" / "settings.json"
        self.path = path.expanduser().resolve()

    def load(self, default_output_dir: Path, *, default_language: str = "ru") -> AppSettings:
        fallback = AppSettings(default_output_dir.expanduser().resolve(), normalize_language(default_language))
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            value = payload.get("outputDir") if isinstance(payload, dict) else None
            if not isinstance(value, str):
                return fallback
            output_dir = Path(value).expanduser()
            if not output_dir.is_absolute() or not output_dir.is_dir():
                return fallback
            raw_language = payload.get("language")
            language = "ru" if raw_language is None else normalize_language(str(raw_language))
            return AppSettings(output_dir.resolve(), language)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return fallback

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        payload = {
            "outputDir": str(settings.output_dir.expanduser().resolve()),
            "language": normalize_language(settings.language),
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
