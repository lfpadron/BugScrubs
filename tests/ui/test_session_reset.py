from __future__ import annotations

import logging
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bugscrub.bug_engine.dataset import load_bug_dataset
from bugscrub.config import get_settings
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.intake.uploads import UPLOAD_SLOTS
from bugscrub.normalization.models import InventoryBatch


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    monkeypatch.setenv("BUGSCRUB_DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("BUGSCRUB_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BUGSCRUB_API_ENABLED", "false")
    get_settings.cache_clear()
    logger = logging.getLogger("bugscrub")
    original_handlers = list(logger.handlers)
    try:
        store = DuckDBStore(tmp_path / "test.duckdb")
        dataset = load_bug_dataset(PROJECT_ROOT / "tests/fixtures/bug_datasets/sample_bug_dataset.csv")
        store.save_bug_dataset(dataset)
        app = AppTest.from_file(str(PROJECT_ROOT / "streamlit_app.py"), default_timeout=30).run()
        assert not app.exception
        yield app, store, dataset.dataset_id
    finally:
        get_settings.cache_clear()
        for handler in list(logger.handlers):
            if handler not in original_handlers:
                logger.removeHandler(handler)
                handler.close()


def test_clear_removes_uploads_results_catalog_and_history(isolated_app, tmp_path):
    app, store, dataset_id = isolated_app
    uploaded_file = tmp_path / "runtime/uploads/previous-session/uploaded.txt"
    uploaded_file.parent.mkdir(parents=True)
    uploaded_file.write_text("Saved command output", encoding="utf-8")
    batch = InventoryBatch("previous-session", "nexus", "robust", str(tmp_path))
    store.save_inventory_batch(batch)
    original_upload_ids = {widget.proto.id for widget in app.get("file_uploader")}

    # Set stale processing state before pressing the button, so it must be cleared
    # before the dashboards and export functions are rendered again.
    for key in (
        "current_session_id", "upload_manifest", "upload_session_dir", "parsed_preview",
        "normalized_devices", "inventory_rows", "discrepancy_rows", "bug_findings",
        "inventory_workbook", "generated_inventory_path", "processing_metrics",
        "duckdb_devices", "duckdb_inventory_rows", "duckdb_discrepancy_rows",
        "duckdb_bug_findings", "duckdb_sessions", "risk_dashboard_data", "risk_dashboard_filters",
        "risk_hostname_filter", "session_warnings",
    ):
        app.session_state[key] = "stale"

    app.text_input[0].set_value("Unsubmitted dataset name")
    app.button(key="clear_analysis").click().run()

    assert not app.exception
    assert app.session_state["upload_generation"] == 1
    assert "current_session_id" not in app.session_state
    assert "risk_dashboard_data" not in app.session_state
    assert "generated_inventory_path" not in app.session_state
    assert app.text_input[0].value == ""
    assert original_upload_ids.isdisjoint(widget.proto.id for widget in app.get("file_uploader"))
    for key in ["bug_dataset_file_upload", *(slot.key for slot in UPLOAD_SLOTS)]:
        assert app.session_state[f"{key}_1"] is None
    assert any("The system has been cleared" in message.value for message in app.success)
    assert store.fetch_active_bug_dataset() is None
    assert store.fetch_bug_catalog() == []
    assert app.session_state["duckdb_bug_catalog"] == []
    assert any(message.value == "The bug catalog is empty." for message in app.info)
    assert not any("bug_id" in frame.value.columns for frame in app.dataframe)
    assert store.fetch_sessions() == []
    assert store.fetch_bug_datasets() == []
    assert store.fetch_bug_catalog(dataset_id) == []
    assert not uploaded_file.exists()

    # Reset can be repeated; previous datasets cannot be reactivated.
    app.button(key="clear_analysis").click().run()
    assert not app.exception
    assert app.session_state["upload_generation"] == 2
    assert not any(button.label == "Set active bug dataset" for button in app.button)
    assert [tab.label for tab in app.tabs] == ["Independent Bug Analysis", "Sample Files"]

    # A refresh and a new browser session must also show an empty catalog.
    for refreshed_app in (
        app.run(),
        AppTest.from_file(str(PROJECT_ROOT / "streamlit_app.py"), default_timeout=30).run(),
    ):
        assert not refreshed_app.exception
        assert refreshed_app.session_state["duckdb_bug_catalog"] == []
        assert any(message.value == "The bug catalog is empty." for message in refreshed_app.info)
        assert not any("bug_id" in frame.value.columns for frame in refreshed_app.dataframe)


def test_clear_failure_reports_incomplete_reset_and_discards_stale_results(isolated_app, monkeypatch):
    app, store, dataset_id = isolated_app
    original_upload_ids = {widget.proto.id for widget in app.get("file_uploader")}

    def fail_to_reset(self):
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(DuckDBStore, "reset_data", fail_to_reset)
    app.text_input[0].set_value("Keep this name")
    app.session_state["current_session_id"] = "stale-session"
    app.session_state["risk_dashboard_data"] = {"stale": True}
    app.button(key="clear_analysis").click().run()

    assert not app.exception
    assert any("Cleanup did not complete" in message.value for message in app.error)
    assert not any("The system has been cleared" in message.value for message in app.success)
    assert app.text_input[0].value == ""
    assert original_upload_ids.isdisjoint(widget.proto.id for widget in app.get("file_uploader"))
    assert "current_session_id" not in app.session_state
    assert "risk_dashboard_data" not in app.session_state
    assert store.fetch_active_bug_dataset()["dataset_id"] == dataset_id
