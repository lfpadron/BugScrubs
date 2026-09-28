[CmdletBinding()]
param(
    [string]$DockerHubUser = "lfpadron",
    [string]$ImageName = "bugscrub-local-first",
    [string]$Tag = "cloudrun-v6",
    [string]$ProjectId = "bugscrubs-t",
    [string]$ServiceName = "bugscrub-web",
    [string]$Region = "us-central1",
    [string]$RuntimeRoot = "/tmp/bugscrub-runtime",
    [string]$DuckDbPath = "/tmp/bugscrub.duckdb",
    [string]$Memory = "2Gi",
    [int]$Cpu = 1,
    [int]$Concurrency = 20,
    [int]$MaxInstances = 3,
    [int]$MinInstances = 1,
    [int]$TimeoutSeconds = 900,
    [switch]$NoCache,
    [switch]$SkipBuild,
    [switch]$SkipPush,
    [switch]$SkipDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$imageRef = "docker.io/${DockerHubUser}/${ImageName}:${Tag}"
$envVars = "BUGSCRUB_RUNTIME_ROOT=$RuntimeRoot,BUGSCRUB_DUCKDB_PATH=$DuckDbPath"

function Invoke-Step {
    param(
        [string]$Message,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
    & $Action
}

function Assert-CommandAvailable {
    param([string]$CommandName)

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command '$CommandName' was not found in PATH."
    }
}

Push-Location $repoRoot
try {
    if (-not ($SkipBuild -and $SkipPush)) {
        Assert-CommandAvailable -CommandName "docker"
    }

    if (-not $SkipDeploy) {
        Assert-CommandAvailable -CommandName "gcloud"
    }

    if (-not ($SkipBuild -and $SkipPush)) {
        Invoke-Step -Message "Validating Docker daemon access" -Action {
            docker info | Out-Null
        }
    }

    if (-not $SkipBuild) {
        Invoke-Step -Message "Building image $imageRef" -Action {
            $buildArgs = @("build", "-t", $imageRef)
            if ($NoCache) {
                $buildArgs += "--no-cache"
            }
            $buildArgs += "."
            & docker @buildArgs
        }
    }

    if (-not $SkipPush) {
        Invoke-Step -Message "Pushing image $imageRef" -Action {
            & docker push $imageRef
        }
    }

    if (-not $SkipDeploy) {
        Invoke-Step -Message "Setting Google Cloud project to $ProjectId" -Action {
            & gcloud config set project $ProjectId
        }

        Invoke-Step -Message "Deploying $ServiceName to Cloud Run in $Region" -Action {
            & gcloud run deploy $ServiceName `
                --image $imageRef `
                --region $Region `
                --platform managed `
                --allow-unauthenticated `
                --port 8080 `
                --memory $Memory `
                --cpu $Cpu `
                --concurrency $Concurrency `
                --max-instances $MaxInstances `
                --min-instances $MinInstances `
                --timeout $TimeoutSeconds `
                --set-env-vars $envVars
        }

        Invoke-Step -Message "Reading deployed service URL" -Action {
            & gcloud run services describe $ServiceName --region $Region --format "value(status.url)"
        }
    }

    Write-Host ""
    Write-Host "Completed successfully." -ForegroundColor Green
    Write-Host "Image: $imageRef"
}
finally {
    Pop-Location
}
