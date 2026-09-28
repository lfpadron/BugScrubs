# Decisions

## Product
- MVP supports Cisco Nexus and Cisco Catalyst
- Nexus support is complete in MVP
- Catalyst support is basic in MVP
- Phase 1 is assistive, not autonomous

## Architecture
- Local-first
- Streamlit for UI
- DuckDB for analytics
- Docker for packaging
- Windows 11 support is mandatory
- Customer VM deployment is supported

## Security
- Cisco API is optional
- Cisco API is disabled by default
- API enablement and policy management are separate screens
- Secrets are loaded from mounted file first, then environment variables

## Bugs Dataset
- Hybrid strategy:
  - internal dataset by default
  - optional Cisco API enrichment

## Exports
- Executive export supports PDF and PowerPoint
- Standard and filtered Excel exports are required

## Scale
- MVP must be credible for hundreds of devices
