FROM python:3.11-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src
COPY streamlit_app.py ./
COPY .streamlit ./.streamlit
COPY docker/entrypoint.sh ./docker/entrypoint.sh

RUN uv sync --locked --no-dev --no-editable --no-cache \
    && mkdir -p /app/storage/runtime/logs /app/data /app/secrets \
    && chmod +x /app/docker/entrypoint.sh

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os, sys, urllib.request; port = int(os.environ.get('BUGSCRUB_STREAMLIT_PORT') or os.environ.get('PORT', '8501')); url = f'http://127.0.0.1:{port}/_stcore/health'; sys.exit(0 if urllib.request.urlopen(url, timeout=3).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]


FROM runtime AS test

COPY tests ./tests

RUN uv sync --locked --no-editable --no-cache

ENTRYPOINT ["python"]
CMD ["-m", "pytest", "tests"]


FROM runtime AS final
