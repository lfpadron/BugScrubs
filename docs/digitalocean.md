# Despliegue de pruebas en un droplet de DigitalOcean

Este procedimiento ejecuta la aplicación actual con Docker Compose, una instancia y persistencia en `storage/`. Requiere un droplet Linux con Docker Engine y el plugin Docker Compose, acceso SSH y permisos para ejecutar Docker. No requiere instalar uv en el host: la imagen incluye uv 0.11.15 y usa Python 3.11.

Referencias de instalación y acceso: [Docker Engine en Ubuntu](https://docs.docker.com/engine/install/ubuntu/) y [SSH a un droplet](https://docs.digitalocean.com/products/droplets/how-to/connect-with-ssh/).

## Subida automatizada desde Windows

El script `subir_droplet.ps1` de la raíz empaqueta el código, lo transfiere por SCP, comprueba su SHA-256 y despliega el servicio `bugscrub` con Docker Compose. Sus valores iniciales son `root@204.48.17.255`, la carpeta `/opt/bugscrubs` y la clave privada `BugScrubs_key` junto al script. La clave pública `BugScrubs_key.pub` debe estar autorizada para ese usuario en el droplet; el script usa la privada y nunca la incluye en el paquete.

Dar doble clic en `subir_droplet.bat` ejecuta primero las pruebas con UV en la PC. Si pasan, sube el código y comprueba la salud del servicio en el droplet. El comando equivalente es:

```powershell
.\subir_droplet.ps1 -UseDefaults -RunTestsLocally
```

Esta modalidad requiere UV local y evita ejecutar el contenedor de pruebas junto a la aplicación en un droplet con poca memoria. Si las pruebas locales fallan, no se conecta ni sube archivos al servidor. Las pruebas se ejecutan sobre el código local que se empaquetará, por lo que `-RunTestsLocally` no se combina con `-ExtractOnly`.

Como opción adicional, si el droplet tiene memoria disponible, se pueden ejecutar las pruebas dentro de Docker antes de arrancar:

```powershell
.\subir_droplet.ps1 -UseDefaults -RunTests
```

Se puede indicar otra clave con `-KeyPath 'C:\ruta\BugScrubs_key'`. Si se pasa la ruta `.pub`, el script busca la privada del mismo nombre sin esa extensión. Sin `-UseDefaults`, pregunta los valores de conexión y las rutas. `-Help` muestra las opciones de solo empaquetar, solo subir, extraer un paquete ya subido y conservar el archivo local.

Para inspeccionar el paquete sin conectarse al servidor:

```powershell
.\subir_droplet.ps1 -UseDefaults -PackageOnly
```

El paquete queda en `storage/deploy/`. Se incluyen los archivos de Docker, código, pruebas, `uv.lock` y las plantillas necesarias; se excluyen claves SSH, entornos virtuales, configuración privada y datos de clientes. Se mantienen las fechas del código. En el servidor, `.env.droplet` se crea solo si no existe y se conservan `storage/`, `data/` y `secrets/`. El script espera el estado saludable del contenedor y comprueba el endpoint HTTP de salud.

Docker Engine y Docker Compose v2 deben estar instalados en el droplet. El script conserva el acceso inicial por túnel SSH descrito abajo; la configuración de `bugscrubs.astrogatolabs.com.mx` y su certificado HTTPS corresponde al proxy del droplet.

## 1. Transferir el proyecto

Desde la raíz de BugScrubs en PowerShell, generar un paquete con los archivos necesarios. El archivo conserva las fechas de modificación del código para el indicador de build:

```powershell
tar -czf bugscrub-deploy.tar.gz --exclude=__pycache__ --exclude=*.pyc Dockerfile docker-compose.yml pyproject.toml uv.lock .python-version README.md streamlit_app.py src docker .streamlit .env.droplet.example tests
scp bugscrub-deploy.tar.gz usuario@IP_DEL_DROPLET:/tmp/bugscrub-deploy.tar.gz
```

El paquete no incluye los datos locales de clientes, secretos, base de datos ni el entorno virtual de Windows. La prueba comienza con almacenamiento propio en el servidor.

## 2. Preparar y arrancar

En el droplet, después de conectarse por SSH:

```sh
mkdir -p ~/bugscrub
cd ~/bugscrub
tar -xzf /tmp/bugscrub-deploy.tar.gz
cp .env.droplet.example .env.droplet
mkdir -p storage data secrets
docker compose --env-file .env.droplet config --quiet
docker compose --env-file .env.droplet up -d --build bugscrub
docker compose --env-file .env.droplet ps
curl --fail http://127.0.0.1:8501/_stcore/health
```

La copia de `.env.droplet.example` es para la primera instalación; conservar `.env.droplet` en actualizaciones. La construcción necesita descargar la imagen base, uv y los paquetes. `uv sync --locked` verifica que `pyproject.toml` y `uv.lock` concuerden.

La configuración del droplet utiliza:

- `BUGSCRUB_DUCKDB_PATH=/app/storage/bugscrub.duckdb`.
- `BUGSCRUB_RUNTIME_ROOT=/app/storage/runtime`.
- Montaje persistente de `./storage` en `/app/storage`.
- Puerto 8501 publicado únicamente en `127.0.0.1`.
- API Cisco desactivada y los demás comportamientos de la aplicación conservados.

## 3. Abrir la aplicación

Desde la computadora del operador, mantener abierta esta conexión:

```text
ssh -N -L 8501:127.0.0.1:8501 usuario@IP_DEL_DROPLET
```

Abrir [BugScrub local](http://localhost:8501). Si ese puerto ya está ocupado en la computadora, usar `-L 8502:127.0.0.1:8501` y abrir el puerto 8502. El acceso se realiza a través de SSH; no hace falta abrir 8501 en el firewall del droplet. La aplicación conserva su modelo actual sin login propio.

## 4. Validar y operar

Ejecutar las pruebas dentro de la imagen:

```sh
docker compose --env-file .env.droplet --profile test run --build --rm bugscrub-test
```

Ver los logs del servicio:

```sh
docker compose --env-file .env.droplet logs --tail=100 bugscrub
```

Los eventos de procesamiento se guardan también en `storage/runtime/logs/bugscrub.jsonl`. Verificar una carga, el dashboard, las descargas y el campo `Time stamp current build` arriba a la derecha. El campo muestra UTC y toma la fecha más reciente entre `streamlit_app.py` y `src/bugscrub/**/*.py`; no incluye cambios de datos, documentación o logs.

Para actualizar, transferir y extraer el nuevo paquete conservando `storage/` y `.env.droplet`, y repetir `docker compose --env-file .env.droplet up -d --build bugscrub`. Para detener el servicio:

```sh
docker compose --env-file .env.droplet down
```

Los archivos de `storage/` permanecen en el host al recrear o detener el contenedor. Para respaldarlos de forma coherente, detener primero el servicio, copiar `storage/` y volver a iniciarlo. No ejecutar varias instancias contra el mismo archivo DuckDB.
