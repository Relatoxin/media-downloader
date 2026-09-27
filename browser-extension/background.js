importScripts("platforms.js", "media-utils.js");

const MAX_ITEMS = 30;
const HLS_RE = /\.m3u8(?:$|[?#])/i;
const DASH_RE = /\.mpd(?:$|[?#])/i;
const DIRECT_RE = /\.(?:mp4|m4v|webm|mov)(?:$|[?#])/i;
const PLACEHOLDER_RE = /(?:^|\/)(?:blank|empty|init|initialize|pixel|transparent)[-_.]?[^/]*\.(?:mp4|webm)(?:$|[?#])/i;
const MASTER_RE = /(?:^|[-_./])master(?:[-_.]|$)/i;
const queues = new Map();
const pendingHeaders = new Map();

function storageKey(tabId) {
  return `media-tab-${tabId}`;
}

function withTabLock(tabId, operation) {
  const previous = queues.get(tabId) || Promise.resolve();
  const current = previous.then(operation, operation);
  let tracked;
  tracked = current.finally(() => {
    if (queues.get(tabId) === tracked) queues.delete(tabId);
  });
  queues.set(tabId, tracked);
  return current;
}

function mediaKind(details) {
  if (HLS_RE.test(details.url)) return "HLS";
  if (DASH_RE.test(details.url)) return "DASH";
  if (details.type === "media" && DIRECT_RE.test(details.url) && !PLACEHOLDER_RE.test(details.url)) return "VIDEO";
  const contentType = (details.responseHeaders || [])
    .find((header) => String(header.name || "").toLowerCase() === "content-type")?.value?.toLowerCase() || "";
  if (/application\/(?:vnd\.apple\.mpegurl|x-mpegurl)|audio\/(?:mpegurl|x-mpegurl)/.test(contentType)) return "HLS";
  if (contentType.includes("application/dash+xml")) return "DASH";
  if (details.type === "media" && /^video\/(?:mp4|webm|quicktime)/.test(contentType) && !PLACEHOLDER_RE.test(details.url)) return "VIDEO";
  return null;
}

function requestHeaders(details) {
  const blocked = new Set([
    "accept-encoding", "connection", "content-length", "host", "if-modified-since",
    "if-none-match", "proxy-authorization", "range"
  ]);
  const result = {};
  for (const header of details.requestHeaders || []) {
    const name = String(header.name || "").toLowerCase();
    if (!blocked.has(name) && /^[a-z0-9-]{1,80}$/.test(name) && typeof header.value === "string") {
      result[name] = header.value;
    }
  }
  return result;
}

async function getItems(tabId) {
  const key = storageKey(tabId);
  const stored = await chrome.storage.session.get(key);
  return stored[key] || [];
}

async function getPlayersForBadge(tabId) {
  if (!chrome.scripting?.executeScript) return [];
  try {
    const frames = await chrome.scripting.executeScript({
      target: {tabId, allFrames: true},
      func: () => ({
        frameUrl: location.href,
        players: Array.from(document.querySelectorAll("video, audio")).map((element) => ({
          active: !element.paused && !element.ended && element.readyState >= 2,
          currentSrc: element.currentSrc || ""
        }))
      })
    });
    return frames.flatMap((frame) => (frame.result?.players || []).map((player) => ({
      ...player,
      frameUrl: frame.result.frameUrl
    })));
  } catch (_) {
    return [];
  }
}

async function updateBadge(tabId, items, knownTab = null) {
  let count = items.length;
  try {
    const tab = knownTab || await chrome.tabs.get(tabId);
    const mode = PlatformRoutes.modeForUrl(tab.url || "");
    const players = mode === "detected_streams" ? await getPlayersForBadge(tabId) : [];
    count = MediaUtils.visibleCount(tab, items, mode, players);
  } catch (_) {
    // The tab may have closed between capture and badge update.
  }
  await chrome.action.setBadgeText({tabId, text: count ? String(count) : ""});
  await chrome.action.setBadgeBackgroundColor({tabId, color: "#0284c7"});
}

async function saveItems(tabId, items) {
  await chrome.storage.session.set({[storageKey(tabId)]: items});
  await updateBadge(tabId, items);
}

function sameHost(left, right) {
  try {
    return new URL(left).host === new URL(right).host;
  } catch (_) {
    return false;
  }
}

function canonicalUrl(value) {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch (_) {
    return value;
  }
}

async function capture(details, capturedHeaders = null) {
  const kind = mediaKind(details);
  if (!kind || details.tabId < 0 || (details.method && details.method !== "GET")) return;

  await withTabLock(details.tabId, async () => {
    const items = await getItems(details.tabId);
    const now = Date.now();
    const existing = items.find((item) =>
      item.kind === kind && (
        canonicalUrl(item.url) === canonicalUrl(details.url)
        || (kind === "HLS" && MASTER_RE.test(item.url) && MASTER_RE.test(details.url) && sameHost(item.url, details.url))
      )
    );
    if (existing) {
      existing.url = details.url;
      existing.lastSeen = now;
      existing.headers = {...existing.headers, ...(capturedHeaders || requestHeaders(details))};
      await saveItems(details.tabId, items);
      return;
    }

    let tab;
    try {
      tab = await chrome.tabs.get(details.tabId);
    } catch (_) {
      return;
    }

    // Сохраняем и master, и реально запрошенный variant: первый нужен для выбора
    // формата, второй — чтобы скачать уже запущенное качество без подмены.
    if (kind === "HLS" && !MASTER_RE.test(details.url)) {
      const master = items.find((item) => item.kind === "HLS" && MASTER_RE.test(item.url) && sameHost(item.url, details.url));
      if (master) {
        master.lastSeen = now;
        master.variantUrls = Array.from(new Set([...(master.variantUrls || []), details.url])).slice(-12);
      }
    }
    if (kind === "HLS" && MASTER_RE.test(details.url)) {
      for (const item of items) {
        if (item.kind === "HLS" && !MASTER_RE.test(item.url) && sameHost(item.url, details.url) && now - item.lastSeen < 60_000) {
          item.masterUrl = details.url;
        }
      }
    }

    items.unshift({
      id: crypto.randomUUID(),
      url: details.url,
      kind,
      title: tab.title || "Медиа из Chrome",
      pageUrl: tab.url || details.documentUrl || details.initiator || "",
      initiator: details.initiator || "",
      headers: capturedHeaders || requestHeaders(details),
      lastSeen: now
    });
    items.splice(MAX_ITEMS);
    await saveItems(details.tabId, items);
  });
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const headers = requestHeaders(details);
    pendingHeaders.set(details.requestId, headers);
    void capture(details, headers);
  },
  {urls: ["<all_urls>"]},
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (mediaKind(details)) void capture(details, pendingHeaders.get(details.requestId) || {});
  },
  {urls: ["<all_urls>"]},
  ["responseHeaders", "extraHeaders"]
);

function forgetRequest(details) {
  pendingHeaders.delete(details.requestId);
}

chrome.webRequest.onCompleted.addListener(forgetRequest, {urls: ["<all_urls>"]});
chrome.webRequest.onErrorOccurred.addListener(forgetRequest, {urls: ["<all_urls>"]});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "loading") {
    void chrome.storage.session.remove(storageKey(tabId));
    void chrome.action.setBadgeText({tabId, text: ""});
  } else if (changeInfo.status === "complete") {
    void getItems(tabId).then((items) => updateBadge(tabId, items, tab));
  }
});

chrome.tabs.onActivated.addListener(({tabId}) => {
  void getItems(tabId).then((items) => updateBadge(tabId, items));
});

chrome.tabs.onRemoved.addListener((tabId) => {
  queues.delete(tabId);
  void chrome.storage.session.remove(storageKey(tabId));
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!Number.isInteger(message.tabId)) return false;
  if (message.action === "get") {
    getItems(message.tabId).then((items) => sendResponse({items}));
    return true;
  }
  if (message.action === "clear") {
    saveItems(message.tabId, []).then(() => sendResponse({ok: true}));
    return true;
  }
  if (message.action === "remove" && typeof message.id === "string") {
    getItems(message.tabId).then((items) => {
      const filtered = items.filter((item) => item.id !== message.id);
      return saveItems(message.tabId, filtered).then(() => sendResponse({ok: true}));
    });
    return true;
  }
  return false;
});

