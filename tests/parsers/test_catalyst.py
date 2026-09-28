from __future__ import annotations

from pathlib import Path

from bugscrub.parsers.catalyst import CatalystParser, SUPPORT_LEVEL


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "catalyst"


def test_parse_show_version_extracts_identity_and_version() -> None:
    parser = CatalystParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_version.txt")

    assert facts.source_type == "show_version"
    assert facts.support_level == SUPPORT_LEVEL
    assert facts.device_name == "dist-sw01"
    assert facts.model == "C9300-48P"
    assert facts.pid == "C9300-48P"
    assert facts.serial == "FCW2145L0AB"
    assert facts.os_version == "17.9.4a"


def test_parse_show_inventory_extracts_primary_switch_identity() -> None:
    parser = CatalystParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_inventory.txt")

    assert facts.source_type == "show_inventory"
    assert facts.model == "C9300-48P"
    assert facts.pid == "C9300-48P"
    assert facts.serial == "FCW2145L0AB"
    assert len(facts.hardware) == 3
    assert facts.hardware[0].name == "Switch 1"


def test_parse_show_running_config_detects_basic_feature_set() -> None:
    parser = CatalystParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_running_config.txt")

    assert facts.source_type == "show_running_config"
    assert facts.device_name == "dist-sw01"
    assert facts.features == ["STP", "HSRP", "OSPF", "BGP", "VLAN", "EtherChannel", "QoS"]


def test_parse_show_module_extracts_module_rows() -> None:
    parser = CatalystParser()

    facts = parser.parse_file(FIXTURE_DIR / "show_module.txt")

    assert facts.source_type == "show_module"
    assert facts.model == "C9300-48P"
    assert facts.pid == "C9300-48P"
    assert facts.serial == "FCW2145L0AB"
    assert len(facts.hardware) == 2
    assert facts.hardware[1].serial == "FCW2145L0AC"


def test_parse_bundle_merges_identity_version_and_features() -> None:
    parser = CatalystParser()

    facts = parser.parse_bundle(
        show_version=FIXTURE_DIR / "show_version.txt",
        show_inventory=FIXTURE_DIR / "show_inventory.txt",
        show_running_config=FIXTURE_DIR / "show_running_config.txt",
        show_module=FIXTURE_DIR / "show_module.txt",
    )

    assert facts.source_type == "merged"
    assert facts.support_level == SUPPORT_LEVEL
    assert facts.device_name == "dist-sw01"
    assert facts.model == "C9300-48P"
    assert facts.pid == "C9300-48P"
    assert facts.serial == "FCW2145L0AB"
    assert facts.os_version == "17.9.4a"
    assert facts.features == ["STP", "HSRP", "OSPF", "BGP", "VLAN", "EtherChannel", "QoS"]
    assert len(facts.hardware) >= 5


def test_generic_parse_returns_parse_result_record() -> None:
    parser = CatalystParser()

    result = parser.parse(FIXTURE_DIR / "show_version.txt")

    assert result.warnings == []
    assert result.records[0]["support_level"] == SUPPORT_LEVEL
    assert result.records[0]["device_name"] == "dist-sw01"
    assert result.records[0]["os_version"] == "17.9.4a"
