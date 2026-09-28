from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4
from zipfile import ZipFile

from pptx import Presentation

from bugscrub.exporters.powerpoint import PowerPointExporter


def test_powerpoint_exporter_writes_pptx_with_all_dashboard_chart_slides() -> None:
    workspace_dir = build_workspace_dir()
    export_path = workspace_dir / "executive.pptx"
    dashboard_data = {
        "metrics": {
            "devices_in_scope": 2,
            "bug_findings_in_scope": 3,
            "discrepancy_pairs_in_scope": 2,
            "affected_findings_in_scope": 2,
            "fixed_in_target_in_scope": 1,
            "top_risk_device": "leaf01",
        },
        "narrative_lines": [
            "leaf01 is the highest-priority device based on combined risk score.",
        ],
        "pareto_quick_analysis_rows": [
            {
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "total_risk_score": 120,
                "finding_type": "bug",
                "platform_family": "nexus",
                "finding_count": 2,
                "affected_devices": ["leaf01", "leaf02"],
                "remediation_status": "affected",
                "recommended_actions": ["Upgrade"],
                "cumulative_percentage": 100.0,
            }
        ],
        "bug_severity_stack_rows": [
            {
                "severity_label": "S2",
                "severity_order": 2,
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "affected_device_count": 2,
                "total_score": 80,
                "stack_order": 1,
            }
        ],
        "platform_stack_rows": [
            {
                "platform_family": "nexus",
                "severity_label": "S2",
                "severity_order": 2,
                "finding_count": 2,
                "platform_order": 1,
                "platform_total_findings": 2,
            }
        ],
        "treemap_rows": [
            {
                "severity_label": "S2",
                "severity_order": 2,
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "finding_type": "bug",
                "affected_device_count": 2,
                "total_score": 80,
                "x0": 0.0,
                "x1": 1.0,
                "y0": 0.0,
                "y1": 1.0,
            }
        ],
        "pareto_rows": [
            {
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "finding_count": 2,
                "total_score": 80,
                "cumulative_percentage": 66.7,
            },
            {
                "bug_id": "CSCvx10002",
                "headline": "Bug B",
                "finding_count": 1,
                "total_score": 20,
                "cumulative_percentage": 100.0,
            },
        ],
    }
    filter_summary = {
        "platform_family": ["Nexus"],
        "hostnames": ["leaf01", "leaf02"],
        "severities": ["2", "3"],
        "features": ["VXLAN"],
        "models": ["N9K-C93180YC-FX"],
        "versions": ["9.3(9)"],
        "firmwares": ["10.2(5)"],
        "bug_ids": ["CSCvx10001"],
        "finding_types": ["bug"],
        "pareto_threshold": 80,
    }

    try:
        exporter = PowerPointExporter()
        pptx_bytes = exporter.export_pptx_to_bytes(
            session_id="session-001",
            platform_family="Nexus",
            dashboard_data=dashboard_data,
            filter_summary=filter_summary,
        )
        exporter.export_pptx(
            session_id="session-001",
            platform_family="Nexus",
            dashboard_data=dashboard_data,
            destination=export_path,
            filter_summary=filter_summary,
        )

        assert export_path.exists()
        assert len(pptx_bytes) > 0
        presentation = Presentation(export_path)
        with ZipFile(export_path) as archive:
            names = set(archive.namelist())
            slide_1_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            slide_5_xml = archive.read("ppt/slides/slide5.xml").decode("utf-8")

        assert len(presentation.slides) == 5
        assert "[Content_Types].xml" in names
        assert "ppt/slides/slide1.xml" in names
        assert "ppt/slides/slide5.xml" in names
        assert any(name.startswith("ppt/media/image") for name in names)
        assert "BugScrub Executive Report" in slide_1_xml
        assert "session-001" in slide_1_xml
        assert "Platform scope: Nexus" in slide_1_xml
        assert "Versions: 9.3(9)" in slide_1_xml
        assert "Firmware: 10.2(5)" in slide_1_xml
        assert "Bugs / CVEs / Notices: CSCvx10001" in slide_1_xml
        assert "Pareto threshold: 80%" in slide_1_xml
        assert "Pareto of Bug Remediation Impact" in slide_5_xml
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_workspace_dir() -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"pptx-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir
