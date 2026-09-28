from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bugscrub.parsers.catalyst import CatalystParser
from bugscrub.parsers.nexus import NexusParser


REQUIRED_BUNDLE_STEMS = ("show_version", "show_inventory", "show_running_config", "show_module")


@dataclass(slots=True)
class ParsedSession:
    platform_family: str
    support_level: str
    session_dir: Path
    parsed_records: list[dict[str, object]]
    warnings: list[str]

    @property
    def parsed_record(self) -> dict[str, object]:
        return self.parsed_records[0] if self.parsed_records else {}


def parse_runtime_session(platform_family: str, session_dir: Path) -> ParsedSession:
    parser = get_parser(platform_family)
    bundle_dirs = discover_bundle_dirs(session_dir)

    parsed_records: list[dict[str, object]] = []
    warnings: list[str] = []
    for bundle_dir in bundle_dirs:
        facts = parser.parse_bundle(
            show_version=_locate_uploaded_file(bundle_dir, "show_version"),
            show_inventory=_locate_uploaded_file(bundle_dir, "show_inventory"),
            show_running_config=_locate_uploaded_file(bundle_dir, "show_running_config"),
            show_module=_locate_uploaded_file(bundle_dir, "show_module"),
        )
        record = facts.to_record()
        record["bundle_name"] = derive_bundle_name(bundle_dir=bundle_dir, session_dir=session_dir)
        parsed_records.append(record)
        warnings.extend(prefix_warning_bundle(facts.warnings, bundle_name=record["bundle_name"]))

    if not parsed_records:
        warnings.append("No command bundles were discovered in the runtime session.")

    return ParsedSession(
        platform_family=normalize_platform_family(platform_family),
        support_level=getattr(parser, "support_level", "robust"),
        session_dir=session_dir,
        parsed_records=parsed_records,
        warnings=warnings,
    )


def get_parser(platform_family: str) -> NexusParser | CatalystParser:
    normalized = normalize_platform_family(platform_family)
    if normalized == "nexus":
        return NexusParser()
    if normalized == "catalyst":
        return CatalystParser()
    raise ValueError(f"Unsupported platform family `{platform_family}`.")


def normalize_platform_family(platform_family: str) -> str:
    normalized = platform_family.strip().lower()
    if normalized in {"nexus", "catalyst"}:
        return normalized
    raise ValueError(f"Unsupported platform family `{platform_family}`.")


def discover_bundle_dirs(session_dir: Path) -> list[Path]:
    bundle_root = session_dir / "bundles"
    search_root = bundle_root if bundle_root.exists() else session_dir

    discovered: dict[str, Path] = {}
    for match in search_root.rglob("show_version.*"):
        parent = match.parent
        key = str(parent.resolve()).lower()
        discovered[key] = parent

    if not discovered and _locate_uploaded_file(session_dir, "show_version") is not None:
        return [session_dir]

    return sorted(discovered.values(), key=lambda path: path.relative_to(search_root).as_posix().lower())


def derive_bundle_name(*, bundle_dir: Path, session_dir: Path) -> str:
    bundle_root = session_dir / "bundles"
    if bundle_root.exists():
        try:
            relative = bundle_dir.relative_to(bundle_root)
            if relative.parts:
                return relative.as_posix()
        except ValueError:
            pass
    return bundle_dir.name or session_dir.name


def prefix_warning_bundle(warnings: list[str], *, bundle_name: str) -> list[str]:
    if not bundle_name:
        return list(warnings)
    return [f"[{bundle_name}] {warning}" for warning in warnings]


def _locate_uploaded_file(session_dir: Path, stem: str) -> Path | None:
    matches = sorted(session_dir.glob(f"{stem}.*"))
    if not matches:
        return None
    return matches[0]
