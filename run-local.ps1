# MEPIQ — start the API and the web app locally (Windows PowerShell).
#
#   .\run-local.ps1              first run: installs dependencies, then starts
#   .\run-local.ps1 -SkipInstall subsequent runs
#
# API  -> http://localhost:8000   (docs at /docs)
# Web  -> http://localhost:5173

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "$name was not found on PATH. $hint"
    }
}

Require-Command python "Install Python 3.11 or newer from https://python.org"
Require-Command npm    "Install Node 20 or newer from https://nodejs.org"

$venv = Join-Path $root "backend\.venv"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not $SkipInstall) {
    if (-not (Test-Path $py)) {
        Write-Host "Creating virtual environment..." -ForegroundColor Cyan
        python -m venv $venv
    }
    Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
    & $py -m pip install --upgrade pip --quiet
    & $py -m pip install -r (Join-Path $root "backend\requirements.txt") --quiet

    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend")
    npm install --no-audit --no-fund
    Pop-Location
}

# Load .env if present, so OPENAI_API_KEY and friends reach the API process.
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), "Process")
        }
    }
    Write-Host "Loaded .env" -ForegroundColor DarkGray
}

if (-not $env:MEPIQ_DATA_DIR) {
    $env:MEPIQ_DATA_DIR = Join-Path $root "data"
}

Write-Host ""
Write-Host "Starting MEPIQ" -ForegroundColor Green
Write-Host "  API  http://localhost:8000  (docs at /docs)"
Write-Host "  Web  http://localhost:5173"
Write-Host "  Data $($env:MEPIQ_DATA_DIR)"
Write-Host ""
Write-Host "Close the two new windows to stop." -ForegroundColor DarkGray

Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend")

Start-Sleep -Seconds 3

Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $root "frontend")

Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"
