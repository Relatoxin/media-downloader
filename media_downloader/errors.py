from __future__ import annotations

from .i18n import translate


def friendly_error(exc: Exception, *, language: str = "ru") -> str:
    text = str(exc)
    lowered = text.lower()
    if "drm" in lowered:
        return translate("error.drm", language)
    if "403" in lowered or "forbidden" in lowered:
        return translate("error.expired", language, details=text)
    if "cookies" in lowered or "sign in" in lowered or "login" in lowered:
        return translate("error.login", language, details=text)
    if "unavailable" in lowered or "not available" in lowered or "country" in lowered or "region" in lowered:
        return translate("error.unavailable", language, details=text)
    if "requested format" in lowered or "формат больше недоступен" in lowered:
        return translate("error.formats_refreshed", language)
    if "ffmpeg" in lowered:
        return translate("error.ffmpeg", language, details=text)
    if "неполный" in lowered or "поврежд" in lowered or "служебный или пустой" in lowered:
        return translate("error.corrupt", language, details=text)
    if "unsupported url" in lowered:
        return translate("error.unsupported", language, details=text)
    return text
