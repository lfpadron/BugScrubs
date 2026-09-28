from __future__ import annotations

from pathlib import Path

from bugscrub.parsers.nexus import NexusParser


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nexus"


def test_parse_show_version_extracts_identity_and_version() -> None:
    parser = NexusParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_version.txt")

    assert facts.source_type == "show_version"
    assert facts.device_name == "leaf01"
    assert facts.model == "Nexus9000 C93180YC-FX"
    assert facts.pid == "C93180YC-FX"
    assert facts.serial == "FDO1234ABCD"
    assert facts.nxos_version == "9.3(9)"


def test_parse_show_inventory_extracts_primary_chassis_identity() -> None:
    parser = NexusParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_inventory.txt")

    assert facts.source_type == "show_inventory"
    assert facts.model == "Nexus9000 C93180YC-FX"
    assert facts.pid == "N9K-C93180YC-FX"
    assert facts.serial == "FDO1234ABCD"
    assert len(facts.hardware) == 3
    assert facts.hardware[0].name == "Chassis"


def test_parse_show_running_config_detects_requested_features() -> None:
    parser = NexusParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_running_config.txt")

    assert facts.source_type == "show_running_config"
    assert facts.device_name == "leaf01"
    assert facts.features == ["VXLAN", "EVPN", "BGP", "VPC", "OSPF", "PBR", "QoS"]


def test_parse_show_module_extracts_module_hardware_and_serials() -> None:
    parser = NexusParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_module.txt")

    assert facts.source_type == "show_module"
    assert facts.model == "48x10/25G + 6x100G Supervisor"
    assert facts.pid == "N9K-C93180YC-FX"
    assert facts.serial == "FDO1234ABCD"
    assert len(facts.hardware) == 2
    assert facts.hardware[1].serial == "FDO9999ZZZZ"


def test_parse_bundle_merges_device_identity_version_and_features() -> None:
    parser = NexusParser()

    facts = parser.parse_bundle(
        show_version=FIXTURE_DIR / "show_version.txt",
        show_inventory=FIXTURE_DIR / "show_inventory.txt",
        show_running_config=FIXTURE_DIR / "show_running_config.txt",
        show_module=FIXTURE_DIR / "show_module.txt",
    )

    assert facts.source_type == "merged"
    assert facts.device_name == "leaf01"
    assert facts.model == "Nexus9000 C93180YC-FX"
    assert facts.pid == "N9K-C93180YC-FX"
    assert facts.serial == "FDO1234ABCD"
    assert facts.nxos_version == "9.3(9)"
    assert facts.features == ["VXLAN", "EVPN", "BGP", "VPC", "OSPF", "PBR", "QoS"]
    assert len(facts.hardware) >= 5


def test_generic_parse_returns_parse_result_record() -> None:
    parser = NexusParser()

    result = parser.parse(FIXTURE_DIR / "show_version.txt")

    assert result.warnings == []
    assert result.records[0]["device_name"] == "leaf01"
    assert result.records[0]["nxos_version"] == "9.3(9)"
