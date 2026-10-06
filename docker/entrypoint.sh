#!/bin/sh
set -eu

: "${BUGSCRUB_RUNTIME_ROOT:=/app/storage/runtime}"
: "${BUGSCRUB_DUCKDB_PATH:=/app/storage/bugscrub.duckdb}"
: "${PORT:=8501}"
: "${BUGSCRUB_STREAMLIT_PORT:=${PORT}}"

mkdir -p "${BUGSCRUB_RUNTIME_ROOT}"
mkdir -p "$(dirname "${BUGSCRUB_DUCKDB_PATH}")"
mkdir -p "${BUGSCRUB_RUNTIME_ROOT}/logs"
mkdir -p /app/data
mkdir -p /app/secrets

exec python -m streamlit run streamlit_app.py \
  --server.address=0.0.0.0 \
  --server.port="${BUGSCRUB_STREAMLIT_PORT}" \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
