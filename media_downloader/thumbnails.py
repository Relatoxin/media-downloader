from __future__ import annotations


def safe_thumbnail_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {"user-agent", "referer", "accept", "accept-language"}
    return {
        name: value
        for name, value in headers.items()
        if name.lower() in allowed and isinstance(value, str) and "\r" not in value and "\n" not in value
    }


def preferred_thumbnail(extension_preview: str, analyzed_thumbnail: str) -> str:
    return extension_preview or analyzed_thumbnail

