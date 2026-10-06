[CmdletBinding()]
param(
    [string]$Server = '204.48.17.255',
    [string]$User = 'root',
    [string]$RemoteDir = '/opt/bugscrubs',
    [string]$ProjectDir = '',
    [string]$KeyPath = '',
    [switch]$UseDefaults,
    [switch]$SkipExtract,
    [switch]$ExtractOnly,
    [switch]$SkipDeploy,
    [switch]$RunTests,
    [switch]$PackageOnly,
    [switch]$KeepArchive,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Show-Help {
    Write-Host @'
BugScrubs - subida y despliegue en el droplet

Uso:
  .\subir_droplet.ps1
  .\subir_droplet.ps1 -UseDefaults
  .\subir_droplet.ps1 -UseDefaults -RunTests
  .\subir_droplet.ps1 -UseDefaults -KeyPath C:\ruta\BugScrubs_key
  .\subir_droplet.ps1 -UseDefaults -PackageOnly

Valores iniciales: root@204.48.17.255, carpeta /opt/bugscrubs.
Proyecto: carpeta de este script. Llave privada: BugScrubs_key en el proyecto.
La clave publica .pub se instala en el droplet; SSH usa la privada local.

Opciones:
  -UseDefaults   Usa los parametros sin preguntar valores.
  -SkipExtract   Solo sube /tmp/bugscrubs-deploy.tar.gz.
  -ExtractOnly   Usa ese paquete remoto existente, sin empaquetar ni subir.
  -SkipDeploy    Extrae el codigo sin reconstruir o arrancar contenedores.
  -RunTests      Ejecuta las pruebas Docker antes de arrancar la aplicacion.
  -PackageOnly   Genera y conserva el paquete local, sin SSH ni SCP.
  -KeepArchive   Conserva el paquete local despues de la subida.

Requisitos locales: tar, ssh y scp en PATH.
Requisitos remotos: Linux, tar, Docker Engine y Docker Compose v2 con --wait.
El usuario SSH debe poder escribir en RemoteDir y usar Docker.
La clave publica correspondiente debe estar autorizada en el droplet.

Se conserva .env.droplet si ya existe. En la primera instalacion se crea
desde .env.droplet.example. Se conservan storage/, data/ y secrets/ remotos.
La configuracion inicial publica el puerto 8501 solo en 127.0.0.1.
El dominio y HTTPS se configuran mediante el proxy del droplet.
'@
}

function Read-Default {
    param([string]$Label, [string]$Default)
    $value = Read-Host "$Label [$Default]"
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value.Trim()
}

function Test-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No encontre '$Name' en PATH."
    }
}

function Invoke-Native {
    param([string]$Description, [string]$Exe, [string[]]$Arguments)
    Write-Host ""
    Write-Host "==> $Description"
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description fallo con codigo $LASTEXITCODE."
    }
}

function Quote-Sh {
    param([string]$Value)
    $singleQuote = [string][char]39
    $escapedQuote = $singleQuote + '"' + $singleQuote + '"' + $singleQuote
    return $singleQuote + $Value.Replace($singleQuote, $escapedQuote) + $singleQuote
}

function Invoke-Remote {
    param([string]$Description, [string]$Command)
    # Transporte ASCII para conservar las comillas y saltos de linea en PS 5.1/7.
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Command.Replace("`r`n", "`n")))
    $transport = "printf %s '$encoded' | base64 -d | sh"
    Invoke-Native $Description 'ssh' ($sshOptions + @($Remote, $transport))
}

if ($Help) {
    Show-Help
    return
}

$createdArchive = $false
$LocalArchive = ''

try {
    if ([string]::IsNullOrWhiteSpace($ProjectDir)) { $ProjectDir = $PSScriptRoot }
    $ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
    if ([string]::IsNullOrWhiteSpace($KeyPath)) {
        $KeyPath = Join-Path $ProjectDir 'BugScrubs_key'
    }

    if (-not $UseDefaults) {
        Write-Host 'Subida de BugScrubs. Presiona Enter para aceptar cada valor.'
        $Server = Read-Default 'IP o dominio del droplet' $Server
        $User = Read-Default 'Usuario SSH' $User
        $RemoteDir = Read-Default 'Carpeta destino remota' $RemoteDir
        $ProjectDir = Read-Default 'Carpeta local del proyecto' $ProjectDir
        $KeyPath = Read-Default 'Llave privada SSH' $KeyPath
    }

    if ($SkipExtract -and $ExtractOnly) {
        throw 'No puedes combinar -SkipExtract y -ExtractOnly.'
    }
    if ($PackageOnly -and ($SkipExtract -or $ExtractOnly -or $SkipDeploy -or $RunTests)) {
        throw '-PackageOnly no se combina con opciones de subida o despliegue.'
    }
    if ($RunTests -and ($SkipExtract -or $SkipDeploy)) {
        throw '-RunTests requiere un despliegue; omite -SkipExtract y -SkipDeploy.'
    }
    if ($Server -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]*$') {
        throw 'Server debe ser una direccion IPv4 o un nombre DNS.'
    }
    if ($User -notmatch '^[a-zA-Z_][a-zA-Z0-9_-]*$') {
        throw 'Usuario SSH no valido.'
    }
    if ($RemoteDir -notmatch '^/[a-zA-Z0-9_.-]+(/[a-zA-Z0-9_.-]+)*/?$' -or
        $RemoteDir -match '(^|/)\.{1,2}(/|$)') {
        throw 'RemoteDir debe ser una ruta Linux absoluta, sin espacios ni segmentos . o ..; por ejemplo /opt/bugscrubs.'
    }
    $ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
    $KeyPath = [IO.Path]::GetFullPath($KeyPath)
    if ($KeyPath.EndsWith('.pub', [StringComparison]::OrdinalIgnoreCase)) {
        $KeyPath = $KeyPath.Substring(0, $KeyPath.Length - 4)
        Write-Host "Usare la llave privada asociada al archivo .pub: $KeyPath"
    }
    $RemoteDir = $RemoteDir.TrimEnd('/')
    $Remote = "${User}@${Server}"
    $RemoteArchive = '/tmp/bugscrubs-deploy.tar.gz'

    if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
        throw "No existe la carpeta local: $ProjectDir"
    }

    # Lista explicita: no se copia todo el proyecto ni los datos de clientes.
    $archiveEntries = @(
        'Dockerfile', 'docker-compose.yml', '.dockerignore',
        'pyproject.toml', 'uv.lock', '.python-version', 'README.md',
        'streamlit_app.py', 'src', 'docker', '.streamlit/config.toml',
        '.env.droplet.example', 'tests'
    )
    if (-not $ExtractOnly) {
        Test-Command 'tar'
        foreach ($entry in $archiveEntries) {
            if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir $entry))) {
                throw "Falta un archivo o carpeta necesario para desplegar: $entry"
            }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir 'docker/entrypoint.sh') -PathType Leaf)) {
            throw 'Falta docker/entrypoint.sh; es necesario para arrancar el contenedor.'
        }
    }

    if (-not $PackageOnly) {
        Test-Command 'ssh'
        if (-not $ExtractOnly) { Test-Command 'scp' }
        if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
            throw "No existe la llave privada SSH: $KeyPath. El archivo .pub por si solo no permite conectarse. Usa -KeyPath con la privada."
        }
        $keyHeader = Get-Content -LiteralPath $KeyPath -TotalCount 1
        if ($keyHeader -notmatch '^-----BEGIN (OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----$') {
            throw 'KeyPath no parece una llave privada SSH. No uses el contenido de la clave publica .pub.'
        }
    }

    $sshOptions = @('-i', $KeyPath, '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4')

    Write-Host ""
    Write-Host "Proyecto: $ProjectDir"
    Write-Host "Destino:  ${Remote}:$RemoteDir"
    if (-not $PackageOnly) {
        Write-Host "Llave privada: $KeyPath"
        Write-Host 'Si tiene passphrase, SSH la pedira durante la conexion.'
        $preflight = @('set -eu', 'command -v tar >/dev/null')
        if (-not $ExtractOnly) { $preflight += 'command -v sha256sum >/dev/null' }
        if (-not $SkipExtract -and -not $SkipDeploy) {
            $preflight += @(
                'command -v docker >/dev/null || { echo "Instala Docker Engine y Docker Compose v2 en el droplet." >&2; exit 1; }',
                'docker info >/dev/null', 'docker compose version'
            )
        }
        Invoke-Remote 'Comprobando conexion y requisitos remotos' ($preflight -join '; ')
    }

    if (-not $ExtractOnly) {
        $archiveDir = Join-Path $ProjectDir 'storage/deploy'
        New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $LocalArchive = Join-Path $archiveDir ("bugscrubs-deploy-$stamp-" + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.tar.gz')
        $keyName = Split-Path -Leaf $KeyPath
        $excludePatterns = @('__pycache__', '*.pyc', '*.pyo', '.pytest_cache',
            '.ruff_cache', '.git', '.venv', '.ssh', '.env', 'secrets.toml',
            'BugScrubs_key', 'BugScrubs_key.pub', '*.pem', '*.key', '*.pub', $keyName, "$keyName.pub") |
            Select-Object -Unique
        $tarArgs = @('-czf', $LocalArchive)
        foreach ($pattern in $excludePatterns) { $tarArgs += @('--exclude', $pattern) }
        $tarArgs += @('-C', $ProjectDir) + $archiveEntries
        $createdArchive = $true
        Invoke-Native 'Empaquetando codigo y conservando fechas de modificacion' 'tar' $tarArgs
        $archiveStream = [IO.File]::OpenRead($LocalArchive)
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $archiveHash = [BitConverter]::ToString($hasher.ComputeHash($archiveStream)).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $archiveStream.Dispose()
            $hasher.Dispose()
        }
        Write-Host "SHA256: $archiveHash"
        if ($PackageOnly) {
            Write-Host 'Paquete preparado. No se realizaron conexiones al droplet.'
            return
        }
        Invoke-Native 'Subiendo paquete al droplet' 'scp' ($sshOptions + @($LocalArchive, "${Remote}:$RemoteArchive"))
        $verifyCommand = "printf '%s  %s\n' " + (Quote-Sh $archiveHash) + ' ' + (Quote-Sh $RemoteArchive) + ' | sha256sum -c -'
        Invoke-Remote 'Verificando integridad del paquete recibido' $verifyCommand
    }
    else {
        Write-Host "ExtractOnly: usare el paquete existente ${Remote}:$RemoteArchive"
    }

    if ($SkipExtract) {
        Write-Host "Paquete subido a ${Remote}:$RemoteArchive"
        Write-Host 'Para continuar despues, usa -ExtractOnly con los mismos parametros de conexion.'
        return
    }

    $remoteSteps = @(
        'set -eu',
        ('test -s ' + (Quote-Sh $RemoteArchive)),
        ('mkdir -p ' + (Quote-Sh $RemoteDir)),
        ('tar -xzf ' + (Quote-Sh $RemoteArchive) + ' -C ' + (Quote-Sh $RemoteDir)),
        ('cd ' + (Quote-Sh $RemoteDir)),
        'mkdir -p storage data secrets',
        'if [ ! -e .env.droplet ]; then (umask 077; cp .env.droplet.example .env.droplet); fi',
        'test -s .env.droplet || { echo ".env.droplet esta vacio; revisa su configuracion." >&2; exit 1; }'
    )
    if (-not $SkipDeploy) {
        $remoteSteps += @(
            'compose() { docker compose --env-file .env.droplet "$@"; }',
            'compose config --quiet'
        )
        if ($RunTests) {
            $remoteSteps += 'compose --profile test run --build --rm bugscrub-test'
        }
        $remoteSteps += @(
            'if ! compose up -d --build --wait --wait-timeout 120 bugscrub; then compose ps; compose logs --tail=80 bugscrub; exit 1; fi',
            'compose ps'
        )
        $healthCheck = 'import os, urllib.request; port = int(os.environ.get("BUGSCRUB_STREAMLIT_PORT") or os.environ.get("PORT", "8501")); response = urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=10); assert response.status == 200; print("Health HTTP", response.status, response.read().decode())'
        $remoteSteps += 'compose exec -T bugscrub python -c ' + (Quote-Sh $healthCheck)
    }
    $remoteSteps += 'rm -f ' + (Quote-Sh $RemoteArchive)
    Invoke-Remote 'Extrayendo y preparando BugScrubs en el droplet' ($remoteSteps -join '; ')

    if ($SkipDeploy) {
        Write-Host "Codigo extraido en $RemoteDir. SkipDeploy: no se reconstruyeron contenedores."
    }
    else {
        Write-Host 'BugScrubs desplegado y comprobacion de salud correcta.'
        Write-Host 'Con la configuracion inicial, abre un tunel SSH desde otra terminal:'
        Write-Host "  ssh -i `"$KeyPath`" -N -L 8501:127.0.0.1:8501 $Remote"
        Write-Host 'Luego abre http://localhost:8501. El dominio y HTTPS requieren el proxy del droplet.'
    }
}
catch {
    Write-Host "Fallo la subida: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if ($createdArchive -and (Test-Path -LiteralPath $LocalArchive)) {
        if ($KeepArchive -or $PackageOnly) {
            Write-Host "Paquete local conservado: $LocalArchive"
        }
        else {
            Remove-Item -LiteralPath $LocalArchive -Force
        }
    }
}
