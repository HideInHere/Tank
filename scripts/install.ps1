# ============================================================
# Tank Trading System — Windows PowerShell Installer
# iex (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install.ps1')
# Requires: Windows 10 21H2+ or Windows 11, PowerShell 5.1+
# ============================================================

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Paper,         # Enable paper trading
    [switch]$SkipDocker,    # Skip Docker installation check
    [string]$TankDir = "$env:USERPROFILE\tank"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Suppress slow progress bars

$TankRepo   = "https://github.com/HideInHere/Tank"
$LogFile    = "$env:TEMP\tank-install.log"
$EnvFile    = "$TankDir\.env"

# ── Helpers ────────────────────────────────────────────────
function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts][$Level] $Msg"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    switch ($Level) {
        "OK"    { Write-Host "[ OK ] $Msg" -ForegroundColor Green }
        "WARN"  { Write-Host "[WARN] $Msg" -ForegroundColor Yellow }
        "ERROR" { Write-Host "[ERR ] $Msg" -ForegroundColor Red }
        default { Write-Host "[INFO] $Msg" -ForegroundColor Cyan }
    }
}

function Exit-Error {
    param([string]$Msg)
    Write-Log $Msg "ERROR"
    Write-Host "`nInstallation failed. Check log: $LogFile" -ForegroundColor Red
    exit 1
}

function Write-Banner {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║   Tank Trading System — Windows Installer            ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

# ── Check Windows version ──────────────────────────────────
function Test-WindowsVersion {
    $os = [System.Environment]::OSVersion.Version
    if ($os.Major -lt 10) {
        Exit-Error "Windows 10 or later required (current: $($os.ToString()))"
    }
    Write-Log "Windows $($os.ToString()) detected" "OK"
}

# ── Check/enable WSL2 & Hyper-V ───────────────────────────
function Enable-Prerequisites {
    Write-Log "Checking Windows features..."

    # Check if running as admin for feature installation
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        Write-Log "Not running as Administrator — cannot enable WSL2/Hyper-V automatically" "WARN"
        Write-Log "If Docker install fails, re-run this script as Administrator" "WARN"
        return
    }

    $wslFeature = Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" -ErrorAction SilentlyContinue
    if ($wslFeature.State -ne "Enabled") {
        Write-Log "Enabling WSL..."
        Enable-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" -NoRestart | Out-Null
    }

    $vmFeature = Get-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" -ErrorAction SilentlyContinue
    if ($vmFeature.State -ne "Enabled") {
        Write-Log "Enabling Virtual Machine Platform..."
        Enable-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" -NoRestart | Out-Null
    }
}

# ── Install Chocolatey ─────────────────────────────────────
function Install-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Log "Chocolatey already installed" "OK"
        return
    }
    Write-Log "Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    # Refresh env
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Log "Chocolatey installed" "OK"
}

# ── Install Docker Desktop ─────────────────────────────────
function Install-Docker {
    if ($SkipDocker) { Write-Log "Skipping Docker install (--SkipDocker)" "WARN"; return }

    $dockerRunning = $false
    try {
        $null = docker info 2>&1
        $dockerRunning = ($LASTEXITCODE -eq 0)
    } catch {}

    if ($dockerRunning) {
        Write-Log "Docker already running" "OK"
        return
    }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Log "Docker installed but not running — starting Docker Desktop..."
        Start-Process "Docker Desktop" -ErrorAction SilentlyContinue
        Start-Sleep 5
    } else {
        Write-Log "Installing Docker Desktop via Chocolatey..."
        Install-Chocolatey
        choco install docker-desktop -y --no-progress 2>&1 | Add-Content -Path $LogFile
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Chocolatey install failed — attempting direct download..." "WARN"
            $installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $installerPath = "$env:TEMP\DockerDesktopInstaller.exe"
            Write-Log "Downloading Docker Desktop..."
            (New-Object Net.WebClient).DownloadFile($installerUrl, $installerPath)
            Write-Log "Running Docker Desktop installer (silent)..."
            Start-Process $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait
        }
    }

    # Wait for Docker daemon
    Write-Log "Waiting for Docker daemon (up to 120s)..."
    $timeout = 40
    for ($i = 0; $i -lt $timeout; $i++) {
        Start-Sleep 3
        try {
            $null = docker info 2>&1
            if ($LASTEXITCODE -eq 0) { Write-Log "Docker daemon ready" "OK"; return }
        } catch {}
        Write-Host -NoNewline "."
    }
    Write-Host ""
    Write-Log "Docker did not start automatically." "WARN"
    Write-Log "Please launch Docker Desktop manually, then re-run this script." "WARN"
    Exit-Error "Docker daemon not available"
}

# ── Install Git ────────────────────────────────────────────
function Install-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Log "git already installed" "OK"
        return
    }
    Write-Log "Installing git..."
    Install-Chocolatey
    choco install git -y --no-progress 2>&1 | Add-Content -Path $LogFile
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Log "git installed" "OK"
}

# ── Clone repo ─────────────────────────────────────────────
function Clone-Repo {
    if (Test-Path "$TankDir\.git") {
        Write-Log "Repo exists — pulling latest..."
        Push-Location $TankDir
        git pull --ff-only 2>&1 | Add-Content -Path $LogFile
        Pop-Location
    } else {
        Write-Log "Cloning $TankRepo → $TankDir"
        $token = [System.Environment]::GetEnvironmentVariable("GIT_TOKEN")
        if ($token) {
            $cloneUrl = $TankRepo -replace "https://", "https://${token}@"
        } else {
            $cloneUrl = $TankRepo
        }
        git clone $cloneUrl $TankDir 2>&1 | Add-Content -Path $LogFile
        if ($LASTEXITCODE -ne 0) {
            Exit-Error "Clone failed. Set GIT_TOKEN environment variable for private repo access."
        }
    }
    Write-Log "Repo ready at $TankDir" "OK"
}

# ── Setup .env ─────────────────────────────────────────────
function Setup-Env {
    if (Test-Path $EnvFile) {
        Write-Log ".env already exists — keeping current values" "WARN"
        return
    }

    Copy-Item "$TankDir\.env.example" $EnvFile

    function Set-EnvVar {
        param([string]$Key, [string]$Val)
        if ($Val) {
            (Get-Content $EnvFile) -replace "^${Key}=.*", "${Key}=${Val}" | Set-Content $EnvFile
        }
    }

    function New-RandomHex {
        param([int]$Bytes = 16)
        -join ((1..$Bytes) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
    }

    $pgPass  = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { New-RandomHex 16 }
    $rdPass  = if ($env:REDIS_PASSWORD)    { $env:REDIS_PASSWORD }    else { New-RandomHex 16 }
    $ocSec   = if ($env:OPENCLAW_SECRET)   { $env:OPENCLAW_SECRET }   else { New-RandomHex 32 }
    $gfPass  = if ($env:GRAFANA_PASSWORD)  { $env:GRAFANA_PASSWORD }  else { New-RandomHex 12 }
    $ulSec   = if ($env:UNLEASH_SECRET)    { $env:UNLEASH_SECRET }    else { New-RandomHex 16 }

    Set-EnvVar "POSTGRES_PASSWORD"  $pgPass
    Set-EnvVar "REDIS_PASSWORD"     $rdPass
    Set-EnvVar "OPENCLAW_SECRET"    $ocSec
    Set-EnvVar "GRAFANA_PASSWORD"   $gfPass
    Set-EnvVar "UNLEASH_SECRET"     $ulSec
    Set-EnvVar "GIT_TOKEN"          $env:GIT_TOKEN
    Set-EnvVar "ANTHROPIC_API_KEY"  $env:ANTHROPIC_API_KEY
    Set-EnvVar "BINANCE_API_KEY"    $env:BINANCE_API_KEY
    Set-EnvVar "BINANCE_API_SECRET" $env:BINANCE_API_SECRET

    if ($Paper) {
        Set-EnvVar "PAPER_TRADING" "true"
        Set-EnvVar "TRADING_ENV"   "paper"
        Write-Log "Paper trading mode ENABLED" "WARN"
    }

    Write-Log ".env created at $EnvFile" "OK"
    Write-Log "Edit $EnvFile to add exchange API keys before live trading" "WARN"
}

# ── Docker compose up ──────────────────────────────────────
function Start-Stack {
    Write-Log "Starting all containers..."
    Push-Location $TankDir
    docker compose --env-file .env pull --ignore-pull-failures 2>&1 | Add-Content -Path $LogFile
    docker compose --env-file .env up -d --build 2>&1 | Add-Content -Path $LogFile
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        Exit-Error "docker compose up failed. Check: docker compose logs"
    }
    Pop-Location
    Write-Log "All containers started" "OK"
}

# ── Wait for gateway ───────────────────────────────────────
function Wait-Ready {
    Write-Log "Waiting for openclaw gateway..."
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep 3
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:18789/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { Write-Log "Gateway ready" "OK"; return }
        } catch {}
        Write-Host -NoNewline "."
    }
    Write-Host ""
    Write-Log "Gateway did not respond — check: docker compose logs openclaw-gateway" "WARN"
}

# ── Install scheduled task (backup) ───────────────────────
function Install-BackupTask {
    $taskName = "TankTradingBackup"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "Scheduled backup task already exists" "WARN"
        return
    }

    $action  = New-ScheduledTaskAction -Execute "bash.exe" -Argument "-c `"bash $($TankDir -replace '\\','/')/backup-sync.sh >> /tmp/tank-backup.log 2>&1`""
    $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RestartCount 2

    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
        Write-Log "Hourly backup task registered (Task Scheduler)" "OK"
    } catch {
        Write-Log "Could not register backup task: $_" "WARN"
    }
}

# ── Print result ───────────────────────────────────────────
function Write-Done {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║         Tank Trading System — Ready!             ║" -ForegroundColor Green
    Write-Host "╠══════════════════════════════════════════════════╣" -ForegroundColor Green
    Write-Host "║  Ready at http://localhost:18789                 ║" -ForegroundColor Green
    Write-Host "║  Grafana  → http://localhost:3000                ║" -ForegroundColor Green
    Write-Host "║  Unleash  → http://localhost:4242                ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Manage: cd $TankDir; docker compose [up|down|logs|ps]"
    Write-Host "  Log:    $LogFile"
    Write-Host ""
}

# ── Main ───────────────────────────────────────────────────
Write-Banner
Test-WindowsVersion
Enable-Prerequisites
Install-Git
Install-Docker
Clone-Repo
Setup-Env
Start-Stack
Wait-Ready
Install-BackupTask
Write-Done
