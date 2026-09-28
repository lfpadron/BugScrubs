from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Iterable

from bugscrub.parsers.base import ParseResult, Parser


FEATURE_ORDER = ("VXLAN", "EVPN", "BGP", "VPC", "OSPF", "PBR", "QoS")
INVENTORY_BLOCK_RE = re.compile(
    r'NAME:\s*"(?P<name>[^"]+)"\s*,\s*DESCR:\s*"(?P<descr>[^"]*)"\s*[\r\n]+'
    r"\s*PID:\s*(?P<pid>[^,]*)\s*,\s*VID:\s*(?P<vid>[^,]*)\s*,\s*SN:\s*(?P<sn>[^\r\n]*)",
    re.IGNORECASE,
)
PID_PATTERNS = (
    re.compile(r"\bN[0-9A-Z]{1,4}-[A-Z0-9-]+\b"),
    re.compile(r"\bC\d{4,}[A-Z0-9-]+\b"),
)


@dataclass(slots=True)
class NexusHardwareComponent:
    name: str
    description: str
    pid: str
    serial: str = ""


@dataclass(slots=True)
class NexusCommandFacts:
    source_type: str
    device_name: str = ""
    model: str = ""
    pid: str = ""
    serial: str = ""
    nxos_version: str = ""
    features: list[str] = field(default_factory=list)
    hardware: list[NexusHardwareComponent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "device_name": self.device_name,
            "model": self.model,
            "pid": self.pid,
            "serial": self.serial,
            "nxos_version": self.nxos_version,
            "features": list(self.features),
            "hardware": [asdict(component) for component in self.hardware],
        }


class NexusParser(Parser):
    """Parses common Nexus command outputs into device facts."""

    def parse(self, source: Path) -> ParseResult:
        facts = self.parse_file(source)
        return ParseResult(source=source, records=[facts.to_record()], warnings=facts.warnings)

    def parse_file(self, source: Path, input_type: str | None = None) -> NexusCommandFacts:
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

        return NexusCommandFacts(
            source_type="unknown",
            warnings=[f"Could not detect Nexus input type for `{source.name}`."],
        )

    def parse_bundle(
        self,
        *,
        show_version: Path | None = None,
        show_inventory: Path | None = None,
        show_running_config: Path | None = None,
        show_module: Path | None = None,
    ) -> NexusCommandFacts:
        facts: list[NexusCommandFacts] = []

        if show_version is not None:
            facts.append(self.parse_file(show_version, input_type="show_version"))
        if show_inventory is not None:
            facts.append(self.parse_file(show_inventory, input_type="show_inventory"))
        if show_running_config is not None:
            facts.append(self.parse_file(show_running_config, input_type="show_running_config"))
        if show_module is not None:
            facts.append(self.parse_file(show_module, input_type="show_module"))

        return merge_facts(facts)

    def parse_show_version_text(self, text: str) -> NexusCommandFacts:
        model_line = _first_match(
            text,
            (
                r"(?im)^\s*Hardware\s+cisco\s+(.+?)\s*$",
                r"(?im)^\s*cisco\s+(.+?\s+Chassis)\s*$",
                r"(?im)^\s*Chassis\s+type\s*:\s*(.+?)\s*$",
            ),
        )
        model = _clean_model(model_line)
        pid = _extract_pid(model_line) or _extract_pid(text)

        facts = NexusCommandFacts(
            source_type="show_version",
            device_name=_first_match(text, (r"(?im)^\s*Device name:\s*(.+?)\s*$",)),
            model=model,
            pid=pid,
            serial=_clean_serial(
                _first_match(
                    text,
                    (
                        r"(?im)^\s*Processor Board ID\s+(\S+)\s*$",
                        r"(?im)^\s*Chassis serial number\s*:\s*(\S+)\s*$",
                    ),
                )
            ),
            nxos_version=_first_match(
                text,
                (
                    r"(?im)^\s*NXOS:\s*version\s*([^\s,]+)",
                    r"(?im)^\s*system:\s*version\s*([^\s,]+)",
                    r"(?im)^\s*NXOS\s+version\s*[: ]\s*([^\s,]+)",
                ),
            ),
        )
        if not facts.device_name:
            facts.warnings.append("show version did not include a device name.")
        if not facts.nxos_version:
            facts.warnings.append("show version did not include an NX-OS version.")
        return facts

    def parse_show_inventory_text(self, text: str) -> NexusCommandFacts:
        components = [
            NexusHardwareComponent(
                name=_compact_spaces(match.group("name")),
                description=_compact_spaces(match.group("descr")),
                pid=_compact_spaces(match.group("pid")),
                serial=_clean_serial(match.group("sn")),
            )
            for match in INVENTORY_BLOCK_RE.finditer(text)
        ]
        chassis = _select_primary_component(components)

        facts = NexusCommandFacts(
            source_type="show_inventory",
            model=_clean_model(chassis.description if chassis else ""),
            pid=chassis.pid if chassis else "",
            serial=chassis.serial if chassis else "",
            hardware=components,
        )
        if not components:
            facts.warnings.append("show inventory did not produce any inventory blocks.")
        return facts

    def parse_show_running_config_text(self, text: str) -> NexusCommandFacts:
        features = detect_features(text)
        facts = NexusCommandFacts(
            source_type="show_running_config",
            device_name=_first_match(text, (r"(?im)^\s*hostname\s+(\S+)\s*$",)),
            features=features,
        )
        if not facts.device_name:
            facts.warnings.append("show running-config did not include a hostname.")
        return facts

    def parse_show_module_text(self, text: str) -> NexusCommandFacts:
        modules: list[dict[str, str]] = []
        serials: dict[str, str] = {}
        state = ""

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if re.search(r"^\s*Mod\s+Ports\s+Module-Type\s+Model\s+Status", line):
                state = "module_rows"
                continue
            if re.search(r"^\s*Mod\s+Sw\s+.*Serial No\.", line):
                state = "serial_rows"
                continue
            if re.match(r"^\s*---", line) or not line.strip():
                continue

            if state == "module_rows" and re.match(r"^\s*\d+\s{2,}", line):
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 5:
                    modules.append(
                        {
                            "module": parts[0],
                            "module_type": parts[2],
                            "model": parts[3],
                        }
                    )
                continue

            if state == "serial_rows" and re.match(r"^\s*\d+\s{2,}", line):
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 2:
                    serials[parts[0]] = _clean_serial(parts[-1])

        hardware = [
            NexusHardwareComponent(
                name=f"Module {row['module']}",
                description=row["module_type"],
                pid=row["model"],
                serial=serials.get(row["module"], ""),
            )
            for row in modules
        ]
        primary = _select_primary_component(hardware, prefer_chassis=False)

        facts = NexusCommandFacts(
            source_type="show_module",
            model=_clean_model(primary.description if primary else ""),
            pid=primary.pid if primary else "",
            serial=primary.serial if primary else "",
            hardware=hardware,
        )
        if not modules:
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
        "VXLAN": (
            r"(?im)^\s*feature\s+nv\s+overlay\b",
            r"(?im)^\s*interface\s+nve\d+\b",
            r"(?im)\bmember\s+vni\b",
        ),
        "EVPN": (
            r"(?im)^\s*nv\s+overlay\s+evpn\b",
            r"(?im)^\s*address-family\s+l2vpn\s+evpn\b",
        ),
        "BGP": (
            r"(?im)^\s*feature\s+bgp\b",
            r"(?im)^\s*router\s+bgp\b",
        ),
        "VPC": (
            r"(?im)^\s*feature\s+vpc\b",
            r"(?im)^\s*vpc\s+domain\b",
        ),
        "OSPF": (
            r"(?im)^\s*feature\s+ospf\b",
            r"(?im)^\s*router\s+ospf\b",
        ),
        "PBR": (
            r"(?im)^\s*feature\s+pbr\b",
            r"(?im)\bip\s+policy\s+route-map\b",
            r"(?im)\bipv6\s+policy\s+route-map\b",
        ),
        "QoS": (
            r"(?im)^\s*feature\s+qos\b",
            r"(?im)^\s*policy-map\b",
            r"(?im)^\s*class-map\b",
            r"(?im)^\s*system\s+qos\b",
            r"(?im)\bservice-policy\b",
        ),
    }

    detected: list[str] = []
    for feature_name in FEATURE_ORDER:
        if any(re.search(pattern, text) for pattern in checks[feature_name]):
            detected.append(feature_name)
    return detected


def merge_facts(facts: Iterable[NexusCommandFacts]) -> NexusCommandFacts:
    fact_list = list(facts)
    feature_set = {
        feature
        for fact in fact_list
        for feature in fact.features
    }
    warnings = [warning for fact in fact_list for warning in fact.warnings]
    hardware = _dedupe_components(
        component
        for fact in fact_list
        for component in fact.hardware
    )

    inventory_fact = _find_fact(fact_list, "show_inventory")
    show_version_fact = _find_fact(fact_list, "show_version")
    show_module_fact = _find_fact(fact_list, "show_module")
    running_config_fact = _find_fact(fact_list, "show_running_config")

    return NexusCommandFacts(
        source_type="merged",
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
        nxos_version=_first_non_empty(show_version_fact.nxos_version if show_version_fact else ""),
        features=[feature for feature in FEATURE_ORDER if feature in feature_set],
        hardware=hardware,
        warnings=warnings,
    )


def _find_fact(facts: Iterable[NexusCommandFacts], source_type: str) -> NexusCommandFacts | None:
    return next((fact for fact in facts if fact.source_type == source_type), None)


def _dedupe_components(components: Iterable[NexusHardwareComponent]) -> list[NexusHardwareComponent]:
    unique: list[NexusHardwareComponent] = []
    seen: set[tuple[str, str, str, str]] = set()

    for component in components:
        key = (component.name, component.description, component.pid, component.serial)
        if key in seen:
            continue
        seen.add(key)
        unique.append(component)

    return unique


def _select_primary_component(
    components: list[NexusHardwareComponent], *, prefer_chassis: bool = True
) -> NexusHardwareComponent | None:
    if not components:
        return None
    if prefer_chassis:
        chassis = next(
            (
                component
                for component in components
                if "chassis" in component.name.lower() or "chassis" in component.description.lower()
            ),
            None,
        )
        if chassis is not None:
            return chassis
    return components[0]


def _extract_pid(text: str) -> str:
    for pattern in PID_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return ""


def _clean_model(value: str) -> str:
    model = _compact_spaces(value).strip('"')
    model = re.sub(r"(?i)^hardware\s+cisco\s+", "", model)
    model = re.sub(r"(?i)^cisco\s+", "", model)
    model = re.sub(r"(?i)\s+chassis$", "", model)
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
