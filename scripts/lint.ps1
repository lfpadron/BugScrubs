Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
}

Push-Location $repoRoot
try {
    uv run --locked python -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw "ruff failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
