$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Spec = Join-Path $ProjectDir "MediaDownloader.spec"
$BundleDir = Join-Path $ProjectDir "dist\MediaDownloader"
$Executable = Join-Path $BundleDir "MediaDownloader.exe"
$RuntimeDir = Join-Path $BundleDir "_internal"
$RootExecutable = Join-Path $ProjectDir "MediaDownloader.exe"
$RootRuntimeDir = Join-Path $ProjectDir "_internal"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found. Create .venv and install requirements-dev.txt first."
}

Push-Location $ProjectDir
try {
    & $Python -m PyInstaller --noconfirm --clean $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "Build completed without the expected executable: $Executable"
    }
    if (-not (Test-Path -LiteralPath $RuntimeDir)) {
        throw "Build completed without the expected runtime directory: $RuntimeDir"
    }

    Copy-Item -LiteralPath $Executable -Destination $RootExecutable -Force
    Copy-Item -LiteralPath $RuntimeDir -Destination $ProjectDir -Recurse -Force

    if (-not (Test-Path -LiteralPath $RootExecutable) -or -not (Test-Path -LiteralPath $RootRuntimeDir)) {
        throw "The root application layout was not created."
    }
    Write-Host "Build ready: $RootExecutable"
}
finally {
    Pop-Location
}
