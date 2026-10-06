@echo off
setlocal EnableExtensions DisableDelayedExpansion

pushd "%~dp0"
if errorlevel 1 (
    echo No fue posible abrir la carpeta del proyecto.
    pause
    exit /b 1
)

if not exist "%~dp0subir_droplet.ps1" (
    echo No se encontro subir_droplet.ps1 junto a este archivo.
    popd
    pause
    exit /b 1
)

rem Las pruebas se ejecutan en esta PC para ahorrar memoria en el droplet.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0subir_droplet.ps1" -UseDefaults -RunTestsLocally %*
set "BUGSCRUB_DEPLOY_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%BUGSCRUB_DEPLOY_EXIT_CODE%"=="0" (
    echo Proceso finalizado correctamente.
) else (
    echo El proceso fallo con codigo %BUGSCRUB_DEPLOY_EXIT_CODE%. Revisa los mensajes anteriores.
)

popd
pause
exit /b %BUGSCRUB_DEPLOY_EXIT_CODE%
