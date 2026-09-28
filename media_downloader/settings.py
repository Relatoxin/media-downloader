from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    output_dir: Path


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            path = local_app_data / "MediaDownloader" / "settings.json"
        self.path = path.expanduser().resolve()

    def load(self, default_output_dir: Path) -> AppSettings:
        fallback = AppSettings(default_output_dir.expanduser().resolve())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            value = payload.get("outputDir") if isinstance(payload, dict) else None
            if not isinstance(value, str):
                return fallback
            output_dir = Path(value).expanduser()
            if not output_dir.is_absolute() or not output_dir.is_dir():
                return fallback
            return AppSettings(output_dir.resolve())
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return fallback

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        payload = {"outputDir": str(settings.output_dir.expanduser().resolve())}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
