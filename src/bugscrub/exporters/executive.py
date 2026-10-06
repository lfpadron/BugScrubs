from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import textwrap

from bugscrub.discrepancies.presentation import format_discrepancy_status
from bugscrub.exporters.pareto import build_pareto_chart_asset
from bugscrub.exporters.risk_charts import (
    DashboardChartAsset,
    build_bug_breakdown_chart_asset,
    build_platform_breakdown_chart_asset,
    build_treemap_chart_asset,
)


class ExecutiveExporter:
    """Executive PDF exporter with a Pareto chart page."""

    def export_pdf(
        self,
        *,
        session_id: str,
        platform_family: str,
        dashboard_data: dict[str, object],
        destination: Path,
        filter_summary: dict[str, object] | None = None,
    ) -> Path:
        pdf_bytes = self.export_pdf_to_bytes(
            session_id=session_id,
            platform_family=platform_family,
            dashboard_data=dashboard_data,
            filter_summary=filter_summary or {},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(pdf_bytes)
        return destination

    def export_pdf_to_bytes(
        self,
        *,
        session_id: str,
        platform_family: str,
        dashboard_data: dict[str, object],
        filter_summary: dict[str, object] | None = None,
    ) -> bytes:
        filter_summary = filter_summary or {}
        lines = self._build_lines(
            session_id=session_id,
            platform_family=platform_family,
            dashboard_data=dashboard_data,
            filter_summary=filter_summary,
        )
        pages: list[dict[str, object]] = [{"type": "text", "lines": page} for page in self._paginate(lines)]

        for asset in self._build_chart_assets(dashboard_data=dashboard_data, filter_summary=filter_summary):
            pages.append({"type": "chart", "asset": asset})

        return self._render_pdf(pages)

    def _build_lines(
        self,
        *,
        session_id: str,
        platform_family: str,
        dashboard_data: dict[str, object],
        filter_summary: dict[str, object],
    ) -> list[str]:
        metrics = dict(dashboard_data.get("metrics", {}))
        device_rows = list(dashboard_data.get("device_summary_rows", []))
        bug_rows = list(dashboard_data.get("bug_summary_rows", []))
        discrepancy_rows = list(dashboard_data.get("discrepancy_status_rows", []))
        remediation_rows = list(dashboard_data.get("remediation_status_rows", []))
        narrative_lines = list(dashboard_data.get("narrative_lines", []))
        pareto_quick_analysis_rows = list(dashboard_data.get("pareto_quick_analysis_rows", []))

        lines: list[str] = []
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines.extend(
            [
                "BugScrub Executive Report",
                "",
                "Scope and Environment",
                f"Session ID: {session_id}",
                f"Platform scope: {platform_family}",
                f"Generated: {timestamp}",
            ]
        )

        filter_lines = self._format_filters(filter_summary)
        if filter_lines:
            lines.append("Filters applied:")
            lines.extend(filter_lines)

        lines.extend(
            [
                "",
                "Executive Summary",
                f"Devices in scope: {metrics.get('devices_in_scope', 0)}",
                f"Bug findings: {metrics.get('bug_findings_in_scope', 0)}",
                f"Discrepancy pairs: {metrics.get('discrepancy_pairs_in_scope', 0)}",
                f"Impacted devices: {metrics.get('impacted_devices_in_scope', 0)}",
                f"Affected findings: {metrics.get('affected_findings_in_scope', 0)}",
                f"Fixed in target: {metrics.get('fixed_in_target_in_scope', 0)}",
                f"Top risk device: {metrics.get('top_risk_device', '-') or '-'}",
                "",
                "Narrative",
            ]
        )

        if narrative_lines:
            for line in narrative_lines:
                lines.append(f"- {line}")
        else:
            lines.append("- No prioritized narrative is available for the current filters.")

        lines.extend(
            [
                "",
                "Top Risks",
            ]
        )

        if device_rows:
            for row in device_rows[:5]:
                lines.append(
                    f"- {row.get('hostname', '')}: risk {row.get('risk_score', 0)}, "
                    f"bugs {row.get('bug_count', 0)}, discrepancies {row.get('discrepancy_pairs', 0)}, "
                    f"top bug {row.get('top_bug_id', '-') or '-'}"
                )
        else:
            lines.append("- No prioritized devices in scope.")

        lines.extend(["", "Bug Overview"])
        if bug_rows:
            for row in bug_rows[:5]:
                affected_devices = ", ".join(list(row.get("affected_devices", []))[:3])
                lines.append(
                    f"- {row.get('bug_id', '')}: severity {row.get('severity', '')}, "
                    f"devices {row.get('affected_device_count', 0)}, findings {row.get('finding_count', 0)}, "
                    f"score {row.get('total_score', 0)}, remediation {', '.join(row.get('remediation_statuses', [])) or '-'}, "
                    f"affected {affected_devices}"
                )
        else:
            lines.append("- No bug findings in scope.")

        lines.extend(["", "Remediation Overview"])
        if remediation_rows:
            for row in remediation_rows:
                lines.append(f"- {row.get('status', '')}: {row.get('finding_count', 0)} finding(s)")
        else:
            lines.append("- No remediation-state data in scope.")

        lines.extend(["", "Key Discrepancies"])
        if discrepancy_rows:
            for row in discrepancy_rows:
                lines.append(f"- {format_discrepancy_status(row.get('status', ''))}: {row.get('pair_count', 0)} pair(s)")
        else:
            lines.append("- No discrepancy pairs in scope.")

        lines.extend(["", "Pareto Bug Impact Quick Analysis"])
        if pareto_quick_analysis_rows:
            for row in pareto_quick_analysis_rows[:5]:
                lines.append(
                    f"- {row.get('bug_id', '')}: risk {row.get('total_risk_score', 0)}, "
                    f"type {row.get('finding_type', '')}, platforms {row.get('platform_family', '')}, "
                    f"findings {row.get('finding_count', 0)}, remediation {row.get('remediation_status', '-')}, "
                    f"affected {', '.join(row.get('affected_devices', [])[:4])}"
                )
        else:
            lines.append("- No pareto quick-analysis rows are available for the current filters.")

        lines.extend(
            [
                "",
                "Charts Included",
                "- Stacked bars by bug and severity.",
                "- Stacked bars by platform and severity.",
                "- Treemap of prioritized findings.",
                "- Pareto analysis of remediation impact.",
            ]
        )

        lines.extend(["", "Recommendations"])
        lines.extend(
            self._build_recommendations(
                device_rows=device_rows,
                bug_rows=bug_rows,
                discrepancy_rows=discrepancy_rows,
                remediation_rows=remediation_rows,
            )
        )

        lines.extend(
            [
                "",
                "Appendix",
                "This executive PDF summarizes the current filtered dashboard state from the local-first MVP.",
                "Use the Excel export for detailed operational rows and pair-level discrepancy review.",
            ]
        )

        wrapped_lines: list[str] = []
        for line in lines:
            if not line:
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(textwrap.wrap(line, width=92) or [""])
        return wrapped_lines

    def _build_chart_assets(
        self,
        *,
        dashboard_data: dict[str, object],
        filter_summary: dict[str, object],
    ) -> list[DashboardChartAsset]:
        assets: list[DashboardChartAsset] = []
        bug_stack_rows = list(dashboard_data.get("bug_severity_stack_rows", []))
        platform_rows = list(dashboard_data.get("platform_stack_rows", []))
        treemap_rows = list(dashboard_data.get("treemap_rows", []))
        pareto_rows = list(dashboard_data.get("pareto_rows", []))

        assets.append(
            build_bug_breakdown_chart_asset(
                stack_rows=bug_stack_rows,
                filter_summary=filter_summary,
                title="Stacked Breakdown by Bug",
            )
        )
        assets.append(
            build_platform_breakdown_chart_asset(
                stack_rows=platform_rows,
                filter_summary=filter_summary,
                title="Stacked Breakdown by Platform",
            )
        )
        assets.append(
            build_treemap_chart_asset(
                treemap_rows=treemap_rows,
                filter_summary=filter_summary,
                title="Treemap of Prioritized Findings",
            )
        )
        assets.append(
            build_pareto_chart_asset(
                pareto_rows=pareto_rows,
                filter_summary=filter_summary,
                title="Pareto of Bug Remediation Impact",
            )
        )
        return assets

    def _build_recommendations(
        self,
        *,
        device_rows: list[dict[str, object]],
        bug_rows: list[dict[str, object]],
        discrepancy_rows: list[dict[str, object]],
        remediation_rows: list[dict[str, object]],
    ) -> list[str]:
        recommendations: list[str] = []
        if device_rows:
            top_device = device_rows[0]
            recommendations.append(
                f"- Prioritize validation and remediation for {top_device.get('hostname', '')} "
                f"because it has the highest current risk score."
            )
        if bug_rows:
            top_bug = bug_rows[0]
            recommendations.append(
                f"- Review bug {top_bug.get('bug_id', '')} first because it currently affects "
                f"{top_bug.get('affected_device_count', 0)} device(s)."
            )
            action = str(top_bug.get("recommended_action", "")).strip()
            if action:
                recommendations.append(f"- Recommended action: {action}")
        fixed_in_target = next((row for row in remediation_rows if row.get("status") == "fixed_in_target"), None)
        if fixed_in_target and int(fixed_in_target.get("finding_count", 0) or 0) > 0:
            recommendations.append(
                f"- {fixed_in_target.get('finding_count', 0)} finding(s) appear remediated by the planned target version; validate those upgrades first."
            )
        if discrepancy_rows:
            highest = sorted(discrepancy_rows, key=lambda row: int(row.get("pair_count", 0) or 0), reverse=True)[0]
            recommendations.append(
                f"- Address `{format_discrepancy_status(highest.get('status', ''))}` discrepancy pairs next because they are currently the most common."
            )
        if not recommendations:
            recommendations.append("- No immediate actions were generated for the current filtered view.")
        return recommendations

    def _format_filters(self, filter_summary: dict[str, object]) -> list[str]:
        if not filter_summary:
            return []

        lines: list[str] = []
        platform_value = filter_summary.get("platform_family", "All")
        platform = ", ".join(platform_value) if isinstance(platform_value, list) else str(platform_value)
        hostnames = ", ".join(filter_summary.get("hostnames", [])) or "All"
        severities = ", ".join(filter_summary.get("severities", [])) or "All"
        features = ", ".join(filter_summary.get("features", [])) or "All"
        models = ", ".join(filter_summary.get("models", [])) or "All"
        versions = ", ".join(filter_summary.get("versions", [])) or "All"
        firmwares = ", ".join(filter_summary.get("firmwares", [])) or "All"
        bug_ids = ", ".join(filter_summary.get("bug_ids", [])) or "All"
        finding_types = ", ".join(filter_summary.get("finding_types", [])) or "All"
        pareto_threshold = filter_summary.get("pareto_threshold", 80)
        lines.append(f"- Platform: {platform}")
        lines.append(f"- Models: {models}")
        lines.append(f"- Versions: {versions}")
        lines.append(f"- Firmware: {firmwares}")
        lines.append(f"- Hostnames: {hostnames}")
        lines.append(f"- Bugs / CVEs / Notices: {bug_ids}")
        lines.append(f"- Severities: {severities}")
        lines.append(f"- Finding types: {finding_types}")
        lines.append(f"- Features: {features}")
        lines.append(f"- Pareto threshold: {pareto_threshold}%")
        return lines

    def _paginate(self, lines: list[str], page_size: int = 48) -> list[list[str]]:
        if not lines:
            return [["BugScrub Executive Report", "No content available."]]
        return [lines[index:index + page_size] for index in range(0, len(lines), page_size)]

    def _render_pdf(self, pages: list[dict[str, object]]) -> bytes:
        objects: list[bytes] = []
        page_object_ids: list[int] = []

        catalog_id = 1
        pages_id = 2
        font_id = 3
        next_object_id = 4

        for page in pages:
            page_type = str(page.get("type", "text"))
            if page_type == "chart":
                asset = page.get("asset")
                if not hasattr(asset, "jpeg_bytes") or not hasattr(asset, "width") or not hasattr(asset, "height"):
                    continue

                page_id = next_object_id
                image_id = next_object_id + 1
                content_id = next_object_id + 2
                next_object_id += 3
                page_object_ids.append(page_id)

                content_stream = self._build_chart_page_content_stream(str(getattr(asset, "title", "Chart")))
                objects.append(
                    self._pdf_object(
                        page_id,
                        self._page_object(
                            pages_id=pages_id,
                            font_id=font_id,
                            content_id=content_id,
                            image_id=image_id,
                        ),
                    )
                )
                objects.append(
                    self._pdf_image_object(
                        image_id=image_id,
                        image_bytes=asset.jpeg_bytes,
                        width=asset.width,
                        height=asset.height,
                    )
                )
                objects.append(self._pdf_stream_object(content_id, content_stream))
                continue

            page_id = next_object_id
            content_id = next_object_id + 1
            next_object_id += 2
            page_object_ids.append(page_id)

            page_lines = list(page.get("lines", []))
            content_stream = self._build_content_stream(page_lines)
            objects.append(
                self._pdf_object(
                    page_id,
                    self._page_object(pages_id=pages_id, font_id=font_id, content_id=content_id),
                )
            )
            objects.append(self._pdf_stream_object(content_id, content_stream))

        pages_kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
        root_objects = [
            self._pdf_object(catalog_id, b"<< /Type /Catalog /Pages 2 0 R >>"),
            self._pdf_object(pages_id, f"<< /Type /Pages /Kids [{pages_kids}] /Count {len(page_object_ids)} >>".encode("ascii")),
            self._pdf_object(font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        ]

        all_objects = root_objects + objects
        buffer = BytesIO()
        buffer.write(b"%PDF-1.4\n")

        offsets = [0]
        for obj in all_objects:
            offsets.append(buffer.tell())
            buffer.write(obj)

        xref_position = buffer.tell()
        buffer.write(f"xref\n0 {len(offsets)}\n".encode("ascii"))
        buffer.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))

        trailer = f"""
trailer
<< /Size {len(offsets)} /Root {catalog_id} 0 R >>
startxref
{xref_position}
%%EOF
""".lstrip()
        buffer.write(trailer.encode("ascii"))
        return buffer.getvalue()

    def _build_content_stream(self, lines: list[str]) -> bytes:
        stream_lines = ["BT", "/F1 10 Tf"]
        y_position = 760
        for line in lines:
            escaped = self._escape_pdf_text(self._safe_text(line))
            stream_lines.append(f"1 0 0 1 50 {y_position} Tm ({escaped}) Tj")
            y_position -= 14
        stream_lines.append("ET")
        return ("\n".join(stream_lines) + "\n").encode("ascii")

    def _build_chart_page_content_stream(self, title: str) -> bytes:
        stream_lines = [
            "BT",
            "/F1 12 Tf",
            f"1 0 0 1 50 760 Tm ({self._escape_pdf_text(self._safe_text(title))}) Tj",
            "1 0 0 1 50 742 Tm (This chart uses the current active dashboard criteria.) Tj",
            "ET",
            "q",
            "520 0 0 292 46 360 cm",
            "/Im1 Do",
            "Q",
        ]
        return ("\n".join(stream_lines) + "\n").encode("ascii")

    def _page_object(self, *, pages_id: int, font_id: int, content_id: int, image_id: int | None = None) -> bytes:
        resources = f"/Font << /F1 {font_id} 0 R >>"
        if image_id is not None:
            resources += f" /XObject << /Im1 {image_id} 0 R >>"
        return (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << {resources} >> >>"
        ).encode("ascii")

    def _pdf_object(self, object_id: int, body: bytes) -> bytes:
        return f"{object_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    def _pdf_stream_object(self, object_id: int, stream: bytes) -> bytes:
        header = f"{object_id} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        footer = b"endstream\nendobj\n"
        return header + stream + footer

    def _pdf_image_object(self, *, image_id: int, image_bytes: bytes, width: int, height: int) -> bytes:
        header = (
            f"{image_id} 0 obj\n"
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(image_bytes)} >>\n"
            f"stream\n"
        ).encode("ascii")
        footer = b"\nendstream\nendobj\n"
        return header + image_bytes + footer

    def _safe_text(self, value: str) -> str:
        return value.encode("ascii", "replace").decode("ascii")

    def _escape_pdf_text(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
