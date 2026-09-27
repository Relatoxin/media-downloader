$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LocalTemp = Join-Path $ProjectDir ".tmp"
New-Item -ItemType Directory -Force -Path $LocalTemp | Out-Null
$env:TEMP = $LocalTemp
$env:TMP = $LocalTemp

if (-not (Test-Path -LiteralPath $VenvPython)) {
    py -m venv (Join-Path $ProjectDir ".venv")
}

if (-not (& $VenvPython -m pip --version 2>$null)) {
    & $VenvPython -m ensurepip --upgrade --default-pip
}

$Requirements = Join-Path $ProjectDir "requirements.txt"
$Marker = Join-Path $ProjectDir ".venv\.dependencies-installed"
$RequirementsHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$InstalledHash = if (Test-Path -LiteralPath $Marker) { Get-Content -LiteralPath $Marker -Raw } else { "" }
if ($InstalledHash.Trim() -ne $RequirementsHash) {
    & $VenvPython -m pip install -r $Requirements
    Set-Content -LiteralPath $Marker -Value $RequirementsHash -NoNewline
}

& $VenvPython (Join-Path $ProjectDir "app.py")

