from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from bugscrub.exporters.executive import ExecutiveExporter


def test_executive_exporter_writes_pdf_with_expected_sections() -> None:
    workspace_dir = build_workspace_dir()
    export_path = workspace_dir / "executive.pdf"
    dashboard_data = {
        "metrics": {
            "devices_in_scope": 2,
            "bug_findings_in_scope": 3,
            "discrepancy_pairs_in_scope": 2,
            "affected_findings_in_scope": 2,
            "fixed_in_target_in_scope": 1,
            "top_risk_device": "leaf01",
        },
        "device_summary_rows": [
            {
                "hostname": "leaf01",
                "risk_score": 120,
                "bug_count": 2,
                "discrepancy_pairs": 1,
                "top_bug_id": "CSCvx10001",
            },
            {
                "hostname": "leaf02",
                "risk_score": 30,
                "bug_count": 1,
                "discrepancy_pairs": 1,
                "top_bug_id": "CSCvx10002",
            },
        ],
        "bug_summary_rows": [
            {
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "severity": "2",
                "affected_device_count": 1,
                "finding_count": 1,
                "total_score": 60,
                "affected_devices": ["leaf01"],
                "remediation_statuses": ["fixed_in_target"],
                "finding_type": "bug",
                "recommended_action": "Upgrade to fixed code.",
            }
        ],
        "pareto_rows": [
            {
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "total_risk_score": 120,
                "finding_type": "bug",
                "platform_family": "nexus",
                "finding_count": 1,
                "affected_devices": ["leaf01"],
                "remediation_status": "fixed_in_target",
                "recommended_actions": ["Upgrade to fixed code."],
                "total_score": 60,
                "cumulative_percentage": 100.0,
            }
        ],
        "pareto_quick_analysis_rows": [
            {
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "total_risk_score": 120,
                "finding_type": "bug",
                "platform_family": "nexus",
                "finding_count": 1,
                "affected_devices": ["leaf01"],
                "remediation_status": "fixed_in_target",
                "recommended_actions": ["Upgrade to fixed code."],
                "cumulative_percentage": 100.0,
            }
        ],
        "remediation_status_rows": [
            {"status": "affected", "finding_count": 2},
            {"status": "fixed_in_target", "finding_count": 1},
        ],
        "impacted_severity_rows": [
            {"severity_label": "S2", "severity_order": 2, "impacted_device_count": 1, "percentage": 50.0},
        ],
        "platform_stack_rows": [
            {
                "platform_family": "nexus",
                "severity_label": "S2",
                "severity_order": 2,
                "finding_count": 1,
                "platform_order": 1,
                "platform_total_findings": 1,
            }
        ],
        "bug_severity_stack_rows": [
            {
                "severity_label": "S2",
                "severity_order": 2,
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "affected_device_count": 1,
                "total_score": 60,
                "stack_order": 1,
            }
        ],
        "treemap_rows": [
            {
                "severity_label": "S2",
                "severity_order": 2,
                "bug_id": "CSCvx10001",
                "headline": "Bug A",
                "finding_type": "bug",
                "affected_device_count": 1,
                "total_score": 60,
                "x0": 0.0,
                "x1": 1.0,
                "y0": 0.0,
                "y1": 1.0,
            }
        ],
        "discrepancy_status_rows": [
            {"status": "discrepancia", "pair_count": 1},
            {"status": "faltante", "pair_count": 1},
        ],
        "narrative_lines": [
            "leaf01 is the highest-priority device based on combined risk score.",
        ],
    }
    filter_summary = {
        "platform_family": ["Nexus"],
        "hostnames": ["leaf01", "leaf02"],
        "severities": ["2", "3"],
        "features": ["VXLAN"],
        "bug_ids": ["CSCvx10001"],
        "finding_types": ["bug"],
        "pareto_threshold": 80,
    }

    try:
        exporter = ExecutiveExporter()
        pdf_bytes = exporter.export_pdf_to_bytes(
            session_id="session-001",
            platform_family="Nexus",
            dashboard_data=dashboard_data,
            filter_summary=filter_summary,
        )
        exporter.export_pdf(
            session_id="session-001",
            platform_family="Nexus",
            dashboard_data=dashboard_data,
            destination=export_path,
            filter_summary=filter_summary,
        )

        text = pdf_bytes.decode("latin-1")

        assert export_path.exists()
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert "BugScrub Executive Report" in text
        assert "Executive Summary" in text
        assert "Narrative" in text
        assert "Top Risks" in text
        assert "Bug Overview" in text
        assert "Remediation Overview" in text
        assert "Pareto Bug Impact Quick Analysis" in text
        assert "Charts Included" in text
        assert "Recommendations" in text
        assert "fixed_in_target" in text
        assert "leaf01" in text
        assert "session-001" in text
        assert "Bugs / CVEs / Notices: CSCvx10001" in text
        assert "Pareto threshold: 80%" in text
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_workspace_dir() -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"pdf-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir
