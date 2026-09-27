const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const PlatformRoutes = require("../../browser-extension/platforms.js");
const {chooseActiveCandidate, buildPreparePayload, buildDiagnostics, selectDisplayItems, visibleCount} = require("../../browser-extension/media-utils.js");

test("exact currentSrc wins and confirms active quality", () => {
  const items = [
    {id: "master", url: "https://cdn.test/master.m3u8", kind: "HLS", lastSeen: 20},
    {id: "variant", url: "https://cdn.test/720/index.m3u8?token=x", kind: "HLS", lastSeen: 10}
  ];
  const players = [{active: true, currentSrc: "https://cdn.test/720/index.m3u8?token=x", width: 1280, height: 720}];
  const result = chooseActiveCandidate(items, players);
  assert.equal(result.item.id, "variant");
  assert.equal(result.confirmed, true);
});

test("master without matching variant remains unconfirmed", () => {
  const result = chooseActiveCandidate(
    [{id: "master", url: "https://cdn.test/master.m3u8", kind: "HLS", lastSeen: 20}],
    [{active: true, currentSrc: "blob:https://player.test/id", width: 1920, height: 1080}]
  );
  assert.equal(result.item.id, "master");
  assert.equal(result.confirmed, false);
});

test("prepare payload includes active dimensions and source type", () => {
  const payload = buildPreparePayload(
    {url: "https://cdn.test/720/index.m3u8", pageUrl: "https://site.test/watch", title: "Video", kind: "HLS"},
    {active: true, width: 1280, height: 720, duration: 60, poster: "https://site.test/poster.jpg"},
    {confirmed: true}
  );
  assert.equal(payload.sourceType, "captured_stream");
  assert.equal(payload.activeQualityConfirmed, true);
  assert.equal(payload.height, 720);
  assert.equal(payload.duration, 60);
});

test("supported social pages use one page URL card", () => {
  const socialUrls = [
    "https://www.youtube.com/watch?v=1",
    "https://youtu.be/1",
    "https://www.tiktok.com/@user/video/1",
    "https://vk.com/video1_2",
    "https://www.instagram.com/reel/1/",
    "https://www.facebook.com/watch/?v=1",
    "https://x.com/user/status/1",
    "https://twitter.com/user/status/1",
    "https://www.reddit.com/r/videos/comments/1/item/",
    "https://vimeo.com/123"
  ];
  for (const url of socialUrls) {
    assert.equal(PlatformRoutes.modeForUrl(url), "page_url", url);
    const shown = selectDisplayItems(
      {url, title: "Social video"},
      [{id: "raw", url: "https://cdn.test/video-only.m3u8", kind: "HLS"}],
      PlatformRoutes.modeForUrl(url)
    );
    assert.equal(shown.length, 1, url);
    assert.equal(shown[0].sourceType, "page_url", url);
    assert.equal(shown[0].url, url, url);
  }
});

test("TikTok page card exists without detected media", () => {
  const tab = {url: "https://www.tiktok.com/@user/video/1", title: "TikTok"};
  const shown = selectDisplayItems(tab, [], PlatformRoutes.modeForUrl(tab.url));
  assert.deepEqual(shown, [{
    url: tab.url,
    pageUrl: tab.url,
    title: "TikTok",
    sourceType: "page_url",
    activeQualityConfirmed: false,
    kind: "PAGE",
    headers: {}
  }]);
});

test("detected-stream sites preserve every independent candidate", () => {
  for (const url of ["https://old.yummyani.me/catalog/item/show", "https://unknown.example/watch"]) {
    assert.equal(PlatformRoutes.modeForUrl(url), "detected_streams");
    const items = [
      {id: "one", url: "https://cdn.test/one.m3u8", kind: "HLS"},
      {id: "two", url: "https://cdn.test/two.mpd", kind: "DASH"}
    ];
    assert.deepEqual(selectDisplayItems({url, title: "Show"}, items, PlatformRoutes.modeForUrl(url)), items);
  }
});

test("master and its active YummyAnime variant are shown as one download", () => {
  const tab = {url: "https://old.yummyani.me/catalog/item/show", title: "Episode"};
  const master = {
    id: "master",
    url: "https://cdn.example/video/master.m3u8?token=one",
    kind: "HLS",
    variantUrls: ["https://cdn.example/video/720/index.m3u8?token=two"],
    lastSeen: 10
  };
  const variant = {
    id: "variant",
    url: "https://cdn.example/video/720/index.m3u8?token=two",
    kind: "HLS",
    masterUrl: master.url,
    lastSeen: 20
  };
  const player = {active: true, currentSrc: variant.url};

  const shown = selectDisplayItems(tab, [master, variant], "detected_streams", [player]);

  assert.equal(shown.length, 1);
  assert.equal(shown[0].id, "variant");
  assert.equal(visibleCount(tab, [master, variant], "detected_streams"), 1);
});

test("active variant is merged with an unlinked master captured in reverse order", () => {
  const tab = {url: "https://old.yummyani.me/catalog/item/show", title: "Episode"};
  const initiator = "https://player.example/embed/episode";
  const variant = {
    id: "variant-reverse",
    url: "https://cdn.example/video/720/index.m3u8?token=one",
    kind: "HLS",
    initiator,
    pageUrl: tab.url,
    lastSeen: 20
  };
  const master = {
    id: "master-reverse",
    url: "https://cdn.example/video/master.m3u8?token=two",
    kind: "HLS",
    initiator,
    pageUrl: tab.url,
    lastSeen: 10
  };
  const player = {active: true, currentSrc: variant.url, frameUrl: initiator};

  const shown = selectDisplayItems(tab, [variant, master], "detected_streams", [player]);

  assert.equal(shown.length, 1);
  assert.equal(shown[0].id, variant.id);
});

test("duplicate Kodik playlists from solodcdn shards become one newest card", () => {
  const tab = {url: "https://old.yummyani.me/catalog/item/show", title: "Episode"};
  const common = {
    kind: "HLS",
    initiator: "https://kodikplayer.com/",
    pageUrl: tab.url
  };
  const older = {
    ...common,
    id: "p12-copy",
    url: "https://p12.solodcdn.com/s/media-id/360.mp4:hls:manifest.m3u8?token=old",
    lastSeen: 100
  };
  const newest = {
    ...common,
    id: "p14-copy",
    url: "https://p14.solodcdn.com/s/media-id/360.mp4:hls:manifest.m3u8?token=new",
    lastSeen: 200
  };
  const otherQuality = {
    ...common,
    id: "p11-720",
    url: "https://p11.solodcdn.com/s/media-id/720.mp4:hls:manifest.m3u8?token=new",
    lastSeen: 190
  };
  const pausedPlayer = {
    active: false,
    currentSrc: "https://kodikplayer.comhttps://kodikplayer.com/player-id",
    frameUrl: "https://kodikplayer.com/season/show/720p"
  };

  const shown = selectDisplayItems(tab, [older, newest, otherQuality], "detected_streams", [pausedPlayer]);

  assert.deepEqual(shown.map((item) => item.id), [newest.id, otherQuality.id]);
  assert.equal(visibleCount(tab, [older, newest, otherQuality], "detected_streams", [pausedPlayer]), 2);
});

test("badge count follows the number of displayed social cards", () => {
  const tab = {url: "https://www.youtube.com/watch?v=1", title: "Video"};
  const raw = [
    {id: "one", url: "https://cdn.example/video.m3u8", kind: "HLS"},
    {id: "two", url: "https://cdn.example/audio.m3u8", kind: "HLS"}
  ];
  assert.equal(visibleCount(tab, raw, PlatformRoutes.modeForUrl(tab.url)), 1);
});

test("completed TikTok navigation sets badge to its one visible page card", async () => {
  const listeners = {};
  const badges = [];
  const event = (name) => ({addListener(listener) { listeners[name] = listener; }});
  const context = {
    console,
    crypto: {randomUUID: () => "id"},
    Date,
    Map,
    Set,
    Promise,
    URL,
    importScripts() {},
    MediaUtils: require("../../browser-extension/media-utils.js"),
    PlatformRoutes,
    chrome: {
      action: {
        async setBadgeText(value) { badges.push(value); },
        async setBadgeBackgroundColor() {}
      },
      runtime: {onMessage: event("message")},
      storage: {session: {async get() { return {}; }, async set() {}, async remove() {}}},
      tabs: {
        async get(tabId) { return {id: tabId, url: "https://www.tiktok.com/@u/video/1", title: "TikTok"}; },
        onActivated: event("activated"),
        onUpdated: event("updated"),
        onRemoved: event("removed")
      },
      webRequest: {
        onBeforeSendHeaders: event("before"),
        onHeadersReceived: event("headers"),
        onCompleted: event("completed"),
        onErrorOccurred: event("error")
      }
    }
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "..", "..", "browser-extension", "background.js"), "utf8"),
    context
  );

  listeners.updated(7, {status: "complete"}, {id: 7, url: "https://www.tiktok.com/@u/video/1", title: "TikTok"});
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(badges.at(-1).text, "1");
});

test("YummyAnime badge counts the merged active variant card", async () => {
  const listeners = {};
  const badges = [];
  const event = (name) => ({addListener(listener) { listeners[name] = listener; }});
  const tab = {id: 8, url: "https://old.yummyani.me/catalog/item/show", title: "Episode"};
  const initiator = "https://player.example/embed/episode";
  const items = [
    {
      id: "variant-badge",
      url: "https://cdn.example/video/720/index.m3u8?token=one",
      kind: "HLS",
      initiator,
      pageUrl: tab.url,
      lastSeen: 20
    },
    {
      id: "master-badge",
      url: "https://cdn.example/video/master.m3u8?token=two",
      kind: "HLS",
      initiator,
      pageUrl: tab.url,
      lastSeen: 10
    }
  ];
  const context = {
    console,
    crypto: {randomUUID: () => "id"},
    Date,
    Map,
    Set,
    Promise,
    URL,
    importScripts() {},
    MediaUtils: require("../../browser-extension/media-utils.js"),
    PlatformRoutes,
    chrome: {
      action: {
        async setBadgeText(value) { badges.push(value); },
        async setBadgeBackgroundColor() {}
      },
      runtime: {onMessage: event("message")},
      scripting: {
        async executeScript() {
          return [{frameId: 1, result: {
            frameUrl: initiator,
            players: [{active: true, currentSrc: items[0].url}]
          }}];
        }
      },
      storage: {session: {
        async get() { return {[`media-tab-${tab.id}`]: items}; },
        async set() {},
        async remove() {}
      }},
      tabs: {
        async get() { return tab; },
        onActivated: event("activated"),
        onUpdated: event("updated"),
        onRemoved: event("removed")
      },
      webRequest: {
        onBeforeSendHeaders: event("before"),
        onHeadersReceived: event("headers"),
        onCompleted: event("completed"),
        onErrorOccurred: event("error")
      }
    }
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "..", "..", "browser-extension", "background.js"), "utf8"),
    context
  );

  listeners.activated({tabId: tab.id});
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(badges.at(-1).text, "1");
});

test("diagnostics explain raw and displayed streams without exposing secrets", () => {
  const tab = {url: "https://old.yummyani.me/catalog/item/show?session=private", title: "Episode"};
  const items = [{
    id: "stream-one",
    url: "https://cdn.example/video/index.m3u8?token=secret",
    kind: "HLS",
    masterUrl: "https://cdn.example/video/master.m3u8?signature=secret",
    variantUrls: ["https://cdn.example/video/720.m3u8?auth=secret"],
    initiator: "https://player.example/embed?id=private",
    pageUrl: tab.url,
    headers: {Cookie: "session=secret", Authorization: "Bearer secret"},
    lastSeen: 123
  }];
  const players = [{
    active: true,
    currentSrc: items[0].url,
    frameUrl: items[0].initiator,
    width: 640,
    height: 360,
    duration: 1447
  }];

  const report = buildDiagnostics(tab, items, players, "detected_streams", "0.3.3");
  const serialized = JSON.stringify(report);

  assert.equal(report.extensionVersion, "0.3.3");
  assert.equal(report.rawCount, 1);
  assert.equal(report.shownCount, 1);
  assert.equal(report.activeCandidate.id, "stream-one");
  assert.equal(report.items[0].url, "https://cdn.example/video/index.m3u8");
  assert.equal(report.players[0].currentSrc, "https://cdn.example/video/index.m3u8");
  assert.deepEqual(report.shownIds, ["stream-one"]);
  assert.doesNotMatch(serialized, /secret|private|Cookie|Authorization|headers|session=/i);
});

test("popup has no technical URL element or full-tab image fallback", () => {
  const extensionDir = path.join(__dirname, "..", "..", "browser-extension");
  const html = fs.readFileSync(path.join(extensionDir, "popup.html"), "utf8");
  const js = fs.readFileSync(path.join(extensionDir, "popup.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionDir, "manifest.json"), "utf8"));
  assert.doesNotMatch(html, /class=["']address["']/);
  assert.doesNotMatch(js, /preview\.src\s*=.*tabScreenshot/);
  assert.match(html, /id=["']diagnostics["']/);
  assert.match(js, /buildDiagnostics/);
  assert.match(js, /navigator\.clipboard\.writeText/);
  assert.ok(manifest.permissions.includes("clipboardWrite"));
});

