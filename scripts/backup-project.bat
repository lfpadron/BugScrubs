@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_SCRIPT=%SCRIPT_DIR%backup-project.ps1"

if not exist "%POWERSHELL_SCRIPT%" (
    echo Could not find PowerShell backup script:
    echo %POWERSHELL_SCRIPT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%POWERSHELL_SCRIPT%" %*
exit /b %ERRORLEVEL%
