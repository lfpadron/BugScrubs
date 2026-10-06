from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from bugscrub.bug_engine.dataset import load_bug_dataset
from bugscrub.bug_engine.service import BugEngine
from bugscrub.config import Settings
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.discrepancies.service import compare_inventory_vs_parsed
from bugscrub.normalization.models import InventoryBatch
from bugscrub.normalization.service import Normalizer
from bugscrub.observability import build_log_path, configure_structured_logging, get_logger
from bugscrub.parsers.service import parse_runtime_session
from bugscrub.reset import reset_application_data
from bugscrub.ui.sample_files import SAMPLE_FILES_DIR
from tests.pipeline.test_session_pipeline import build_runtime_session


DATASET_FIXTURE = Path(__file__).parent / "fixtures/bug_datasets/sample_bug_dataset.csv"


@pytest.fixture
def reset_environment(tmp_path):
    settings = Settings(
        duckdb_path=tmp_path / "app.duckdb", runtime_root=tmp_path / "runtime",
        api_enabled=False, policy_path=tmp_path / "secrets/policy.yaml",
        log_level="INFO", cisco_client_id="", cisco_client_secret="",
    )
    logger = get_logger()
    original_handlers = list(logger.handlers)
    try:
        yield settings, DuckDBStore(settings.duckdb_path)
    finally:
        for handler in list(logger.handlers):
            if handler not in original_handlers:
                logger.removeHandler(handler)
                handler.close()


def test_full_reset_removes_all_customer_data_and_is_ready_for_new_uploads(reset_environment, tmp_path):
    settings, store = reset_environment
    saved_dataset = settings.runtime_root / "bug-datasets/client/catalog.csv"
    saved_dataset.parent.mkdir(parents=True)
    shutil.copyfile(DATASET_FIXTURE, saved_dataset)
    active_dataset = load_bug_dataset(saved_dataset)
    inactive_dataset = load_bug_dataset(saved_dataset)
    store.save_bug_dataset(active_dataset)
    store.save_bug_dataset(inactive_dataset, activate=False)

    session_dir = build_runtime_session(settings.runtime_root / "uploads", fixture_family="nexus")
    parsed = parse_runtime_session("Nexus", session_dir)
    batch = Normalizer().normalize_parsed_devices(
        parsed_records=parsed.parsed_records, platform_family=parsed.platform_family,
        support_level=parsed.support_level, session_dir=session_dir,
        inventory_path=session_dir / "inventory.xlsx", source_count=5, warnings=parsed.warnings,
    )
    batch.discrepancy_rows = compare_inventory_vs_parsed(
        session_id=batch.session_id, inventory_rows=batch.inventory_rows, parsed_devices=batch.devices,
    )
    batch.bug_findings = [finding.to_record() for finding in BugEngine(bug_records=store.fetch_bug_catalog()).run(batch)]
    store.save_inventory_batch(batch)
    store.save_inventory_batch(InventoryBatch("older-session", "nexus", "robust", str(session_dir)))
    assert len(store.fetch_sessions()) == 2
    assert store.fetch_devices_for_session(batch.session_id)
    assert store.fetch_inventory_rows_for_session(batch.session_id)
    assert store.fetch_discrepancy_rows_for_session(batch.session_id)
    assert store.fetch_bug_findings_for_session(batch.session_id)

    export = settings.runtime_root / "exports/older-session/report.pdf"
    export.parent.mkdir(parents=True)
    export.write_bytes(b"customer report")
    configure_structured_logging(settings.runtime_root)
    get_logger().info("old-client-log")
    rotated_log = settings.runtime_root / "logs/bugscrub.jsonl.1"
    rotated_log.write_text("old-client-log", encoding="utf-8")
    settings.policy_path.parent.mkdir()
    settings.policy_path.write_text("keep policy", encoding="utf-8")
    config = tmp_path / ".env.droplet"
    config.write_text("keep deployment settings", encoding="utf-8")
    samples = {path: path.read_bytes() for path in SAMPLE_FILES_DIR.iterdir()}

    reset_application_data(settings, store)

    with store.connect() as connection:
        for table in ("bug_catalog", "bug_dataset_entries", "bug_datasets"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert store.fetch_sessions() == []
    assert store.fetch_bug_datasets() == []
    assert store.fetch_active_bug_dataset() is None
    assert store.fetch_devices_for_session(batch.session_id) == []
    assert store.fetch_inventory_rows_for_session(batch.session_id) == []
    assert store.fetch_discrepancy_rows_for_session(batch.session_id) == []
    assert store.fetch_bug_findings_for_session(batch.session_id) == []
    assert store.fetch_bug_catalog(active_dataset.dataset_id) == []
    assert store.fetch_bug_catalog(inactive_dataset.dataset_id) == []
    assert store.fetch_bug_catalog() == []
    assert BugEngine(bug_records=store.fetch_bug_catalog()).run(batch) == []
    # Reopening the database and saving a new session must not restore demo bugs.
    reopened_store = DuckDBStore(settings.duckdb_path)
    assert reopened_store.fetch_bug_catalog() == []
    reopened_store.save_inventory_batch(InventoryBatch("new-session", "nexus", "robust", str(tmp_path)))
    assert reopened_store.fetch_bug_catalog() == []
    for directory in ("uploads", "bug-datasets", "exports"):
        assert not (settings.runtime_root / directory).exists()
    assert not rotated_log.exists()
    assert "old-client-log" not in build_log_path(settings.runtime_root).read_text(encoding="utf-8")
    assert settings.policy_path.read_text(encoding="utf-8") == "keep policy"
    assert config.read_text(encoding="utf-8") == "keep deployment settings"
    assert all(path.read_bytes() == data for path, data in samples.items())
    get_logger().info("new-client-log")
    assert "new-client-log" in build_log_path(settings.runtime_root).read_text(encoding="utf-8")

    reset_application_data(settings, store)
    saved_dataset.parent.mkdir(parents=True)
    shutil.copyfile(DATASET_FIXTURE, saved_dataset)
    new_dataset = load_bug_dataset(saved_dataset)
    store.save_bug_dataset(new_dataset)
    assert store.fetch_active_bug_dataset()["dataset_id"] == new_dataset.dataset_id
    assert {bug["bug_id"] for bug in store.fetch_bug_catalog()} == {
        bug["bug_id"] for bug in new_dataset.bug_records
    }


def test_reset_database_failure_rolls_back_before_removing_files(reset_environment, monkeypatch):
    settings, store = reset_environment
    dataset = load_bug_dataset(DATASET_FIXTURE)
    store.save_bug_dataset(dataset)
    uploaded = settings.runtime_root / "uploads/client/show_version.txt"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_text("customer input", encoding="utf-8")
    original_catalog = store.fetch_bug_catalog()

    original_connect = store.connect

    class FailingConnection:
        def __init__(self):
            self.connection = original_connect()

        def execute(self, query, *args):
            result = self.connection.execute(query, *args)
            if query == "DELETE FROM bug_catalog":
                raise RuntimeError("Simulated catalog failure")
            return result

        def close(self):
            self.connection.close()

    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", FailingConnection)
        with pytest.raises(RuntimeError, match="Simulated catalog failure"):
            reset_application_data(settings, store)
    assert store.fetch_active_bug_dataset()["dataset_id"] == dataset.dataset_id
    assert store.fetch_bug_catalog() == original_catalog
    assert uploaded.read_text(encoding="utf-8") == "customer input"


def test_reset_refuses_redirected_directory_without_touching_data(reset_environment, tmp_path):
    settings, store = reset_environment
    dataset = load_bug_dataset(DATASET_FIXTURE)
    store.save_bug_dataset(dataset)
    outside = tmp_path / "unrelated-files"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    settings.runtime_root.mkdir()
    redirected = settings.runtime_root / "uploads"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(redirected), str(outside)],
            capture_output=True, text=True,
        )
        if result.returncode:
            pytest.skip("Directory junctions unavailable in this environment")
    else:
        redirected.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="redirected"):
        reset_application_data(settings, store)
    assert store.fetch_active_bug_dataset()["dataset_id"] == dataset.dataset_id
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_failed_file_cleanup_is_reported_and_can_be_retried(reset_environment, monkeypatch):
    settings, store = reset_environment
    report = settings.runtime_root / "exports/session/report.pdf"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"customer report")
    real_rmtree = shutil.rmtree

    def deny_export_removal(path):
        if path.name == "exports":
            raise PermissionError("Simulated locked export")
        real_rmtree(path)

    with monkeypatch.context() as patch:
        patch.setattr("bugscrub.reset.shutil.rmtree", deny_export_removal)
        with pytest.raises(PermissionError, match="locked export"):
            reset_application_data(settings, store)
        assert report.exists()
    reset_application_data(settings, store)
    assert not report.exists()
