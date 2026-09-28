from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bugscrub.bug_engine.risk_summary import build_inventory_overview_metrics, build_risk_dashboard_data
from bugscrub.bug_engine.service import BugEngine
from bugscrub.discrepancies.service import compare_inventory_vs_parsed
from bugscrub.normalization.service import Normalizer
from bugscrub.parsers.service import parse_runtime_session


OUTPUT_DIR = REPO_ROOT / "storage" / "test-artifacts" / "nexus-demo-120-equipos"
INVENTORY_HEADERS = [
    "Device Name",
    "Model Number",
    "Platform PID",
    "Serial Number",
    "Current Version",
    "Target Version",
    "Site",
    "Role",
    "Product Family",
    "Enabled Features",
    "Criticality",
]

MODEL_LIBRARY = {
    "N9K-C93180YC-FX": {
        "model": "Nexus9000 C93180YC-FX",
        "module_type": "48x10/25G + 6x100G Supervisor",
        "ports": 54,
    },
    "N9K-C93108TC-FX3P": {
        "model": "Nexus9000 C93108TC-FX3P",
        "module_type": "48x1/10G-T + 6x100G Supervisor",
        "ports": 54,
    },
    "N9K-C9364C-GX": {
        "model": "Nexus9000 C9364C-GX",
        "module_type": "64x100G/40G QSFP Fabric Module",
        "ports": 64,
    },
    "N9K-C9336C-FX2": {
        "model": "Nexus9000 C9336C-FX2",
        "module_type": "36x100G/40G QSFP28 Supervisor",
        "ports": 36,
    },
}

BUG_DATASET = [
    {
        "bug_id": "PSIRT-NX-2026-1001",
        "headline": "PSIRT Nexus EVPN route leak under fabric convergence",
        "product_scope": "nexus",
        "affected_releases": ["9.3(8)", "9.3(9)"],
        "fixed_releases": ["10.2(5)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93*"],
        "required_features": ["EVPN"],
        "optional_features": ["BGP"],
        "severity": "1",
        "recommended_action": "Prioritize upgrade to 10.2(5) or later for EVPN-enabled fabrics.",
    },
    {
        "bug_id": "CVE-2026-9001",
        "headline": "CVE Nexus VXLAN tunnel parsing issue on 100G fabrics",
        "product_scope": "nexus",
        "affected_releases": ["10.2(2)"],
        "fixed_releases": ["10.3(1)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C9364C-*"],
        "required_features": ["VXLAN"],
        "optional_features": ["QoS"],
        "severity": "1",
        "recommended_action": "Move border fabrics to 10.3(1) or later and validate VXLAN adjacency stability.",
    },
    {
        "bug_id": "CSCwb30001",
        "headline": "Nexus QoS hardware profile sync issue on 9.3(9)",
        "product_scope": "nexus",
        "affected_releases": ["9.3(9)"],
        "fixed_releases": ["10.2(3)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93180YC-*"],
        "required_features": ["QoS"],
        "optional_features": [],
        "severity": "2",
        "recommended_action": "Upgrade QoS-heavy leaf nodes to at least 10.2(3).",
    },
    {
        "bug_id": "CVE-2026-9002",
        "headline": "CVE Nexus OSPF SPF storm can overrun route processors",
        "product_scope": "nexus",
        "affected_releases": ["10.2(3)"],
        "fixed_releases": ["10.3(2)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C9364C-*"],
        "required_features": ["OSPF"],
        "optional_features": ["BGP"],
        "severity": "2",
        "recommended_action": "Upgrade OSPF spines to 10.3(2) and review adjacency churn.",
    },
    {
        "bug_id": "PSIRT-NX-2026-1002",
        "headline": "PSIRT Nexus vPC consistency exposure in 9.3(8)",
        "product_scope": "nexus",
        "affected_releases": ["9.3(8)"],
        "fixed_releases": ["10.2(5)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93*"],
        "required_features": ["VPC"],
        "optional_features": [],
        "severity": "2",
        "recommended_action": "Escalate upgrades for vPC peers still running 9.3(8).",
    },
    {
        "bug_id": "FN-72510",
        "headline": "Field Notice PBR TCAM pressure can trigger policy drops",
        "product_scope": "nexus",
        "affected_releases": ["10.2(2)-10.2(3)"],
        "fixed_releases": ["10.3(1)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93*"],
        "required_features": ["PBR"],
        "optional_features": ["QoS"],
        "severity": "3",
        "recommended_action": "Plan TCAM review and upgrade PBR-heavy nodes to 10.3(1).",
    },
    {
        "bug_id": "CSCwb30002",
        "headline": "Nexus BGP process memory growth under route churn",
        "product_scope": "nexus",
        "affected_releases": ["9.3(8)-10.2(2)"],
        "fixed_releases": ["10.2(5)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93*"],
        "required_features": ["BGP"],
        "optional_features": [],
        "severity": "3",
        "recommended_action": "Prioritize BGP-heavy fabrics that have not reached 10.2(5).",
    },
    {
        "bug_id": "FN-72511",
        "headline": "Field Notice OSPF adjacency reset during supervisor reload",
        "product_scope": "nexus",
        "affected_releases": ["9.3(8)-10.2(3)"],
        "fixed_releases": ["10.2(5)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93*"],
        "required_features": ["OSPF"],
        "optional_features": [],
        "severity": "4",
        "recommended_action": "Schedule maintenance validation for OSPF nodes and target 10.2(5).",
    },
    {
        "bug_id": "CSCwb30003",
        "headline": "Nexus QoS counter drift after upgrade rehearsal",
        "product_scope": "nexus",
        "affected_releases": ["10.2(5)"],
        "fixed_releases": ["10.3(2)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93108TC-*"],
        "required_features": ["QoS"],
        "optional_features": [],
        "severity": "4",
        "recommended_action": "Treat as medium priority and align affected access blocks to 10.3(2).",
    },
    {
        "bug_id": "CSCwb30004",
        "headline": "Nexus BGP dampening telemetry mismatch on 10.3(1)",
        "product_scope": "nexus",
        "affected_releases": ["10.3(1)"],
        "fixed_releases": ["10.3(2)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C9336C-*"],
        "required_features": ["BGP"],
        "optional_features": [],
        "severity": "5",
        "recommended_action": "Track during normal lifecycle upgrades to 10.3(2).",
    },
    {
        "bug_id": "PSIRT-NX-2026-1003",
        "headline": "PSIRT Nexus vPC role flap exposure in 10.2(5)",
        "product_scope": "nexus",
        "affected_releases": ["10.2(5)"],
        "fixed_releases": ["10.3(2)"],
        "trigger_features": [],
        "platform_pids": ["N9K-C93108TC-*"],
        "required_features": ["VPC"],
        "optional_features": [],
        "severity": "5",
        "recommended_action": "Include 10.2(5) vPC blocks in the next remediation wave toward 10.3(2).",
    },
]


@dataclass(slots=True)
class Cohort:
    code: str
    count: int
    role: str
    site: str
    pid: str
    current_version: str
    target_version: str
    features: list[str]
    criticality: int


@dataclass(slots=True)
class DeviceSpec:
    hostname: str
    role: str
    site: str
    pid: str
    model: str
    current_version: str
    target_version: str
    features: list[str]
    criticality: int
    serial: str
    fabric_serial: str
    cohort: str


COHORTS = [
    Cohort("LEAF-A", 10, "leaf", "MEX-DC1", "N9K-C93180YC-FX", "9.3(8)", "10.2(3)", ["VXLAN", "EVPN", "BGP", "VPC", "QoS"], 1),
    Cohort("LEAF-B", 10, "leaf", "MEX-DC1", "N9K-C93180YC-FX", "9.3(9)", "10.2(5)", ["VXLAN", "EVPN", "BGP", "QoS"], 2),
    Cohort("BORDER-A", 10, "border", "MEX-DC1", "N9K-C9364C-GX", "10.2(2)", "10.3(1)", ["VXLAN", "EVPN", "BGP", "PBR"], 1),
    Cohort("SPINE-A", 10, "spine", "MEX-DC1", "N9K-C9364C-GX", "10.2(3)", "10.2(5)", ["BGP", "OSPF"], 2),
    Cohort("AGG-A", 10, "aggregation", "MEX-DC2", "N9K-C93108TC-FX3P", "10.2(5)", "10.3(2)", ["QoS", "VPC"], 3),
    Cohort("CORE-A", 10, "core", "MEX-DC2", "N9K-C9336C-FX2", "10.3(1)", "10.3(2)", ["BGP"], 1),
    Cohort("LEAF-C", 10, "leaf", "MEX-DC2", "N9K-C93180YC-FX", "10.2(5)", "10.3(2)", ["VXLAN", "EVPN", "BGP"], 3),
    Cohort("SPINE-B", 10, "spine", "MEX-DC2", "N9K-C9364C-GX", "10.3(2)", "10.3(2)", ["OSPF"], 4),
    Cohort("BORDER-B", 10, "border", "GDL-DC1", "N9K-C9336C-FX2", "10.2(3)", "10.3(2)", ["QoS"], 3),
    Cohort("LEAF-D", 10, "leaf", "GDL-DC1", "N9K-C93108TC-FX3P", "9.3(8)", "10.2(5)", ["OSPF", "VPC"], 2),
    Cohort("AGG-B", 10, "aggregation", "QRO-DC1", "N9K-C93108TC-FX3P", "10.2(2)", "10.2(5)", ["BGP", "QoS", "PBR"], 3),
    Cohort("LEAF-E", 10, "leaf", "QRO-DC1", "N9K-C93180YC-FX", "9.3(9)", "10.2(3)", ["VXLAN", "EVPN", "BGP", "QoS", "PBR", "VPC", "OSPF"], 1),
]


def main() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    devices = build_devices()
    write_inventory_workbook(OUTPUT_DIR / "inventory.xlsx", devices)
    write_bug_dataset_csv(OUTPUT_DIR / "demo_bug_dataset.csv")
    write_bundles(OUTPUT_DIR / "bundles", devices)
    write_bundle_zip(OUTPUT_DIR / "nexus-demo-120-equipos-bundle.zip", OUTPUT_DIR / "bundles")
    summary = write_expected_outputs(OUTPUT_DIR, devices)
    write_readme(OUTPUT_DIR / "README.txt", summary)
    write_package_zip(OUTPUT_DIR.with_suffix(".zip"), OUTPUT_DIR)

    print(f"Generated demo package at: {OUTPUT_DIR}")
    print(json.dumps(summary, indent=2))


def build_devices() -> list[DeviceSpec]:
    devices: list[DeviceSpec] = []
    for cohort_index, cohort in enumerate(COHORTS, start=1):
        model_info = MODEL_LIBRARY[cohort.pid]
        for device_index in range(1, cohort.count + 1):
            hostname = f"N9K-{cohort.code}-{device_index:02d}"
            devices.append(
                DeviceSpec(
                    hostname=hostname,
                    role=cohort.role,
                    site=cohort.site,
                    pid=cohort.pid,
                    model=model_info["model"],
                    current_version=cohort.current_version,
                    target_version=cohort.target_version,
                    features=list(cohort.features),
                    criticality=cohort.criticality,
                    serial=f"FDO{cohort_index:02d}{device_index:02d}A1",
                    fabric_serial=f"FAB{cohort_index:02d}{device_index:02d}B1",
                    cohort=cohort.code,
                )
            )
    return devices


def write_inventory_workbook(destination: Path, devices: list[DeviceSpec]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inventory_Input"
    sheet.append(INVENTORY_HEADERS)
    for device in devices:
        sheet.append(
            [
                device.hostname,
                device.model,
                device.pid,
                device.serial,
                device.current_version,
                device.target_version,
                device.site,
                device.role,
                "nexus9000",
                "; ".join(device.features),
                device.criticality,
            ]
        )
    workbook.create_sheet("Candidate_Bugs")
    workbook.save(destination)
    workbook.close()


def write_bug_dataset_csv(destination: Path) -> None:
    fieldnames = list(BUG_DATASET[0].keys())
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(serialize_row(row) for row in BUG_DATASET)


def write_bundles(bundle_root: Path, devices: list[DeviceSpec]) -> None:
    for device in devices:
        device_dir = bundle_root / device.hostname
        device_dir.mkdir(parents=True, exist_ok=True)
        (device_dir / "show_version.txt").write_text(render_show_version(device), encoding="utf-8")
        (device_dir / "show_inventory.txt").write_text(render_show_inventory(device), encoding="utf-8")
        (device_dir / "show_running_config.txt").write_text(render_show_running_config(device), encoding="utf-8")
        (device_dir / "show_module.txt").write_text(render_show_module(device), encoding="utf-8")


def write_bundle_zip(destination: Path, bundle_root: Path) -> None:
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(bundle_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_root).as_posix())


def write_expected_outputs(output_dir: Path, devices: list[DeviceSpec]) -> dict[str, object]:
    session_dir = output_dir / "_validation-session"
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_dir / "inventory.xlsx", session_dir / "inventory.xlsx")
    shutil.copytree(output_dir / "bundles", session_dir / "bundles")

    parsed_session = parse_runtime_session("Nexus", session_dir)
    batch = Normalizer().normalize_parsed_devices(
        parsed_records=parsed_session.parsed_records,
        platform_family=parsed_session.platform_family,
        support_level=parsed_session.support_level,
        session_dir=session_dir,
        inventory_path=session_dir / "inventory.xlsx",
        source_count=len(parsed_session.parsed_records),
        warnings=parsed_session.warnings,
    )
    batch.discrepancy_rows = compare_inventory_vs_parsed(
        session_id=batch.session_id,
        inventory_rows=batch.inventory_rows,
        parsed_devices=batch.devices,
    )
    batch.bug_findings = [finding.to_record() for finding in BugEngine(bug_records=BUG_DATASET).run(batch)]

    devices_records = [device.to_record() for device in batch.devices]
    inventory_records = [row.to_record() for row in batch.inventory_rows]
    discrepancy_records = [row.to_record() for row in batch.discrepancy_rows]
    bug_records = list(batch.bug_findings)

    overview = build_inventory_overview_metrics(
        devices=devices_records,
        inventory_rows=inventory_records,
        discrepancy_rows=discrepancy_records,
        bug_findings=bug_records,
        customer_inventory_uploaded=True,
    )
    dashboard = build_risk_dashboard_data(
        devices=devices_records,
        inventory_rows=inventory_records,
        discrepancy_rows=discrepancy_records,
        bug_findings=bug_records,
    )

    write_csv(output_dir / "manifest.csv", [manifest_row(device) for device in devices])
    write_csv(output_dir / "expected_bug_findings.csv", bug_records)
    write_csv(output_dir / "expected_bug_summary.csv", dashboard["bug_summary_rows"])
    write_csv(output_dir / "expected_device_summary.csv", dashboard["device_summary_rows"])
    write_csv(output_dir / "expected_pareto_quick_analysis.csv", dashboard["pareto_quick_analysis_rows"])

    summary = {
        "package_name": output_dir.name,
        "platform_family": "Nexus",
        "device_count": len(devices_records),
        "inventory_rows": len(inventory_records),
        "parsed_bundles": len(parsed_session.parsed_records),
        "discrepancy_pairs": len({row["pair_id"] for row in discrepancy_records if row.get("pair_id")}),
        "bug_findings": len(bug_records),
        "unique_bugs": len({record["bug_id"] for record in bug_records}),
        "devices_with_bugs": overview["devices_with_bugs_count"],
        "severity_counts": severity_counts(bug_records),
        "top_risk_device": dashboard["metrics"]["top_risk_device"],
        "pareto_top_5": dashboard["pareto_quick_analysis_rows"][:5],
    }
    (output_dir / "expected_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    shutil.rmtree(session_dir, ignore_errors=True)
    return summary


def manifest_row(device: DeviceSpec) -> dict[str, object]:
    return {
        "hostname": device.hostname,
        "cohort": device.cohort,
        "site": device.site,
        "role": device.role,
        "model": device.model,
        "pid": device.pid,
        "serial": device.serial,
        "current_version": device.current_version,
        "target_version": device.target_version,
        "features": list(device.features),
        "criticality": device.criticality,
    }


def write_csv(destination: Path, rows: list[dict[str, object]]) -> None:
    serializable_rows = [serialize_row(row) for row in rows]
    if not serializable_rows:
        destination.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in serializable_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(serializable_rows)


def serialize_row(row: dict[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, list):
            serialized[key] = "; ".join(str(item) for item in value)
        else:
            serialized[key] = value
    return serialized


def severity_counts(bug_records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in bug_records:
        severity = f"S{record.get('severity', '')}"
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def write_readme(destination: Path, summary: dict[str, object]) -> None:
    lines = [
        "Nexus 120-device realistic demo package",
        "",
        "Contents:",
        "- inventory.xlsx: customer inventory workbook with 120 devices",
        "- demo_bug_dataset.csv: custom dataset with representative findings from S1 to S5",
        "- nexus-demo-120-equipos-bundle.zip: upload this file in Multi-device command bundle",
        "- bundles/: raw uncompressed bundle folders, one per device",
        "- manifest.csv: device manifest",
        "- expected_summary.json: expected high-level output",
        "- expected_bug_summary.csv: expected summary by bug",
        "- expected_device_summary.csv: expected summary by device",
        "- expected_pareto_quick_analysis.csv: expected pareto quick-analysis table",
        "",
        "Recommended validation flow:",
        "1. Load demo_bug_dataset.csv in Bug Dataset Catalog and activate it.",
        "2. Select Platform family = Nexus.",
        "3. Upload inventory.xlsx.",
        "4. Upload nexus-demo-120-equipos-bundle.zip.",
        "5. Run the analysis and compare the UI/export outputs against expected_summary.json.",
        "",
        f"Generated devices: {summary['device_count']}",
        f"Bug findings: {summary['bug_findings']}",
        f"Devices with bugs: {summary['devices_with_bugs']}",
        f"Unique bugs: {summary['unique_bugs']}",
        f"Top risk device: {summary['top_risk_device']}",
        f"Severity counts: {json.dumps(summary['severity_counts'])}",
    ]
    destination.write_text("\n".join(lines), encoding="utf-8")


def write_package_zip(destination: Path, package_dir: Path) -> None:
    if destination.exists():
        destination.unlink()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir.parent).as_posix())


def render_show_version(device: DeviceSpec) -> str:
    return (
        "Cisco Nexus Operating System (NX-OS) Software\n"
        "TAC support: http://www.cisco.com/tac\n\n"
        "Software\n"
        "  BIOS: version 05.47\n"
        f"  NXOS: version {device.current_version}\n"
        "  BIOS compile time:  05/17/2023\n"
        f"  Device name: {device.hostname}\n"
        "  bootflash:  53298520 kB\n\n"
        "Hardware\n"
        f"  cisco {device.model} Chassis\n"
        "  Intel(R) Xeon(R) CPU\n"
        f"  Processor Board ID {device.serial}\n\n"
        "Kernel uptime is 21 day(s), 3 hour(s), 19 minute(s), 10 second(s)\n"
    )


def render_show_inventory(device: DeviceSpec) -> str:
    model_info = MODEL_LIBRARY[device.pid]
    return (
        f'NAME: "Chassis", DESCR: "{device.model} Chassis"\n'
        f"PID: {device.pid:<20}, VID: V01, SN: {device.serial}\n\n"
        f'NAME: "Slot 1", DESCR: "{model_info["module_type"]}"\n'
        f"PID: {device.pid:<20}, VID: V01, SN: {device.serial}\n\n"
        'NAME: "Fan 1", DESCR: "Nexus9000 Fan Module"\n'
        "PID: NXA-FAN-30CFM-B      , VID: V01, SN: N/A\n"
    )


def render_show_module(device: DeviceSpec) -> str:
    model_info = MODEL_LIBRARY[device.pid]
    return (
        "Mod Ports Module-Type                         Model              Status\n"
        "--- ----- ----------------------------------- ------------------ ----------\n"
        f"1   {model_info['ports']:<5} {model_info['module_type']:<35} {device.pid:<18} ok\n"
        "2   0     Fabric Module                       N9K-C9500-FM-E     ok\n\n"
        "Mod  Sw               Hw    Slot  Status  Plugin  Ports  Serial No.\n"
        "---  ---------------  ----- ----- ------- ------- -----  ----------\n"
        f"1    {device.current_version:<15} 1.0   NA    ok      yes     {model_info['ports']:<5} {device.serial}\n"
        f"2    {device.current_version:<15} 1.0   NA    ok      yes     0      {device.fabric_serial}\n"
    )


def render_show_running_config(device: DeviceSpec) -> str:
    lines = [f"hostname {device.hostname}"]
    feature_lines = {
        "OSPF": "feature ospf",
        "BGP": "feature bgp",
        "PBR": "feature pbr",
        "QoS": "feature qos",
        "VPC": "feature vpc",
        "VXLAN": "feature nv overlay",
    }
    for feature_name in ["OSPF", "BGP", "PBR", "QoS", "VPC", "VXLAN"]:
        if feature_name in device.features:
            lines.append(feature_lines[feature_name])

    if "EVPN" in device.features:
        lines.append("")
        lines.append("nv overlay evpn")
    if "VPC" in device.features:
        lines.append("vpc domain 10")
    if "OSPF" in device.features:
        lines.append("")
        lines.append("router ospf UNDERLAY")
    if "BGP" in device.features:
        lines.append("router bgp 65001")
        if "EVPN" in device.features:
            lines.append("  address-family l2vpn evpn")
    if "VXLAN" in device.features:
        lines.extend(
            [
                "",
                "interface nve1",
                "  source-interface loopback1",
                "  member vni 10010 associate-vrf",
            ]
        )
    if "PBR" in device.features:
        lines.extend(
            [
                "",
                "route-map PBR-TO-FW permit 10",
            ]
        )
    if "QoS" in device.features:
        lines.extend(
            [
                "system qos",
                "policy-map type network-qos JUMBO",
                "class-map type qos match-any GOLD",
            ]
        )
    lines.extend(["", "interface Ethernet1/1"])
    if "PBR" in device.features:
        lines.append("  ip policy route-map PBR-TO-FW")
    if "QoS" in device.features:
        lines.append("  service-policy type qos input GOLD-IN")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
