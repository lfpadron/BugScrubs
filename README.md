# BugScrub Local-First

Local-first Cisco Bug Scrub MVP with `Streamlit`, `DuckDB`, structured runtime logging, Docker packaging, staged file uploads, offline bug correlation, discrepancy analysis, and executive exports.

## Revisión verificada del sistema

La [revisión técnica y funcional del 27 de septiembre de 2026](docs/revision_sistema_2026-09-27.md) describe en español el flujo real, los contratos de entrada, las pruebas realizadas y la preparación propuesta para un droplet de DigitalOcean.

El sistema procesa catálogos estructurados CSV/Excel y archivos de comandos Nexus/Catalyst. Los documentos Cisco originales en PDF/Word requieren una transformación previa; la API Cisco sigue siendo un esqueleto. La revisión distingue las funciones implementadas de los objetivos históricos de `docs/` y registra las limitaciones que deben atenderse antes de ampliar el acceso al servidor.

## Implemented scope

- Upload and validate customer inventory plus raw command outputs.
- Parse Nexus command bundles with robust coverage.
- Parse Catalyst command bundles with `basic` support.
- Support single-device uploads and multi-device ZIP bundle sessions.
- Normalize inventory Excel columns and discovered device data.
- Compare inventory versus discovered state and persist paired discrepancy rows.
- Load local bug datasets from CSV/XLSX into DuckDB and activate them offline.
- Correlate bugs by platform, release, PID, features, and remediation status.
- Render Streamlit dashboards, Pareto analysis, and operational previews.
- Export Excel, executive PDF, and executive PowerPoint outputs.
- Persist sessions, findings, discrepancies, and catalogs in DuckDB.
- Record structured JSONL runtime logs for troubleshooting and handoff.

## Repository notes

The repository also contains discovery material in [`docs/`](./docs):

- architecture, backlog, export-format, and decision notes
- a legacy Python prototype
- customer examples and reference material

## Local quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. The project uses Python 3.11 (`.python-version`); uv creates the environment and installs the versions recorded in `uv.lock`.

```powershell
.\scripts\setup-dev.ps1
.\scripts\run-app.ps1
```

Run validation locally:

```powershell
.\scripts\lint.ps1
.\scripts\test.ps1
```

## Docker quick start

```powershell
Copy-Item .env.example .env
.\scripts\docker-up.ps1
```

Run the containerized test profile:

```powershell
.\scripts\docker-test.ps1
```

Stop the Docker stack:

```powershell
.\scripts\docker-down.ps1
```

The app is available on `http://localhost:8501` by default.

## DigitalOcean Droplet

Use the existing Docker Compose service with `.env.droplet.example`. The [droplet deployment guide](docs/digitalocean.md) covers packaging, persistent storage, startup, and access through an SSH tunnel.

## Current build timestamp

The top-right field `Time stamp current build` shows the latest modification time of `streamlit_app.py` and the Python files under `src/bugscrub`, in UTC. It uses source file timestamps, not server startup time. Preserve timestamps when transferring the source (the deployment guide uses a tar archive).

## Runtime defaults

- DuckDB: `storage/bugscrub.duckdb`
- Runtime root: `storage/runtime`
- Structured log: `storage/runtime/logs/bugscrub.jsonl`
- Default host port: `8501`

## Operations docs

- Development notes: [`docs/development.md`](./docs/development.md)
- Runtime and Docker operations: [`docs/operations.md`](./docs/operations.md)
