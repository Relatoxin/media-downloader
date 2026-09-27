(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.MediaUtils = api;
})(globalThis, function () {
  const MASTER_RE = /(?:^|[-_./])master(?:[-_.]|$)/i;

  function canonicalUrl(value) {
    try {
      const url = new URL(value);
      return `${url.origin}${url.pathname}`;
    } catch (_) {
      return value || "";
    }
  }

  function sameHost(left, right) {
    try {
      return new URL(left).host === new URL(right).host;
    } catch (_) {
      return false;
    }
  }

  function samePlaybackContext(left, right) {
    if (left.initiator && right.initiator && canonicalUrl(left.initiator) === canonicalUrl(right.initiator)) {
      return true;
    }
    return Boolean(left.pageUrl && right.pageUrl && canonicalUrl(left.pageUrl) === canonicalUrl(right.pageUrl));
  }

  function solodCdnReplicaKey(value) {
    try {
      const url = new URL(value);
      return /^p\d+\.solodcdn\.com$/i.test(url.hostname) ? `solodcdn:${url.pathname}` : "";
    } catch (_) {
      return "";
    }
  }

  function chooseActiveCandidate(items, players) {
    const activePlayer = players.find((player) => player.active) || players[0] || null;
    if (!items.length) return {item: null, player: activePlayer, confirmed: false};
    if (activePlayer?.currentSrc) {
      const exact = items.find((item) => canonicalUrl(item.url) === canonicalUrl(activePlayer.currentSrc));
      if (exact) return {item: exact, player: activePlayer, confirmed: true};
    }
    const candidates = items
      .filter((item) => !MASTER_RE.test(item.url) && (!activePlayer?.frameUrl || sameHost(item.initiator, activePlayer.frameUrl)))
      .sort((left, right) => (right.lastSeen || 0) - (left.lastSeen || 0));
    if (activePlayer?.active && candidates.length) {
      return {item: candidates[0], player: activePlayer, confirmed: true};
    }
    const newest = [...items].sort((left, right) => (right.lastSeen || 0) - (left.lastSeen || 0))[0];
    return {item: newest, player: activePlayer, confirmed: false};
  }

  function buildPreparePayload(item, player, match = {}) {
    return {
      ...item,
      sourceType: "captured_stream",
      activeQualityConfirmed: Boolean(match.confirmed),
      duration: player?.live ? null : (Number.isFinite(player?.duration) ? player.duration : item.duration),
      width: Number(player?.width) || null,
      height: Number(player?.height) || null,
      thumbnail: player?.poster || player?.preview || item.thumbnail || ""
    };
  }

  function buildPagePayload(tab) {
    return {
      url: tab.url,
      pageUrl: tab.url,
      title: tab.title || "Страница из Chrome",
      sourceType: "page_url",
      activeQualityConfirmed: false,
      kind: "PAGE",
      headers: {}
    };
  }

  function relatedHlsGroup(item, items, active) {
    if (item.kind !== "HLS") return [item];
    const replicaKey = solodCdnReplicaKey(item.url);
    if (replicaKey) {
      const replicas = items.filter((candidate) => (
        candidate.kind === "HLS"
        && solodCdnReplicaKey(candidate.url) === replicaKey
        && samePlaybackContext(item, candidate)
      ));
      if (replicas.length > 1) return replicas;
    }
    const canUseActiveFallback = (master, variant) => (
      active?.id === variant.id
      && sameHost(master.url, variant.url)
      && samePlaybackContext(master, variant)
    );
    const master = MASTER_RE.test(item.url)
      ? item
      : items.find((candidate) => candidate.kind === "HLS" && MASTER_RE.test(candidate.url) && (
        canonicalUrl(item.masterUrl) === canonicalUrl(candidate.url)
        || (candidate.variantUrls || []).some((url) => canonicalUrl(url) === canonicalUrl(item.url))
        || canUseActiveFallback(candidate, item)
      ));
    if (!master) return [item];
    const variants = items.filter((candidate) => candidate.kind === "HLS" && !MASTER_RE.test(candidate.url) && (
      canonicalUrl(candidate.masterUrl) === canonicalUrl(master.url)
      || (master.variantUrls || []).some((url) => canonicalUrl(url) === canonicalUrl(candidate.url))
      || canUseActiveFallback(master, candidate)
    ));
    return [...new Map([master, ...variants].map((candidate) => [candidate.id, candidate])).values()];
  }

  function collapseRelatedCandidates(items, players = []) {
    const activeMatch = chooseActiveCandidate(items, players);
    const active = activeMatch.item;
    const confirmedActive = activeMatch.confirmed ? active : null;
    const consumed = new Set();
    const result = [];
    for (const item of items) {
      if (consumed.has(item.id)) continue;
      const group = relatedHlsGroup(item, items, confirmedActive);
      for (const member of group) consumed.add(member.id);
      const newest = [...group].sort((left, right) => (right.lastSeen || 0) - (left.lastSeen || 0))[0];
      result.push(group.find((member) => member.id === active?.id) || group.find((member) => MASTER_RE.test(member.url)) || newest || item);
    }
    return result;
  }

  function selectDisplayItems(tab, items, mode, players = []) {
    return mode === "page_url" ? [buildPagePayload(tab)] : collapseRelatedCandidates(items, players);
  }

  function visibleCount(tab, items, mode, players = []) {
    return selectDisplayItems(tab, items, mode, players).length;
  }

  function diagnosticUrl(value) {
    if (!value) return "";
    try {
      const url = new URL(value);
      return `${url.origin}${url.pathname}`;
    } catch (_) {
      return "[invalid-or-relative-url]";
    }
  }

  function buildDiagnostics(tab, items, players, mode, extensionVersion) {
    const active = chooseActiveCandidate(items, players);
    const shown = selectDisplayItems(tab, items, mode, players);
    return {
      schemaVersion: 1,
      extensionVersion,
      mode,
      page: diagnosticUrl(tab?.url),
      rawCount: items.length,
      shownCount: shown.length,
      activeCandidate: active.item ? {id: active.item.id, confirmed: active.confirmed} : null,
      shownIds: shown.map((item) => item.id || "page-url"),
      items: items.map((item, index) => ({
        index,
        id: item.id,
        kind: item.kind,
        url: diagnosticUrl(item.url),
        isMaster: MASTER_RE.test(item.url || ""),
        masterUrl: diagnosticUrl(item.masterUrl),
        variantUrls: (item.variantUrls || []).map(diagnosticUrl),
        initiator: diagnosticUrl(item.initiator),
        pageUrl: diagnosticUrl(item.pageUrl),
        lastSeen: Number(item.lastSeen) || null
      })),
      players: players.map((player, index) => ({
        index,
        active: Boolean(player.active),
        currentSrc: diagnosticUrl(player.currentSrc),
        frameUrl: diagnosticUrl(player.frameUrl),
        width: Number(player.width) || null,
        height: Number(player.height) || null,
        duration: Number.isFinite(player.duration) ? player.duration : null,
        live: Boolean(player.live)
      }))
    };
  }

  return {canonicalUrl, chooseActiveCandidate, buildPreparePayload, buildPagePayload, buildDiagnostics, collapseRelatedCandidates, selectDisplayItems, visibleCount};
});

