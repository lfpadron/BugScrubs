from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4
from zipfile import ZipFile

from openpyxl import Workbook

from bugscrub.intake.uploads import MAX_TEXT_UPLOAD_BYTES, save_uploads, validate_uploads


class FakeUploadedFile:
    def __init__(self, name: str, payload: bytes) -> None:
        self.name = name
        self._payload = payload
        self.size = len(payload)

    def getbuffer(self) -> memoryview:
        return memoryview(self._payload)


def test_validate_uploads_rejects_corrupt_excel_and_binary_command_output() -> None:
    uploads = build_single_device_uploads(
        inventory_file=FakeUploadedFile("inventory.xlsx", b"not-a-real-workbook"),
        show_version=FakeUploadedFile("show_version.txt", b"\x00\x01\x02"),
    )

    errors = validate_uploads(uploads)

    assert any("appears corrupt or unreadable as an Excel workbook" in error for error in errors)
    assert any("looks like a binary file" in error for error in errors)


def test_validate_uploads_rejects_large_text_files() -> None:
    uploads = build_single_device_uploads(
        show_version=FakeUploadedFile("show_version.txt", b"A" * (MAX_TEXT_UPLOAD_BYTES + 1)),
    )

    errors = validate_uploads(uploads)

    assert any("exceeds the current size limit" in error for error in errors)


def test_validate_uploads_accepts_valid_multi_device_bundle() -> None:
    uploads = {
        "inventory_excel": FakeUploadedFile("inventory.xlsx", build_inventory_workbook_bytes()),
        "multi_device_bundle": FakeUploadedFile("bundle.zip", build_multi_device_zip_bytes()),
        "show_version": None,
        "show_inventory": None,
        "show_running_config": None,
        "show_module": None,
    }

    errors = validate_uploads(uploads)

    assert errors == []


def test_validate_uploads_accepts_show_files_without_inventory_excel() -> None:
    uploads = build_single_device_uploads(include_inventory=False)

    errors = validate_uploads(uploads)

    assert errors == []


def test_validate_uploads_accepts_multi_device_bundle_without_inventory_excel() -> None:
    uploads = {
        "inventory_excel": None,
        "multi_device_bundle": FakeUploadedFile("bundle.zip", build_multi_device_zip_bytes()),
        "show_version": None,
        "show_inventory": None,
        "show_running_config": None,
        "show_module": None,
    }

    errors = validate_uploads(uploads)

    assert errors == []


def test_save_uploads_extracts_multi_device_bundle() -> None:
    workspace_dir = build_workspace_dir("uploads")
    runtime_root = workspace_dir / "runtime"
    uploads = {
        "inventory_excel": FakeUploadedFile("inventory.xlsx", build_inventory_workbook_bytes()),
        "multi_device_bundle": FakeUploadedFile("bundle.zip", build_multi_device_zip_bytes()),
        "show_version": None,
        "show_inventory": None,
        "show_running_config": None,
        "show_module": None,
    }

    try:
        session_dir, saved_files = save_uploads(uploads, runtime_root)

        assert len(saved_files) == 2
        assert (session_dir / "bundles" / "leaf01" / "show_version.txt").exists()
        assert (session_dir / "bundles" / "leaf02" / "show_module.txt").exists()
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


def build_single_device_uploads(
    *,
    inventory_file: FakeUploadedFile | None = None,
    show_version: FakeUploadedFile | None = None,
    include_inventory: bool = True,
) -> dict[str, FakeUploadedFile | None]:
    inventory = inventory_file or FakeUploadedFile("inventory.xlsx", build_inventory_workbook_bytes())
    default_text = b"hostname test-device\n"
    return {
        "inventory_excel": inventory if include_inventory else None,
        "multi_device_bundle": None,
        "show_version": show_version or FakeUploadedFile("show_version.txt", default_text),
        "show_inventory": FakeUploadedFile("show_inventory.txt", default_text),
        "show_running_config": FakeUploadedFile("show_running_config.txt", default_text),
        "show_module": FakeUploadedFile("show_module.txt", default_text),
    }


def build_inventory_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inventory_Input"
    sheet.append(["Device Name", "Platform PID", "Current Version"])
    sheet.append(["leaf01", "N9K-C93180YC-FX", "9.3(9)"])

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def build_multi_device_zip_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w") as archive:
        for device_name in ("leaf01", "leaf02"):
            archive.writestr(f"{device_name}/show_version.txt", f"hostname {device_name}\n")
            archive.writestr(f"{device_name}/show_inventory.txt", "inventory\n")
            archive.writestr(f"{device_name}/show_running_config.txt", f"hostname {device_name}\n")
            archive.writestr(f"{device_name}/show_module.txt", "module\n")
    return buffer.getvalue()


def build_workspace_dir(prefix: str) -> Path:
    workspace_dir = Path("storage") / "test-artifacts" / f"{prefix}-{uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir
