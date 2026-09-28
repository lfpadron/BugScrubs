@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"

set "DETACH_FLAG="
set "NO_CACHE_FLAG="

:parse_args
if "%~1"=="" goto run
if /I "%~1"=="--detach" (
    set "DETACH_FLAG=-d"
    shift
    goto parse_args
)
if /I "%~1"=="--no-cache" (
    set "NO_CACHE_FLAG=--no-cache"
    shift
    goto parse_args
)

echo Unrecognized argument: %~1
echo Usage: %~nx0 [--detach] [--no-cache]
exit /b 1

:run
pushd "%REPO_ROOT%" || exit /b 1

call :ensure_docker_ready
if errorlevel 1 goto fail

echo [1/3] Stopping existing Docker Compose services...
docker compose down --remove-orphans
if errorlevel 1 goto fail

echo [2/3] Building Docker image for bugscrub...
docker compose build %NO_CACHE_FLAG% bugscrub
if errorlevel 1 goto fail

echo [3/3] Starting bugscrub service...
docker compose up %DETACH_FLAG% bugscrub
if errorlevel 1 goto fail

popd
exit /b 0

:ensure_docker_ready
echo Checking Docker daemon...
docker info >nul 2>nul
if not errorlevel 1 (
    echo Docker daemon is already running.
    exit /b 0
)

if not exist "%DOCKER_DESKTOP_EXE%" (
    echo Docker Desktop was not found at "%DOCKER_DESKTOP_EXE%".
    echo Start Docker Desktop manually and run this script again.
    exit /b 1
)

echo Docker daemon is not running. Starting Docker Desktop...
start "" "%DOCKER_DESKTOP_EXE%"

echo Waiting for Docker daemon to become available...
for /L %%I in (1,1,60) do (
    docker info >nul 2>nul
    if not errorlevel 1 (
        echo Docker daemon is ready.
        exit /b 0
    )
    timeout /t 2 /nobreak >nul
)

echo Docker daemon did not become available in time.
echo Open Docker Desktop and confirm the Linux engine is running, then try again.
exit /b 1

:fail
set "EXIT_CODE=%ERRORLEVEL%"
popd
echo Docker rebuild/run failed with exit code %EXIT_CODE%.
exit /b %EXIT_CODE%
