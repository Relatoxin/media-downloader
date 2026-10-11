(function initExtensionI18n(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ExtensionI18n = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const messages = {
    ru: {
      title: "Медиапотоки",
      connectionChecking: "Проверка локального приложения…",
      connectionReady: "Локальное приложение подключено",
      connectionMissing: "Сначала запустите MediaDownloader.exe",
      diagnostics: "Диагностика",
      diagnosticsTitle: "Скопировать безопасный диагностический отчёт",
      clear: "Очистить",
      addPage: "Добавить текущую страницу",
      previewAlt: "Кадр из воспроизводимого видео",
      durationUnknown: "Длительность неизвестна",
      removeTitle: "Убрать из списка",
      addToApp: "Добавить в приложение",
      footer: "Добавление не начинает загрузку. Запуск выполняется отдельно в локальном приложении. DRM не поддерживается.",
      languageTitle: "Язык интерфейса",
      appNotRunning: "Локальное приложение не запущено. Запустите MediaDownloader.exe и откройте расширение снова.",
      transferring: "Передача…",
      taskAdded: "Задача добавлена. Запустите её кнопкой в локальном приложении.",
      added: "Добавлено",
      transferFailed: "Не удалось передать поток: {error}",
      noStreams: "Потоки не обнаружены. Запустите воспроизведение нужной серии, подождите несколько секунд и откройте это окно снова.",
      videoPage: "СТРАНИЦА С ВИДЕО",
      masterRecommended: "HLS · MASTER · РЕКОМЕНДУЕТСЯ",
      resolutionUnknown: "Разрешение неизвестно",
      currentPage: "Текущая страница",
      currentlyPlaying: "{dimensions} · сейчас воспроизводится",
      cannotAddPage: "Текущую страницу нельзя передать приложению.",
      listCleared: "Список очищен.",
      noActiveTab: "Нет активной вкладки для диагностики.",
      diagnosticsCopied: "Диагностика скопирована. Пришлите JSON в чат.",
      diagnosticsFailed: "Не удалось скопировать диагностику: {error}"
    },
    en: {
      title: "Media streams",
      connectionChecking: "Checking the local application…",
      connectionReady: "Local application connected",
      connectionMissing: "Start MediaDownloader.exe first",
      diagnostics: "Diagnostics",
      diagnosticsTitle: "Copy a safe diagnostic report",
      clear: "Clear",
      addPage: "Add current page",
      previewAlt: "Frame from the playing video",
      durationUnknown: "Duration unknown",
      removeTitle: "Remove from list",
      addToApp: "Add to application",
      footer: "Adding an item does not start downloading. Start it separately in the local application. DRM is not supported.",
      languageTitle: "Interface language",
      appNotRunning: "The local application is not running. Start MediaDownloader.exe and open the extension again.",
      transferring: "Sending…",
      taskAdded: "Download added. Start it with the button in the local application.",
      added: "Added",
      transferFailed: "Could not send the stream: {error}",
      noStreams: "No streams detected. Start the required episode, wait a few seconds, and open this popup again.",
      videoPage: "VIDEO PAGE",
      masterRecommended: "HLS · MASTER · RECOMMENDED",
      resolutionUnknown: "Resolution unknown",
      currentPage: "Current page",
      currentlyPlaying: "{dimensions} · currently playing",
      cannotAddPage: "The current page cannot be sent to the application.",
      listCleared: "List cleared.",
      noActiveTab: "No active tab is available for diagnostics.",
      diagnosticsCopied: "Diagnostics copied. Send the JSON in chat.",
      diagnosticsFailed: "Could not copy diagnostics: {error}"
    }
  };

  function normalizeLanguage(value) {
    const code = String(value || "").toLowerCase().replace("_", "-").split("-", 1)[0];
    return Object.hasOwn(messages, code) ? code : "en";
  }

  function t(key, language, values = {}) {
    const template = messages[normalizeLanguage(language)][key];
    return template.replace(/\{(\w+)\}/g, (_match, name) => String(values[name] ?? ""));
  }

  function applyDocument(document, language) {
    const normalized = normalizeLanguage(language);
    if (document.documentElement) document.documentElement.lang = normalized;
    for (const element of document.querySelectorAll("[data-i18n]")) {
      element.textContent = t(element.dataset.i18n, normalized);
    }
    for (const element of document.querySelectorAll("[data-i18n-title]")) {
      element.title = t(element.dataset.i18nTitle, normalized);
    }
    for (const element of document.querySelectorAll("[data-i18n-alt]")) {
      element.alt = t(element.dataset.i18nAlt, normalized);
    }
  }

  return {messages, normalizeLanguage, t, applyDocument};
});
