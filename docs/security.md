# Security and privacy model

## Data flow

The extension observes request metadata needed to identify media. When the user explicitly adds a card, it sends the URL, filtered request headers, page title, dimensions, duration, and a bounded preview to `http://127.0.0.1:17843`. The desktop app passes only the required data to `yt-dlp`/FFmpeg.

## Stored data

The settings file contains only `outputDir`. Jobs, URLs, previews, cookies, authorization headers, and browser profiles remain in memory and are discarded when the app exits. Downloaded files remain in the user-selected directory.

## Protections

- Loopback-only bind (`127.0.0.1`), not all interfaces.
- Chrome-extension-only CORS response and a required custom request header.
- 128 KiB JSON request limit and bounded text/image fields.
- HTTP(S)-only URL validation and CR/LF rejection in forwarded headers.
- Filename sanitization and resolved output paths.
- Browser cookies are requested from the selected browser by `yt-dlp`; the app does not export them itself.
- Cancellation targets only partial files created or changed by the current operation.

## User responsibility

Use the project only for content you may lawfully download. The project deliberately does not implement DRM circumvention, authentication bypass, paywall bypass, or regional-unblocking features.

## Publishing diagnostics

Before sharing a diagnostic report, review its page and media paths. The extension removes query strings, but path components can still identify private content. Never publish cookies, authorization headers, signed URLs, browser profiles, or downloaded samples.
