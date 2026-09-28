param(
    [string]$DestinationRoot = "C:\Users\lfpad\Documents",
    [switch]$ExcludeVenv,
    [switch]$ExcludeRuntime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectName = Split-Path -Leaf $repoRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$destination = Join-Path $DestinationRoot "$projectName-backup-$timestamp"

$excludedDirectories = @(".git", "__pycache__")
if ($ExcludeVenv) {
    $excludedDirectories += ".venv"
}
if ($ExcludeRuntime) {
    $excludedDirectories += "storage"
}

$robocopyArgs = @(
    $repoRoot,
    $destination,
    "/E",
    "/XD"
) + $excludedDirectories + @(
    "/XF",
    "*.pyc"
)

Write-Host "Creating backup..."
Write-Host "Source      : $repoRoot"
Write-Host "Destination : $destination"
Write-Host "Excluded    : $($excludedDirectories -join ', '), *.pyc"

& robocopy @robocopyArgs
$exitCode = $LASTEXITCODE

if ($exitCode -gt 7) {
    throw "Backup failed with robocopy exit code $exitCode."
}

Write-Host ""
Write-Host "Backup completed successfully."
Write-Host "BACKUP_PATH=$destination"
