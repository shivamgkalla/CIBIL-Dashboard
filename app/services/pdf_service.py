from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

_HEADER_BG = colors.HexColor("#EAEAEA")
_ALT_ROW_BG = colors.HexColor("#F7F7F7")


def _build_key_value_table(data: dict[str, Any], label_width: float, value_width: float) -> Table:
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle(
        "KVLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
    )
    value_style = ParagraphStyle(
        "KVValue",
        parent=styles["Normal"],
        fontSize=8,
    )

    rows: list[list[Any]] = []
    for key, value in data.items():
        if value is None or value == "":
            continue
        label = Paragraph(str(key), label_style)
        val = Paragraph(str(value), value_style)
        rows.append([label, val])

    if not rows:
        rows.append(
            [
                Paragraph("-", label_style),
                Paragraph("-", value_style),
            ]
        )

    table = Table(rows, hAlign="LEFT", colWidths=[label_width, value_width])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (0, -1), 2),
                ("RIGHTPADDING", (0, 0), (0, -1), 6),
                ("LEFTPADDING", (1, 0), (1, -1), 2),
                ("RIGHTPADDING", (1, 0), (1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _build_section_title(text: str) -> Paragraph:
    styles = getSampleStyleSheet()
    style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
    )
    return Paragraph(text, style)


def generate_customer_pdf(customer_data: dict[str, Any]) -> bytes:
    """Generate a bureau-style customer report PDF.

    The layout is intentionally simple but structured:
    - Customer Overview
    - Account Information
    - Identity Information
    - Timeline (when present)
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []

    # Top header
    header_style = ParagraphStyle(
        "ReportHeader",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        alignment=1,  # center
        spaceAfter=10,
    )
    header = Paragraph("CREDIT INFORMATION REPORT", header_style)
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    # Customer Overview
    width = A4[0] - doc.leftMargin - doc.rightMargin
    label_width = 55 * mm
    value_width = width - label_width

    overview = customer_data.get("overview") or {}
    story.append(_build_section_title("Customer Overview"))
    overview_table = _build_key_value_table(
        {
            "Customer ID:": overview.get("customer_id"),
            "Primary Account Key:": overview.get("primary_acct_key"),
            "Latest Bank Type:": overview.get("bank_type"),
            "Latest Income:": overview.get("income"),
            "Latest Report Date:": overview.get("rpt_dt"),
        },
        label_width=label_width,
        value_width=value_width,
    )
    story.append(overview_table)
    story.append(Spacer(1, 8 * mm))

    # Account Information
    accounts = customer_data.get("accounts") or []
    story.append(_build_section_title("Account Information"))
    if accounts:
        account_rows: list[list[str]] = [
            [
                "Acct Key",
                "Bank Type",
                "Income",
                "Income Freq",
                "Occup Status",
                "Report Date",
                "Snapshot ID",
            ]
        ]
        for acc in accounts:
            account_rows.append(
                [
                    str(acc.get("acct_key") or ""),
                    str(acc.get("bank_type") or ""),
                    str(acc.get("income") or ""),
                    str(acc.get("income_freq") or ""),
                    str(acc.get("occup_status_cd") or ""),
                    str(acc.get("rpt_dt") or ""),
                    str(acc.get("snapshot_id") or ""),
                ]
            )

        account_table = Table(
            account_rows,
            hAlign="LEFT",
            repeatRows=1,
            colWidths=[width / 7] * 7,
        )
        account_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ALT_ROW_BG]),
                ]
            )
        )
        story.append(account_table)
    else:
        empty_table = _build_key_value_table(
            {"Status:": "No account records available."},
            label_width=label_width,
            value_width=value_width,
        )
        story.append(empty_table)
    story.append(Spacer(1, 8 * mm))

    # Identity Information
    identity = customer_data.get("identity") or {}
    story.append(_build_section_title("Identity Information"))
    identity_table = _build_key_value_table(
        {
            "PAN:": identity.get("pan"),
            "UID:": identity.get("uid"),
            "Passport:": identity.get("passport"),
            "Voter ID:": identity.get("voter_id"),
            "Driving License:": identity.get("driving_license"),
            "Ration Card:": identity.get("ration_card"),
        },
        label_width=label_width,
        value_width=value_width,
    )
    story.append(identity_table)
    story.append(Spacer(1, 8 * mm))

    # Timeline
    timeline = customer_data.get("timeline") or []
    if timeline:
        story.append(_build_section_title("Timeline"))
        timeline_rows: list[list[str]] = [
            [
                "Snapshot ID",
                "Report Date",
                "Income",
                "Bank Type",
            ]
        ]
        for entry in timeline:
            timeline_rows.append(
                [
                    str(entry.get("snapshot_id") or ""),
                    str(entry.get("rpt_dt") or ""),
                    str(entry.get("income") or ""),
                    str(entry.get("bank_type") or ""),
                ]
            )

        timeline_table = Table(
            timeline_rows,
            hAlign="LEFT",
            repeatRows=1,
            colWidths=[width / 4] * 4,
        )
        timeline_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ALT_ROW_BG]),
                ]
            )
        )
        story.append(timeline_table)

    doc.build(story)
    return buffer.getvalue()
