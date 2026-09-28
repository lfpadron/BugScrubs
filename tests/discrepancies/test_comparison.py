from __future__ import annotations

from bugscrub.discrepancies.service import compare_inventory_vs_parsed
from bugscrub.normalization.models import DeviceRecord, InventoryRowRecord


def test_compare_inventory_vs_parsed_creates_new_missing_and_discrepancy_pairs() -> None:
    inventory_rows = [
        InventoryRowRecord(
            session_id="session-001",
            sheet_name="Inventory_Input",
            row_number=2,
            hostname="leaf01.dc1.example.com",
            pid="N9K-C93180YC-FX",
            serial="FDO1234ABCD",
            os_version="9.3(8)",
            features=["VXLAN"],
        ),
        InventoryRowRecord(
            session_id="session-001",
            sheet_name="Inventory_Input",
            row_number=3,
            hostname="leaf02",
            pid="N9K-C93180YC-FX",
            os_version="9.3(8)",
        ),
    ]
    parsed_devices = [
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
            features=["VXLAN", "EVPN"],
        ),
        DeviceRecord(
            session_id="session-001",
            hostname="leaf03",
            vendor="Cisco",
            platform_family="nexus",
            support_level="robust",
            model="Nexus9000 C93180YC-FX",
            pid="N9K-C93180YC-FX",
            serial="FDO9999ABCD",
            os_name="NX-OS",
            os_version="9.3(9)",
            features=["BGP"],
        ),
    ]

    discrepancy_rows = compare_inventory_vs_parsed(
        session_id="session-001",
        inventory_rows=inventory_rows,
        parsed_devices=parsed_devices,
    )

    assert len(discrepancy_rows) == 6
    discovered_statuses = [row.discrepancy_status for row in discrepancy_rows if row.row_source == "descubierto"]
    assert discovered_statuses == ["discrepancia", "faltante", "nuevo"]
    assert discrepancy_rows[0].row_source == "cliente"
    assert discrepancy_rows[1].row_source == "descubierto"
    assert discrepancy_rows[0].match_key == "serial:fdo1234abcd"
    assert discrepancy_rows[0].discrepancy_fields == ["os_version", "features"]
    assert discrepancy_rows[3].discrepancy_status == "faltante"
    assert discrepancy_rows[5].hostname == "leaf03"


def test_compare_inventory_vs_parsed_matches_rows_by_serial_even_when_hostname_is_missing() -> None:
    inventory_rows = [
        InventoryRowRecord(
            session_id="session-002",
            sheet_name="Inventory_Input",
            row_number=2,
            hostname="",
            model="C9300-48P",
            serial="FCW2145L0AB",
            os_version="17.9.4a",
            features=["QoS"],
        )
    ]
    parsed_devices = [
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
            os_version="17.9.4a",
            features=["QoS"],
        )
    ]

    discrepancy_rows = compare_inventory_vs_parsed(
        session_id="session-002",
        inventory_rows=inventory_rows,
        parsed_devices=parsed_devices,
    )

    assert len(discrepancy_rows) == 2
    assert discrepancy_rows[0].discrepancy_status == "discrepancia"
    assert discrepancy_rows[0].match_key == "serial:fcw2145l0ab"
    assert discrepancy_rows[0].discrepancy_fields == ["hostname"]
    assert discrepancy_rows[1].hostname == "dist-sw01"


def test_compare_inventory_vs_parsed_uses_platform_heuristics_for_multi_device_matching() -> None:
    inventory_rows = [
        InventoryRowRecord(
            session_id="session-003",
            sheet_name="Inventory_Input",
            row_number=2,
            hostname="leaf01",
            pid="N9K-C93180YC-FX",
            model="",
            serial="",
            os_version="9.3(9)",
            features=["VXLAN"],
            family="nexus",
        ),
        InventoryRowRecord(
            session_id="session-003",
            sheet_name="Inventory_Input",
            row_number=3,
            hostname="leaf02",
            pid="N9K-C93180YC-FX",
            model="",
            serial="",
            os_version="9.3(9)",
            features=["EVPN"],
            family="nexus",
        ),
    ]
    parsed_devices = [
        DeviceRecord(
            session_id="session-003",
            hostname="leaf02.corp.local",
            vendor="Cisco",
            platform_family="nexus",
            support_level="robust",
            model="Nexus9000 C93180YC-FX",
            pid="N9K-C93180YC-FX",
            serial="",
            os_name="NX-OS",
            os_version="9.3(9)",
            features=["EVPN"],
        ),
        DeviceRecord(
            session_id="session-003",
            hostname="leaf01.corp.local",
            vendor="Cisco",
            platform_family="nexus",
            support_level="robust",
            model="Nexus9000 C93180YC-FX",
            pid="N9K-C93180YC-FX",
            serial="",
            os_name="NX-OS",
            os_version="9.3(9)",
            features=["VXLAN"],
        ),
    ]

    discrepancy_rows = compare_inventory_vs_parsed(
        session_id="session-003",
        inventory_rows=inventory_rows,
        parsed_devices=parsed_devices,
    )

    assert discrepancy_rows == []
