# Testing and quality gates

Run from the repository root in PowerShell after installing `requirements-dev.txt` and `npm ci`.

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe app.py media_downloader
npm run lint
npm run typecheck
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
npm test
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\pip-audit.exe -r requirements.txt
./build.ps1
```

The Python suite covers state transitions, format selection, local HTTP validation, preview/header filtering, settings, Explorer integration, cancellation cleanup, and a local synthetic HLS fixture. The JavaScript suite covers routing, stream grouping, visible badge counts, diagnostics, and popup privacy behavior.

CI uses Windows, Python 3.12, and Node.js 24. It does not contact live media or social platforms. Live checks are documented separately in [social-platform-matrix.md](social-platform-matrix.md) and must use content/accounts the tester is authorized to access.

`build.ps1` creates the folder distribution at `dist/MediaDownloader`, then copies `MediaDownloader.exe` and `_internal` to the repository root. Release validation launches the root executable, waits for a successful `http://127.0.0.1:17843/health` response, and then terminates the smoke-test process.

TypeScript checks the two shared pure-logic JavaScript modules with `checkJs`; DOM-heavy popup/service-worker code is linted and exercised by Node regression tests. This focused scope keeps the current JavaScript implementation honest without pretending it is fully migrated to TypeScript.
