const SERVICE = "http://127.0.0.1:17843";
const results = document.querySelector("#results");
const message = document.querySelector("#message");
const connection = document.querySelector("#connection");
const template = document.querySelector("#candidate");
const languageSelect = document.querySelector("#language");
let activeTabId = null;
let activeTab = null;
let serviceReady = false;
let tabScreenshot = "";
let players = [];
let topFrame = null;
let language = "en";

function tr(key, values = {}) {
  return ExtensionI18n.t(key, language, values);
}

async function initializeLanguage() {
  const stored = await chrome.storage.local.get("language");
  language = ExtensionI18n.normalizeLanguage(stored.language || chrome.i18n.getUILanguage());
  languageSelect.value = language;
  ExtensionI18n.applyDocument(document, language);
}

function formatDuration(seconds, isLive = false) {
  if (isLive) return "LIVE";
  if (!Number.isFinite(seconds) || seconds <= 0) return tr("durationUnknown");
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remaining = rounded % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
    : `${minutes}:${String(remaining).padStart(2, "0")}`;
}

function originOf(value) {
  try {
    return new URL(value).origin;
  } catch (_) {
    return "";
  }
}

function playerFor(item) {
  const sourceOrigin = originOf(item.initiator);
  const matching = players.filter((player) => sourceOrigin && originOf(player.frameUrl) === sourceOrigin);
  return matching.find((player) => player.active)
    || matching[0]
    || players.find((player) => player.active)
    || players[0]
    || null;
}

function rectForPlayer(player) {
  if (!player || !topFrame) return null;
  if (player.frameId === 0) return player.rect;
  const playerOrigin = originOf(player.frameUrl);
  return topFrame.iframes.find((frame) => originOf(frame.src) === playerOrigin)?.rect || null;
}

async function cropScreenshot(dataUrl, rect, viewport) {
  if (!dataUrl || !rect || rect.width < 40 || rect.height < 30 || !viewport?.width || !viewport?.height) return "";
  const image = new Image();
  image.src = dataUrl;
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
  });
  const scaleX = image.naturalWidth / viewport.width;
  const scaleY = image.naturalHeight / viewport.height;
  const sx = Math.max(0, rect.x * scaleX);
  const sy = Math.max(0, rect.y * scaleY);
  const sw = Math.min(image.naturalWidth - sx, rect.width * scaleX);
  const sh = Math.min(image.naturalHeight - sy, rect.height * scaleY);
  if (sw < 40 || sh < 30) return "";
  const targetWidth = Math.min(640, Math.round(sw));
  const canvas = document.createElement("canvas");
  canvas.width = targetWidth;
  canvas.height = Math.max(1, Math.round(targetWidth * sh / sw));
  canvas.getContext("2d").drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.76);
}

async function inspectPlayers(tab) {
  try {
    tabScreenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {format: "jpeg", quality: 60});
  } catch (_) {
    tabScreenshot = "";
  }
  try {
    const frames = await chrome.scripting.executeScript({
      target: {tabId: tab.id, allFrames: true},
      func: () => ({
        frameUrl: location.href,
        viewport: {width: innerWidth, height: innerHeight},
        players: Array.from(document.querySelectorAll("video, audio")).map((element) => {
          const box = element.getBoundingClientRect();
          return {
            active: !element.paused && !element.ended && element.readyState >= 2,
            duration: Number.isFinite(element.duration) ? element.duration : null,
            live: element.duration === Infinity,
            width: element.videoWidth || 0,
            height: element.videoHeight || 0,
            poster: element.poster || "",
            currentSrc: element.currentSrc || "",
            rect: {x: box.x, y: box.y, width: box.width, height: box.height}
          };
        }),
        iframes: Array.from(document.querySelectorAll("iframe")).map((element) => {
          const box = element.getBoundingClientRect();
          return {src: element.src || "", rect: {x: box.x, y: box.y, width: box.width, height: box.height}};
        })
      })
    });
    topFrame = frames.find((frame) => frame.frameId === 0)?.result || null;
    players = frames.flatMap((frame) => (frame.result?.players || []).map((player) => ({
      ...player,
      frameId: frame.frameId,
      frameUrl: frame.result.frameUrl
    })));
    players.sort((left, right) => Number(right.active) - Number(left.active));
    for (const player of players) {
      try {
        player.preview = await cropScreenshot(tabScreenshot, rectForPlayer(player), topFrame?.viewport);
      } catch (_) {
        player.preview = "";
      }
    }
  } catch (_) {
    players = [];
    topFrame = null;
  }
}

async function checkService() {
  try {
    const response = await fetch(`${SERVICE}/health`, {cache: "no-store"});
    serviceReady = response.ok && (await response.json()).ok === true;
  } catch (_) {
    serviceReady = false;
  }
  connection.textContent = serviceReady
    ? tr("connectionReady")
    : tr("connectionMissing");
  connection.className = serviceReady ? "ok" : "bad";
}

async function prepare(payload, button) {
  if (!serviceReady) {
    message.textContent = tr("appNotRunning");
    return;
  }
  button.disabled = true;
  button.textContent = tr("transferring");
  try {
    const response = await fetch(`${SERVICE}/api/prepare`, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Media-Helper": "1"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    message.textContent = tr("taskAdded");
    button.textContent = tr("added");
  } catch (error) {
    message.textContent = tr("transferFailed", {error: error.message});
    button.disabled = false;
    button.textContent = tr("addToApp");
  }
}

async function removeCandidate(id) {
  await chrome.runtime.sendMessage({action: "remove", tabId: activeTabId, id});
  await refresh();
}

function render(items) {
  results.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = tr("noStreams");
    results.append(empty);
    return;
  }
  for (const item of items) {
    const node = template.content.cloneNode(true);
    ExtensionI18n.applyDocument(node, language);
    const player = playerFor(item);
    const pageSource = item.sourceType === "page_url";
    if (player?.live || Number.isFinite(player?.duration)) item.duration = player.live ? null : player.duration;
    const preview = node.querySelector(".preview");
    const previewWrap = node.querySelector(".preview-wrap");
    const hidePreview = () => {
      if (previewWrap) previewWrap.style.display = "none";
    };
    const poster = player?.poster || "";
    preview.src = poster || player?.preview || "";
    preview.addEventListener("error", () => {
      preview.removeAttribute("src");
      hidePreview();
    });
    if (!preview.src) hidePreview();
    node.querySelector(".duration").textContent = formatDuration(player?.duration, player?.live);
    const isMaster = item.kind === "HLS" && /(?:^|[-_./])master(?:[-_.]|$)/i.test(item.url);
    node.querySelector(".kind").textContent = pageSource
      ? tr("videoPage")
      : (isMaster ? tr("masterRecommended") : item.kind);
    const dimensions = player?.width && player?.height ? `${player.width}×${player.height}` : tr("resolutionUnknown");
    node.querySelector(".media-info").textContent = pageSource
      ? (item.title || tr("currentPage"))
      : (player?.active ? tr("currentlyPlaying", {dimensions}) : dimensions);
    const button = node.querySelector(".download");
    const activeMatch = pageSource ? null : MediaUtils.chooseActiveCandidate(items, players);
    const confirmed = !pageSource && activeMatch.item?.id === item.id && activeMatch.confirmed;
    const payload = pageSource ? {
      ...item,
      duration: player?.live ? null : player?.duration,
      width: Number(player?.width) || null,
      height: Number(player?.height) || null,
      thumbnail: poster || player?.preview || ""
    } : MediaUtils.buildPreparePayload(item, player, {confirmed});
    button.addEventListener("click", () => prepare(payload, button));
    const remove = node.querySelector(".remove");
    if (pageSource) remove.remove();
    else remove.addEventListener("click", () => removeCandidate(item.id));
    results.append(node);
  }
}

async function refresh() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  activeTab = tab || null;
  activeTabId = tab?.id;
  if (!Number.isInteger(activeTabId)) return render([]);
  await inspectPlayers(tab);
  const response = await chrome.runtime.sendMessage({action: "get", tabId: activeTabId});
  const mode = PlatformRoutes.modeForUrl(tab.url);
  document.querySelector("#add-page").hidden = mode === "page_url";
  render(MediaUtils.selectDisplayItems(tab, response?.items || [], mode, players, tr("currentPage")));
}

document.querySelector("#add-page").addEventListener("click", async (event) => {
  if (!activeTab?.url?.startsWith("http")) {
    message.textContent = tr("cannotAddPage");
    return;
  }
  await prepare(MediaUtils.buildPagePayload(activeTab, tr("currentPage")), event.currentTarget);
});

document.querySelector("#clear").addEventListener("click", async () => {
  if (!Number.isInteger(activeTabId)) return;
  await chrome.runtime.sendMessage({action: "clear", tabId: activeTabId});
  message.textContent = tr("listCleared");
  render([]);
});

document.querySelector("#diagnostics").addEventListener("click", async () => {
  if (!activeTab || !Number.isInteger(activeTabId)) {
    message.textContent = tr("noActiveTab");
    return;
  }
  try {
    await inspectPlayers(activeTab);
    const response = await chrome.runtime.sendMessage({action: "get", tabId: activeTabId});
    const mode = PlatformRoutes.modeForUrl(activeTab.url || "");
    const report = MediaUtils.buildDiagnostics(
      activeTab,
      response?.items || [],
      players,
      mode,
      chrome.runtime.getManifest().version
    );
    await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
    message.textContent = tr("diagnosticsCopied");
  } catch (error) {
    message.textContent = tr("diagnosticsFailed", {error: error.message});
  }
});

languageSelect.addEventListener("change", async () => {
  language = ExtensionI18n.normalizeLanguage(languageSelect.value);
  await chrome.storage.local.set({language});
  ExtensionI18n.applyDocument(document, language);
  message.textContent = "";
  await Promise.all([checkService(), refresh()]);
});

async function initialize() {
  await initializeLanguage();
  await Promise.all([checkService(), refresh()]);
}

void initialize();
