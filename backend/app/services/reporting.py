"""Grounded executive metrics and bounded dependency-free report exports."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import textwrap
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from xml.sax.saxutils import escape

FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_REPORT_ROWS = 10_000
CHART_LABELS = {
    "average_acknowledgement_seconds": "Avg. acknowledgement (s)",
    "average_resolution_seconds": "Avg. resolution (s)",
    "critical_alerts": "Critical alerts",
    "completed_actions": "Completed actions",
    "machine_count": "Machines",
    "maintenance_feedback_count": "Maintenance feedback",
    "open_alerts": "Open alerts",
    "overdue_actions": "Overdue actions",
    "shift_activity_count": "Shift activity",
}


def spreadsheet_safe(value: object) -> str:
    """Return text that spreadsheet applications cannot interpret as a formula."""
    text = str(value) if value is not None else ""
    if text.startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def csv_report(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    fields = list(rows[0]) if rows else ["message"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows[:MAX_REPORT_ROWS]:
        writer.writerow({key: spreadsheet_safe(row.get(key)) for key in fields})
    return output.getvalue().encode("utf-8")


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _sheet_xml(rows: list[dict[str, object]]) -> str:
    fields = list(rows[0]) if rows else ["message"]
    values: list[list[object]] = [
        list(fields),
        *[[row.get(field, "") for field in fields] for row in rows],
    ]
    xml_rows = []
    for row_number, row in enumerate(values, start=1):
        cells = []
        for column_number, raw in enumerate(row, start=1):
            reference = f"{_column_name(column_number)}{row_number}"
            style = ' s="1"' if row_number == 1 else ""
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                cells.append(f'<c r="{reference}"{style}><v>{raw}</v></c>')
            elif isinstance(raw, datetime):
                aware = raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
                epoch = datetime(1899, 12, 30, tzinfo=UTC)
                serial = (aware.astimezone(UTC) - epoch).total_seconds() / 86_400
                cells.append(f'<c r="{reference}" s="2"><v>{serial:.10f}</v></c>')
            else:
                value = escape(spreadsheet_safe(raw))
                cells.append(
                    f'<c r="{reference}"{style} t="inlineStr"><is><t>{value}'
                    "</t></is></c>"
                )
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    auto_filter = f"A1:{_column_name(len(fields))}{max(1, len(values))}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols><col min="1" max="{len(fields)}" width="22" customWidth="1"/>'
        f'</cols><sheetData>{"".join(xml_rows)}</sheetData>'
        f'<autoFilter ref="{auto_filter}"/>'
        "</worksheet>"
    )


def xlsx_report(sheets: dict[str, list[dict[str, object]]]) -> bytes:
    """Build a small standards-compliant macro-free XLSX workbook."""
    safe_sheets = list(sheets.items())[:8]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.'
            'openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for index in range(1, len(safe_sheets) + 1)
            )
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>',
        )
        workbook_sheets = "".join(
            f'<sheet name="{escape(re.sub(r"[][\\\\:*?/]", "-", name)[:31])}" '
            f'sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(safe_sheets, start=1)
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{workbook_sheets}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
                for index in range(1, len(safe_sheets) + 1)
            )
            + (
                f'<Relationship Id="rId{len(safe_sheets) + 1}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/styles" Target="styles.xml"/>'
            )
            + "</Relationships>",
        )
        archive.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/>'
            '<name val="Aptos"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF5941C6"/>'
            '<bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/>'
            "<diagonal/></border></borders>"
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
            'borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" '
            'borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="1" '
            'borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
            '<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" '
            'applyNumberFormat="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
            'builtinId="0"/></cellStyles></styleSheet>',
        )
        for index, (_, rows) in enumerate(safe_sheets, start=1):
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows[:MAX_REPORT_ROWS])
            )
    return output.getvalue()


def _pdf_escape(value: object) -> str:
    return (
        html.escape(str(value), quote=False)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def pdf_report(
    title: str,
    lines: Iterable[str],
    *,
    chart_values: Iterable[tuple[str, float]] = (),
    metadata: Iterable[tuple[str, str]] = (),
) -> bytes:
    """Create a deterministic A4 vector report with labelled, bounded charts."""
    flattened: list[str] = []
    for label, value in metadata:
        flattened.extend(
            textwrap.wrap(f"{label}: {value}", width=82) or [f"{label}: -"]
        )
    for line in lines:
        value = str(line).strip()
        flattened.extend(textwrap.wrap(value, width=82) if value else [""])
    bounded_chart = [
        (
            CHART_LABELS.get(str(label), str(label).replace("_", " ").title())[:28],
            float(value),
        )
        for label, value in list(chart_values)[:6]
    ]
    pages: list[list[str]] = []
    first_page_limit = 21 if bounded_chart else 42
    pages.append(flattened[:first_page_limit])
    remaining = flattened[first_page_limit:]
    while remaining:
        pages.append(remaining[:42])
        remaining = remaining[42:]
    if not pages:
        pages = [[]]

    objects: list[bytes] = []
    page_ids: list[int] = []
    font_id = 3
    chart_maximum = max((abs(value) for _, value in bounded_chart), default=0)
    for page_number, page_lines in enumerate(pages, start=1):
        display_title = title if page_number == 1 else f"{title} - continued"
        content = [
            "q",
            "1 1 1 rg",
            "0 0 595 842 re f",
            "Q",
            "q",
            "0.035 0.078 0.161 rg",
            "0 762 595 80 re f",
            "0.427 0.290 1 rg",
            "0 756 595 6 re f",
            "Q",
            "BT",
            "/F1 19 Tf",
            "1 1 1 rg",
            f"1 0 0 1 46 803 Tm ({_pdf_escape(display_title[:72])}) Tj",
            "/F1 9 Tf",
            "0.82 0.80 0.90 rg",
            "1 0 0 1 46 781 Tm (FK SOLUTIONS | AI Manufacturing Platform) Tj",
            "ET",
        ]
        y = 730
        for line in page_lines:
            if not line:
                y -= 8
                continue
            content.extend(
                [
                    "BT",
                    "/F1 9 Tf",
                    "0.12 0.14 0.22 rg",
                    f"1 0 0 1 48 {y} Tm ({_pdf_escape(line)}) Tj",
                    "ET",
                ]
            )
            y -= 14
        if page_number == 1 and bounded_chart:
            content.extend(
                [
                    "q",
                    "0.976 0.973 0.992 rg",
                    "42 92 511 284 re f",
                    "0.847 0.827 0.902 RG",
                    "0.8 w",
                    "42 92 511 284 re S",
                    "Q",
                    "BT",
                    "/F1 12 Tf",
                    "0.035 0.078 0.161 rg",
                    "1 0 0 1 58 352 Tm (Key metrics chart) Tj",
                    "/F1 8 Tf",
                    "0.35 0.37 0.46 rg",
                    (
                        "1 0 0 1 58 337 Tm "
                        "(Grounded values for the selected reporting period) Tj"
                    ),
                    "ET",
                ]
            )
            for tick in range(5):
                x = 180 + tick * 76
                content.extend(
                    [
                        "q",
                        "0.88 0.87 0.92 RG",
                        "0.5 w",
                        f"{x} 116 m {x} 320 l S",
                        "Q",
                    ]
                )
            if chart_maximum > 0:
                for index, (metric_label, metric_value) in enumerate(bounded_chart):
                    row_y = 298 - index * 32
                    width = max(2.0, 300 * abs(metric_value) / chart_maximum)
                    content.extend(
                        [
                            "BT",
                            "/F1 8 Tf",
                            "0.18 0.20 0.29 rg",
                            (
                                f"1 0 0 1 58 {row_y} Tm "
                                f"({_pdf_escape(metric_label)}) Tj"
                            ),
                            "ET",
                            "q",
                            "0.427 0.290 1 rg",
                            f"180 {row_y - 5} {width:.2f} 12 re f",
                            "Q",
                            "BT",
                            "/F1 8 Tf",
                            "0.18 0.20 0.29 rg",
                            (
                                f"1 0 0 1 {min(492, 187 + width):.2f} {row_y} Tm "
                                f"({_pdf_escape(f'{metric_value:,.1f}')}) Tj"
                            ),
                            "ET",
                        ]
                    )
            else:
                content.extend(
                    [
                        "BT",
                        "/F1 10 Tf",
                        "0.35 0.37 0.46 rg",
                        (
                            "1 0 0 1 58 285 Tm "
                            "(No non-zero metric values are available for this "
                            "period.) Tj"
                        ),
                        "ET",
                    ]
                )
        content.extend(
            [
                "q",
                "0.847 0.827 0.902 RG",
                "0.5 w",
                "42 48 m 553 48 l S",
                "Q",
                "BT",
                "/F1 8 Tf",
                "0.35 0.37 0.46 rg",
                (
                    "1 0 0 1 42 31 Tm "
                    "(Authorized operational records | Confidential) Tj"
                ),
                (f"1 0 0 1 500 31 Tm " f"(Page {page_number} of {len(pages)}) Tj"),
                "ET",
            ]
        )
        stream = "\n".join(content).encode("latin-1")
        content_id = 4 + (page_number - 1) * 2
        page_id = content_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
        )
    base = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids "
            f"[{' '.join(f'{value} 0 R' for value in page_ids)}] "
            f"/Count {len(page_ids)} >>"
        ).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *objects,
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(base, start=1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(base) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        (
            f"trailer << /Size {len(base) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(result)


def report_payload(
    format: str,
    *,
    title: str,
    summary: dict[str, object],
    tables: dict[str, list[dict[str, object]]],
    metadata: Iterable[tuple[str, str]] = (),
) -> bytes:
    if format == "csv":
        rows = [{"metric": key, "value": value} for key, value in summary.items()]
        return csv_report(rows)
    if format == "xlsx":
        summary_rows = [
            {"metric": key, "value": value} for key, value in summary.items()
        ]
        ordered = {
            "Summary": summary_rows,
            "Machines": tables.get("Machines", []),
            "Alerts": tables.get("Alerts", []),
            "Actions": tables.get("Actions", []),
            "Feedback": tables.get("Feedback", []),
            "Shifts": tables.get("Shifts", []),
            "Data Quality": tables.get("Data Quality", []),
            "Model Governance": tables.get("Model Governance", []),
        }
        return xlsx_report(ordered)
    lines = [
        f"{key.replace('_', ' ').title()}: {value}" for key, value in summary.items()
    ]
    lines.extend(
        [
            "",
            "Limitations: metrics reflect authorized records in the selected period.",
            "No financial savings, avoided downtime, ROI, or production "
            "efficiency is inferred.",
        ]
    )
    metric_definitions = {
        "machine_count": "Authorized active machines in the selected factory scope.",
        "open_alerts": "Alerts detected in the period that are not resolved.",
        "critical_alerts": "Critical alerts first detected in the selected period.",
        "overdue_actions": "Incomplete actions whose due timestamp has passed.",
        "completed_actions": "Actions completed during the selected period.",
        "average_acknowledgement_seconds": (
            "Mean elapsed seconds from alert detection to acknowledgement."
        ),
        "average_resolution_seconds": (
            "Mean elapsed seconds from alert detection to resolution."
        ),
        "data_freshness_at": "Most recent authorized sensor-reading timestamp.",
    }
    present_definitions = [
        f"{key.replace('_', ' ').title()}: {definition}"
        for key, definition in metric_definitions.items()
        if key in summary
    ]
    if present_definitions:
        lines.extend(["", "Metric definitions:", *present_definitions])
    chart_values = [
        (key, float(value))
        for key, value in summary.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return pdf_report(title, lines, chart_values=chart_values, metadata=metadata)


def json_summary(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
