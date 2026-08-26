# MEPIQ — serve on this machine's LAN address so others can reach it.
#
#   .\run-lan.ps1                 start and print the shareable URL
#   .\run-lan.ps1 -OpenFirewall   also add the Windows Firewall rules (needs admin)
#   .\run-lan.ps1 -Stop           stop the stack
#
# Docker already binds 0.0.0.0, and the frontend calls the API on whatever host
# the browser used — so nothing has to be rebuilt when the address changes. The
# only thing that usually blocks a colleague is Windows Firewall.

param(
    [switch]$OpenFirewall,
    [switch]$Stop,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Read-EnvValue($name, $fallback) {
    $envFile = Join-Path $PSScriptRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$name\s*=\s*(.*)$") {
                $v = $Matches[1].Trim().Trim('"')
                if ($v) { return $v }
            }
        }
    }
    return $fallback
}

function Get-LanAddress {
    # The interface that actually carries traffic off this machine — not a
    # Docker/WSL/Hyper-V virtual switch, and not an APIPA fallback.
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and
            $_.PrefixOrigin -ne 'WellKnown'
        }

    $preferred = $candidates | Where-Object {
        $alias = $_.InterfaceAlias
        $alias -notmatch 'Loopback|vEthernet|WSL|Hyper-V|Docker|VirtualBox|VMware|Bluetooth'
    }

    $pick = ($preferred | Sort-Object -Property InterfaceMetric | Select-Object -First 1)
    if (-not $pick) { $pick = ($candidates | Select-Object -First 1) }
    return $pick
}

# --- stop -------------------------------------------------------------------

if ($Stop) {
    docker compose down
    Write-Host "Stopped. Uploads and results are preserved in the mepiq-data volume." -ForegroundColor DarkGray
    exit 0
}

# --- preflight --------------------------------------------------------------

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker was not found on PATH. Install Docker Desktop and make sure it is running."
}
try { docker info *> $null } catch { Write-Error "Docker Desktop does not appear to be running. Start it and try again." }

if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") (Join-Path $PSScriptRoot ".env")
    Write-Host "Created .env from .env.example. Add your OPENAI_API_KEY there if you want the LLM copilot." -ForegroundColor Yellow
}

$webPort = Read-EnvValue "MEPIQ_WEB_PORT" "8080"
$apiPort = Read-EnvValue "MEPIQ_API_PORT" "8000"
$bind    = Read-EnvValue "MEPIQ_BIND"     "0.0.0.0"

if ($bind -eq "127.0.0.1") {
    Write-Warning "MEPIQ_BIND is 127.0.0.1 in .env, so the app will NOT be reachable from other machines. Set it to 0.0.0.0."
}

$nic = Get-LanAddress
if (-not $nic) { Write-Error "Could not find a LAN IPv4 address. Are you connected to a network?" }
$ip = $nic.IPAddress

# --- firewall ---------------------------------------------------------------

if ($OpenFirewall) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Error "-OpenFirewall needs an elevated prompt. Right-click PowerShell -> Run as administrator, then re-run."
    }
    foreach ($p in @($webPort, $apiPort)) {
        $ruleName = "MEPIQ $p"
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort $p -Profile Private | Out-Null
            Write-Host "Firewall: allowed inbound TCP $p on private networks." -ForegroundColor Green
        } else {
            Write-Host "Firewall: rule '$ruleName' already exists." -ForegroundColor DarkGray
        }
    }
}

# --- start ------------------------------------------------------------------

Write-Host ""
Write-Host "Starting MEPIQ..." -ForegroundColor Cyan
if ($NoBuild) { docker compose up -d } else { docker compose up -d --build }

Write-Host "Waiting for the API to come up..." -NoNewline
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 2
        if ($r.status -eq "ok") { $ready = $true; break }
    } catch { }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
}
Write-Host ""

if (-not $ready) {
    Write-Warning "The API did not report healthy in time. Check: docker compose logs -f api"
    exit 1
}

$llm = if ($r.llm_enabled) { "LLM copilot ($($r.llm_model))" } else { "rule-based copilot (no OPENAI_API_KEY set)" }

Write-Host ""
Write-Host "  MEPIQ is running" -ForegroundColor Green
Write-Host "  ----------------------------------------------------"
Write-Host "  Share this with anyone on the same network:"
Write-Host "     http://${ip}:${webPort}" -ForegroundColor Cyan
Write-Host ""
Write-Host "  On this machine:  http://localhost:${webPort}"
Write-Host "  API docs:         http://${ip}:${apiPort}/docs"
Write-Host "  Interface:        $($nic.InterfaceAlias)"
Write-Host "  Copilot:          $llm"
Write-Host "  ----------------------------------------------------"
Write-Host ""
Write-Host "  Stop with:  .\run-lan.ps1 -Stop" -ForegroundColor DarkGray
Write-Host "  Logs with:  docker compose logs -f" -ForegroundColor DarkGray

if (-not $OpenFirewall) {
    Write-Host ""
    Write-Host "  If a colleague cannot connect, Windows Firewall is the usual cause." -ForegroundColor Yellow
    Write-Host "  Run this once from an admin PowerShell:" -ForegroundColor Yellow
    Write-Host "     .\run-lan.ps1 -OpenFirewall -NoBuild" -ForegroundColor Yellow
}

Start-Process "http://localhost:${webPort}"
