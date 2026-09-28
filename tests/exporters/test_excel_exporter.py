from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from bugscrub.exporters.excel import ExcelExporter


def test_excel_exporter_writes_discrepancy_workbook() -> None:
    workspace_dir = build_workspace_dir()
    export_path = workspace_dir / "discrepancias.xlsx"
    discrepancy_rows = [
        {
            "pair_id": "session-001-pair-001",
            "row_source": "cliente",
            "discrepancy_status": "discrepancia",
            "discrepancy_summary": "Discrepancia en: os_version, features.",
            "hostname": "leaf01",
            "model": "Nexus9000 C93180YC-FX",
            "pid": "N9K-C93180YC-FX",
            "serial": "",
            "os_version": "9.3(8)",
            "target_version": "10.2(5)",
            "site": "DC1",
            "role": "leaf",
            "family": "nexus9000",
            "features": ["VXLAN"],
            "discrepancy_fields": ["os_version", "features"],
        },
        {
            "pair_id": "session-001-pair-001",
            "row_source": "descubierto",
            "discrepancy_status": "discrepancia",
            "discrepancy_summary": "Discrepancia en: os_version, features.",
            "hostname": "leaf01",
            "model": "Nexus9000 C93180YC-FX",
            "pid": "N9K-C93180YC-FX",
            "serial": "FDO1234ABCD",
            "os_version": "9.3(9)",
            "target_version": "",
            "site": "",
            "role": "",
            "family": "",
            "features": ["VXLAN", "EVPN"],
            "discrepancy_fields": ["os_version", "features"],
        },
    ]
    bug_findings = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "VXLAN EVPN control-plane instability on Nexus 9K",
            "severity": "2",
            "score": 60,
            "current_version": "9.3(9)",
            "target_version": "10.2(5)",
            "remediation_status": "fixed_in_target",
            "version_match_type": "exact",
            "matched_release": "9.3(9)",
            "matched_on": ["version", "features", "platform"],
            "fixed_releases": ["10.2(5)"],
            "recommended_action": "Upgrade to a fixed release before enabling additional EVPN scale.",
            "rationale": ["Affected release match: 9.3(9).", "Feature match: VXLAN, EVPN."],
        }
    ]

    try:
        exporter = ExcelExporter()
        exporter.export_discrepancies(discrepancy_rows, export_path, bug_findings=bug_findings)
        exported_rows = exporter.read_export_rows(export_path)
        finding_rows = exporter.read_export_rows(export_path, sheet_name="Bug Findings")
        export_bytes = exporter.export_discrepancies_to_bytes(discrepancy_rows, bug_findings=bug_findings)

        assert export_path.exists()
        assert len(export_bytes) > 0
        assert len(exported_rows) == 2
        assert exported_rows[0][0] == "session-001-pair-001"
        assert exported_rows[0][1] == "cliente"
        assert exported_rows[0][4] == "leaf01"
        assert exported_rows[0][7] is None
        assert exported_rows[1][1] == "descubierto"
        assert exported_rows[1][7] == "FDO1234ABCD"
        assert exported_rows[1][13] == "VXLAN, EVPN"
        assert exported_rows[1][14] == "os_version, features"
        assert len(finding_rows) == 1
        assert finding_rows[0][0] == "leaf01"
        assert finding_rows[0][2] == "CSCvx10001"
        assert finding_rows[0][6] == "9.3(9)"
        assert finding_rows[0][8] == "fixed_in_target"
        assert finding_rows[0][11] == "version, features, platform"
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def test_excel_exporter_writes_bug_findings_even_without_discrepancies() -> None:
    workspace_dir = build_workspace_dir()
    export_path = workspace_dir / "analysis.xlsx"
    bug_findings = [
        {
            "hostname": "N9K-LEAF-01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "VXLAN EVPN control-plane instability on Nexus 9K",
            "severity": "2",
            "score": 60,
            "current_version": "9.3(9)",
            "target_version": "",
            "remediation_status": "affected",
            "version_match_type": "exact",
            "matched_release": "9.3(9)",
            "matched_on": ["version", "features", "platform"],
            "fixed_releases": ["10.2(5)"],
            "recommended_action": "Upgrade to a fixed release before enabling additional EVPN scale.",
            "rationale": ["Affected release match: 9.3(9).", "Feature match: VXLAN, EVPN."],
        }
    ]

    try:
        exporter = ExcelExporter()
        exporter.export_discrepancies([], export_path, bug_findings=bug_findings)
        exported_rows = exporter.read_export_rows(export_path)
        finding_rows = exporter.read_export_rows(export_path, sheet_name="Bug Findings")

        assert export_path.exists()
        assert exported_rows == []
        assert len(finding_rows) == 1
        assert finding_rows[0][0] == "N9K-LEAF-01"
        assert finding_rows[0][2] == "CSCvx10001"
        assert finding_rows[0][8] == "affected"
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_workspace_dir() -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"export-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir
