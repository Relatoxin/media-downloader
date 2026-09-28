$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VirtualEnvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Spec = Join-Path $ProjectDir "MediaDownloader.spec"
$BundleDir = Join-Path $ProjectDir "dist\MediaDownloader"
$Executable = Join-Path $BundleDir "MediaDownloader.exe"
$RuntimeDir = Join-Path $BundleDir "_internal"
$RootExecutable = Join-Path $ProjectDir "MediaDownloader.exe"
$RootRuntimeDir = Join-Path $ProjectDir "_internal"

if (Test-Path -LiteralPath $VirtualEnvPython) {
    $Python = $VirtualEnvPython
}
else {
    $PythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $PythonCommand) {
        throw "Python not found. Create .venv or add Python to PATH, then install requirements-dev.txt."
    }
    $Python = $PythonCommand.Path
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
