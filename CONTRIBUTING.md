# Contributing

Thanks for helping improve Media Downloader.

## Development setup

1. Install Python 3.12+, Node.js 20+, and Chrome.
2. Create a virtual environment and install `requirements-dev.txt`.
3. Run `npm ci`.
4. Load `browser-extension` as an unpacked extension when testing browser behavior.

Before opening a pull request, run every command in [docs/testing.md](docs/testing.md). Keep live platform checks manual: CI must remain deterministic and must not use personal cookies, accounts, or captured media URLs.

## Change guidelines

- Add a regression test before fixing a bug.
- Never commit cookies, authorization headers, signed CDN URLs, downloaded media, browser profiles, or diagnostic exports containing private URLs.
- Keep the local API bound to loopback and preserve its origin/header checks.
- Update both READMEs when user-facing behavior changes.
- Describe observable behavior and verification steps in the pull request.

By contributing, you agree that your contribution is licensed under the MIT License.
