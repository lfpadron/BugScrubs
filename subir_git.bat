@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"
if errorlevel 1 goto startup_error

set "REPO_URL=https://github.com/lfpadron/BugScrubs.git"
set "BUGSCRUB_GIT_DIR=%~dp0storage\git-helper"

where git >nul 2>nul
if errorlevel 1 (
    echo Git no esta disponible en PATH.
    goto startup_error
)

if not exist ".git" (
    echo Esta carpeta no tiene un repositorio Git inicializado.
    echo Carpeta: "%CD%"
    goto startup_error
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo No fue posible abrir el repositorio Git de BugScrubs.
    goto startup_error
)

rem Sin argumentos se muestra el menu para uso con doble clic.
if "%~1"=="" goto menu
if /i "%~1"=="--push" goto push_once
if /i "%~1"=="--diff" goto diff_once
echo Uso: subir_git.bat [--push ^| --diff]
exit /b 1

:menu
cls
echo ========================================
echo  BugScrubs - GitHub
echo ========================================
echo.
echo Carpeta: "%CD%"
echo Repo: %REPO_URL%
echo Rama de subida: main
echo.
echo Estado actual:
git status --short --branch
echo.
echo [1] Guardar diff con fecha
echo [2] Subir cambios a GitHub
echo [3] Guardar diff y subir cambios
echo [4] Salir
echo.
choice /c 1234 /n /m "Elige una opcion: "
if errorlevel 255 goto startup_error
if errorlevel 4 exit /b 0
if errorlevel 3 goto menu_both
if errorlevel 2 goto menu_push
if errorlevel 1 goto menu_diff
exit /b 0

:menu_diff
call :save_diff
pause
goto menu

:menu_push
call :push_changes
pause
goto menu

:menu_both
call :save_diff
if errorlevel 1 (
    pause
    goto menu
)
call :push_changes
pause
goto menu

:push_once
call :push_changes
exit /b %errorlevel%

:diff_once
call :save_diff
exit /b %errorlevel%

:startup_error
if "%~1"=="" pause
exit /b 1

:prepare_output
git check-ignore -q -- storage/git-helper/commit-message.txt
if errorlevel 1 (
    echo La carpeta storage/git-helper debe estar excluida en .gitignore.
    exit /b 1
)
if exist "%BUGSCRUB_GIT_DIR%\" exit /b 0
mkdir "%BUGSCRUB_GIT_DIR%"
if errorlevel 1 (
    echo No fue posible crear la carpeta de archivos auxiliares.
    exit /b 1
)
exit /b 0

:timestamp
set "STAMP="
for /f %%A in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss-fff"') do set "STAMP=%%A"
if not defined STAMP (
    echo No fue posible obtener la fecha con PowerShell.
    exit /b 1
)
exit /b 0

:save_diff
call :prepare_output
if errorlevel 1 exit /b 1
call :timestamp
if errorlevel 1 exit /b 1
set "DIFF_FILE=%BUGSCRUB_GIT_DIR%\diff-%STAMP%.txt"
git status --short > "%DIFF_FILE%"
if errorlevel 1 goto diff_error
git diff --no-ext-diff --binary >> "%DIFF_FILE%"
if errorlevel 1 goto diff_error
git diff --cached --no-ext-diff --binary >> "%DIFF_FILE%"
if errorlevel 1 goto diff_error
echo Diff guardado en "%DIFF_FILE%"
echo Incluye estado y cambios pendientes, incluidos los preparados para commit.
echo Los archivos nuevos se listan por nombre; su contenido no se incluye.
exit /b 0

:diff_error
echo No fue posible completar el diff.
exit /b 1

:check_destination
set "CURRENT_BRANCH="
for /f "delims=" %%A in ('git branch --show-current') do set "CURRENT_BRANCH=%%A"
if not "%CURRENT_BRANCH%"=="main" (
    echo La subida requiere estar en la rama main.
    echo Rama actual: "%CURRENT_BRANCH%"
    exit /b 1
)
set "REMOTE_COUNT=0"
set "REMOTE_URL="
for /f "delims=" %%A in ('git remote get-url --push --all origin 2^>nul') do (
    set /a REMOTE_COUNT+=1 >nul
    set "REMOTE_URL=%%A"
)
if not "%REMOTE_COUNT%"=="1" goto destination_error
if /i "%REMOTE_URL%"=="%REPO_URL%" exit /b 0
if /i "%REMOTE_URL%"=="git@github.com:lfpadron/BugScrubs.git" exit /b 0

:destination_error
echo El remoto origin debe tener un solo destino de subida: %REPO_URL%
echo Comprueba la configuracion con: git remote -v
exit /b 1

:push_changes
call :check_destination
if errorlevel 1 exit /b 1
call :prepare_output
if errorlevel 1 exit /b 1

echo.
echo Preparando cambios de BugScrubs conforme a .gitignore...
git add -A
if errorlevel 1 (
    echo Fallo git add. No se hizo commit ni push.
    exit /b 1
)
git diff --cached --quiet
if errorlevel 2 (
    echo No fue posible revisar los cambios preparados.
    exit /b 1
)
if errorlevel 1 goto create_commit
echo No hay cambios nuevos. Se intentaran subir los commits pendientes.
goto publish

:create_commit
git diff --cached --stat
call :timestamp
if errorlevel 1 exit /b 1
set "BUGSCRUB_COMMIT_MESSAGE="
set /p "BUGSCRUB_COMMIT_MESSAGE=Mensaje del commit (Enter para usar fecha): "
if not defined BUGSCRUB_COMMIT_MESSAGE set "BUGSCRUB_COMMIT_MESSAGE=Actualizacion BugScrubs %STAMP%"
set "BUGSCRUB_COMMIT_FILE=%BUGSCRUB_GIT_DIR%\commit-message.txt"
rem El mensaje se pasa por una variable de entorno, sin ejecutarlo como codigo.
powershell -NoProfile -Command "[IO.File]::WriteAllText($env:BUGSCRUB_COMMIT_FILE, $env:BUGSCRUB_COMMIT_MESSAGE, (New-Object Text.UTF8Encoding($false)))"
if errorlevel 1 (
    echo No fue posible guardar el mensaje del commit.
    exit /b 1
)
git commit --file "%BUGSCRUB_COMMIT_FILE%"
if errorlevel 1 (
    echo Fallo git commit. Revisa el error anterior; no se hizo push.
    exit /b 1
)

:publish
git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 (
    echo Todavia no hay commits para subir.
    exit /b 1
)
git push --set-upstream origin main
if errorlevel 1 (
    echo Fallo git push. Los commits permanecen guardados localmente.
    echo Resuelve el error indicado por Git y vuelve a elegir Subir cambios.
    exit /b 1
)
echo.
echo BugScrubs subido correctamente a %REPO_URL%
exit /b 0
