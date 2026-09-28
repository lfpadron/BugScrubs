# Module Map

## Application packages

- `src/bugscrub/parsers/`: raw input parsing contracts and platform parsers.
  Current status: Nexus support is more complete for the first command set; Catalyst support is intentionally basic.
- `src/bugscrub/normalization/`: canonical device records and normalization flow.
- `src/bugscrub/bug_engine/`: bug matching, scoring, and recommendation logic.
- `src/bugscrub/exporters/`: Excel and executive export backends.
- `src/bugscrub/security/`: policy gates and secret handling helpers.
- `src/bugscrub/cisco_api/`: optional Cisco API client and policy-aware gateway.
- `src/bugscrub/db/`: DuckDB entry points and future schema helpers.
- `src/bugscrub/ui/`: Streamlit rendering helpers.

## Reserved directories

- `data/raw/`: uploaded source files and staged imports.
- `data/processed/`: normalized or derived intermediate files when needed.
- `storage/`: DuckDB database and future local cache files.
- `secrets/`: mounted customer secrets and policy files.

## Notes

The scaffold intentionally keeps downstream business logic out of these modules until the first ingestion workflow is defined.

Parser maturity note:

- `NexusParser` covers the initial command bundle with richer heuristics.
- `CatalystParser` is explicitly `basic` support and should be treated as best-effort for common IOS XE outputs only.
