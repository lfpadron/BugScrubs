from __future__ import annotations

from bugscrub.bug_engine.service import BugEngine
from bugscrub.normalization.models import DeviceRecord, InventoryBatch, InventoryRowRecord


def test_bug_engine_matches_internal_dataset_by_version_and_features() -> None:
    batch = InventoryBatch(
        session_id="session-001",
        platform_family="nexus",
        support_level="robust",
        session_dir="storage/runtime/session-001",
        devices=[
            DeviceRecord(
                session_id="session-001",
                hostname="leaf01",
                vendor="Cisco",
                platform_family="nexus",
                support_level="robust",
                model="Nexus9000 C93180YC-FX",
                pid="N9K-C93180YC-FX",
                serial="FDO1234ABCD",
                os_name="NX-OS",
                os_version="9.3(9)",
                features=["VXLAN", "EVPN", "BGP", "QoS"],
            )
        ],
    )

    findings = BugEngine().run(batch)

    assert len(findings) == 2
    assert findings[0].hostname == "leaf01"
    assert findings[0].bug_id == "CSCvx10001"
    assert "version" in findings[0].matched_on
    assert "features" in findings[0].matched_on
    assert findings[0].score > findings[1].score


def test_bug_engine_skips_devices_without_affected_version_match() -> None:
    batch = InventoryBatch(
        session_id="session-002",
        platform_family="catalyst",
        support_level="basic",
        session_dir="storage/runtime/session-002",
        devices=[
            DeviceRecord(
                session_id="session-002",
                hostname="dist-sw01",
                vendor="Cisco",
                platform_family="catalyst",
                support_level="basic",
                model="C9300-48P",
                pid="C9300-48P",
                serial="FCW2145L0AB",
                os_name="IOS XE",
                os_version="17.6.1",
                features=["QoS"],
            )
        ],
    )

    findings = BugEngine().run(batch)

    assert findings == []


def test_bug_engine_marks_fixed_in_target_for_range_match_and_target_release() -> None:
    batch = InventoryBatch(
        session_id="session-003",
        platform_family="nexus",
        support_level="robust",
        session_dir="storage/runtime/session-003",
        inventory_rows=[
            InventoryRowRecord(
                session_id="session-003",
                sheet_name="Inventory",
                row_number=2,
                hostname="leaf01",
                pid="N9K-C93180YC-FX",
                target_version="10.2(5)",
                features=["VXLAN", "EVPN"],
            )
        ],
        devices=[
            DeviceRecord(
                session_id="session-003",
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
    bug_records = [
        {
            "bug_id": "CSCcustom90001",
            "headline": "Range-based Nexus issue",
            "product_scope": "nexus",
            "affected_releases": ["9.3(8)-9.3(9)"],
            "fixed_releases": ["10.2(5)"],
            "trigger_features": ["VXLAN"],
            "platform_pids": ["N9K-C93180YC-*"],
            "required_features": ["EVPN"],
            "optional_features": ["QoS"],
            "severity": "2",
            "recommended_action": "Upgrade to target release.",
        }
    ]

    findings = BugEngine(bug_records=bug_records).run(batch)

    assert len(findings) == 1
    assert findings[0].bug_id == "CSCcustom90001"
    assert findings[0].remediation_status == "fixed_in_target"
    assert findings[0].version_match_type == "range"
    assert findings[0].matched_release == "9.3(8)-9.3(9)"
    assert findings[0].target_version == "10.2(5)"
    assert "pid" in findings[0].matched_on
    assert "required_features" in findings[0].matched_on
    assert "target_version" in findings[0].matched_on


def test_bug_engine_marks_already_fixed_and_skips_missing_required_features() -> None:
    batch = InventoryBatch(
        session_id="session-004",
        platform_family="catalyst",
        support_level="basic",
        session_dir="storage/runtime/session-004",
        devices=[
            DeviceRecord(
                session_id="session-004",
                hostname="dist-sw01",
                vendor="Cisco",
                platform_family="catalyst",
                support_level="basic",
                model="C9300-48P",
                pid="C9300-48P",
                serial="FCW2145L0AB",
                os_name="IOS XE",
                os_version="17.12.1",
                features=["QoS"],
            )
        ],
    )
    bug_records = [
        {
            "bug_id": "CSCcustom93001",
            "headline": "Catalyst bug already fixed",
            "product_scope": "catalyst",
            "affected_releases": ["17.9.3-17.9.5"],
            "fixed_releases": ["17.12.1"],
            "trigger_features": [],
            "required_features": ["QoS"],
            "optional_features": [],
            "severity": "3",
            "recommended_action": "No action if already fixed.",
        },
        {
            "bug_id": "CSCcustom93002",
            "headline": "Catalyst bug needing HSRP",
            "product_scope": "catalyst",
            "affected_releases": ["17.12.1"],
            "fixed_releases": ["17.12.2"],
            "trigger_features": [],
            "required_features": ["HSRP"],
            "optional_features": [],
            "severity": "2",
            "recommended_action": "Only relevant with HSRP.",
        },
    ]

    findings = BugEngine(bug_records=bug_records).run(batch)

    assert len(findings) == 1
    assert findings[0].bug_id == "CSCcustom93001"
    assert findings[0].remediation_status == "already_fixed"
    assert findings[0].version_match_type == "exact"
    assert "required_features" in findings[0].matched_on
    assert "fixed_release" in findings[0].matched_on
