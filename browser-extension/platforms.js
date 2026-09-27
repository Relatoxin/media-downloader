(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PlatformRoutes = api;
})(globalThis, function () {
  const PAGE_SOURCE_HOSTS = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "vk.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "x.com",
    "twitter.com",
    "reddit.com",
    "redd.it",
    "vimeo.com"
  ];

  function hostnameOf(value) {
    try {
      return new URL(value).hostname.toLowerCase().replace(/\.$/, "");
    } catch (_) {
      return "";
    }
  }

  function isPageSourceUrl(value) {
    const hostname = hostnameOf(value);
    return PAGE_SOURCE_HOSTS.some((host) => hostname === host || hostname.endsWith(`.${host}`));
  }

  function modeForUrl(value) {
    return isPageSourceUrl(value) ? "page_url" : "detected_streams";
  }

  return {isPageSourceUrl, modeForUrl};
});

