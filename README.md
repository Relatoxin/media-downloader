# Media Downloader 0.5

English · [Русский](README.ru.md)

A local Windows companion and Chrome MV3 extension for preparing and downloading media that the user can already access. It handles active HLS/DASH streams in embedded players and page URLs supported by `yt-dlp`.

> This project does not bypass DRM, paywalls, privacy controls, or regional restrictions. Download only media you are authorized to save.

![Media Downloader workflow](docs/assets/workflow.svg)

## Highlights

- Detects HLS/DASH requests in Chrome and collapses technical duplicates into one card.
- Shows a preview, duration, and resolution before a download starts.
- Offers explicit video-quality and audio-only choices for page URLs.
- Can use browser cookies directly through `yt-dlp` without persisting them in the app.
- Runs downloads in a separate process and removes newly created `.part`, `.part-Frag*`, and `.ytdl` files after cancellation.
- Opens Windows Explorer with the completed file selected.
- Remembers the chosen output directory between launches.

## Requirements

- Windows 10 or 11
- Chrome 102+

FFmpeg is supplied by `imageio-ffmpeg`.

## Quick start

1. Run `MediaDownloader.exe` from the project root. Keep the adjacent `_internal` folder in place. Python is not required.
2. Open `chrome://extensions` and enable Developer mode.
3. Choose **Load unpacked** and select `browser-extension`.
4. Start a video, open the extension, and choose **Добавить в приложение**.
5. Select a format in the desktop app and click **Начать загрузку**.

For YouTube, TikTok, VK, Instagram, Facebook, X, Reddit, and Vimeo, the extension sends the current page URL to the app. On embedded-player sites it lists independent detected streams. Actual platform support depends on the installed `yt-dlp` version, content availability, and authentication.

## Privacy and local communication

The companion listens only on `127.0.0.1:17843`. It persists only the selected output directory; job history, URLs, cookies, request headers, and previews are not written to settings. See the [security model](docs/security.md).

## Development

Building from source requires Python 3.12+; Node.js 24+ is used for extension checks.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm ci
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
npm test
./build.ps1
```

The folder build is written to `dist/MediaDownloader` and copied to the project root as `MediaDownloader.exe` plus `_internal`. `run.bat` remains available as a source-development launcher.
Successful GitHub Actions runs also provide the same folder as a downloadable `MediaDownloader-windows-*` artifact.

See [testing](docs/testing.md) for every quality gate, [architecture](docs/architecture.md) for the system design, and the [case study](docs/case-study.md) for the portfolio narrative.

## Limitations

- DRM-protected streams are unsupported.
- Signed CDN URLs can expire and may require replaying the video in Chrome.
- Social platforms change frequently; extraction relies on the pinned `yt-dlp` release.
- The extension is loaded manually and is not published in the Chrome Web Store.

## License

[MIT](LICENSE) © 2026 Relatoxin.
