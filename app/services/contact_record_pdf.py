"""Printable PDF export for CRM contact records."""
from html import escape
from io import BytesIO
from pathlib import Path


def _paragraph_text(value: str | None) -> str:
    """Escape record text and make it safe for the installed Chinese font."""
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = (
        text.replace("\u00a0", " ")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return escape(text).replace("\n", "<br/>")


def export_contact_records_pdf(contact, records) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "CRMContactChinese"
    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(Path("C:/Windows/Fonts/simhei.ttf"))))
    except Exception:
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    translation_font = "STSong-Light"
    if translation_font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(translation_font))

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{contact.name} 的跟进",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "contact-title", parent=styles["Title"], fontName=font_name, fontSize=19,
        leading=26, textColor=colors.HexColor("#176548"), alignment=TA_LEFT, spaceAfter=10,
    )
    meta = ParagraphStyle(
        "contact-meta", parent=styles["BodyText"], fontName=font_name, fontSize=10,
        leading=16, textColor=colors.HexColor("#31533f"), splitLongWords=1,
    )
    heading = ParagraphStyle(
        "record-heading", parent=styles["Heading3"], fontName=font_name, fontSize=12,
        leading=18, textColor=colors.HexColor("#176548"), spaceBefore=12, spaceAfter=5,
    )
    body = ParagraphStyle(
        "record-body", parent=styles["BodyText"], fontName=font_name, fontSize=10.5,
        leading=18, textColor=colors.HexColor("#263f33"), splitLongWords=1,
    )
    label = ParagraphStyle(
        "record-label", parent=styles["BodyText"], fontName=font_name, fontSize=9,
        leading=13, textColor=colors.HexColor("#4E7E63"), spaceBefore=4, spaceAfter=3,
    )
    translation = ParagraphStyle(
        "record-translation", parent=body, fontName=translation_font, fontSize=11,
        leading=20, textColor=colors.HexColor("#315F48"), leftIndent=4,
    )

    story = [Paragraph(f"{_paragraph_text(contact.name)} 的跟进", title)]
    meta_rows = [
        [Paragraph("公司名称", meta), Paragraph(_paragraph_text(contact.company or "未填写"), meta)],
        [Paragraph("官网", meta), Paragraph(_paragraph_text(contact.company_website or "-"), meta)],
        [Paragraph("公司地址", meta), Paragraph(_paragraph_text(contact.company_address or "-"), meta)],
        [Paragraph("邮箱", meta), Paragraph(_paragraph_text(contact.email or "-"), meta)],
        [Paragraph("电话", meta), Paragraph(_paragraph_text(contact.phone or "-"), meta)],
    ]
    table = Table(meta_rows, colWidths=[28 * mm, 136 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF4EE")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([table, Spacer(1, 6 * mm)])

    if not records:
        story.append(Paragraph("暂无跟进。", body))

    for index, item in enumerate(records, 1):
        # Do not put message content into one table or KeepTogether: long emails must split across pages.
        story.append(Paragraph(
            f"{index}. {item.occurred_at:%Y-%m-%d} · {_paragraph_text(item.contact_name or '未填写联系人')} · {_paragraph_text(item.channel)}",
            heading,
        ))
        if getattr(item,"subject",None):story.append(Paragraph("标题："+_paragraph_text(item.subject),label))
        story.append(Paragraph("内容", label))
        story.append(Paragraph(_paragraph_text(item.content), body))
        if item.content_translation:
            story.append(Paragraph("历史翻译（保留）", label))
            story.append(Paragraph(_paragraph_text(item.content_translation), translation))
        story.extend([
            Spacer(1, 4 * mm),
            HRFlowable(width="100%", thickness=0.35, color=colors.HexColor("#D7E5DD")),
        ])

    doc.build(story)
    return output.getvalue()
