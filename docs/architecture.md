# Architecture

## Overview
BugScrub Local-First is a local analytics application for Cisco bug scrub assistance.

## Main components
1. Streamlit UI
2. Parsing layer
3. Inventory normalization layer
4. Discrepancy engine
5. Bug correlation engine
6. DuckDB analytics layer
7. Export layer
8. Security and policy layer
9. Optional Cisco API integration

## Data flow
Upload/Input -> Parsing -> Normalization -> DuckDB -> Discrepancies -> Bug Correlation -> Dashboards -> Exports

## Security model
- local-first
- API off by default
- policy-gated API usage
- mounted secrets preferred
- environment variables fallback

## Deployment
- Docker Desktop on Windows 11
- Docker runtime on customer VMs
