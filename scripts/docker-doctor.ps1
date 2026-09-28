param(
    [int]$Port = 0,
    [switch]$SkipComposeChecks,
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env"
$defaultPort = 8501

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Write-Pass {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Read-EnvPort {
    param(
        [string]$FilePath,
        [int]$Fallback
    )

    if (-not (Test-Path $FilePath)) {
        return $Fallback
    }

    $line = Get-Content $FilePath | Where-Object { $_ -match '^\s*BUGSCRUB_HOST_PORT\s*=' } | Select-Object -First 1
    if (-not $line) {
        return $Fallback
    }

    $value = ($line -split '=', 2)[1].Trim()
    $parsed = 0
    if ([int]::TryParse($value, [ref]$parsed)) {
        return $parsed
    }

    return $Fallback
}

function Invoke-ExternalCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $output = & $FilePath @ArgumentList 2>&1
    return @{
        ExitCode = $LASTEXITCODE
        Output = @($output)
    }
}

function Test-CommandExists {
    param([string]$CommandName)

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

if ($Port -le 0) {
    $Port = Read-EnvPort -FilePath $envFile -Fallback $defaultPort
}

Write-Host "BugScrub Docker Doctor" -ForegroundColor Magenta
Write-Host "Repository: $repoRoot"
Write-Host "Target host port: $Port"

Write-Section "Docker CLI"
if (-not (Test-CommandExists "docker")) {
    Write-Fail "Docker CLI is not installed or not in PATH."
    Write-Host "Install Docker Desktop and reopen PowerShell."
    exit 1
}

$dockerPath = (Get-Command docker).Source
Write-Pass "Docker CLI found at $dockerPath"

Write-Section "Docker Daemon"
$dockerInfo = Invoke-ExternalCommand -FilePath "docker" -ArgumentList @("info", "--format", "{{.OSType}}")
if ($dockerInfo.ExitCode -ne 0) {
    Write-Fail "Docker daemon is not reachable."
    $dockerInfo.Output | ForEach-Object { Write-Host $_ }
    Write-Host ""
    Write-Host "Try this:"
    Write-Host "1. Open Docker Desktop"
    Write-Host "2. Wait for 'Engine running'"
    Write-Host "3. Re-run this script"
    exit 1
}

$osType = (($dockerInfo.Output | Select-Object -Last 1) -as [string]).Trim()
if ($osType -eq "linux") {
    Write-Pass "Docker daemon is running with Linux containers."
}
else {
    Write-Warn "Docker daemon is reachable, but OSType is '$osType'."
    Write-Host "Switch Docker Desktop to Linux containers before running BugScrub."
}

Write-Section "WSL"
if (Test-CommandExists "wsl") {
    $wslInfo = Invoke-ExternalCommand -FilePath "wsl" -ArgumentList @("-l", "-v")
    if ($wslInfo.ExitCode -eq 0) {
        $wslInfo.Output | ForEach-Object { Write-Host $_ }
        if (($wslInfo.Output | Out-String) -match '\s2\s') {
            Write-Pass "At least one WSL distribution appears to be using version 2."
        }
        else {
            Write-Warn "No WSL2 distribution was detected in the output above."
        }
    }
    else {
        Write-Warn "Unable to query WSL status."
        $wslInfo.Output | ForEach-Object { Write-Host $_ }
    }
}
else {
    Write-Warn "WSL command was not found."
}

Write-Section "Docker Compose"
if (-not $SkipComposeChecks) {
    Push-Location $repoRoot
    try {
        $composeConfig = Invoke-ExternalCommand -FilePath "docker" -ArgumentList @("compose", "config")
        if ($composeConfig.ExitCode -eq 0) {
            Write-Pass "docker compose config rendered successfully."
        }
        else {
            Write-Fail "docker compose config failed."
            $composeConfig.Output | ForEach-Object { Write-Host $_ }
        }

        $composeTestConfig = Invoke-ExternalCommand -FilePath "docker" -ArgumentList @("compose", "--profile", "test", "config")
        if ($composeTestConfig.ExitCode -eq 0) {
            Write-Pass "docker compose --profile test config rendered successfully."
        }
        else {
            Write-Fail "docker compose --profile test config failed."
            $composeTestConfig.Output | ForEach-Object { Write-Host $_ }
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Warn "Compose checks were skipped."
}

Write-Section "Port and Health"
if (-not $SkipHealthCheck) {
    $tcpResult = Test-NetConnection -ComputerName "localhost" -Port $Port -WarningAction SilentlyContinue
    if ($tcpResult.TcpTestSucceeded) {
        Write-Pass "A service is listening on localhost:$Port."
        try {
            $healthUrl = "http://localhost:$Port/_stcore/health"
            $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Write-Pass "Streamlit health endpoint responded with HTTP 200."
            }
            else {
                Write-Warn "Health endpoint responded with HTTP $($response.StatusCode)."
            }
        }
        catch {
            Write-Warn "A service is listening on localhost:$Port, but the Streamlit health endpoint did not respond cleanly."
            Write-Host $_
        }
    }
    else {
        Write-Warn "Nothing appears to be listening on localhost:$Port right now."
        Write-Host "If the app should be running, start it with:"
        Write-Host "  .\scripts\docker-up.ps1"
    }
}
else {
    Write-Warn "Health checks were skipped."
}

Write-Section "Runtime Files"
$duckdbPath = Join-Path $repoRoot "storage\bugscrub.duckdb"
$logPath = Join-Path $repoRoot "storage\runtime\logs\bugscrub.jsonl"

if (Test-Path $duckdbPath) {
    Write-Pass "DuckDB file exists: $duckdbPath"
}
else {
    Write-Warn "DuckDB file not found yet: $duckdbPath"
}

if (Test-Path $logPath) {
    Write-Pass "Structured log exists: $logPath"
    Write-Host "Last 5 log lines:"
    Get-Content $logPath -Tail 5 | ForEach-Object { Write-Host $_ }
}
else {
    Write-Warn "Structured log not found yet: $logPath"
}

Write-Section "Recommended Next Commands"
Write-Host ".\scripts\docker-up.ps1"
Write-Host ".\scripts\docker-test.ps1"
Write-Host ".\scripts\docker-down.ps1"
