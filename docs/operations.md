# Operations Guide

## Goal

This guide covers reproducible local and Docker-based operation of BugScrub Local-First for delivery, consulting, and controlled team handoff.

## Runtime layout

The application writes operational state under `storage/`:

- `storage/bugscrub.duckdb`: DuckDB database
- `storage/runtime/uploads/`: staged upload sessions
- `storage/runtime/exports/`: generated Excel, PDF, and PowerPoint outputs
- `storage/runtime/logs/bugscrub.jsonl`: structured application log

The repository also uses:

- `data/`: optional local source files or customer-supplied examples
- `secrets/`: policy file and any future secret material

## Local PowerShell workflow

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). Setup creates the Python 3.11 environment from `uv.lock`.

```powershell
.\scripts\setup-dev.ps1
.\scripts\run-app.ps1
```

Run the automated suite:

```powershell
.\scripts\test.ps1
.\scripts\lint.ps1
```

## Docker workflow

Copy the environment template if needed:

```powershell
Copy-Item .env.example .env
```

Start the application container:

```powershell
.\scripts\docker-up.ps1
```

Stop the stack:

```powershell
.\scripts\docker-down.ps1
```

Run the containerized test profile:

```powershell
.\scripts\docker-test.ps1
```

Equivalent raw Docker Compose commands:

```powershell
docker compose up --build bugscrub
docker compose --profile test run --rm bugscrub-test
docker compose down --remove-orphans
```

## Container defaults

Dependencies are installed with uv from the included lockfile during image construction. For a DigitalOcean droplet, follow the [deployment guide](digitalocean.md) and use `.env.droplet.example` for Linux paths and localhost port binding.

The Docker packaging uses these defaults:

- app port: `8501`
- DuckDB path: `/app/storage/bugscrub.duckdb`
- runtime root: `/app/storage/runtime`
- policy path: `/app/secrets/policy.yaml`
- log level: `INFO`

Mounted volumes:

- `./storage:/app/storage`
- `./data:/app/data:ro`
- `./secrets:/app/secrets:ro`

`storage` is writable because it holds session runtime data, logs, generated reports, and the DuckDB file.

## Health and logs

The runtime image exposes a health check against:

- `http://localhost:8501/_stcore/health`

Structured logs are written to:

- `storage/runtime/logs/bugscrub.jsonl`

Each line is JSON and includes timestamp, level, event, message, and contextual fields.

## Recommended operator checks

After startup, verify:

1. The app opens on `http://localhost:8501`
2. `storage/runtime/logs/bugscrub.jsonl` is created
3. The container reports healthy
4. A sample upload creates rows in DuckDB and generated exports in `storage/runtime/exports/`

## Troubleshooting

- If uploads fail immediately, review the UI validation messages first; the intake flow now blocks corrupt Excel files, binary command outputs, oversized payloads, and invalid ZIP bundles.
- If processing fails after upload, inspect `storage/runtime/logs/bugscrub.jsonl` for the recorded exception and event trail.
- If Docker starts but the UI is unreachable, check port conflicts on `8501` or override `BUGSCRUB_HOST_PORT`.
- If bind-mounted secrets are missing, ensure `secrets/` exists before startup.

## Handoff notes

- Keep `storage/` for persistence between runs.
- Back up `storage/bugscrub.duckdb` and `storage/runtime/exports/` when preserving deliverables.
- Use `.env.example` as the baseline contract for environment variables across teams.
