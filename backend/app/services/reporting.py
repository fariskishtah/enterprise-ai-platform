"""Grounded executive metrics and bounded dependency-free report exports."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from collections.abc import Iterable
from datetime import datetime
from xml.sax.saxutils import escape

FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_REPORT_ROWS = 10_000


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
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                cells.append(f'<c r="{reference}"><v>{raw}</v></c>')
            elif isinstance(raw, datetime):
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>'
                    f"{escape(raw.isoformat())}</t></is></c>"
                )
            else:
                value = escape(spreadsheet_safe(raw))
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    auto_filter = f"A1:{_column_name(len(fields))}{max(1, len(values))}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(xml_rows)}</sheetData><autoFilter ref="{auto_filter}"/>'
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
            + "</Relationships>",
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
) -> bytes:
    """Create a deterministic printable A4 report with a bounded metrics chart."""
    pages: list[list[str]] = []
    current = [title]
    for line in lines:
        current.append(str(line)[:110])
        if len(current) == 45:
            pages.append(current)
            current = [f"{title} — continued"]
    pages.append(current)
    objects: list[bytes] = []
    page_ids: list[int] = []
    font_id = 3
    bounded_chart = list(chart_values)[:6]
    chart_maximum = max((abs(value) for _, value in bounded_chart), default=0)
    for page_number, page_lines in enumerate(pages, start=1):
        content = ["BT", "/F1 10 Tf", "48 795 Td", "14 TL"]
        for index, line in enumerate(page_lines):
            if index == 0:
                content.extend(
                    ["/F1 16 Tf", f"({_pdf_escape(line)}) Tj", "0 -24 Td", "/F1 10 Tf"]
                )
            else:
                content.extend([f"({_pdf_escape(line)}) Tj", "T*"])
        content.append("ET")
        if page_number == 1 and chart_maximum > 0:
            content.extend(
                [
                    "BT",
                    "/F1 11 Tf",
                    "48 430 Td",
                    "(Key metrics chart) Tj",
                    "ET",
                    "q",
                    "0.43 0.29 1 rg",
                ]
            )
            for index, (_label, value) in enumerate(bounded_chart):
                width = max(1.0, 300 * abs(value) / chart_maximum)
                content.append(f"48 {400 - index * 22} {width:.2f} 10 re f")
            content.append("Q")
        content.extend(
            [
                "BT",
                "/F1 9 Tf",
                f"280 24 Td (Page {page_number} of {len(pages)}) Tj",
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
    lines = [f"{key}: {value}" for key, value in summary.items()]
    lines.extend(
        [
            "",
            "Limitations: metrics reflect authorized records in the selected period.",
            "No financial savings, avoided downtime, ROI, or production "
            "efficiency is inferred.",
        ]
    )
    chart_values = [
        (key, float(value))
        for key, value in summary.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return pdf_report(title, lines, chart_values=chart_values)


def json_summary(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
