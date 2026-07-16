$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[PFIS] No .venv found. Creating one with the available Python launcher..."
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 -m venv (Join-Path $Root ".venv")
    }
    else {
        & python -m venv (Join-Path $Root ".venv")
    }
}

if (-not (Test-Path $PythonExe)) {
    throw "[PFIS] Failed to create .venv. Install Python 3.13+ and try again."
}

& $PythonExe (Join-Path $Root "scripts\start.py") @args
exit $LASTEXITCODE
