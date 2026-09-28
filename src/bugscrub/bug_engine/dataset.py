from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import pandas as pd


DEFAULT_BUG_DATASET = [
    {
        "bug_id": "CSCvx10001",
        "headline": "VXLAN EVPN control-plane instability on Nexus 9K",
        "product_scope": "nexus",
        "affected_releases": ["9.3(9)", "9.3(8)"],
        "fixed_releases": ["10.2(5)"],
        "trigger_features": ["VXLAN", "EVPN", "BGP"],
        "severity": "2",
        "recommended_action": "Upgrade to a fixed release before enabling additional EVPN scale.",
    },
    {
        "bug_id": "CSCvx10002",
        "headline": "QoS policy reload can impact forwarding on Nexus 9K",
        "product_scope": "nexus",
        "affected_releases": ["9.3(9)"],
        "fixed_releases": ["10.2(3)"],
        "trigger_features": ["QoS"],
        "severity": "3",
        "recommended_action": "Review QoS policy usage and plan upgrade to fixed code.",
    },
    {
        "bug_id": "CSCwa20001",
        "headline": "Catalyst 9300 EtherChannel flap under specific IOS XE conditions",
        "product_scope": "catalyst",
        "affected_releases": ["17.9.4a", "17.9.3"],
        "fixed_releases": ["17.12.1"],
        "trigger_features": ["EtherChannel", "STP"],
        "severity": "2",
        "recommended_action": "Move to a fixed IOS XE release and validate channel stability.",
    },
    {
        "bug_id": "CSCwa20002",
        "headline": "Catalyst QoS classification issue with auto-qos templates",
        "product_scope": "catalyst",
        "affected_releases": ["17.9.4a"],
        "fixed_releases": ["17.9.5"],
        "trigger_features": ["QoS"],
        "severity": "4",
        "recommended_action": "Audit QoS templates and schedule upgrade if affected.",
    },
]

BUG_DATASET_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xlsm"}
BUG_DATASET_REQUIRED_COLUMNS = (
    "bug_id",
    "headline",
    "product_scope",
    "affected_releases",
    "fixed_releases",
    "trigger_features",
    "severity",
    "recommended_action",
)
BUG_HEADER_ALIASES = {
    "bug_id": {"bug_id", "bug id", "cisco bug id", "csc id", "id"},
    "headline": {"headline", "title", "bug title", "summary"},
    "product_scope": {"product_scope", "product scope", "platform family", "platform", "family"},
    "affected_releases": {
        "affected_releases",
        "affected releases",
        "affected versions",
        "affected version",
        "impacted releases",
    },
    "fixed_releases": {"fixed_releases", "fixed releases", "fixed versions", "fixed version", "first fixed"},
    "trigger_features": {
        "trigger_features",
        "trigger features",
        "features",
        "feature set",
        "relevant features",
    },
    "severity": {"severity", "sev", "priority", "risk"},
    "recommended_action": {"recommended_action", "recommended action", "recommendation", "action"},
    "platform_pids": {"platform_pids", "platform pids", "platform pid", "pid", "pids", "supported pids"},
    "required_features": {"required_features", "required features", "mandatory features"},
    "optional_features": {"optional_features", "optional features", "recommended features", "related features"},
}


@dataclass(slots=True)
class BugDatasetDefinition:
    dataset_id: str
    dataset_name: str
    source_file: str
    source_kind: str
    selected_sheet: str = ""
    normalized_columns: list[str] = field(default_factory=list)
    row_count: int = 0
    bug_records: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    loaded_at: str = ""
    status: str = "inactive"

    def to_metadata_record(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "source_file": self.source_file,
            "source_kind": self.source_kind,
            "selected_sheet": self.selected_sheet,
            "normalized_columns": list(self.normalized_columns),
            "row_count": self.row_count,
            "warnings": list(self.warnings),
            "loaded_at": self.loaded_at,
            "status": self.status,
        }


def load_internal_bug_dataset() -> list[dict[str, object]]:
    return [dict(row) for row in DEFAULT_BUG_DATASET]


def validate_bug_dataset_file(file_name: str) -> list[str]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in BUG_DATASET_ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(BUG_DATASET_ALLOWED_EXTENSIONS))
        return [f"Invalid bug dataset file type `{file_name}`. Allowed extensions: {allowed}."]
    return []


def load_bug_dataset(dataset_path: Path, *, dataset_name: str | None = None) -> BugDatasetDefinition:
    dataset_path = Path(dataset_path)
    validation_errors = validate_bug_dataset_file(dataset_path.name)
    if validation_errors:
        raise ValueError(validation_errors[0])
    if not dataset_path.exists():
        raise FileNotFoundError(f"Bug dataset file was not found: {dataset_path}")

    frame, selected_sheet = read_bug_dataset_frame(dataset_path)
    normalized_columns = [map_bug_header(str(column)) for column in frame.columns]
    missing_columns = [column for column in BUG_DATASET_REQUIRED_COLUMNS if column not in normalized_columns]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Bug dataset is missing required columns: {joined}.")

    warnings: list[str] = []
    bug_records: list[dict[str, object]] = []
    for index, row in frame.iterrows():
        mapped = map_bug_row(row=row, normalized_columns=normalized_columns)
        if not any(mapped.values()):
            continue

        bug_id = mapped.get("bug_id", "")
        headline = mapped.get("headline", "")
        product_scope = normalize_product_scope(mapped.get("product_scope", ""))
        affected_releases = parse_list_field(mapped.get("affected_releases", ""))
        fixed_releases = parse_list_field(mapped.get("fixed_releases", ""))
        trigger_features = parse_list_field(mapped.get("trigger_features", ""))
        platform_pids = parse_list_field(mapped.get("platform_pids", ""))
        required_features = parse_list_field(mapped.get("required_features", ""))
        optional_features = parse_list_field(mapped.get("optional_features", ""))
        severity = normalize_severity(mapped.get("severity", ""))
        recommended_action = mapped.get("recommended_action", "")

        if not bug_id or not headline or not product_scope or not affected_releases or not severity:
            warnings.append(
                f"Skipped bug dataset row {index + 2} due to missing required values for bug_id/headline/product_scope/affected_releases/severity."
            )
            continue

        bug_records.append(
            {
                "bug_id": bug_id,
                "headline": headline,
                "product_scope": product_scope,
                "affected_releases": affected_releases,
                "fixed_releases": fixed_releases,
                "trigger_features": trigger_features,
                "platform_pids": platform_pids,
                "required_features": required_features,
                "optional_features": optional_features,
                "severity": severity,
                "recommended_action": recommended_action,
            }
        )

    if not bug_records:
        raise ValueError("Bug dataset did not contain any valid bug rows after validation.")

    suffix = dataset_path.suffix.lower()
    return BugDatasetDefinition(
        dataset_id=build_bug_dataset_id(),
        dataset_name=(dataset_name or dataset_path.stem).strip() or dataset_path.stem,
        source_file=dataset_path.name,
        source_kind="excel" if suffix in {".xlsx", ".xlsm"} else "csv",
        selected_sheet=selected_sheet,
        normalized_columns=[column for column in normalized_columns if column],
        row_count=len(bug_records),
        bug_records=bug_records,
        warnings=warnings,
        loaded_at=datetime.now(UTC).isoformat(),
    )


def read_bug_dataset_frame(dataset_path: Path) -> tuple[pd.DataFrame, str]:
    suffix = dataset_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(dataset_path, dtype=str, keep_default_na=False).fillna("")
        return frame, ""

    workbook = pd.ExcelFile(dataset_path)
    best_sheet_name = ""
    best_frame: pd.DataFrame | None = None
    best_score = -1
    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(dataset_path, sheet_name=sheet_name, dtype=str, keep_default_na=False).fillna("")
        recognized_columns = [column for column in [map_bug_header(str(value)) for value in frame.columns] if column]
        score = len(set(recognized_columns))
        preferred_bonus = 1 if normalize_header_name(sheet_name) in {"bugs", "bug catalog", "bug_catalog"} else 0
        if score + preferred_bonus > best_score:
            best_sheet_name = sheet_name
            best_frame = frame
            best_score = score + preferred_bonus

    if best_frame is None:
        raise ValueError("Bug dataset workbook did not contain a readable worksheet.")
    return best_frame, best_sheet_name


def map_bug_row(*, row: pd.Series, normalized_columns: list[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for index, normalized_column in enumerate(normalized_columns):
        if not normalized_column:
            continue
        value = row.iloc[index] if index < len(row) else ""
        mapped[normalized_column] = stringify_value(value)
    return mapped


def map_bug_header(value: str) -> str:
    normalized = normalize_header_name(value)
    for canonical_name, aliases in BUG_HEADER_ALIASES.items():
        if normalized in {normalize_header_name(alias) for alias in aliases}:
            return canonical_name
    return ""


def normalize_header_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_list_field(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[;,\n/|]|(?:\s+\+\s+)", value)
    return [part.strip() for part in parts if part and part.strip()]


def normalize_product_scope(value: str) -> str:
    normalized = normalize_header_name(value)
    if normalized in {"nexus", "nx os", "nxos", "nexus9000", "nexus 9000"}:
        return "nexus"
    if normalized in {"catalyst", "ios xe", "iosxe", "catalyst9300", "c9300", "c9200", "c9500"}:
        return "catalyst"
    return normalized.replace(" ", "")


def normalize_severity(value: str) -> str:
    normalized = normalize_header_name(value)
    if normalized.isdigit():
        return normalized

    severity_map = {
        "critical": "1",
        "high": "2",
        "medium": "3",
        "moderate": "3",
        "low": "4",
        "informational": "5",
        "info": "5",
    }
    return severity_map.get(normalized, stringify_value(value))


def build_bug_dataset_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"bugset-{timestamp}-{uuid4().hex[:8]}"
