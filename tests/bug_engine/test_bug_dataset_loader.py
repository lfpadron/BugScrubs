from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from openpyxl import Workbook

from bugscrub.bug_engine.dataset import load_bug_dataset, validate_bug_dataset_file
from bugscrub.bug_engine.service import BugEngine
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.normalization.models import DeviceRecord, InventoryBatch


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "bug_datasets"


def test_load_bug_dataset_from_csv_normalizes_records() -> None:
    fixture_path = FIXTURE_ROOT / "sample_bug_dataset.csv"

    dataset = load_bug_dataset(fixture_path, dataset_name="Customer Catalog")

    assert validate_bug_dataset_file(fixture_path.name) == []
    assert dataset.dataset_name == "Customer Catalog"
    assert dataset.source_kind == "csv"
    assert dataset.selected_sheet == ""
    assert dataset.row_count == 2
    assert dataset.normalized_columns == [
        "bug_id",
        "headline",
        "product_scope",
        "affected_releases",
        "fixed_releases",
        "trigger_features",
        "severity",
        "recommended_action",
    ]
    assert dataset.bug_records[0]["bug_id"] == "CSCzz90001"
    assert dataset.bug_records[0]["product_scope"] == "nexus"
    assert dataset.bug_records[0]["affected_releases"] == ["9.3(9)", "9.3(8)"]
    assert dataset.bug_records[0]["trigger_features"] == ["VXLAN", "EVPN"]
    assert dataset.bug_records[1]["product_scope"] == "catalyst"
    assert dataset.bug_records[1]["severity"] == "4"


def test_load_bug_dataset_from_workbook_selects_bug_sheet() -> None:
    workspace_dir = build_workspace_dir("bug-workbook")
    workbook_path = workspace_dir / "custom_bug_catalog.xlsx"
    create_bug_workbook(workbook_path)

    try:
        dataset = load_bug_dataset(workbook_path)

        assert dataset.source_kind == "excel"
        assert dataset.selected_sheet == "Bug Catalog"
        assert dataset.row_count == 1
        assert dataset.bug_records[0]["bug_id"] == "CSCcustom70001"
        assert dataset.bug_records[0]["product_scope"] == "nexus"
        assert dataset.bug_records[0]["fixed_releases"] == ["10.2(7)"]
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def test_store_can_activate_bug_dataset_and_use_it_for_matching() -> None:
    workspace_dir = build_workspace_dir("bug-store")
    store = DuckDBStore(workspace_dir / "catalog.duckdb")

    try:
        default_catalog = store.fetch_bug_catalog()
        assert any(row["bug_id"] == "CSCvx10001" for row in default_catalog)

        dataset = load_bug_dataset(FIXTURE_ROOT / "sample_bug_dataset.csv", dataset_name="Loaded catalog")
        dataset_id = store.save_bug_dataset(dataset, activate=True)

        active_dataset = store.fetch_active_bug_dataset()
        stored_datasets = store.fetch_bug_datasets()
        active_catalog = store.fetch_bug_catalog()

        assert active_dataset is not None
        assert active_dataset["dataset_id"] == dataset_id
        assert active_dataset["dataset_name"] == "Loaded catalog"
        assert len(stored_datasets) == 1
        assert [row["bug_id"] for row in active_catalog] == ["CSCzz90001", "CSCzz93001"]

        batch = InventoryBatch(
            session_id="session-bugs",
            platform_family="nexus",
            support_level="robust",
            session_dir=str(workspace_dir),
            devices=[
                DeviceRecord(
                    session_id="session-bugs",
                    hostname="leaf01",
                    vendor="Cisco",
                    platform_family="nexus",
                    support_level="robust",
                    model="Nexus9000 C93180YC-FX",
                    pid="N9K-C93180YC-FX",
                    serial="FDO1234ABCD",
                    os_name="NX-OS",
                    os_version="9.3(9)",
                    features=["VXLAN", "EVPN"],
                )
            ],
        )

        findings = BugEngine(bug_records=active_catalog).run(batch)

        assert len(findings) == 1
        assert findings[0].bug_id == "CSCzz90001"
        assert findings[0].headline == "Custom Nexus VXLAN issue"
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_workspace_dir(prefix: str) -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"{prefix}-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def create_bug_workbook(destination: Path) -> None:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Notes", "Value"])
    summary.append(["Ignore", "This is not the bug sheet"])

    bug_sheet = workbook.create_sheet("Bug Catalog")
    bug_sheet.append(
        [
            "Cisco Bug ID",
            "Title",
            "Platform",
            "Affected Releases",
            "Fixed Releases",
            "Relevant Features",
            "Priority",
            "Recommendation",
        ]
    )
    bug_sheet.append(
        [
            "CSCcustom70001",
            "Workbook-only Nexus issue",
            "NX-OS",
            "10.2(6)",
            "10.2(7)",
            "BGP, EVPN",
            "High",
            "Upgrade when maintenance window is available.",
        ]
    )
    workbook.save(destination)
