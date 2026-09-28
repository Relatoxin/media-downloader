from __future__ import annotations


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "drm" in lowered:
        return "Поток защищён DRM. Приложение не обходит DRM-защиту."
    if "403" in lowered or "forbidden" in lowered:
        return "Ссылка или подпись CDN устарела. Снова запустите видео в Chrome и добавьте поток заново.\n\n" + text
    if "cookies" in lowered or "sign in" in lowered or "login" in lowered:
        return "Сайт требует вход. Выберите браузер, где выполнен вход, и повторите анализ.\n\n" + text
    if "unavailable" in lowered or "not available" in lowered or "country" in lowered or "region" in lowered:
        return "Видео недоступно или ограничено для текущего региона/аккаунта.\n\n" + text
    if "requested format" in lowered or "формат больше недоступен" in lowered:
        return "Список форматов обновлён. Выберите качество снова."
    if "ffmpeg" in lowered:
        return "FFmpeg недоступен или не смог обработать медиа.\n\n" + text
    if "неполный" in lowered or "поврежд" in lowered or "служебный или пустой" in lowered:
        return "Итоговый файл повреждён или скачан не полностью.\n\n" + text
    if "unsupported url" in lowered:
        return "Эта страница пока не поддерживается yt-dlp.\n\n" + text
    return text
