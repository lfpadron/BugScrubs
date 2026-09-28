from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from openpyxl import Workbook

from bugscrub.normalization.service import generate_inventory_workbook_from_parsed_records, parse_inventory_workbook


def test_parse_inventory_workbook_normalizes_key_columns() -> None:
    workspace_dir = build_workspace_dir()
    workbook_path = workspace_dir / "inventory.xlsx"
    create_workbook(workbook_path)

    try:
        workbook, rows, warnings = parse_inventory_workbook(workbook_path, session_id="session-123")

        assert warnings == []
        assert workbook.file_name == "inventory.xlsx"
        assert workbook.selected_sheet == "Inventory_Input"
        assert workbook.parsed_row_count == 2
        assert workbook.normalized_columns == [
            "hostname",
            "pid",
            "os_version",
            "target_version",
            "site",
            "role",
            "features",
            "business_criticality",
        ]
        assert len(rows) == 2
        assert rows[0].session_id == "session-123"
        assert rows[0].hostname == "leaf01"
        assert rows[0].pid == "N9K-C93180YC-FX"
        assert rows[0].os_version == "9.3(9)"
        assert rows[0].target_version == "10.2(5)"
        assert rows[0].site == "DC1"
        assert rows[0].role == "leaf"
        assert rows[0].features == ["VXLAN", "EVPN"]
        assert rows[0].business_criticality == 1
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def test_generate_inventory_workbook_from_parsed_records_creates_template_with_rows() -> None:
    workspace_dir = build_workspace_dir()
    workbook_path = workspace_dir / "generated_inventory.xlsx"

    try:
        generate_inventory_workbook_from_parsed_records(
            parsed_records=[
                {
                    "device_name": "leaf01",
                    "model": "Nexus9000 C93180YC-FX",
                    "pid": "N9K-C93180YC-FX",
                    "serial": "FDO1234ABCD",
                    "nxos_version": "9.3(9)",
                    "features": ["VXLAN", "EVPN"],
                }
            ],
            destination=workbook_path,
            platform_family="nexus",
        )
        workbook, rows, warnings = parse_inventory_workbook(workbook_path, session_id="session-generated")

        assert warnings == []
        assert workbook.file_name == "generated_inventory.xlsx"
        assert workbook.selected_sheet == "Inventory_Input"
        assert workbook.sheet_count == 2
        assert workbook.parsed_row_count == 1
        assert rows[0].hostname == "leaf01"
        assert rows[0].model == "Nexus9000 C93180YC-FX"
        assert rows[0].pid == "N9K-C93180YC-FX"
        assert rows[0].serial == "FDO1234ABCD"
        assert rows[0].os_version == "9.3(9)"
        assert rows[0].family == "nexus9000"
        assert rows[0].features == ["VXLAN", "EVPN"]
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_workspace_dir() -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"inventory-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def create_workbook(destination: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inventory_Input"
    sheet.append(
        [
            "Host Name",
            "Unmapped Column",
            "Platform PID",
            "Current Version",
            "Target Version",
            "Location",
            "Device Role",
            "Enabled Features",
            "Criticality",
        ]
    )
    sheet.append(["leaf01", "ignore", "N9K-C93180YC-FX", "9.3(9)", "10.2(5)", "DC1", "leaf", "VXLAN, EVPN", 1])
    sheet.append(["leaf02", "ignore", "N9K-C93180YC-FX", "9.3(8)", "10.2(5)", "DC2", "spine", "BGP / OSPF", 2])
    workbook.save(destination)
