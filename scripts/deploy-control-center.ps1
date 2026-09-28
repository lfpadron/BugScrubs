Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$entrypoint = Join-Path $repoRoot "scripts\deploy-control-center.py"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
}

if (-not (Test-Path $entrypoint)) {
    throw "The deploy control entrypoint was not found at '$entrypoint'."
}

Push-Location $repoRoot
try {
    uv run --locked python $entrypoint
    if ($LASTEXITCODE -ne 0) { throw "Deploy control failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
