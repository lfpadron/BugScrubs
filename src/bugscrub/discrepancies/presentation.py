from __future__ import annotations


STATUS_LABELS = {"discrepancia": "discrepancy", "faltante": "missing", "nuevo": "new"}
SOURCE_LABELS = {"cliente": "customer", "descubierto": "discovered"}
SUMMARY_TRANSLATIONS = {
    "Faltante: estaba en el inventario del cliente, pero no fue descubierto por la herramienta.":
        "Missing: present in the customer inventory but not discovered by the tool.",
    "Nuevo: fue descubierto por la herramienta, pero no estaba en el inventario del cliente.":
        "New: discovered by the tool but not present in the customer inventory.",
}


def format_discrepancy_status(status: object) -> str:
    value = str(status or "")
    return STATUS_LABELS.get(value, value)


def format_discrepancy_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Translate display values, including saved sessions, without changing stored codes."""
    formatted_rows = []
    for row in rows:
        formatted = dict(row)
        if "row_source" in row:
            source = str(row["row_source"] or "")
            formatted["row_source"] = SOURCE_LABELS.get(source, source)
        if "discrepancy_status" in row:
            formatted["discrepancy_status"] = format_discrepancy_status(row["discrepancy_status"])
        if "discrepancy_summary" in row:
            summary = str(row["discrepancy_summary"] or "")
            if summary.startswith("Discrepancia en: "):
                summary = "Discrepancy in: " + summary.removeprefix("Discrepancia en: ")
            formatted["discrepancy_summary"] = SUMMARY_TRANSLATIONS.get(summary, summary)
        formatted_rows.append(formatted)
    return formatted_rows
