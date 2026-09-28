from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeviceRecord:
    session_id: str
    hostname: str
    vendor: str
    platform_family: str
    support_level: str
    model: str
    pid: str
    serial: str
    os_name: str
    os_version: str
    inventory_file: str = ""
    inventory_sheet_names: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "platform_family": self.platform_family,
            "support_level": self.support_level,
            "model": self.model,
            "pid": self.pid,
            "serial": self.serial,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "inventory_file": self.inventory_file,
            "inventory_sheet_names": list(self.inventory_sheet_names),
            "features": list(self.features),
        }


@dataclass(slots=True)
class InventoryWorkbook:
    file_name: str = ""
    sheet_names: list[str] = field(default_factory=list)
    sheet_count: int = 0
    selected_sheet: str = ""
    normalized_columns: list[str] = field(default_factory=list)
    parsed_row_count: int = 0

    def to_record(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "sheet_names": list(self.sheet_names),
            "sheet_count": self.sheet_count,
            "selected_sheet": self.selected_sheet,
            "normalized_columns": list(self.normalized_columns),
            "parsed_row_count": self.parsed_row_count,
        }


@dataclass(slots=True)
class InventoryRowRecord:
    session_id: str
    sheet_name: str
    row_number: int
    hostname: str = ""
    model: str = ""
    pid: str = ""
    serial: str = ""
    os_version: str = ""
    target_version: str = ""
    site: str = ""
    role: str = ""
    family: str = ""
    features: list[str] = field(default_factory=list)
    business_criticality: int | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "hostname": self.hostname,
            "model": self.model,
            "pid": self.pid,
            "serial": self.serial,
            "os_version": self.os_version,
            "target_version": self.target_version,
            "site": self.site,
            "role": self.role,
            "family": self.family,
            "features": list(self.features),
            "business_criticality": self.business_criticality,
        }


@dataclass(slots=True)
class DiscrepancyRowRecord:
    session_id: str
    pair_id: str
    row_source: str
    discrepancy_status: str
    match_key: str
    discrepancy_fields: list[str] = field(default_factory=list)
    discrepancy_summary: str = ""
    hostname: str = ""
    model: str = ""
    pid: str = ""
    serial: str = ""
    os_version: str = ""
    target_version: str = ""
    site: str = ""
    role: str = ""
    family: str = ""
    features: list[str] = field(default_factory=list)
    business_criticality: int | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "pair_id": self.pair_id,
            "row_source": self.row_source,
            "discrepancy_status": self.discrepancy_status,
            "match_key": self.match_key,
            "discrepancy_fields": list(self.discrepancy_fields),
            "discrepancy_summary": self.discrepancy_summary,
            "hostname": self.hostname,
            "model": self.model,
            "pid": self.pid,
            "serial": self.serial,
            "os_version": self.os_version,
            "target_version": self.target_version,
            "site": self.site,
            "role": self.role,
            "family": self.family,
            "features": list(self.features),
            "business_criticality": self.business_criticality,
        }


@dataclass(slots=True)
class InventoryBatch:
    session_id: str
    platform_family: str
    support_level: str
    session_dir: str
    inventory_workbook: InventoryWorkbook = field(default_factory=InventoryWorkbook)
    inventory_rows: list[InventoryRowRecord] = field(default_factory=list)
    discrepancy_rows: list[DiscrepancyRowRecord] = field(default_factory=list)
    bug_findings: list[dict[str, object]] = field(default_factory=list)
    devices: list[DeviceRecord] = field(default_factory=list)
    source_count: int = 0
    warnings: list[str] = field(default_factory=list)
