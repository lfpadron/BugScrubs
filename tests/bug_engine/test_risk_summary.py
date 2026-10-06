from __future__ import annotations

from bugscrub.bug_engine.risk_summary import (
    available_dashboard_filters,
    build_inventory_overview_metrics,
    build_risk_dashboard_data,
)


def test_build_risk_dashboard_data_prioritizes_devices_and_bugs() -> None:
    devices = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "model": "N9K",
            "os_version": "9.3(9)",
            "features": ["VXLAN", "EVPN", "BGP"],
        },
        {
            "hostname": "leaf02",
            "platform_family": "nexus",
            "model": "N9K",
            "os_version": "9.3(8)",
            "features": ["QoS"],
        },
    ]
    inventory_rows = [
        {"hostname": "leaf01", "target_version": "10.2(5)"},
        {"hostname": "leaf02", "target_version": "10.2(5)"},
    ]
    discrepancy_rows = [
        {
            "pair_id": "session-pair-001",
            "row_source": "cliente",
            "discrepancy_status": "discrepancia",
            "hostname": "leaf01",
        },
        {
            "pair_id": "session-pair-001",
            "row_source": "descubierto",
            "discrepancy_status": "discrepancia",
            "hostname": "leaf01",
        },
        {
            "pair_id": "session-pair-002",
            "row_source": "cliente",
            "discrepancy_status": "faltante",
            "hostname": "leaf02",
        },
        {
            "pair_id": "session-pair-002",
            "row_source": "descubierto",
            "discrepancy_status": "faltante",
            "hostname": "",
        },
    ]
    bug_findings = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "Bug A",
            "severity": "2",
            "score": 60,
            "recommended_action": "Upgrade",
        },
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10002",
            "headline": "Bug B",
            "severity": "3",
            "score": 45,
            "recommended_action": "Review",
        },
        {
            "hostname": "leaf02",
            "platform_family": "nexus",
            "bug_id": "CSCvx10003",
            "headline": "Bug C",
            "severity": "4",
            "score": 20,
            "recommended_action": "Plan",
        },
    ]

    dashboard = build_risk_dashboard_data(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=discrepancy_rows,
        bug_findings=bug_findings,
        platform_family="All",
        platform_families=["nexus"],
        hostnames=["leaf01", "leaf02"],
        severities=["2", "3", "4"],
        features=[],
        models=[],
        versions=[],
        firmwares=[],
    )

    assert dashboard["metrics"]["devices_in_scope"] == 2
    assert dashboard["metrics"]["bug_findings_in_scope"] == 3
    assert dashboard["metrics"]["discrepancy_pairs_in_scope"] == 2
    assert dashboard["metrics"]["impacted_devices_in_scope"] == 2
    assert dashboard["metrics"]["top_risk_device"] == "leaf01"
    assert dashboard["device_summary_rows"][0]["hostname"] == "leaf01"
    assert dashboard["device_summary_rows"][0]["risk_score"] == 120
    assert dashboard["device_summary_rows"][1]["risk_score"] == 30
    assert dashboard["discrepancy_status_rows"] == [
        {"status": "discrepancy", "pair_count": 1},
        {"status": "missing", "pair_count": 1},
    ]
    assert dashboard["bug_summary_rows"][0]["bug_id"] == "CSCvx10001"
    assert dashboard["bug_severity_stack_rows"][0]["severity_label"] == "S2"
    assert dashboard["platform_stack_rows"][0]["platform_family"] == "nexus"
    assert dashboard["treemap_rows"][0]["bug_id"] == "CSCvx10001"
    assert dashboard["pareto_rows"][0]["bug_id"] == "CSCvx10001"


def test_build_risk_dashboard_data_applies_filters() -> None:
    devices = [
        {
            "hostname": "dist-sw01",
            "platform_family": "catalyst",
            "model": "C9300-48P",
            "os_version": "17.9.4a",
            "features": ["STP", "EtherChannel", "QoS"],
        },
        {
            "hostname": "dist-sw02",
            "platform_family": "catalyst",
            "model": "C9300-48P",
            "os_version": "17.9.4a",
            "features": ["VLAN"],
        },
    ]
    inventory_rows = [
        {"hostname": "dist-sw01", "target_version": "17.12.1"},
        {"hostname": "dist-sw02", "target_version": "17.12.1"},
    ]
    bug_findings = [
        {
            "hostname": "dist-sw01",
            "platform_family": "catalyst",
            "bug_id": "CSCwa20001",
            "headline": "Bug D",
            "severity": "2",
            "score": 60,
            "recommended_action": "Upgrade",
        },
        {
            "hostname": "dist-sw02",
            "platform_family": "catalyst",
            "bug_id": "CSCwa20002",
            "headline": "Bug E",
            "severity": "4",
            "score": 25,
            "recommended_action": "Review",
        },
    ]

    filters = available_dashboard_filters(devices=devices, inventory_rows=inventory_rows, bug_findings=bug_findings)
    assert filters["platform_families"] == ["catalyst"]
    assert filters["hostnames"] == ["dist-sw01", "dist-sw02"]
    assert filters["models"] == ["C9300-48P"]
    assert filters["severities"] == ["2", "4"]
    assert filters["versions"] == ["17.9.4a"]
    assert filters["firmwares"] == ["17.12.1"]
    assert filters["bug_ids"] == ["CSCwa20001", "CSCwa20002"]
    assert "EtherChannel" in filters["features"]
    assert filters["finding_types"] == ["bug"]

    dashboard = build_risk_dashboard_data(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=[],
        bug_findings=bug_findings,
        platform_family="catalyst",
        platform_families=["catalyst"],
        hostnames=["dist-sw01", "dist-sw02"],
        severities=["2"],
        features=["EtherChannel"],
        models=["C9300-48P"],
        versions=["17.9.4a"],
        firmwares=["17.12.1"],
        bug_ids=["CSCwa20001"],
        finding_types=["bug"],
    )

    assert dashboard["metrics"]["devices_in_scope"] == 1
    assert dashboard["metrics"]["bug_findings_in_scope"] == 1
    assert dashboard["device_summary_rows"][0]["hostname"] == "dist-sw01"
    assert dashboard["bug_summary_rows"][0]["bug_id"] == "CSCwa20001"


def test_build_risk_dashboard_data_tracks_remediation_status_counts() -> None:
    devices = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "model": "N9K",
            "os_version": "9.3(9)",
            "features": ["VXLAN"],
        }
    ]
    inventory_rows = [{"hostname": "leaf01", "target_version": "10.2(5)"}]
    bug_findings = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "Bug A",
            "severity": "2",
            "score": 60,
            "remediation_status": "affected",
            "recommended_action": "Upgrade",
        },
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10002",
            "headline": "Bug B",
            "severity": "3",
            "score": 40,
            "remediation_status": "fixed_in_target",
            "recommended_action": "Upgrade",
        },
    ]

    dashboard = build_risk_dashboard_data(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=[],
        bug_findings=bug_findings,
        platform_family="All",
        platform_families=["nexus"],
        hostnames=["leaf01"],
        severities=["2", "3"],
        features=[],
        models=[],
        versions=[],
        firmwares=["10.2(5)"],
    )

    assert dashboard["metrics"]["affected_findings_in_scope"] == 1
    assert dashboard["metrics"]["fixed_in_target_in_scope"] == 1
    assert dashboard["device_summary_rows"][0]["risk_score"] == 80
    assert dashboard["remediation_status_rows"] == [
        {"status": "affected", "finding_count": 1},
        {"status": "fixed_in_target", "finding_count": 1},
    ]
    assert dashboard["pareto_rows"][0]["finding_count"] == 1


def test_build_risk_dashboard_data_builds_thresholded_pareto_quick_analysis() -> None:
    devices = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "model": "N9K-A",
            "os_version": "9.3(9)",
            "features": ["VXLAN"],
        },
        {
            "hostname": "leaf02",
            "platform_family": "nexus",
            "model": "N9K-B",
            "os_version": "9.3(8)",
            "features": ["EVPN"],
        },
        {
            "hostname": "leaf03",
            "platform_family": "nexus",
            "model": "N9K-C",
            "os_version": "9.3(7)",
            "features": ["BGP"],
        },
    ]
    inventory_rows = [
        {"hostname": "leaf01", "target_version": "10.2(5)"},
        {"hostname": "leaf02", "target_version": "10.2(5)"},
        {"hostname": "leaf03", "target_version": "10.2(5)"},
    ]
    bug_findings = [
        {
            "hostname": "leaf01",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "Bug A",
            "severity": "1",
            "score": 60,
            "remediation_status": "affected",
            "recommended_action": "Upgrade",
        },
        {
            "hostname": "leaf02",
            "platform_family": "nexus",
            "bug_id": "CSCvx10001",
            "headline": "Bug A",
            "severity": "1",
            "score": 55,
            "remediation_status": "affected",
            "recommended_action": "Upgrade",
        },
        {
            "hostname": "leaf03",
            "platform_family": "nexus",
            "bug_id": "CSCvx10002",
            "headline": "Bug B",
            "severity": "4",
            "score": 20,
            "remediation_status": "needs_review",
            "recommended_action": "Review",
        },
    ]

    dashboard = build_risk_dashboard_data(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=[],
        bug_findings=bug_findings,
        platform_family="All",
        platform_families=["nexus"],
        hostnames=["leaf01", "leaf02", "leaf03"],
        severities=["1", "4"],
        features=[],
        models=[],
        versions=[],
        firmwares=["10.2(5)"],
        pareto_cumulative_threshold=80,
    )

    assert dashboard["metrics"]["pareto_cumulative_threshold"] == 80
    assert len(dashboard["pareto_all_rows"]) == 2
    assert dashboard["pareto_all_rows"][0]["bug_id"] == "CSCvx10001"
    assert dashboard["pareto_all_rows"][0]["total_risk_score"] == 115
    assert dashboard["pareto_all_rows"][0]["affected_devices"] == ["leaf01", "leaf02"]
    assert dashboard["pareto_quick_analysis_rows"][0]["bug_id"] == "CSCvx10001"
    assert len(dashboard["pareto_quick_analysis_rows"]) == 1
    assert dashboard["pareto_quick_analysis_rows"][0]["cumulative_percentage"] >= 80.0


def test_build_inventory_overview_metrics_uses_customer_inventory_flag() -> None:
    devices = [
        {"hostname": "leaf01"},
        {"hostname": "leaf02"},
    ]
    inventory_rows = [
        {"hostname": "leaf01"},
        {"hostname": "leaf02"},
        {"hostname": "leaf03"},
    ]
    discrepancy_rows = [
        {"pair_id": "pair-001", "hostname": "leaf03", "discrepancy_status": "faltante"},
        {"pair_id": "pair-001", "hostname": "", "discrepancy_status": "faltante"},
    ]
    bug_findings = [
        {"hostname": "leaf01", "bug_id": "CSCvx10001"},
        {"hostname": "leaf02", "bug_id": "CSCvx10001"},
        {"hostname": "leaf02", "bug_id": "CSCvx10002"},
    ]

    uploaded_metrics = build_inventory_overview_metrics(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=discrepancy_rows,
        bug_findings=bug_findings,
        customer_inventory_uploaded=True,
    )
    generated_metrics = build_inventory_overview_metrics(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=discrepancy_rows,
        bug_findings=bug_findings,
        customer_inventory_uploaded=False,
    )

    assert uploaded_metrics["devices_in_inventory"] == 3
    assert uploaded_metrics["inconsistency_count"] == 1
    assert uploaded_metrics["inconsistency_percentage"] == 33.33
    assert uploaded_metrics["devices_with_bugs_count"] == 2
    assert uploaded_metrics["total_bugs_found"] == 2
    assert generated_metrics["devices_in_inventory"] is None
    assert generated_metrics["inconsistency_count"] is None
