from __future__ import annotations

from dataclasses import dataclass, field
import re

from bugscrub.bug_engine.dataset import load_internal_bug_dataset
from bugscrub.normalization.models import DeviceRecord, InventoryBatch, InventoryRowRecord


REMEDIATION_SCORE_MULTIPLIERS = {
    "affected": 1.0,
    "needs_review": 0.75,
    "fixed_in_target": 0.5,
    "already_fixed": 0.25,
}


@dataclass(slots=True)
class BugRecord:
    bug_id: str
    headline: str
    product_scope: str
    affected_releases: list[str]
    fixed_releases: list[str]
    trigger_features: list[str]
    severity: str
    recommended_action: str
    platform_pids: list[str] = field(default_factory=list)
    required_features: list[str] = field(default_factory=list)
    optional_features: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return {
            "bug_id": self.bug_id,
            "headline": self.headline,
            "product_scope": self.product_scope,
            "affected_releases": list(self.affected_releases),
            "fixed_releases": list(self.fixed_releases),
            "trigger_features": list(self.trigger_features),
            "platform_pids": list(self.platform_pids),
            "required_features": list(self.required_features),
            "optional_features": list(self.optional_features),
            "severity": self.severity,
            "recommended_action": self.recommended_action,
        }


@dataclass(slots=True)
class ReleaseMatch:
    matched: bool = False
    match_type: str = "none"
    matched_expression: str = ""
    rationale: str = ""


@dataclass(slots=True)
class RemediationAssessment:
    status: str
    rationale: list[str] = field(default_factory=list)
    version_match_type: str = ""
    matched_release: str = ""


@dataclass(slots=True)
class BugFinding:
    session_id: str
    hostname: str
    platform_family: str
    bug_id: str
    headline: str
    severity: str
    score: int
    current_version: str = ""
    target_version: str = ""
    remediation_status: str = ""
    version_match_type: str = ""
    matched_release: str = ""
    matched_on: list[str] = field(default_factory=list)
    fixed_releases: list[str] = field(default_factory=list)
    recommended_action: str = ""
    rationale: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "hostname": self.hostname,
            "platform_family": self.platform_family,
            "bug_id": self.bug_id,
            "headline": self.headline,
            "severity": self.severity,
            "score": self.score,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "remediation_status": self.remediation_status,
            "version_match_type": self.version_match_type,
            "matched_release": self.matched_release,
            "matched_on": list(self.matched_on),
            "fixed_releases": list(self.fixed_releases),
            "recommended_action": self.recommended_action,
            "rationale": list(self.rationale),
        }


class BugEngine:
    """Improved internal bug correlation engine with remediation assessment."""

    def __init__(self, bug_records: list[dict[str, object]] | None = None) -> None:
        records = load_internal_bug_dataset() if bug_records is None else bug_records
        self.bug_records = [BugRecord(**self._prepare_record(record)) for record in records]

    def run(self, inventory: InventoryBatch) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for device in inventory.devices:
            matching_inventory_row = match_inventory_row(device, inventory.inventory_rows)
            target_version = matching_inventory_row.target_version if matching_inventory_row else ""

            for bug in self.bug_records:
                matched_on: list[str] = []
                rationale: list[str] = []

                platform_match = evaluate_platform_match(device, bug)
                if not platform_match.matched:
                    continue
                matched_on.extend(platform_match_tokens(platform_match))
                if platform_match.rationale:
                    rationale.append(platform_match.rationale)

                feature_match = evaluate_feature_match(device.features, bug)
                if feature_match is None:
                    continue
                matched_on.extend(feature_match.matched_on)
                rationale.extend(feature_match.rationale)

                remediation = assess_remediation(
                    current_version=device.os_version,
                    target_version=target_version,
                    bug=bug,
                )
                if remediation.status == "not_applicable":
                    continue

                if remediation.rationale:
                    rationale.extend(remediation.rationale)
                if remediation.status in {"affected", "needs_review"}:
                    matched_on.append("version")
                if remediation.status == "fixed_in_target":
                    matched_on.append("target_version")
                if remediation.status == "already_fixed":
                    matched_on.append("fixed_release")

                findings.append(
                    BugFinding(
                        session_id=inventory.session_id,
                        hostname=device.hostname,
                        platform_family=device.platform_family,
                        bug_id=bug.bug_id,
                        headline=bug.headline,
                        severity=bug.severity,
                        score=score_bug(
                            severity=bug.severity,
                            matched_on=matched_on,
                            remediation_status=remediation.status,
                        ),
                        current_version=device.os_version,
                        target_version=target_version,
                        remediation_status=remediation.status,
                        version_match_type=remediation.version_match_type,
                        matched_release=remediation.matched_release,
                        matched_on=dedupe_preserve_order(matched_on),
                        fixed_releases=list(bug.fixed_releases),
                        recommended_action=bug.recommended_action,
                        rationale=dedupe_preserve_order(rationale),
                    )
                )

        return sorted(findings, key=lambda finding: (finding.hostname, -finding.score, finding.bug_id))

    def _prepare_record(self, record: dict[str, object]) -> dict[str, object]:
        prepared = dict(record)
        prepared.setdefault("platform_pids", [])
        prepared.setdefault("required_features", [])
        prepared.setdefault("optional_features", [])
        prepared.setdefault("trigger_features", [])
        prepared.setdefault("fixed_releases", [])
        prepared.setdefault("affected_releases", [])
        return prepared


@dataclass(slots=True)
class PlatformMatch:
    matched: bool
    family_match: bool = False
    pid_match: bool = False
    rationale: str = ""


@dataclass(slots=True)
class FeatureMatch:
    matched_on: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)


def match_inventory_row(device: DeviceRecord, inventory_rows: list[InventoryRowRecord]) -> InventoryRowRecord | None:
    device_hostname = normalize_identifier(device.hostname)
    device_serial = normalize_identifier(device.serial)
    device_pid = normalize_identifier(device.pid)

    for row in inventory_rows:
        if device_serial and normalize_identifier(row.serial) == device_serial:
            return row
    for row in inventory_rows:
        if device_hostname and normalize_identifier(row.hostname) == device_hostname:
            return row
    for row in inventory_rows:
        if device_pid and normalize_identifier(row.pid) == device_pid:
            return row
    return None


def evaluate_platform_match(device: DeviceRecord, bug: BugRecord) -> PlatformMatch:
    device_family = normalize_identifier(device.platform_family)
    bug_family = normalize_identifier(bug.product_scope)
    if bug_family and device_family != bug_family:
        return PlatformMatch(matched=False)

    if bug.platform_pids:
        pid_match = any(pid_matches_pattern(device.pid, pattern) for pattern in bug.platform_pids)
        if not pid_match:
            return PlatformMatch(matched=False)
        return PlatformMatch(
            matched=True,
            family_match=True,
            pid_match=True,
            rationale=f"Platform family and PID match: {device.platform_family} / {device.pid}.",
        )

    return PlatformMatch(
        matched=True,
        family_match=True,
        rationale=f"Platform family match: {device.platform_family}.",
    )


def platform_match_tokens(match: PlatformMatch) -> list[str]:
    tokens: list[str] = []
    if match.family_match:
        tokens.append("platform")
    if match.pid_match:
        tokens.append("pid")
    return tokens


def evaluate_feature_match(device_features: list[str], bug: BugRecord) -> FeatureMatch | None:
    normalized_device_features = {normalize_feature(feature): feature for feature in device_features if feature}

    required_features = [feature for feature in bug.required_features if feature]
    optional_features = [feature for feature in bug.optional_features if feature]
    legacy_trigger_features = [feature for feature in bug.trigger_features if feature]

    match = FeatureMatch()

    if required_features:
        missing_required = [
            feature for feature in required_features if normalize_feature(feature) not in normalized_device_features
        ]
        if missing_required:
            return None
        match.matched_on.append("required_features")
        match.rationale.append(f"Required features present: {', '.join(required_features)}.")

    shared_optional = [
        normalized_device_features[normalize_feature(feature)]
        for feature in optional_features
        if normalize_feature(feature) in normalized_device_features
    ]
    if shared_optional:
        match.matched_on.append("optional_features")
        match.rationale.append(f"Optional feature match: {', '.join(shared_optional)}.")

    shared_trigger = [
        normalized_device_features[normalize_feature(feature)]
        for feature in legacy_trigger_features
        if normalize_feature(feature) in normalized_device_features
    ]
    if legacy_trigger_features and not required_features and not shared_trigger:
        return None
    if shared_trigger:
        match.matched_on.append("features")
        match.rationale.append(f"Feature match: {', '.join(shared_trigger)}.")

    return match


def assess_remediation(*, current_version: str, target_version: str, bug: BugRecord) -> RemediationAssessment:
    affected_current = evaluate_release_against_expressions(current_version, bug.affected_releases)
    affected_target = evaluate_release_against_expressions(target_version, bug.affected_releases) if target_version else ReleaseMatch()
    fixed_current = evaluate_fixed_release_posture(current_version, bug.fixed_releases)
    fixed_target = evaluate_fixed_release_posture(target_version, bug.fixed_releases) if target_version else ReleaseMatch()

    rationale: list[str] = []
    if affected_current.matched:
        rationale.append(affected_current.rationale)
        if target_version:
            if fixed_target.matched:
                rationale.append(fixed_target.rationale or f"Target release `{target_version}` appears fixed.")
                return RemediationAssessment(
                    status="fixed_in_target",
                    rationale=dedupe_preserve_order(rationale),
                    version_match_type=affected_current.match_type,
                    matched_release=affected_current.matched_expression,
                )
            if affected_target.matched:
                rationale.append(
                    affected_target.rationale
                    or f"Target release `{target_version}` is still within the affected release scope."
                )
            return RemediationAssessment(
                status="affected",
                rationale=dedupe_preserve_order(rationale),
                version_match_type=affected_current.match_type,
                matched_release=affected_current.matched_expression,
            )
        return RemediationAssessment(
            status="affected",
            rationale=dedupe_preserve_order(rationale),
            version_match_type=affected_current.match_type,
            matched_release=affected_current.matched_expression,
        )

    if fixed_current.matched:
        rationale.append(fixed_current.rationale or f"Current release `{current_version}` appears fixed.")
        return RemediationAssessment(
            status="already_fixed",
            rationale=dedupe_preserve_order(rationale),
            version_match_type=fixed_current.match_type,
            matched_release=fixed_current.matched_expression,
        )

    review_matches = [match for match in [affected_current, affected_target, fixed_current, fixed_target] if match.match_type == "review"]
    if review_matches:
        rationale.extend([match.rationale for match in review_matches if match.rationale])
        return RemediationAssessment(
            status="needs_review",
            rationale=dedupe_preserve_order(rationale),
            version_match_type=review_matches[0].match_type,
            matched_release=review_matches[0].matched_expression,
        )

    return RemediationAssessment(status="not_applicable")


def evaluate_release_against_expressions(version: str, expressions: list[str]) -> ReleaseMatch:
    normalized_version = normalize_release(version)
    if not normalized_version or not expressions:
        return ReleaseMatch()

    for expression in expressions:
        release_match = evaluate_release_expression(normalized_version, expression)
        if release_match.matched:
            return release_match
        if release_match.match_type == "review":
            return release_match
    return ReleaseMatch()


def evaluate_fixed_release_posture(version: str, fixed_releases: list[str]) -> ReleaseMatch:
    normalized_version = normalize_release(version)
    if not normalized_version or not fixed_releases:
        return ReleaseMatch()

    direct_match = evaluate_release_against_expressions(normalized_version, fixed_releases)
    if direct_match.matched or direct_match.match_type == "review":
        return direct_match

    for expression in fixed_releases:
        normalized_expression = normalize_release(expression)
        if split_release_range(normalized_expression) is not None:
            continue
        if any(normalized_expression.startswith(operator) for operator in [">=", "<=", ">", "<"]):
            continue
        if normalized_expression.endswith("*") or normalized_expression.endswith("x"):
            continue
        comparator = compare_release_values(normalized_version, expression)
        if comparator is None:
            continue
        if comparator >= 0:
            return ReleaseMatch(
                matched=True,
                match_type="at_or_after_fixed",
                matched_expression=expression,
                rationale=f"Current or target release `{version}` is at or after fixed release `{expression}`.",
            )
    return ReleaseMatch()


def evaluate_release_expression(version: str, expression: str) -> ReleaseMatch:
    normalized_expression = normalize_release(expression)
    if not normalized_expression:
        return ReleaseMatch()

    if any(operator in normalized_expression for operator in [">=", "<=", ">", "<"]):
        return evaluate_comparator_expression(version, normalized_expression)

    range_parts = split_release_range(normalized_expression)
    if range_parts is not None:
        start, end = range_parts
        if not start or not end:
            return ReleaseMatch(
                matched=False,
                match_type="review",
                matched_expression=expression,
                rationale=f"Could not interpret release range `{expression}`.",
            )
        start_compare = compare_release_values(version, start)
        end_compare = compare_release_values(version, end)
        if start_compare is None or end_compare is None:
            return ReleaseMatch(
                matched=False,
                match_type="review",
                matched_expression=expression,
                rationale=f"Release range `{expression}` needs manual review.",
            )
        if start_compare >= 0 and end_compare <= 0:
            return ReleaseMatch(
                matched=True,
                match_type="range",
                matched_expression=expression,
                rationale=f"Release `{version}` falls within affected range `{expression}`.",
            )
        return ReleaseMatch()

    if normalized_expression.endswith("*"):
        prefix = normalized_expression[:-1]
        if version.startswith(prefix):
            return ReleaseMatch(
                matched=True,
                match_type="prefix",
                matched_expression=expression,
                rationale=f"Release `{version}` matches version family `{expression}`.",
            )
        return ReleaseMatch()

    if normalized_expression.endswith("x"):
        prefix = normalized_expression[:-1]
        if version.startswith(prefix):
            return ReleaseMatch(
                matched=True,
                match_type="prefix",
                matched_expression=expression,
                rationale=f"Release `{version}` matches version family `{expression}`.",
            )
        return ReleaseMatch()

    comparator = compare_release_values(version, normalized_expression)
    if comparator is None:
        return ReleaseMatch(
            matched=False,
            match_type="review",
            matched_expression=expression,
            rationale=f"Release `{version}` could not be normalized against `{expression}`.",
        )
    if comparator == 0:
        return ReleaseMatch(
            matched=True,
            match_type="exact",
            matched_expression=expression,
            rationale=f"Affected release match: {version}.",
        )
    return ReleaseMatch()


def evaluate_comparator_expression(version: str, expression: str) -> ReleaseMatch:
    operator = next((candidate for candidate in [">=", "<=", ">", "<"] if expression.startswith(candidate)), "")
    release_value = expression[len(operator):].strip()
    comparator = compare_release_values(version, release_value)
    if comparator is None:
        return ReleaseMatch(
            matched=False,
            match_type="review",
            matched_expression=expression,
            rationale=f"Comparator expression `{expression}` needs manual review.",
        )

    is_match = (
        (operator == ">=" and comparator >= 0)
        or (operator == "<=" and comparator <= 0)
        or (operator == ">" and comparator > 0)
        or (operator == "<" and comparator < 0)
    )
    if is_match:
        return ReleaseMatch(
            matched=True,
            match_type="comparator",
            matched_expression=expression,
            rationale=f"Release `{version}` matches comparator `{expression}`.",
        )
    return ReleaseMatch()


def split_release_range(expression: str) -> tuple[str, str] | None:
    for separator in [" - ", " to ", ".."]:
        if separator in expression:
            left, right = expression.split(separator, maxsplit=1)
            return left.strip(), right.strip()
    if "-" in expression and expression.count("-") == 1 and not expression.startswith("-"):
        left, right = expression.split("-", maxsplit=1)
        if left and right and any(character.isdigit() for character in left + right):
            return left.strip(), right.strip()
    return None


def compare_release_values(left: str, right: str) -> int | None:
    left_tokens = tokenize_release(left)
    right_tokens = tokenize_release(right)
    if not left_tokens or not right_tokens:
        return None

    max_length = max(len(left_tokens), len(right_tokens))
    for index in range(max_length):
        left_token = left_tokens[index] if index < len(left_tokens) else ("num", 0)
        right_token = right_tokens[index] if index < len(right_tokens) else ("num", 0)

        if left_token == right_token:
            continue

        if left_token[0] == right_token[0] == "num":
            return -1 if int(left_token[1]) < int(right_token[1]) else 1
        if left_token[0] == right_token[0] == "str":
            return -1 if str(left_token[1]) < str(right_token[1]) else 1
        if left_token[0] == "num":
            return 1
        return -1
    return 0


def tokenize_release(value: str) -> list[tuple[str, int | str]]:
    normalized = normalize_release(value)
    if not normalized:
        return []

    tokens = re.findall(r"[0-9]+|[a-z]+", normalized)
    parsed_tokens: list[tuple[str, int | str]] = []
    for token in tokens:
        if token.isdigit():
            parsed_tokens.append(("num", int(token)))
        else:
            parsed_tokens.append(("str", token))
    return parsed_tokens


def normalize_release(value: str) -> str:
    return str(value or "").strip().lower()


def pid_matches_pattern(pid: str, pattern: str) -> bool:
    normalized_pid = normalize_identifier(pid)
    normalized_pattern = str(pattern or "").strip().lower()
    has_wildcard = normalized_pattern.endswith("*")
    if has_wildcard:
        normalized_pattern = normalize_identifier(normalized_pattern[:-1])
    else:
        normalized_pattern = normalize_identifier(normalized_pattern)
    if not normalized_pid or not normalized_pattern:
        return False
    if has_wildcard:
        return normalized_pid.startswith(normalized_pattern)
    return normalized_pid == normalized_pattern


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def normalize_feature(value: str) -> str:
    return normalize_identifier(value)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def score_bug(*, severity: str, matched_on: list[str], remediation_status: str = "") -> int:
    try:
        severity_value = int(severity)
    except Exception:
        severity_value = 4

    severity_score = max(1, 7 - severity_value)
    match_score = len(set(matched_on))
    base_score = severity_score * 10 + match_score * 5
    multiplier = REMEDIATION_SCORE_MULTIPLIERS.get(remediation_status or "", 1.0)
    return max(1, int(round(base_score * multiplier)))
