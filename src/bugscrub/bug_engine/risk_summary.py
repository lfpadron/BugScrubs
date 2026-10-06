from __future__ import annotations

from collections import defaultdict
from math import isclose
import re

from bugscrub.discrepancies.presentation import format_discrepancy_status


DISCREPANCY_WEIGHTS = {
    "discrepancia": 15,
    "faltante": 10,
    "nuevo": 8,
}

REMEDIATION_SCORE_WEIGHTS = {
    "affected": 1.0,
    "needs_review": 0.75,
    "fixed_in_target": 0.5,
    "already_fixed": 0.25,
}

SEVERITY_ORDER = {
    "critical": 0,
    "s1": 1,
    "s2": 2,
    "s3": 3,
    "s4": 4,
    "s5": 5,
    "low": 6,
    "other": 7,
}

SEVERITY_COLORS = {
    "critical": "#7F1D1D",
    "s1": "#B91C1C",
    "s2": "#DC2626",
    "s3": "#F97316",
    "s4": "#F59E0B",
    "s5": "#EAB308",
    "low": "#84CC16",
    "other": "#94A3B8",
}

BUG_TYPE_ORDER = {
    "bug": 0,
    "cve": 1,
    "field_notice": 2,
    "psirt": 3,
}


def build_inventory_overview_metrics(
    *,
    devices: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
    discrepancy_rows: list[dict[str, object]],
    bug_findings: list[dict[str, object]],
    customer_inventory_uploaded: bool,
) -> dict[str, object]:
    customer_inventory_count = len(inventory_rows) if customer_inventory_uploaded else None
    inconsistency_count = len(filter_discrepancy_pairs(discrepancy_rows, set()))
    discovered_devices_count = len(devices)
    devices_with_bugs = {
        str(finding.get("hostname", ""))
        for finding in bug_findings
        if finding.get("hostname")
    }
    unique_bug_count = len({str(finding.get("bug_id", "")) for finding in bug_findings if finding.get("bug_id")})

    return {
        "devices_in_inventory": customer_inventory_count,
        "discovered_devices": discovered_devices_count,
        "inconsistency_count": inconsistency_count if customer_inventory_uploaded else None,
        "inconsistency_percentage": percentage(inconsistency_count, customer_inventory_count),
        "devices_with_bugs_count": len(devices_with_bugs),
        "devices_with_bugs_percentage": percentage(len(devices_with_bugs), discovered_devices_count),
        "total_bugs_found": unique_bug_count,
        "total_bug_findings": len(bug_findings),
    }


def build_risk_dashboard_data(
    *,
    devices: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
    discrepancy_rows: list[dict[str, object]],
    bug_findings: list[dict[str, object]],
    platform_family: str = "All",
    platform_families: list[str] | None = None,
    hostnames: list[str] | None = None,
    severities: list[str] | None = None,
    features: list[str] | None = None,
    models: list[str] | None = None,
    versions: list[str] | None = None,
    firmwares: list[str] | None = None,
    bug_ids: list[str] | None = None,
    finding_types: list[str] | None = None,
    pareto_cumulative_threshold: int = 80,
) -> dict[str, object]:
    platform_families = platform_families or ([] if platform_family == "All" else [platform_family])
    hostnames = hostnames or []
    severities = severities or []
    features = features or []
    models = models or []
    versions = versions or []
    firmwares = firmwares or []
    bug_ids = bug_ids or []
    finding_types = finding_types or []

    selected_devices = filter_devices(
        devices=devices,
        inventory_rows=inventory_rows,
        platform_families=platform_families,
        hostnames=hostnames,
        features=features,
        models=models,
        versions=versions,
        firmwares=firmwares,
    )
    selected_hostnames = {str(device.get("hostname", "")) for device in selected_devices if device.get("hostname")}

    filtered_bug_findings = [
        enrich_bug_finding(finding)
        for finding in bug_findings
        if str(finding.get("hostname", "")) in selected_hostnames
        and (not bug_ids or str(finding.get("bug_id", "")) in bug_ids)
        and (not severities or str(finding.get("severity", "")) in severities)
        and (not finding_types or infer_finding_type(finding) in finding_types)
    ]
    filtered_pairs = filter_discrepancy_pairs(discrepancy_rows, selected_hostnames)

    bug_findings_by_host: dict[str, list[dict[str, object]]] = defaultdict(list)
    for finding in filtered_bug_findings:
        bug_findings_by_host[str(finding.get("hostname", ""))].append(finding)

    pair_map_by_host: dict[str, list[dict[str, object]]] = defaultdict(list)
    for pair in filtered_pairs:
        for hostname in pair["hostnames"]:
            pair_map_by_host[hostname].append(pair)

    device_summary_rows = []
    for device in selected_devices:
        hostname = str(device.get("hostname", ""))
        device_findings = bug_findings_by_host.get(hostname, [])
        device_pairs = pair_map_by_host.get(hostname, [])
        total_bug_score = sum(weighted_bug_score(finding) for finding in device_findings)
        discrepancy_penalty = sum(DISCREPANCY_WEIGHTS.get(pair["status"], 0) for pair in device_pairs)
        risk_score = total_bug_score + discrepancy_penalty

        severity_values = parse_severity_values(device_findings)
        top_bug = next(iter(sorted(device_findings, key=lambda row: -int(row.get("score", 0) or 0))), None)
        remediation_counts = count_remediation_statuses(device_findings)

        device_summary_rows.append(
            {
                "hostname": hostname,
                "platform_family": device.get("platform_family", ""),
                "model": device.get("model", ""),
                "os_version": device.get("os_version", ""),
                "features": list(device.get("features", [])),
                "bug_count": len(device_findings),
                "discrepancy_pairs": len(device_pairs),
                "highest_severity": str(min(severity_values)) if severity_values else "",
                "top_bug_id": top_bug.get("bug_id", "") if top_bug else "",
                "top_bug_score": int(top_bug.get("score", 0) or 0) if top_bug else 0,
                "affected_bug_count": remediation_counts.get("affected", 0),
                "fixed_in_target_count": remediation_counts.get("fixed_in_target", 0),
                "already_fixed_count": remediation_counts.get("already_fixed", 0),
                "needs_review_count": remediation_counts.get("needs_review", 0),
                "risk_score": risk_score,
                "risk_band": classify_risk_score(risk_score),
            }
        )

    device_summary_rows = sorted(
        device_summary_rows,
        key=lambda row: (-int(row["risk_score"]), str(row["hostname"])),
    )

    bug_summary_rows = build_bug_summary_rows(filtered_bug_findings)
    discrepancy_status_rows = build_discrepancy_status_rows(filtered_pairs)
    remediation_status_rows = build_remediation_status_rows(filtered_bug_findings)
    impacted_severity_rows = build_impacted_severity_rows(filtered_bug_findings)
    bug_severity_stack_rows = build_bug_severity_stack_rows(bug_summary_rows)
    platform_stack_rows = build_platform_stack_rows(filtered_bug_findings)
    treemap_rows = build_treemap_rows(bug_summary_rows)
    pareto_all_rows = build_pareto_quick_analysis_rows(
        bug_findings=filtered_bug_findings,
        device_summary_rows=device_summary_rows,
    )
    normalized_pareto_threshold = normalize_pareto_threshold(pareto_cumulative_threshold)
    pareto_rows = apply_pareto_threshold(
        pareto_all_rows,
        cumulative_threshold=normalized_pareto_threshold,
    )
    detailed_rows = build_detail_rows(
        selected_devices=selected_devices,
        filtered_bug_findings=filtered_bug_findings,
        filtered_pairs=filtered_pairs,
    )
    narrative_lines = build_narrative_lines(
        device_summary_rows=device_summary_rows,
        bug_summary_rows=bug_summary_rows,
        impacted_severity_rows=impacted_severity_rows,
        discrepancy_status_rows=discrepancy_status_rows,
        platform_stack_rows=platform_stack_rows,
    )

    impacted_devices = {
        str(finding.get("hostname", ""))
        for finding in filtered_bug_findings
        if finding.get("hostname")
    }

    return {
        "metrics": {
            "devices_in_scope": len(selected_devices),
            "bug_findings_in_scope": len(filtered_bug_findings),
            "discrepancy_pairs_in_scope": len(filtered_pairs),
            "affected_findings_in_scope": remediation_status_count(filtered_bug_findings, "affected"),
            "fixed_in_target_in_scope": remediation_status_count(filtered_bug_findings, "fixed_in_target"),
            "top_risk_device": device_summary_rows[0]["hostname"] if device_summary_rows else "",
            "impacted_devices_in_scope": len(impacted_devices),
            "pareto_cumulative_threshold": normalized_pareto_threshold,
        },
        "device_summary_rows": device_summary_rows,
        "bug_summary_rows": bug_summary_rows,
        "discrepancy_status_rows": discrepancy_status_rows,
        "remediation_status_rows": remediation_status_rows,
        "impacted_severity_rows": impacted_severity_rows,
        "bug_severity_stack_rows": bug_severity_stack_rows,
        "platform_stack_rows": platform_stack_rows,
        "treemap_rows": treemap_rows,
        "pareto_all_rows": pareto_all_rows,
        "pareto_rows": pareto_rows,
        "pareto_quick_analysis_rows": pareto_rows,
        "detailed_rows": detailed_rows,
        "filtered_discovered_devices": selected_devices,
        "filtered_discrepancy_pairs": filtered_pairs,
        "filtered_bug_findings": filtered_bug_findings,
        "narrative_lines": narrative_lines,
    }


def available_dashboard_filters(
    *,
    devices: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
    bug_findings: list[dict[str, object]],
) -> dict[str, list[str]]:
    platform_families = sorted({str(device.get("platform_family", "")) for device in devices if device.get("platform_family")})
    hostnames = sorted({str(device.get("hostname", "")) for device in devices if device.get("hostname")})
    severities = sorted(
        {str(finding.get("severity", "")) for finding in bug_findings if finding.get("severity")},
        key=severity_sort_key,
    )
    models = sorted({str(device.get("model", "")) for device in devices if device.get("model")})
    versions = sorted({str(device.get("os_version", "")) for device in devices if device.get("os_version")})
    firmware_versions = sorted({str(row.get("target_version", "")) for row in inventory_rows if row.get("target_version")})
    bug_ids = sorted({str(finding.get("bug_id", "")) for finding in bug_findings if finding.get("bug_id")})
    features = sorted(
        {
            str(feature)
            for device in devices
            for feature in list(device.get("features", []))
            if feature
        }
    )
    finding_types = sorted(
        {infer_finding_type(finding) for finding in bug_findings},
        key=lambda value: BUG_TYPE_ORDER.get(value, 99),
    )
    return {
        "platform_families": platform_families,
        "hostnames": hostnames,
        "severities": severities,
        "models": models,
        "versions": versions,
        "firmwares": firmware_versions,
        "bug_ids": bug_ids,
        "features": features,
        "finding_types": finding_types,
    }


def filter_devices(
    *,
    devices: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
    platform_families: list[str],
    hostnames: list[str],
    features: list[str],
    models: list[str],
    versions: list[str],
    firmwares: list[str],
) -> list[dict[str, object]]:
    firmware_by_host = build_firmware_map(inventory_rows)
    selected = []
    for device in devices:
        device_platform = str(device.get("platform_family", ""))
        device_hostname = str(device.get("hostname", ""))
        device_features = {str(feature) for feature in list(device.get("features", []))}
        device_model = str(device.get("model", ""))
        device_version = str(device.get("os_version", ""))
        device_firmwares = firmware_by_host.get(device_hostname, set())

        if platform_families and device_platform not in platform_families:
            continue
        if hostnames and device_hostname not in hostnames:
            continue
        if models and device_model not in models:
            continue
        if versions and device_version not in versions:
            continue
        if firmwares and not (set(firmwares) & device_firmwares):
            continue
        if features and not set(features).issubset(device_features):
            continue
        selected.append(device)
    return selected


def filter_discrepancy_pairs(
    discrepancy_rows: list[dict[str, object]],
    selected_hostnames: set[str],
) -> list[dict[str, object]]:
    pair_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in discrepancy_rows:
        pair_rows[str(row.get("pair_id", ""))].append(row)

    pairs = []
    for pair_id, rows in pair_rows.items():
        hostnames = {str(row.get("hostname", "")) for row in rows if row.get("hostname")}
        if selected_hostnames and not (hostnames & selected_hostnames):
            continue
        status = str(next((row.get("discrepancy_status", "") for row in rows if row.get("discrepancy_status")), ""))
        pairs.append({"pair_id": pair_id, "rows": rows, "hostnames": hostnames, "status": status})
    return sorted(pairs, key=lambda pair: pair["pair_id"])


def build_bug_summary_rows(bug_findings: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for finding in bug_findings:
        key = (str(finding.get("bug_id", "")), str(finding.get("headline", "")))
        if key not in grouped:
            grouped[key] = {
                "bug_id": key[0],
                "headline": key[1],
                "severity": str(finding.get("severity", "")),
                "severity_label": severity_label(finding.get("severity", "")),
                "severity_order": severity_order_value(finding.get("severity", "")),
                "finding_type": infer_finding_type(finding),
                "affected_devices": set(),
                "finding_count": 0,
                "total_score": 0,
                "platform_families": set(),
                "remediation_statuses": set(),
                "recommended_action": str(finding.get("recommended_action", "")),
            }
        grouped[key]["affected_devices"].add(str(finding.get("hostname", "")))
        grouped[key]["finding_count"] += 1
        grouped[key]["platform_families"].add(str(finding.get("platform_family", "")))
        remediation_status = str(finding.get("remediation_status", "")).strip()
        if remediation_status:
            grouped[key]["remediation_statuses"].add(remediation_status)
        grouped[key]["total_score"] += int(finding.get("score", 0) or 0)

    rows = []
    for group in grouped.values():
        rows.append(
            {
                "bug_id": group["bug_id"],
                "headline": group["headline"],
                "severity": group["severity"],
                "severity_label": group["severity_label"],
                "severity_order": group["severity_order"],
                "finding_type": group["finding_type"],
                "affected_device_count": len(group["affected_devices"]),
                "finding_count": group["finding_count"],
                "affected_devices": sorted(group["affected_devices"]),
                "platform_families": sorted(group["platform_families"]),
                "total_score": group["total_score"],
                "remediation_statuses": sorted(group.get("remediation_statuses", set())),
                "recommended_action": group["recommended_action"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["severity_order"],
            -int(row["affected_device_count"]),
            -int(row["total_score"]),
            str(row["bug_id"]),
        ),
    )


def build_discrepancy_status_rows(filtered_pairs: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: dict[str, int] = defaultdict(int)
    for pair in filtered_pairs:
        counts[format_discrepancy_status(pair["status"])] += 1
    return sorted(
        [{"status": status, "pair_count": count} for status, count in counts.items() if status],
        key=lambda row: str(row["status"]),
    )


def build_remediation_status_rows(bug_findings: list[dict[str, object]]) -> list[dict[str, object]]:
    counts = count_remediation_statuses(bug_findings)
    return sorted(
        [{"status": status, "finding_count": count} for status, count in counts.items() if status],
        key=lambda row: str(row["status"]),
    )


def build_impacted_severity_rows(bug_findings: list[dict[str, object]]) -> list[dict[str, object]]:
    impacted_hosts = {
        str(finding.get("hostname", ""))
        for finding in bug_findings
        if finding.get("hostname")
    }
    total_impacted = len(impacted_hosts)
    severity_hosts: dict[str, set[str]] = defaultdict(set)
    for finding in bug_findings:
        hostname = str(finding.get("hostname", ""))
        if not hostname:
            continue
        severity_hosts[severity_label(finding.get("severity", ""))].add(hostname)

    rows = []
    for label, hostnames in severity_hosts.items():
        rows.append(
            {
                "severity_label": label,
                "severity_order": SEVERITY_ORDER.get(label.lower(), 99),
                "impacted_device_count": len(hostnames),
                "percentage": percentage(len(hostnames), total_impacted),
            }
        )
    return sorted(rows, key=lambda row: (int(row["severity_order"]), str(row["severity_label"])))


def build_bug_severity_stack_rows(bug_summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in bug_summary_rows:
        grouped[str(row.get("severity_label", "Other"))].append(row)

    stack_rows: list[dict[str, object]] = []
    for severity_name, rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda row: (
                -int(row.get("affected_device_count", 0) or 0),
                -int(row.get("total_score", 0) or 0),
                str(row.get("bug_id", "")),
            ),
        )
        for order_rank, row in enumerate(ordered, start=1):
            stack_rows.append(
                {
                    "severity_label": severity_name,
                    "severity_order": SEVERITY_ORDER.get(severity_name.lower(), 99),
                    "bug_id": row.get("bug_id", ""),
                    "headline": row.get("headline", ""),
                    "affected_device_count": int(row.get("affected_device_count", 0) or 0),
                    "total_score": int(row.get("total_score", 0) or 0),
                    "stack_order": order_rank,
                }
            )
    return sorted(
        stack_rows,
        key=lambda row: (int(row["severity_order"]), int(row["stack_order"])),
    )


def build_platform_stack_rows(bug_findings: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    platform_totals: dict[str, int] = defaultdict(int)

    for finding in bug_findings:
        platform = str(finding.get("platform_family", "") or "unknown")
        severity = severity_label(finding.get("severity", ""))
        key = (platform, severity)
        if key not in grouped:
            grouped[key] = {
                "platform_family": platform,
                "severity_label": severity,
                "severity_order": SEVERITY_ORDER.get(severity.lower(), 99),
                "finding_count": 0,
            }
        grouped[key]["finding_count"] += 1
        platform_totals[platform] += 1

    ordered_platforms = sorted(platform_totals.items(), key=lambda item: (-item[1], item[0]))
    platform_rank = {platform: index for index, (platform, _) in enumerate(ordered_platforms, start=1)}

    rows = []
    for grouped_row in grouped.values():
        platform = str(grouped_row["platform_family"])
        rows.append(
            {
                **grouped_row,
                "platform_order": platform_rank.get(platform, 999),
                "platform_total_findings": platform_totals.get(platform, 0),
            }
        )
    return sorted(
        rows,
        key=lambda row: (int(row["platform_order"]), int(row["severity_order"])),
    )


def build_treemap_rows(bug_summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    severity_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in bug_summary_rows:
        severity_groups[str(row.get("severity_label", "Other"))].append(row)

    severity_items = [
        {
            "severity_label": severity_label_name,
            "severity_order": SEVERITY_ORDER.get(severity_label_name.lower(), 99),
            "value": sum(int(row.get("affected_device_count", 0) or 0) for row in rows),
            "rows": rows,
        }
        for severity_label_name, rows in severity_groups.items()
        if rows
    ]
    severity_items = sorted(severity_items, key=lambda row: (int(row["severity_order"]), -int(row["value"])))
    total_value = sum(int(item["value"]) for item in severity_items)
    if total_value <= 0:
        return []

    treemap_rows: list[dict[str, object]] = []
    cursor_x = 0.0
    for item in severity_items:
        width = float(item["value"]) / total_value
        x0 = cursor_x
        x1 = cursor_x + width
        cursor_y = 0.0
        child_total = sum(int(row.get("affected_device_count", 0) or 0) for row in item["rows"])
        ordered_children = sorted(
            item["rows"],
            key=lambda row: (
                -int(row.get("affected_device_count", 0) or 0),
                -int(row.get("total_score", 0) or 0),
                str(row.get("bug_id", "")),
            ),
        )
        for child in ordered_children:
            child_value = int(child.get("affected_device_count", 0) or 0)
            if child_total <= 0 or child_value <= 0:
                continue
            height = child_value / child_total
            y0 = cursor_y
            y1 = cursor_y + height
            treemap_rows.append(
                {
                    "severity_label": item["severity_label"],
                    "severity_order": item["severity_order"],
                    "bug_id": child.get("bug_id", ""),
                    "headline": child.get("headline", ""),
                    "finding_type": child.get("finding_type", ""),
                    "affected_device_count": child_value,
                    "total_score": int(child.get("total_score", 0) or 0),
                    "x0": round(x0, 6),
                    "x1": round(x1, 6),
                    "y0": round(y0, 6),
                    "y1": round(y1, 6),
                }
            )
            cursor_y = y1
        cursor_x = x1

    if treemap_rows and not isclose(float(treemap_rows[-1]["x1"]), 1.0):
        treemap_rows[-1]["x1"] = 1.0
    return treemap_rows


def build_pareto_quick_analysis_rows(
    *,
    bug_findings: list[dict[str, object]],
    device_summary_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    device_risk_map = {
        str(row.get("hostname", "")): int(row.get("risk_score", 0) or 0)
        for row in device_summary_rows
        if row.get("hostname")
    }
    grouped: dict[tuple[str, str], dict[str, object]] = {}

    for finding in bug_findings:
        bug_id = str(finding.get("bug_id", ""))
        headline = str(finding.get("headline", ""))
        key = (bug_id, headline)
        if key not in grouped:
            grouped[key] = {
                "bug_id": bug_id,
                "headline": headline,
                "finding_type": infer_finding_type(finding),
                "platform_families": set(),
                "finding_count": 0,
                "affected_devices": set(),
                "remediation_statuses": set(),
                "recommended_actions": set(),
            }

        hostname = str(finding.get("hostname", ""))
        if hostname:
            grouped[key]["affected_devices"].add(hostname)
        platform_family = str(finding.get("platform_family", "")).strip()
        if platform_family:
            grouped[key]["platform_families"].add(platform_family)
        remediation_status = str(finding.get("remediation_status", "")).strip()
        if remediation_status:
            grouped[key]["remediation_statuses"].add(remediation_status)
        recommended_action = str(finding.get("recommended_action", "")).strip()
        if recommended_action:
            grouped[key]["recommended_actions"].add(recommended_action)
        grouped[key]["finding_count"] += 1

    rows: list[dict[str, object]] = []
    for group in grouped.values():
        affected_devices = sorted(group["affected_devices"])
        total_risk_score = sum(device_risk_map.get(hostname, 0) for hostname in affected_devices)
        rows.append(
            {
                "bug_id": group["bug_id"],
                "headline": group["headline"],
                "total_risk_score": total_risk_score,
                "finding_type": group["finding_type"],
                "platform_family": ", ".join(sorted(group["platform_families"])) or "unknown",
                "finding_count": int(group["finding_count"]),
                "affected_devices": affected_devices,
                "affected_device_count": len(affected_devices),
                "remediation_status": ", ".join(sorted(group["remediation_statuses"])) or "-",
                "recommended_actions": sorted(group["recommended_actions"]),
            }
        )

    ordered_rows = sorted(
        rows,
        key=lambda row: (
            -int(row.get("total_risk_score", 0) or 0),
            -int(row.get("finding_count", 0) or 0),
            str(row.get("bug_id", "")),
        ),
    )
    total_risk = sum(int(row.get("total_risk_score", 0) or 0) for row in ordered_rows)
    running_total = 0
    for rank, row in enumerate(ordered_rows, start=1):
        running_total += int(row.get("total_risk_score", 0) or 0)
        row["cumulative_percentage"] = (running_total / total_risk * 100.0) if total_risk else 0.0
        row["sort_rank"] = rank
    return ordered_rows


def apply_pareto_threshold(
    pareto_rows: list[dict[str, object]],
    *,
    cumulative_threshold: int,
) -> list[dict[str, object]]:
    if not pareto_rows:
        return []

    if cumulative_threshold >= 100:
        return [dict(row) for row in pareto_rows]

    selected_rows: list[dict[str, object]] = []
    for row in pareto_rows:
        selected_rows.append(dict(row))
        if float(row.get("cumulative_percentage", 0.0) or 0.0) >= cumulative_threshold:
            break
    return selected_rows


def normalize_pareto_threshold(value: int | float | str | None) -> int:
    try:
        threshold = int(float(value or 0))
    except Exception:
        threshold = 80
    return max(10, min(threshold, 100))


def build_detail_rows(
    *,
    selected_devices: list[dict[str, object]],
    filtered_bug_findings: list[dict[str, object]],
    filtered_pairs: list[dict[str, object]],
) -> list[dict[str, object]]:
    devices_by_hostname = {
        str(device.get("hostname", "")): device
        for device in selected_devices
        if device.get("hostname")
    }
    discrepancy_count_by_host: dict[str, int] = defaultdict(int)
    for pair in filtered_pairs:
        for hostname in pair["hostnames"]:
            discrepancy_count_by_host[hostname] += 1

    rows: list[dict[str, object]] = []
    if filtered_bug_findings:
        for finding in filtered_bug_findings:
            hostname = str(finding.get("hostname", ""))
            device = devices_by_hostname.get(hostname, {})
            rows.append(
                {
                    "hostname": hostname,
                    "platform_family": device.get("platform_family", finding.get("platform_family", "")),
                    "model": device.get("model", ""),
                    "current_version": device.get("os_version", finding.get("current_version", "")),
                    "features": list(device.get("features", [])),
                    "finding_type": infer_finding_type(finding),
                    "severity": str(finding.get("severity", "")),
                    "bug_id": str(finding.get("bug_id", "")),
                    "headline": str(finding.get("headline", "")),
                    "score": int(finding.get("score", 0) or 0),
                    "remediation_status": str(finding.get("remediation_status", "")),
                    "matched_on": list(finding.get("matched_on", [])),
                    "recommended_action": str(finding.get("recommended_action", "")),
                    "discrepancy_pairs": discrepancy_count_by_host.get(hostname, 0),
                }
            )
        return sorted(rows, key=lambda row: (-int(row["score"]), str(row["hostname"]), str(row["bug_id"])))

    for device in selected_devices:
        hostname = str(device.get("hostname", ""))
        rows.append(
            {
                "hostname": hostname,
                "platform_family": device.get("platform_family", ""),
                "model": device.get("model", ""),
                "current_version": device.get("os_version", ""),
                "features": list(device.get("features", [])),
                "finding_type": "",
                "severity": "",
                "bug_id": "",
                "headline": "",
                "score": 0,
                "remediation_status": "",
                "matched_on": [],
                "recommended_action": "",
                "discrepancy_pairs": discrepancy_count_by_host.get(hostname, 0),
            }
        )
    return sorted(rows, key=lambda row: str(row["hostname"]))


def build_narrative_lines(
    *,
    device_summary_rows: list[dict[str, object]],
    bug_summary_rows: list[dict[str, object]],
    impacted_severity_rows: list[dict[str, object]],
    discrepancy_status_rows: list[dict[str, object]],
    platform_stack_rows: list[dict[str, object]],
) -> list[str]:
    lines: list[str] = []
    if device_summary_rows:
        top_device = device_summary_rows[0]
        lines.append(
            f"{top_device.get('hostname', '')} is the highest-priority device based on combined risk score, "
            f"bug load, and discrepancy pressure."
        )
    if bug_summary_rows:
        top_bug = bug_summary_rows[0]
        lines.append(
            f"{top_bug.get('bug_id', '')} is currently the most widespread finding, affecting "
            f"{top_bug.get('affected_device_count', 0)} device(s)."
        )
    if impacted_severity_rows:
        highest_severity = impacted_severity_rows[0]
        lines.append(
            f"The highest active severity bucket is {highest_severity.get('severity_label', '')}, "
            f"covering {highest_severity.get('impacted_device_count', 0)} impacted device(s)."
        )
    if discrepancy_status_rows:
        top_discrepancy = sorted(discrepancy_status_rows, key=lambda row: -int(row.get("pair_count", 0) or 0))[0]
        lines.append(
            f"The most common inconsistency class is `{top_discrepancy.get('status', '')}` with "
            f"{top_discrepancy.get('pair_count', 0)} pair(s)."
        )
    if platform_stack_rows:
        platform_totals: dict[str, int] = defaultdict(int)
        for row in platform_stack_rows:
            platform_totals[str(row.get("platform_family", ""))] += int(row.get("finding_count", 0) or 0)
        if platform_totals:
            platform_name = sorted(platform_totals.items(), key=lambda item: (-item[1], item[0]))[0][0]
            lines.append(f"{platform_name} currently carries the highest overall bug volume in scope.")
    if not lines:
        lines.append("No prioritized vulnerability narrative is available for the current filters.")
    return lines


def classify_risk_score(score: int) -> str:
    if score >= 70:
        return "High"
    if score >= 35:
        return "Medium"
    if score > 0:
        return "Low"
    return "None"


def parse_severity_values(device_findings: list[dict[str, object]]) -> list[int]:
    values: list[int] = []
    for finding in device_findings:
        try:
            values.append(int(str(finding.get("severity", "")).strip()))
        except Exception:
            continue
    return values


def remediation_status_count(bug_findings: list[dict[str, object]], status: str) -> int:
    return count_remediation_statuses(bug_findings).get(status, 0)


def count_remediation_statuses(bug_findings: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for finding in bug_findings:
        remediation_status = str(finding.get("remediation_status", "")).strip()
        if remediation_status:
            counts[remediation_status] += 1
    return counts


def weighted_bug_score(finding: dict[str, object]) -> int:
    raw_score = int(finding.get("score", 0) or 0)
    remediation_status = str(finding.get("remediation_status", "")).strip()
    weight = REMEDIATION_SCORE_WEIGHTS.get(remediation_status, 1.0)
    return int(round(raw_score * weight))


def build_firmware_map(inventory_rows: list[dict[str, object]]) -> dict[str, set[str]]:
    firmware_by_host: dict[str, set[str]] = defaultdict(set)
    for row in inventory_rows:
        hostname = str(row.get("hostname", "")).strip()
        target_version = str(row.get("target_version", "")).strip()
        if hostname and target_version:
            firmware_by_host[hostname].add(target_version)
    return firmware_by_host


def infer_finding_type(finding: dict[str, object]) -> str:
    explicit_type = normalize_finding_type(str(finding.get("finding_type", "")))
    if explicit_type:
        return explicit_type

    bug_id = str(finding.get("bug_id", "")).strip().lower()
    headline = str(finding.get("headline", "")).strip().lower()
    if bug_id.startswith("cve-") or "cve-" in headline:
        return "cve"
    if bug_id.startswith("fn") or "field notice" in headline:
        return "field_notice"
    if bug_id.startswith("psirt") or "psirt" in headline:
        return "psirt"
    return "bug"


def normalize_finding_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if normalized in {"bug", "bugs"}:
        return "bug"
    if normalized in {"cve", "cves"}:
        return "cve"
    if normalized in {"field_notice", "field_notices", "fieldnotice", "fieldnotices", "fn"}:
        return "field_notice"
    if normalized in {"psirt"}:
        return "psirt"
    return normalized


def enrich_bug_finding(finding: dict[str, object]) -> dict[str, object]:
    enriched = dict(finding)
    enriched["finding_type"] = infer_finding_type(enriched)
    enriched["severity_label"] = severity_label(enriched.get("severity", ""))
    enriched["severity_order"] = severity_order_value(enriched.get("severity", ""))
    return enriched


def severity_label(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"critical", "critico", "crítico"}:
        return "Critical"
    if normalized.isdigit():
        return f"S{normalized}"
    if normalized.startswith("s") and normalized[1:].isdigit():
        return normalized.upper()
    if normalized == "low":
        return "Low"
    return "Other"


def severity_order_value(value: object) -> int:
    return SEVERITY_ORDER.get(severity_label(value).lower(), 99)


def severity_sort_key(value: str) -> tuple[int, str]:
    return severity_order_value(value), str(value)


def percentage(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return round((numerator / denominator) * 100.0, 2)
