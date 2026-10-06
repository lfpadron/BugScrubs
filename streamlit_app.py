from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from bugscrub.build_info import current_build_timestamp
from bugscrub.config import get_settings
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.observability import configure_structured_logging, get_logger, log_event
from bugscrub.ui.branding import PAGE_TITLE, render_footer
from bugscrub.ui.pages import render_home


def main() -> None:
    settings = get_settings()
    log_path = configure_structured_logging(settings.runtime_root, level=settings.log_level)
    store = DuckDBStore(settings.duckdb_path)
    logger = get_logger("app")

    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=":material/shield:",
        layout="wide",
    )
    build_timestamp = current_build_timestamp(Path(__file__).resolve().parent)
    st.markdown(
        '<div style="text-align: right; font-size: 0.875rem;">'
        f"Time stamp current build: {build_timestamp}</div>",
        unsafe_allow_html=True,
    )
    log_event(
        logger,
        logging.INFO,
        "app_initialized",
        "BugScrub Streamlit app initialized.",
        duckdb_path=settings.duckdb_path,
        runtime_root=settings.runtime_root,
        log_path=log_path,
    )
    render_home(settings=settings, store=store)
    render_footer()


if __name__ == "__main__":
    main()
