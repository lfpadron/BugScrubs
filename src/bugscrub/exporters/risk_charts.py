from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from bugscrub.bug_engine.risk_summary import SEVERITY_COLORS
from bugscrub.exporters.pareto import CHART_HEIGHT, CHART_MARGIN_BOTTOM, CHART_MARGIN_LEFT, CHART_MARGIN_RIGHT, CHART_MARGIN_TOP, CHART_WIDTH, format_filter_lines

BUG_BREAKDOWN_SEVERITY_SEQUENCE = ["S1", "S2", "S3", "S4", "S5", "Critical", "Low", "Other"]


@dataclass(slots=True)
class DashboardChartAsset:
    jpeg_bytes: bytes
    width: int
    height: int
    title: str


def build_bug_breakdown_chart_asset(
    *,
    stack_rows: list[dict[str, object]],
    filter_summary: dict[str, object],
    title: str,
) -> DashboardChartAsset:
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), color="white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw_chart_header(draw=draw, title=title, filter_summary=filter_summary, font=font)

    if not stack_rows:
        draw_empty_chart(draw=draw, font=font, message="No bug severity breakdown is available for the current filters.")
        return encode_chart(image=image, title=title)

    severities = ordered_unique(stack_rows, "severity_label")
    bug_ids = ordered_unique(stack_rows, "bug_id")
    chart_left, chart_top, chart_right, chart_bottom = chart_bounds()
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    totals_by_severity = {
        severity: sum(int(row.get("affected_device_count", 0) or 0) for row in stack_rows if row.get("severity_label") == severity)
        for severity in severities
    }
    max_total = max(max(totals_by_severity.values(), default=0), 1)
    draw_axes(draw=draw, chart_left=chart_left, chart_top=chart_top, chart_right=chart_right, chart_bottom=chart_bottom, font=font, max_value=max_total)

    bar_width = chart_width / max(len(severities), 1)
    legend = []
    bug_colors = color_map_for_keys(bug_ids)

    for index, severity in enumerate(severities):
        rows = [row for row in stack_rows if row.get("severity_label") == severity]
        rows = sorted(rows, key=lambda row: int(row.get("stack_order", 0) or 0))
        current_height = 0.0
        x0 = chart_left + index * bar_width + 12
        x1 = chart_left + (index + 1) * bar_width - 18
        for row in rows:
            bug_id = str(row.get("bug_id", ""))
            value = int(row.get("affected_device_count", 0) or 0)
            segment_height = (value / max_total) * chart_height
            y1 = chart_bottom - current_height
            y0 = y1 - segment_height
            color = bug_colors[bug_id]
            draw.rectangle((x0, y0, x1, y1), fill=color, outline="white")
            current_height += segment_height
            if bug_id not in [entry[0] for entry in legend]:
                legend.append((bug_id, color))
        draw.text((x0, chart_bottom + 12), severity, fill="black", font=font)

    draw_legend(draw=draw, legend_items=legend[:12], origin_x=chart_right - 170, origin_y=chart_top, font=font)
    return encode_chart(image=image, title=title)


def build_platform_breakdown_chart_asset(
    *,
    stack_rows: list[dict[str, object]],
    filter_summary: dict[str, object],
    title: str,
) -> DashboardChartAsset:
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), color="white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw_chart_header(draw=draw, title=title, filter_summary=filter_summary, font=font)

    if not stack_rows:
        draw_empty_chart(draw=draw, font=font, message="No platform severity breakdown is available for the current filters.")
        return encode_chart(image=image, title=title)

    platforms = ordered_unique(stack_rows, "platform_family")
    chart_left, chart_top, chart_right, chart_bottom = chart_bounds()
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    totals_by_platform = {
        platform: sum(int(row.get("finding_count", 0) or 0) for row in stack_rows if row.get("platform_family") == platform)
        for platform in platforms
    }
    max_total = max(max(totals_by_platform.values(), default=0), 1)
    draw_axes(draw=draw, chart_left=chart_left, chart_top=chart_top, chart_right=chart_right, chart_bottom=chart_bottom, font=font, max_value=max_total)

    bar_width = chart_width / max(len(platforms), 1)
    legend = []
    for index, platform in enumerate(platforms):
        rows = [row for row in stack_rows if row.get("platform_family") == platform]
        rows = sorted(rows, key=lambda row: int(row.get("severity_order", 0) or 0))
        current_height = 0.0
        x0 = chart_left + index * bar_width + 12
        x1 = chart_left + (index + 1) * bar_width - 18
        for row in rows:
            severity = str(row.get("severity_label", "Other"))
            value = int(row.get("finding_count", 0) or 0)
            segment_height = (value / max_total) * chart_height
            y1 = chart_bottom - current_height
            y0 = y1 - segment_height
            color = SEVERITY_COLORS.get(severity.lower(), SEVERITY_COLORS["other"])
            draw.rectangle((x0, y0, x1, y1), fill=color, outline="white")
            current_height += segment_height
            if severity not in [entry[0] for entry in legend]:
                legend.append((severity, color))
        draw.text((x0, chart_bottom + 12), platform[:14], fill="black", font=font)

    draw_legend(draw=draw, legend_items=legend, origin_x=chart_right - 170, origin_y=chart_top, font=font)
    return encode_chart(image=image, title=title)


def build_treemap_chart_asset(
    *,
    treemap_rows: list[dict[str, object]],
    filter_summary: dict[str, object],
    title: str,
) -> DashboardChartAsset:
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), color="white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw_chart_header(draw=draw, title=title, filter_summary=filter_summary, font=font)

    chart_left, chart_top, chart_right, chart_bottom = chart_bounds()
    if not treemap_rows:
        draw_empty_chart(draw=draw, font=font, message="No treemap data is available for the current filters.")
        return encode_chart(image=image, title=title)

    width = chart_right - chart_left
    height = chart_bottom - chart_top
    legend = []
    for row in treemap_rows:
        severity = str(row.get("severity_label", "Other"))
        color = SEVERITY_COLORS.get(severity.lower(), SEVERITY_COLORS["other"])
        x0 = chart_left + float(row.get("x0", 0.0)) * width
        x1 = chart_left + float(row.get("x1", 1.0)) * width
        y0 = chart_top + float(row.get("y0", 0.0)) * height
        y1 = chart_top + float(row.get("y1", 1.0)) * height
        draw.rectangle((x0, y0, x1, y1), fill=color, outline="white")
        label = f"{row.get('bug_id', '')} ({row.get('affected_device_count', 0)})"
        draw.text((x0 + 6, y0 + 6), label[:24], fill="black", font=font)
        if severity not in [entry[0] for entry in legend]:
            legend.append((severity, color))

    draw_legend(draw=draw, legend_items=legend, origin_x=chart_right - 170, origin_y=chart_top, font=font)
    return encode_chart(image=image, title=title)


def draw_chart_header(*, draw: ImageDraw.ImageDraw, title: str, filter_summary: dict[str, object], font: ImageFont.ImageFont) -> None:
    draw.text((40, 32), title, fill="black", font=font)
    draw.text((40, 58), "Exported from the active dashboard filters and discovered-device analysis scope.", fill="black", font=font)
    y_position = 86
    for line in format_filter_lines(filter_summary):
        draw.text((40, y_position), line, fill="#333333", font=font)
        y_position += 18


def draw_empty_chart(*, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, message: str) -> None:
    chart_left, chart_top, chart_right, chart_bottom = chart_bounds()
    draw.rectangle((chart_left, chart_top, chart_right, chart_bottom), outline="#999999", width=2)
    draw.text((chart_left + 30, chart_top + 80), message, fill="black", font=font)


def draw_axes(
    *,
    draw: ImageDraw.ImageDraw,
    chart_left: int,
    chart_top: int,
    chart_right: int,
    chart_bottom: int,
    font: ImageFont.ImageFont,
    max_value: int,
) -> None:
    chart_height = chart_bottom - chart_top
    draw.line((chart_left, chart_top, chart_left, chart_bottom), fill="black", width=2)
    draw.line((chart_left, chart_bottom, chart_right, chart_bottom), fill="black", width=2)
    for tick_index in range(6):
        tick_value = round(max_value * tick_index / 5)
        y_tick = chart_bottom - (chart_height * tick_index / 5)
        draw.line((chart_left - 6, y_tick, chart_left, y_tick), fill="black", width=1)
        draw.text((chart_left - 40, y_tick - 6), str(tick_value), fill="black", font=font)


def draw_legend(
    *,
    draw: ImageDraw.ImageDraw,
    legend_items: list[tuple[str, str]],
    origin_x: int,
    origin_y: int,
    font: ImageFont.ImageFont,
) -> None:
    y_position = origin_y
    for label, color in legend_items:
        draw.rectangle((origin_x, y_position, origin_x + 12, y_position + 12), fill=color, outline=color)
        draw.text((origin_x + 18, y_position - 1), str(label)[:22], fill="black", font=font)
        y_position += 18


def chart_bounds() -> tuple[int, int, int, int]:
    return (
        CHART_MARGIN_LEFT,
        CHART_MARGIN_TOP,
        CHART_WIDTH - CHART_MARGIN_RIGHT,
        CHART_HEIGHT - CHART_MARGIN_BOTTOM,
    )


def ordered_unique(rows: list[dict[str, object]], key: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    def sort_key(item: dict[str, object]) -> tuple[int, str]:
        value = str(item.get(key, ""))
        if key == "severity_label":
            try:
                return BUG_BREAKDOWN_SEVERITY_SEQUENCE.index(value), value
            except ValueError:
                return len(BUG_BREAKDOWN_SEVERITY_SEQUENCE), value
        return 0, value

    for row in sorted(rows, key=sort_key):
        value = str(row.get(key, ""))
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def color_map_for_keys(keys: list[str]) -> dict[str, str]:
    palette = [
        "#4C78A8",
        "#F58518",
        "#54A24B",
        "#E45756",
        "#72B7B2",
        "#EECA3B",
        "#B279A2",
        "#FF9DA6",
        "#9D755D",
        "#BAB0AC",
        "#5F8DD3",
        "#D08C60",
    ]
    return {key: palette[index % len(palette)] for index, key in enumerate(keys)}


def encode_chart(*, image: Image.Image, title: str) -> DashboardChartAsset:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return DashboardChartAsset(
        jpeg_bytes=buffer.getvalue(),
        width=image.width,
        height=image.height,
        title=title,
    )
