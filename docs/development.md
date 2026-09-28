# Development Setup

## Scope

This document covers the current MVP development workflow, including local execution, Docker packaging, test entry points, and the runtime contract used by the application.

## Local run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. Python 3.11 is selected by `.python-version` and dependencies are locked in `uv.lock`.

```powershell
.\scripts\setup-dev.ps1
.\scripts\run-app.ps1
```

Equivalent commands on Windows or Linux:

```text
uv sync --locked
uv run --locked python -m streamlit run streamlit_app.py
```

Development tools are in the `dev` dependency group and are included by default. Docker installs runtime dependencies with `uv sync --locked --no-dev --no-editable`; its test target includes the development group. The container runs from that installed environment without resolving packages at startup.

After intentionally changing dependencies in `pyproject.toml`, run `uv lock` and keep the updated `uv.lock` with the source. Routine setup and launch commands use `--locked` so they do not silently change dependency versions. See [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/).

## Local validation

```powershell
.\scripts\lint.ps1
.\scripts\test.ps1
```

## Docker run

```powershell
Copy-Item .env.example .env
.\scripts\docker-up.ps1
```

## Docker validation

```powershell
.\scripts\docker-test.ps1
.\scripts\docker-down.ps1
```

## Environment

- Copy `.env.example` to `.env` when you need to tune runtime paths, host port, logging, or Cisco API credentials.
- Cisco API remains disabled by default.
- Structured logging writes to `storage/runtime/logs/bugscrub.jsonl`.
- Docker uses `storage/` as the writable persistent volume and mounts `data/` and `secrets/` read-only.

## Runtime contract

- `storage/bugscrub.duckdb`: DuckDB persistence
- `storage/runtime/uploads/`: staged upload sessions
- `storage/runtime/exports/`: generated deliverables
- `storage/runtime/logs/bugscrub.jsonl`: structured application log

## Operator docs

Use [`docs/operations.md`](./operations.md) for deployment, health checks, volume expectations, troubleshooting, and handoff guidance.

For the Linux test server, use the [DigitalOcean guide](digitalocean.md).

## Immediate implementation targets

- Robustecer parsers Nexus y Catalyst para más variantes reales.
- Extender Catalyst más allá de soporte `basic`.
- Mejorar el motor de bugs offline con reglas más ricas y menos `needs_review`.
- Agregar historial y comparación entre sesiones.
- Mejorar pruebas UI y flujo end-to-end.
