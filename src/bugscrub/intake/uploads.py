from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook


EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
TEXT_EXTENSIONS = {".txt", ".log", ".cfg", ".conf"}
ARCHIVE_EXTENSIONS = {".zip"}
COMMAND_BUNDLE_STEMS = ("show_version", "show_inventory", "show_running_config", "show_module")
MAX_EXCEL_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_TEXT_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_UPLOAD_BYTES = 75 * 1024 * 1024


@dataclass(frozen=True)
class UploadSlot:
    key: str
    label: str
    detected_type: str
    required: bool
    allowed_extensions: set[str]
    target_stem: str


@dataclass(frozen=True)
class SavedUpload:
    input_label: str
    detected_type: str
    original_name: str
    saved_path: str
    size_bytes: int

    def to_record(self) -> dict[str, object]:
        return {
            "input_label": self.input_label,
            "detected_type": self.detected_type,
            "original_name": self.original_name,
            "saved_path": self.saved_path,
            "size_bytes": self.size_bytes,
        }


UPLOAD_SLOTS = (
    UploadSlot(
        key="inventory_excel",
        label="Excel inventory",
        detected_type="excel_inventory",
        required=False,
        allowed_extensions=EXCEL_EXTENSIONS,
        target_stem="inventory",
    ),
    UploadSlot(
        key="multi_device_bundle",
        label="Multi-device command bundle",
        detected_type="multi_device_bundle_zip",
        required=False,
        allowed_extensions=ARCHIVE_EXTENSIONS,
        target_stem="multi_device_bundle",
    ),
    UploadSlot(
        key="show_version",
        label="show version",
        detected_type="raw_show_version",
        required=True,
        allowed_extensions=TEXT_EXTENSIONS,
        target_stem="show_version",
    ),
    UploadSlot(
        key="show_inventory",
        label="show inventory",
        detected_type="raw_show_inventory",
        required=True,
        allowed_extensions=TEXT_EXTENSIONS,
        target_stem="show_inventory",
    ),
    UploadSlot(
        key="show_running_config",
        label="show running-config",
        detected_type="raw_show_running_config",
        required=True,
        allowed_extensions=TEXT_EXTENSIONS,
        target_stem="show_running_config",
    ),
    UploadSlot(
        key="show_module",
        label="show module",
        detected_type="raw_show_module",
        required=True,
        allowed_extensions=TEXT_EXTENSIONS,
        target_stem="show_module",
    ),
)


def validate_uploads(upload_map: dict[str, object | None]) -> list[str]:
    errors: list[str] = []
    has_multi_device_bundle = upload_map.get("multi_device_bundle") is not None

    for slot in UPLOAD_SLOTS:
        uploaded_file = upload_map.get(slot.key)
        is_single_bundle_slot = slot.key in {"show_version", "show_inventory", "show_running_config", "show_module"}

        if uploaded_file is None:
            if is_single_bundle_slot:
                if not has_multi_device_bundle:
                    errors.append(f"Missing required file for `{slot.label}`.")
                continue
            if slot.required:
                errors.append(f"Missing required file for `{slot.label}`.")
            continue

        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix not in slot.allowed_extensions:
            allowed = ", ".join(sorted(slot.allowed_extensions))
            errors.append(
                f"Invalid file type for `{slot.label}`: `{uploaded_file.name}`. Allowed extensions: {allowed}."
            )
            continue

        size_error = validate_upload_size(slot, uploaded_file.size)
        if size_error:
            errors.append(size_error)
            continue

        payload = bytes(uploaded_file.getbuffer())
        payload_error = validate_upload_payload(slot, uploaded_file.name, payload)
        if payload_error:
            errors.append(payload_error)

    return errors


def save_uploads(upload_map: dict[str, object | None], runtime_root: Path) -> tuple[Path, list[SavedUpload]]:
    session_dir = runtime_root / "uploads" / build_session_id()
    session_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[SavedUpload] = []
    for slot in UPLOAD_SLOTS:
        uploaded_file = upload_map.get(slot.key)
        if uploaded_file is None:
            continue
        suffix = Path(uploaded_file.name).suffix.lower()
        destination = session_dir / f"{slot.target_stem}{suffix}"
        destination.write_bytes(uploaded_file.getbuffer())
        saved_files.append(
            SavedUpload(
                input_label=slot.label,
                detected_type=slot.detected_type,
                original_name=uploaded_file.name,
                saved_path=str(destination),
                size_bytes=uploaded_file.size,
            )
        )
        if slot.key == "multi_device_bundle":
            extract_multi_device_archive(destination, session_dir / "bundles")

    return session_dir, saved_files


def find_saved_upload(saved_files: list[SavedUpload], detected_type: str) -> SavedUpload | None:
    return next((saved_file for saved_file in saved_files if saved_file.detected_type == detected_type), None)


def build_session_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def extract_multi_device_archive(archive_path: Path, destination_root: Path) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            extracted_path = destination_root / member.filename
            resolved_path = extracted_path.resolve()
            destination_base = destination_root.resolve()
            if destination_base not in resolved_path.parents and resolved_path != destination_base:
                raise ValueError(f"Archive member escapes destination root: {member.filename}")
        archive.extractall(destination_root)


def validate_upload_size(slot: UploadSlot, size_bytes: int) -> str | None:
    if size_bytes <= 0:
        return f"`{slot.label}` is empty."

    max_bytes = max_upload_size_for_slot(slot)
    if size_bytes > max_bytes:
        return (
            f"`{slot.label}` exceeds the current size limit of {format_bytes(max_bytes)} "
            f"with an uploaded size of {format_bytes(size_bytes)}."
        )
    return None


def validate_upload_payload(slot: UploadSlot, file_name: str, payload: bytes) -> str | None:
    suffix = Path(file_name).suffix.lower()
    if suffix in EXCEL_EXTENSIONS:
        return validate_excel_payload(slot, file_name, payload)
    if suffix in TEXT_EXTENSIONS:
        return validate_text_payload(slot, payload)
    if suffix in ARCHIVE_EXTENSIONS:
        return validate_archive_payload(slot, payload)
    return None


def validate_excel_payload(slot: UploadSlot, file_name: str, payload: bytes) -> str | None:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".xls":
        return (
            f"`{slot.label}` uses the legacy `.xls` format, which is not supported by the current parser. "
            "Save it as `.xlsx` or `.xlsm` and try again."
        )

    try:
        workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
        workbook.close()
    except Exception:
        return f"`{slot.label}` appears corrupt or unreadable as an Excel workbook."
    return None


def validate_text_payload(slot: UploadSlot, payload: bytes) -> str | None:
    if b"\x00" in payload:
        return f"`{slot.label}` looks like a binary file instead of raw command text."

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")

    if not text.strip():
        return f"`{slot.label}` does not contain readable command output."
    return None


def validate_archive_payload(slot: UploadSlot, payload: bytes) -> str | None:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            bad_member = archive.testzip()
            if bad_member:
                return f"`{slot.label}` contains a corrupt archive member: `{bad_member}`."

            file_names = [info.filename for info in archive.infolist() if not info.is_dir()]
            if not file_names:
                return f"`{slot.label}` does not contain any files."

            stems = {Path(name).stem.lower() for name in file_names}
            missing = [stem for stem in COMMAND_BUNDLE_STEMS if stem not in stems]
            if missing:
                joined = ", ".join(missing)
                return f"`{slot.label}` is missing required command files inside the ZIP: {joined}."
    except BadZipFile:
        return f"`{slot.label}` is not a valid ZIP archive."

    return None


def max_upload_size_for_slot(slot: UploadSlot) -> int:
    if slot.allowed_extensions == EXCEL_EXTENSIONS:
        return MAX_EXCEL_UPLOAD_BYTES
    if slot.allowed_extensions == ARCHIVE_EXTENSIONS:
        return MAX_ARCHIVE_UPLOAD_BYTES
    return MAX_TEXT_UPLOAD_BYTES


def format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
