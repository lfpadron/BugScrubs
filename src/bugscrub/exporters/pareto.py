from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageFont


CHART_WIDTH = 1280
CHART_HEIGHT = 720
CHART_MARGIN_LEFT = 110
CHART_MARGIN_RIGHT = 80
CHART_MARGIN_TOP = 180
CHART_MARGIN_BOTTOM = 150
MAX_PARETO_ITEMS = 20


@dataclass(slots=True)
class ParetoChartAsset:
    jpeg_bytes: bytes
    width: int
    height: int
    title: str


def build_pareto_chart_asset(
    *,
    pareto_rows: list[dict[str, object]],
    filter_summary: dict[str, object],
    title: str = "Pareto of Bug Remediation Impact",
) -> ParetoChartAsset:
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), color="white")
    draw = ImageDraw.Draw(image)
    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()

    draw.text((40, 32), title, fill="black", font=font_title)
    draw.text((40, 58), "Bugs sorted by total impacted-device risk. The cumulative line shows the risk coverage reached.", fill="black", font=font_body)

    filter_lines = format_filter_lines(filter_summary)
    y_position = 86
    for line in filter_lines:
        draw.text((40, y_position), line, fill="#333333", font=font_body)
        y_position += 18

    display_rows = condense_pareto_rows(pareto_rows)
    if not display_rows:
        draw.rectangle((CHART_MARGIN_LEFT, CHART_MARGIN_TOP, CHART_WIDTH - CHART_MARGIN_RIGHT, CHART_HEIGHT - CHART_MARGIN_BOTTOM), outline="#999999", width=2)
        draw.text((CHART_MARGIN_LEFT + 40, CHART_MARGIN_TOP + 80), "No pareto bug data is available for the current filters.", fill="black", font=font_body)
        return encode_jpeg(image, title=title)

    chart_left = CHART_MARGIN_LEFT
    chart_top = CHART_MARGIN_TOP
    chart_right = CHART_WIDTH - CHART_MARGIN_RIGHT
    chart_bottom = CHART_HEIGHT - CHART_MARGIN_BOTTOM
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    draw.line((chart_left, chart_top, chart_left, chart_bottom), fill="black", width=2)
    draw.line((chart_left, chart_bottom, chart_right, chart_bottom), fill="black", width=2)

    max_count = max(int(row.get("total_risk_score", 0) or 0) for row in display_rows)
    max_count = max(max_count, 1)
    tick_count = min(max_count, 5)
    for tick_index in range(tick_count + 1):
        tick_value = ceil(max_count * tick_index / tick_count) if tick_count else 0
        y_tick = chart_bottom - (chart_height * tick_index / tick_count if tick_count else 0)
        draw.line((chart_left - 6, y_tick, chart_left, y_tick), fill="black", width=1)
        draw.text((chart_left - 44, y_tick - 6), str(tick_value), fill="black", font=font_body)

    bar_width = chart_width / max(len(display_rows), 1)
    cumulative_points: list[tuple[float, float]] = []
    for index, row in enumerate(display_rows):
        bug_label = format_pareto_axis_label(
            bug_id=str(row.get("bug_id", "")),
            rank=int(row.get("sort_rank", index + 1) or index + 1),
        )
        finding_count = int(row.get("total_risk_score", 0) or 0)
        cumulative_percentage = float(row.get("cumulative_percentage", 0.0) or 0.0)
        bar_height = (finding_count / max_count) * chart_height

        x0 = chart_left + index * bar_width + 10
        x1 = chart_left + (index + 1) * bar_width - 16
        y0 = chart_bottom - bar_height
        y1 = chart_bottom
        draw.rectangle((x0, y0, x1, y1), fill="#4C78A8", outline="#2F4B6E")
        draw.text((x0, y0 - 16), str(finding_count), fill="black", font=font_body)
        draw.multiline_text((x0, chart_bottom + 12), bug_label, fill="black", font=font_body, spacing=2)

        cumulative_x = chart_left + index * bar_width + (bar_width / 2)
        cumulative_y = chart_bottom - ((cumulative_percentage / 100.0) * chart_height)
        cumulative_points.append((cumulative_x, cumulative_y))

    if len(cumulative_points) >= 2:
        draw.line(cumulative_points, fill="#E45756", width=3)
    for point_index, (x_position, y_position) in enumerate(cumulative_points):
        draw.ellipse((x_position - 4, y_position - 4, x_position + 4, y_position + 4), fill="#E45756", outline="#E45756")
        if point_index in {0, len(cumulative_points) - 1}:
            percentage = float(display_rows[point_index].get("cumulative_percentage", 0.0) or 0.0)
            draw.text((x_position - 14, y_position - 20), f"{percentage:.0f}%", fill="#E45756", font=font_body)

    draw.text((chart_right - 118, chart_top - 28), "Cumulative %", fill="#E45756", font=font_body)
    draw.text((chart_left, chart_top - 28), "Total risk score", fill="#4C78A8", font=font_body)

    return encode_jpeg(image, title=title)


def condense_pareto_rows(pareto_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if len(pareto_rows) <= MAX_PARETO_ITEMS:
        return [dict(row) for row in pareto_rows]

    kept_rows = [dict(row) for row in pareto_rows[: MAX_PARETO_ITEMS - 1]]
    remaining_rows = pareto_rows[MAX_PARETO_ITEMS - 1 :]
    remaining_count = sum(int(row.get("finding_count", 0) or 0) for row in remaining_rows)
    remaining_total_score = sum(int(row.get("total_risk_score", 0) or 0) for row in remaining_rows)
    cumulative_percentage = float(kept_rows[-1].get("cumulative_percentage", 0.0) or 0.0)
    remaining_share = max(0.0, 100.0 - cumulative_percentage)
    kept_rows.append(
        {
            "bug_id": "Other",
            "headline": "Remaining bugs outside the display limit",
            "finding_type": "bug",
            "platform_family": "Mixed",
            "finding_count": remaining_count,
            "total_risk_score": remaining_total_score,
            "affected_devices": [],
            "affected_device_count": 0,
            "remediation_status": "-",
            "recommended_actions": [],
            "cumulative_percentage": min(100.0, cumulative_percentage + remaining_share),
        }
    )
    recompute_cumulative_percentages(kept_rows)
    return kept_rows


def recompute_cumulative_percentages(rows: list[dict[str, object]]) -> None:
    total_count = sum(int(row.get("total_risk_score", 0) or 0) for row in rows)
    running_total = 0
    for row in rows:
        running_total += int(row.get("total_risk_score", 0) or 0)
        row["cumulative_percentage"] = (running_total / total_count * 100.0) if total_count else 0.0


def format_filter_lines(filter_summary: dict[str, object]) -> list[str]:
    platform = join_filter_values(filter_summary.get("platform_family", []))
    hostnames = join_filter_values(filter_summary.get("hostnames", []))
    severities = join_filter_values(filter_summary.get("severities", []))
    features = join_filter_values(filter_summary.get("features", []))
    models = join_filter_values(filter_summary.get("models", []))
    versions = join_filter_values(filter_summary.get("versions", []))
    firmwares = join_filter_values(filter_summary.get("firmwares", []))
    bug_ids = join_filter_values(filter_summary.get("bug_ids", []))
    finding_types = join_filter_values(filter_summary.get("finding_types", []))
    pareto_threshold = str(filter_summary.get("pareto_threshold", "80"))

    return [
        f"Platform: {platform}",
        f"Models: {models}",
        f"Versions: {versions}",
        f"Firmware: {firmwares}",
        f"Hostnames: {hostnames}",
        f"Bugs / CVEs / Notices: {bug_ids}",
        f"Finding types: {finding_types}",
        f"Severities: {severities}",
        f"Features: {features}",
        f"Pareto threshold: {pareto_threshold}%",
    ]


def join_filter_values(values: object) -> str:
    if isinstance(values, str):
        return values or "All"
    if not isinstance(values, list) or not values:
        return "All"
    return ", ".join(str(value) for value in values)


def encode_jpeg(image: Image.Image, *, title: str) -> ParetoChartAsset:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return ParetoChartAsset(
        jpeg_bytes=buffer.getvalue(),
        width=image.width,
        height=image.height,
        title=title,
    )


def format_pareto_axis_label(*, bug_id: str, rank: int) -> str:
    clean_bug_id = bug_id[:16] + "..." if len(bug_id) > 19 else bug_id
    return f"{rank}.\n{clean_bug_id}"
