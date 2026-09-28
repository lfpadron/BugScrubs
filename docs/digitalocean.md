# Despliegue de pruebas en un droplet de DigitalOcean

Este procedimiento ejecuta la aplicación actual con Docker Compose, una instancia y persistencia en `storage/`. Requiere un droplet Linux con Docker Engine y el plugin Docker Compose, acceso SSH y permisos para ejecutar Docker. No requiere instalar uv en el host: la imagen incluye uv 0.11.15 y usa Python 3.11.

Referencias de instalación y acceso: [Docker Engine en Ubuntu](https://docs.docker.com/engine/install/ubuntu/) y [SSH a un droplet](https://docs.digitalocean.com/products/droplets/how-to/connect-with-ssh/).

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
