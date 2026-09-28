from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Iterable

from bugscrub.parsers.base import ParseResult, Parser


SUPPORT_LEVEL = "basic"
FEATURE_ORDER = ("STP", "HSRP", "OSPF", "BGP", "VLAN", "EtherChannel", "QoS")
INVENTORY_BLOCK_RE = re.compile(
    r'NAME:\s*"(?P<name>[^"]+)"\s*,\s*DESCR:\s*"(?P<descr>[^"]*)"\s*[\r\n]+'
    r"\s*PID:\s*(?P<pid>[^,]*)\s*,\s*VID:\s*(?P<vid>[^,]*)\s*,\s*SN:\s*(?P<sn>[^\r\n]*)",
    re.IGNORECASE,
)
PID_PATTERNS = (
    re.compile(r"\bC\d{4}[A-Z0-9-]*\b"),
    re.compile(r"\bWS-C\d{4}[A-Z0-9-]*\b"),
)


@dataclass(slots=True)
class CatalystHardwareComponent:
    name: str
    description: str
    pid: str
    serial: str = ""


@dataclass(slots=True)
class CatalystCommandFacts:
    source_type: str
    support_level: str = SUPPORT_LEVEL
    device_name: str = ""
    model: str = ""
    pid: str = ""
    serial: str = ""
    os_version: str = ""
    features: list[str] = field(default_factory=list)
    hardware: list[CatalystHardwareComponent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "support_level": self.support_level,
            "device_name": self.device_name,
            "model": self.model,
            "pid": self.pid,
            "serial": self.serial,
            "os_version": self.os_version,
            "features": list(self.features),
            "hardware": [asdict(component) for component in self.hardware],
        }


class CatalystParser(Parser):
    """Basic Catalyst parser for common IOS XE command outputs."""

    support_level = SUPPORT_LEVEL

    def parse(self, source: Path) -> ParseResult:
        facts = self.parse_file(source)
        return ParseResult(source=source, records=[facts.to_record()], warnings=facts.warnings)

    def parse_file(self, source: Path, input_type: str | None = None) -> CatalystCommandFacts:
        text = source.read_text(encoding="utf-8", errors="ignore")
        detected_input = input_type or detect_input_type(source)

        if detected_input == "show_version":
            return self.parse_show_version_text(text)
        if detected_input == "show_inventory":
            return self.parse_show_inventory_text(text)
        if detected_input == "show_running_config":
            return self.parse_show_running_config_text(text)
        if detected_input == "show_module":
            return self.parse_show_module_text(text)

        return CatalystCommandFacts(
            source_type="unknown",
            warnings=[f"Could not detect Catalyst input type for `{source.name}`."],
        )

    def parse_bundle(
        self,
        *,
        show_version: Path | None = None,
        show_inventory: Path | None = None,
        show_running_config: Path | None = None,
        show_module: Path | None = None,
    ) -> CatalystCommandFacts:
        facts: list[CatalystCommandFacts] = []

        if show_version is not None:
            facts.append(self.parse_file(show_version, input_type="show_version"))
        if show_inventory is not None:
            facts.append(self.parse_file(show_inventory, input_type="show_inventory"))
        if show_running_config is not None:
            facts.append(self.parse_file(show_running_config, input_type="show_running_config"))
        if show_module is not None:
            facts.append(self.parse_file(show_module, input_type="show_module"))

        return merge_facts(facts)

    def parse_show_version_text(self, text: str) -> CatalystCommandFacts:
        model = _first_match(
            text,
            (
                r"(?im)^\s*Model Number\s*:\s*(.+?)\s*$",
                r"(?im)^\s*cisco\s+(\S+)\s+\(.+processor",
            ),
        )
        pid = _extract_pid(model) or _extract_pid(text)

        facts = CatalystCommandFacts(
            source_type="show_version",
            device_name=_first_match(
                text,
                (
                    r"(?im)^\s*(\S+)\s+uptime is .+$",
                    r"(?im)^\s*Switch name:\s*(.+?)\s*$",
                ),
            ),
            model=model,
            pid=pid,
            serial=_clean_serial(
                _first_match(
                    text,
                    (
                        r"(?im)^\s*System Serial Number\s*:\s*(\S+)\s*$",
                        r"(?im)^\s*Processor board ID\s+(\S+)\s*$",
                    ),
                )
            ),
            os_version=_first_match(
                text,
                (
                    r"(?im)^\s*Cisco IOS XE Software,\s*Version\s*([^\s,]+)",
                    r"(?im)^\s*Cisco IOS Software.*Version\s*([^\s,]+)",
                ),
            ),
        )
        if not facts.device_name:
            facts.warnings.append("show version did not include a device name.")
        if not facts.os_version:
            facts.warnings.append("show version did not include an OS version.")
        return facts

    def parse_show_inventory_text(self, text: str) -> CatalystCommandFacts:
        components = [
            CatalystHardwareComponent(
                name=_compact_spaces(match.group("name")),
                description=_compact_spaces(match.group("descr")),
                pid=_compact_spaces(match.group("pid")),
                serial=_clean_serial(match.group("sn")),
            )
            for match in INVENTORY_BLOCK_RE.finditer(text)
        ]
        primary = _select_primary_component(components)

        facts = CatalystCommandFacts(
            source_type="show_inventory",
            model=_clean_model(primary.pid if primary else ""),
            pid=primary.pid if primary else "",
            serial=primary.serial if primary else "",
            hardware=components,
        )
        if not components:
            facts.warnings.append("show inventory did not produce any inventory blocks.")
        return facts

    def parse_show_running_config_text(self, text: str) -> CatalystCommandFacts:
        facts = CatalystCommandFacts(
            source_type="show_running_config",
            device_name=_first_match(text, (r"(?im)^\s*hostname\s+(\S+)\s*$",)),
            features=detect_features(text),
        )
        if not facts.device_name:
            facts.warnings.append("show running-config did not include a hostname.")
        return facts

    def parse_show_module_text(self, text: str) -> CatalystCommandFacts:
        hardware: list[CatalystHardwareComponent] = []

        for line in text.splitlines():
            if not re.match(r"^\s*\d+\s+\d+\s+", line):
                continue
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 4:
                continue
            hardware.append(
                CatalystHardwareComponent(
                    name=f"Module {parts[0]}",
                    description=f"Catalyst switch member {parts[0]}",
                    pid=parts[2],
                    serial=_clean_serial(parts[3]),
                )
            )

        primary = _select_primary_component(hardware, prefer_switch=False)
        facts = CatalystCommandFacts(
            source_type="show_module",
            model=_clean_model(primary.pid if primary else ""),
            pid=primary.pid if primary else "",
            serial=primary.serial if primary else "",
            hardware=hardware,
        )
        if not hardware:
            facts.warnings.append("show module did not produce any module rows.")
        return facts


def detect_input_type(source: Path) -> str | None:
    stem = source.stem.lower().replace("-", "_").replace(" ", "_")
    if "show_version" in stem or stem == "version":
        return "show_version"
    if "show_inventory" in stem or stem == "inventory":
        return "show_inventory"
    if "show_running_config" in stem or "running_config" in stem or stem == "running":
        return "show_running_config"
    if "show_module" in stem or stem == "module":
        return "show_module"
    return None


def detect_features(text: str) -> list[str]:
    checks = {
        "STP": (
            r"(?im)^\s*spanning-tree\s+mode\b",
            r"(?im)^\s*spanning-tree\s+portfast\b",
        ),
        "HSRP": (
            r"(?im)^\s*standby\s+\d+\s+ip\b",
            r"(?im)^\s*interface\s+Vlan\d+[\s\S]*?\bstandby\s+\d+\s+ip\b",
        ),
        "OSPF": (
            r"(?im)^\s*router\s+ospf\b",
            r"(?im)^\s*ip\s+ospf\b",
        ),
        "BGP": (
            r"(?im)^\s*router\s+bgp\b",
            r"(?im)^\s*neighbor\s+\S+\s+remote-as\b",
        ),
        "VLAN": (
            r"(?im)^\s*vlan\s+\d+\b",
            r"(?im)^\s*interface\s+Vlan\d+\b",
            r"(?im)^\s*switchport\s+access\s+vlan\b",
            r"(?im)^\s*switchport\s+trunk\s+allowed\s+vlan\b",
        ),
        "EtherChannel": (
            r"(?im)^\s*interface\s+Port-channel\d+\b",
            r"(?im)^\s*channel-group\s+\d+\s+mode\b",
        ),
        "QoS": (
            r"(?im)^\s*mls\s+qos\b",
            r"(?im)^\s*policy-map\b",
            r"(?im)^\s*class-map\b",
            r"(?im)\bservice-policy\b",
            r"(?im)^\s*auto\s+qos\b",
        ),
    }

    detected: list[str] = []
    for feature_name in FEATURE_ORDER:
        if any(re.search(pattern, text) for pattern in checks[feature_name]):
            detected.append(feature_name)
    return detected


def merge_facts(facts: Iterable[CatalystCommandFacts]) -> CatalystCommandFacts:
    fact_list = list(facts)
    feature_set = {feature for fact in fact_list for feature in fact.features}
    warnings = [warning for fact in fact_list for warning in fact.warnings]
    hardware = _dedupe_components(component for fact in fact_list for component in fact.hardware)

    inventory_fact = _find_fact(fact_list, "show_inventory")
    show_version_fact = _find_fact(fact_list, "show_version")
    show_module_fact = _find_fact(fact_list, "show_module")
    running_config_fact = _find_fact(fact_list, "show_running_config")

    return CatalystCommandFacts(
        source_type="merged",
        support_level=SUPPORT_LEVEL,
        device_name=_first_non_empty(
            running_config_fact.device_name if running_config_fact else "",
            show_version_fact.device_name if show_version_fact else "",
        ),
        model=_first_non_empty(
            inventory_fact.model if inventory_fact else "",
            show_version_fact.model if show_version_fact else "",
            show_module_fact.model if show_module_fact else "",
        ),
        pid=_first_non_empty(
            inventory_fact.pid if inventory_fact else "",
            show_module_fact.pid if show_module_fact else "",
            show_version_fact.pid if show_version_fact else "",
        ),
        serial=_first_non_empty(
            inventory_fact.serial if inventory_fact else "",
            show_version_fact.serial if show_version_fact else "",
            show_module_fact.serial if show_module_fact else "",
        ),
        os_version=_first_non_empty(show_version_fact.os_version if show_version_fact else ""),
        features=[feature for feature in FEATURE_ORDER if feature in feature_set],
        hardware=hardware,
        warnings=warnings,
    )


def _find_fact(facts: Iterable[CatalystCommandFacts], source_type: str) -> CatalystCommandFacts | None:
    return next((fact for fact in facts if fact.source_type == source_type), None)


def _dedupe_components(components: Iterable[CatalystHardwareComponent]) -> list[CatalystHardwareComponent]:
    unique: list[CatalystHardwareComponent] = []
    seen: set[tuple[str, str, str, str]] = set()

    for component in components:
        key = (component.name, component.description, component.pid, component.serial)
        if key in seen:
            continue
        seen.add(key)
        unique.append(component)

    return unique


def _select_primary_component(
    components: list[CatalystHardwareComponent], *, prefer_switch: bool = True
) -> CatalystHardwareComponent | None:
    if not components:
        return None
    if prefer_switch:
        switch_component = next(
            (
                component
                for component in components
                if "switch" in component.name.lower() or "switch" in component.description.lower()
            ),
            None,
        )
        if switch_component is not None:
            return switch_component
    return components[0]


def _extract_pid(text: str) -> str:
    for pattern in PID_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return ""


def _clean_model(value: str) -> str:
    model = _compact_spaces(value).strip('"')
    model = re.sub(r"(?i)^cisco\s+", "", model)
    return model.strip()


def _clean_serial(value: str) -> str:
    serial = _compact_spaces(value).strip(",")
    if serial.upper() in {"", "N/A", "NA"}:
        return ""
    return serial


def _compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first_non_empty(*values: str) -> str:
    return next((value for value in values if value), "")


def _first_match(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _compact_spaces(match.group(1))
    return ""
