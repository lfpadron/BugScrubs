from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from bugscrub.normalization.models import DeviceRecord, DiscrepancyRowRecord, InventoryRowRecord


COMPARABLE_FIELDS = ("hostname", "model", "pid", "serial", "os_version", "features")
MATCH_THRESHOLD = 320
PLATFORM_STOPWORDS = {"cisco", "nexus", "nexus9000", "catalyst", "series", "switch"}


@dataclass(slots=True)
class CandidateMatch:
    inventory_index: int
    parsed_index: int
    score: int
    match_key: str
    strategy: str


def compare_inventory_vs_parsed(
    *,
    session_id: str,
    inventory_rows: list[InventoryRowRecord],
    parsed_devices: list[DeviceRecord],
) -> list[DiscrepancyRowRecord]:
    discrepancy_rows: list[DiscrepancyRowRecord] = []
    pair_number = 0

    matches = resolve_matches(inventory_rows=inventory_rows, parsed_devices=parsed_devices)
    matched_inventory_indices = {match.inventory_index for match in matches}
    matched_parsed_indices = {match.parsed_index for match in matches}

    for match in sorted(matches, key=lambda item: inventory_sort_key(inventory_rows[item.inventory_index])):
        inventory_row = inventory_rows[match.inventory_index]
        parsed_device = parsed_devices[match.parsed_index]
        differing_fields = detect_differing_fields(inventory_row, parsed_device)
        if not differing_fields:
            continue

        pair_number += 1
        pair_id = build_pair_id(session_id, pair_number)
        summary = f"Discrepancia en: {', '.join(differing_fields)}."
        discrepancy_rows.extend(
            [
                build_client_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="discrepancia",
                    match_key=match.match_key,
                    summary=summary,
                    differing_fields=differing_fields,
                    inventory_row=inventory_row,
                ),
                build_discovered_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="discrepancia",
                    match_key=match.match_key,
                    summary=summary,
                    differing_fields=differing_fields,
                    parsed_device=parsed_device,
                ),
            ]
        )

    unmatched_inventory = [
        (index, row)
        for index, row in enumerate(inventory_rows)
        if index not in matched_inventory_indices
    ]
    for index, inventory_row in sorted(unmatched_inventory, key=lambda item: inventory_sort_key(item[1])):
        pair_number += 1
        pair_id = build_pair_id(session_id, pair_number)
        match_key = build_fallback_match_key(
            hostname=inventory_row.hostname,
            serial=inventory_row.serial,
            pid=inventory_row.pid,
            model=inventory_row.model,
            row_number=inventory_row.row_number,
        )
        summary = "Faltante: estaba en el inventario del cliente, pero no fue descubierto por la herramienta."
        discrepancy_rows.extend(
            [
                build_client_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="faltante",
                    match_key=match_key,
                    summary=summary,
                    differing_fields=["hostname"],
                    inventory_row=inventory_row,
                ),
                build_discovered_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="faltante",
                    match_key=match_key,
                    summary=summary,
                    differing_fields=["hostname"],
                    parsed_device=None,
                ),
            ]
        )

    unmatched_parsed = [
        (index, device)
        for index, device in enumerate(parsed_devices)
        if index not in matched_parsed_indices
    ]
    for index, parsed_device in sorted(unmatched_parsed, key=lambda item: parsed_sort_key(item[1])):
        pair_number += 1
        pair_id = build_pair_id(session_id, pair_number)
        match_key = build_fallback_match_key(
            hostname=parsed_device.hostname,
            serial=parsed_device.serial,
            pid=parsed_device.pid,
            model=parsed_device.model,
            row_number=index + 1,
        )
        summary = "Nuevo: fue descubierto por la herramienta, pero no estaba en el inventario del cliente."
        discrepancy_rows.extend(
            [
                build_client_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="nuevo",
                    match_key=match_key,
                    summary=summary,
                    differing_fields=["hostname"],
                    inventory_row=None,
                ),
                build_discovered_row(
                    session_id=session_id,
                    pair_id=pair_id,
                    status="nuevo",
                    match_key=match_key,
                    summary=summary,
                    differing_fields=["hostname"],
                    parsed_device=parsed_device,
                ),
            ]
        )

    return discrepancy_rows


def resolve_matches(
    *,
    inventory_rows: list[InventoryRowRecord],
    parsed_devices: list[DeviceRecord],
) -> list[CandidateMatch]:
    matches: list[CandidateMatch] = []
    matched_inventory_indices: set[int] = set()
    matched_parsed_indices: set[int] = set()

    for strategy_name, inventory_key_getter, parsed_key_getter in (
        ("serial", lambda row: normalize_identifier(row.serial), lambda device: normalize_identifier(device.serial)),
        ("hostname", lambda row: normalize_hostname(row.hostname), lambda device: normalize_hostname(device.hostname)),
    ):
        for match in unique_exact_matches(
            inventory_rows=inventory_rows,
            parsed_devices=parsed_devices,
            matched_inventory_indices=matched_inventory_indices,
            matched_parsed_indices=matched_parsed_indices,
            inventory_key_getter=inventory_key_getter,
            parsed_key_getter=parsed_key_getter,
            strategy=strategy_name,
        ):
            matches.append(match)
            matched_inventory_indices.add(match.inventory_index)
            matched_parsed_indices.add(match.parsed_index)

    candidates: list[CandidateMatch] = []
    for inventory_index, inventory_row in enumerate(inventory_rows):
        if inventory_index in matched_inventory_indices:
            continue
        for parsed_index, parsed_device in enumerate(parsed_devices):
            if parsed_index in matched_parsed_indices:
                continue
            candidate = score_candidate_pair(
                inventory_index=inventory_index,
                inventory_row=inventory_row,
                parsed_index=parsed_index,
                parsed_device=parsed_device,
            )
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            inventory_sort_key(inventory_rows[candidate.inventory_index]),
            parsed_sort_key(parsed_devices[candidate.parsed_index]),
        )
    )
    for candidate in candidates:
        if candidate.inventory_index in matched_inventory_indices or candidate.parsed_index in matched_parsed_indices:
            continue
        matches.append(candidate)
        matched_inventory_indices.add(candidate.inventory_index)
        matched_parsed_indices.add(candidate.parsed_index)

    return matches


def unique_exact_matches(
    *,
    inventory_rows: list[InventoryRowRecord],
    parsed_devices: list[DeviceRecord],
    matched_inventory_indices: set[int],
    matched_parsed_indices: set[int],
    inventory_key_getter,
    parsed_key_getter,
    strategy: str,
) -> list[CandidateMatch]:
    inventory_map: dict[str, list[int]] = defaultdict(list)
    parsed_map: dict[str, list[int]] = defaultdict(list)

    for index, row in enumerate(inventory_rows):
        if index in matched_inventory_indices:
            continue
        key = inventory_key_getter(row)
        if key:
            inventory_map[key].append(index)

    for index, device in enumerate(parsed_devices):
        if index in matched_parsed_indices:
            continue
        key = parsed_key_getter(device)
        if key:
            parsed_map[key].append(index)

    matches: list[CandidateMatch] = []
    for key in sorted(set(inventory_map) & set(parsed_map)):
        if len(inventory_map[key]) != 1 or len(parsed_map[key]) != 1:
            continue
        inventory_index = inventory_map[key][0]
        parsed_index = parsed_map[key][0]
        matches.append(
            CandidateMatch(
                inventory_index=inventory_index,
                parsed_index=parsed_index,
                score=2000 if strategy == "serial" else 1500,
                match_key=f"{strategy}:{key}",
                strategy=strategy,
            )
        )
    return matches


def score_candidate_pair(
    *,
    inventory_index: int,
    inventory_row: InventoryRowRecord,
    parsed_index: int,
    parsed_device: DeviceRecord,
) -> CandidateMatch | None:
    inventory_serial = normalize_identifier(inventory_row.serial)
    parsed_serial = normalize_identifier(parsed_device.serial)
    inventory_hostname = normalize_hostname(inventory_row.hostname)
    parsed_hostname = normalize_hostname(parsed_device.hostname)
    inventory_pid = normalize_identifier(inventory_row.pid)
    parsed_pid = normalize_identifier(parsed_device.pid)

    score = 0
    strategy = "heuristic"
    match_key = ""
    has_identity_anchor = False

    if inventory_serial and parsed_serial:
        if inventory_serial != parsed_serial:
            return None
        score += 1200
        strategy = "serial"
        match_key = f"serial:{inventory_serial}"
        has_identity_anchor = True

    hostname_alias = False
    if inventory_hostname and parsed_hostname:
        if inventory_hostname == parsed_hostname:
            score += 900
            has_identity_anchor = True
            if not match_key:
                strategy = "hostname"
                match_key = f"hostname:{inventory_hostname}"
        elif hostnames_loosely_match(inventory_hostname, parsed_hostname):
            score += 420
            hostname_alias = True
            has_identity_anchor = True
            if not match_key:
                strategy = "hostname_alias"
                match_key = f"hostname:{inventory_hostname}"
        else:
            score -= 160

    if inventory_pid and parsed_pid:
        if inventory_pid == parsed_pid:
            score += 240
            has_identity_anchor = True
            if not match_key:
                strategy = "pid"
                match_key = f"pid:{inventory_pid}"
        else:
            score -= 50

    platform_match = platform_identity_matches(inventory_row=inventory_row, parsed_device=parsed_device)
    if platform_match:
        score += 180
        has_identity_anchor = True
        if not match_key:
            strategy = "platform"
            match_key = build_fallback_match_key(
                hostname=inventory_row.hostname or parsed_device.hostname,
                serial=inventory_row.serial or parsed_device.serial,
                pid=inventory_row.pid or parsed_device.pid,
                model=inventory_row.model or parsed_device.model,
                row_number=inventory_row.row_number,
            )

    if same_platform_family(inventory_row=inventory_row, parsed_device=parsed_device):
        score += 35

    if normalize_version(inventory_row.os_version) and normalize_version(inventory_row.os_version) == normalize_version(parsed_device.os_version):
        score += 35

    shared_features = normalized_feature_set(inventory_row.features) & normalized_feature_set(parsed_device.features)
    score += min(30, len(shared_features) * 10)

    if not has_identity_anchor:
        return None

    if strategy not in {"serial", "hostname"} and not hostname_alias and score < MATCH_THRESHOLD:
        return None

    return CandidateMatch(
        inventory_index=inventory_index,
        parsed_index=parsed_index,
        score=score,
        match_key=match_key or build_fallback_match_key(
            hostname=inventory_row.hostname or parsed_device.hostname,
            serial=inventory_row.serial or parsed_device.serial,
            pid=inventory_row.pid or parsed_device.pid,
            model=inventory_row.model or parsed_device.model,
            row_number=inventory_row.row_number,
        ),
        strategy=strategy,
    )


def detect_differing_fields(inventory_row: InventoryRowRecord, parsed_device: DeviceRecord) -> list[str]:
    differing_fields: list[str] = []
    if not hostnames_equal(inventory_row.hostname, parsed_device.hostname):
        differing_fields.append("hostname")
    if not models_equal(inventory_row, parsed_device):
        differing_fields.append("model")
    if not pids_equal(inventory_row, parsed_device):
        differing_fields.append("pid")
    if normalize_identifier(inventory_row.serial) != normalize_identifier(parsed_device.serial):
        differing_fields.append("serial")
    if normalize_version(inventory_row.os_version) != normalize_version(parsed_device.os_version):
        differing_fields.append("os_version")
    if normalized_feature_set(inventory_row.features) != normalized_feature_set(parsed_device.features):
        differing_fields.append("features")
    return differing_fields


def build_client_row(
    *,
    session_id: str,
    pair_id: str,
    status: str,
    match_key: str,
    summary: str,
    differing_fields: list[str],
    inventory_row: InventoryRowRecord | None,
) -> DiscrepancyRowRecord:
    if inventory_row is None:
        return DiscrepancyRowRecord(
            session_id=session_id,
            pair_id=pair_id,
            row_source="cliente",
            discrepancy_status=status,
            match_key=match_key,
            discrepancy_fields=differing_fields,
            discrepancy_summary=summary,
        )

    return DiscrepancyRowRecord(
        session_id=session_id,
        pair_id=pair_id,
        row_source="cliente",
        discrepancy_status=status,
        match_key=match_key,
        discrepancy_fields=differing_fields,
        discrepancy_summary=summary,
        hostname=inventory_row.hostname,
        model=inventory_row.model,
        pid=inventory_row.pid,
        serial=inventory_row.serial,
        os_version=inventory_row.os_version,
        target_version=inventory_row.target_version,
        site=inventory_row.site,
        role=inventory_row.role,
        family=inventory_row.family,
        features=list(inventory_row.features),
        business_criticality=inventory_row.business_criticality,
    )


def build_discovered_row(
    *,
    session_id: str,
    pair_id: str,
    status: str,
    match_key: str,
    summary: str,
    differing_fields: list[str],
    parsed_device: DeviceRecord | None,
) -> DiscrepancyRowRecord:
    if parsed_device is None:
        return DiscrepancyRowRecord(
            session_id=session_id,
            pair_id=pair_id,
            row_source="descubierto",
            discrepancy_status=status,
            match_key=match_key,
            discrepancy_fields=differing_fields,
            discrepancy_summary=summary,
        )

    return DiscrepancyRowRecord(
        session_id=session_id,
        pair_id=pair_id,
        row_source="descubierto",
        discrepancy_status=status,
        match_key=match_key,
        discrepancy_fields=differing_fields,
        discrepancy_summary=summary,
        hostname=parsed_device.hostname,
        model=parsed_device.model,
        pid=parsed_device.pid,
        serial=parsed_device.serial,
        os_version=parsed_device.os_version,
        features=list(parsed_device.features),
    )


def build_pair_id(session_id: str, pair_number: int) -> str:
    return f"{session_id}-pair-{pair_number:03d}"


def build_fallback_match_key(*, hostname: str, serial: str, pid: str, model: str, row_number: int) -> str:
    normalized_hostname = normalize_hostname(hostname)
    if normalized_hostname:
        return f"hostname:{normalized_hostname}"
    normalized_serial = normalize_identifier(serial)
    if normalized_serial:
        return f"serial:{normalized_serial}"
    platform_signature = next(iter(sorted(build_platform_signatures(pid, model))), "")
    if platform_signature:
        return f"platform:{platform_signature}:{row_number}"
    return f"row:{row_number}"


def inventory_sort_key(row: InventoryRowRecord) -> tuple[int, str, str]:
    return (int(row.row_number), normalize_hostname(row.hostname), normalize_identifier(row.serial))


def parsed_sort_key(device: DeviceRecord) -> tuple[str, str, str]:
    return (
        normalize_hostname(device.hostname),
        normalize_identifier(device.serial),
        normalize_identifier(device.pid or device.model),
    )


def hostnames_equal(inventory_hostname: str, parsed_hostname: str) -> bool:
    return normalize_hostname(inventory_hostname) == normalize_hostname(parsed_hostname)


def hostnames_loosely_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shortest, longest = sorted([left, right], key=len)
    return len(shortest) >= 6 and longest.startswith(shortest)


def models_equal(inventory_row: InventoryRowRecord, parsed_device: DeviceRecord) -> bool:
    inventory_value = inventory_row.model or inventory_row.pid
    parsed_value = parsed_device.model or parsed_device.pid
    if not inventory_value and not parsed_value:
        return True
    return bool(build_platform_signatures(inventory_value, inventory_row.pid) & build_platform_signatures(parsed_value, parsed_device.pid))


def pids_equal(inventory_row: InventoryRowRecord, parsed_device: DeviceRecord) -> bool:
    inventory_pid = normalize_identifier(inventory_row.pid)
    parsed_pid = normalize_identifier(parsed_device.pid)
    if inventory_pid and parsed_pid:
        return inventory_pid == parsed_pid
    if not inventory_row.pid and not parsed_device.pid:
        return True
    return platform_identity_matches(inventory_row=inventory_row, parsed_device=parsed_device)


def platform_identity_matches(*, inventory_row: InventoryRowRecord, parsed_device: DeviceRecord) -> bool:
    inventory_signatures = build_platform_signatures(inventory_row.pid, inventory_row.model)
    parsed_signatures = build_platform_signatures(parsed_device.pid, parsed_device.model)
    if not inventory_signatures or not parsed_signatures:
        return False
    return bool(inventory_signatures & parsed_signatures)


def same_platform_family(*, inventory_row: InventoryRowRecord, parsed_device: DeviceRecord) -> bool:
    family = normalize_identifier(inventory_row.family)
    platform_family = normalize_identifier(parsed_device.platform_family)
    if not family or not platform_family:
        return False
    return family in platform_family or platform_family in family


def build_platform_signatures(*values: str) -> set[str]:
    signatures: set[str] = set()
    for value in values:
        raw_value = str(value or "").strip().lower()
        if not raw_value:
            continue

        tokens = [token for token in re.findall(r"[a-z0-9]+", raw_value) if token not in PLATFORM_STOPWORDS]
        if not tokens:
            continue

        joined = "".join(tokens)
        signatures.add(joined)
        for token in tokens:
            if any(character.isdigit() for character in token):
                signatures.add(token)
        if len(tokens) > 1:
            signatures.add("".join(tokens[1:]))
            signatures.add("".join(token for token in tokens if token not in {"n9k", "c9k", "c9300", "c9500", "c9200"}))
    return {signature for signature in signatures if signature}


def normalize_identifier(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def normalize_hostname(value: object) -> str:
    hostname = str(value or "").strip().lower()
    if not hostname:
        return ""
    hostname = hostname.split(".", maxsplit=1)[0]
    return re.sub(r"[^a-z0-9-]+", "", hostname)


def normalize_version(value: object) -> str:
    return str(value or "").strip().lower()


def normalized_feature_set(features: list[str]) -> set[str]:
    return {normalize_identifier(feature) for feature in features if normalize_identifier(feature)}
