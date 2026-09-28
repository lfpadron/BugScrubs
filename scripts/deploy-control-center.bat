@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_SCRIPT=%SCRIPT_DIR%deploy-control-center.ps1"

if not exist "%POWERSHELL_SCRIPT%" (
    echo deploy-control-center.ps1 was not found at:
    echo %POWERSHELL_SCRIPT%
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File "%POWERSHELL_SCRIPT%"
exit /b %errorlevel%
