"""Polished PDF export for one competitor research profile."""

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path


def _text(value) -> str:
    return escape(str(value or "—")).replace("\n", "<br/>")


def export_competitor_pdf(competitor, websites, keywords) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Table, TableStyle

    font_name = "CRMChinese"
    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(Path("C:/Windows/Fonts/msyh.ttc"))))
    except Exception:
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title=f"{competitor.name} 竞品档案",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("competitor-title", parent=styles["Title"], fontName=font_name, fontSize=20, leading=28, textColor=colors.HexColor("#176548"), alignment=TA_LEFT, spaceAfter=4)
    subtitle = ParagraphStyle("competitor-subtitle", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=15, textColor=colors.HexColor("#6B8778"), spaceAfter=12)
    heading = ParagraphStyle("competitor-heading", parent=styles["Heading3"], fontName=font_name, fontSize=12, leading=18, textColor=colors.HexColor("#176548"), spaceBefore=14, spaceAfter=7)
    body = ParagraphStyle("competitor-body", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=16, textColor=colors.HexColor("#294637"))
    header = ParagraphStyle("competitor-table-header", parent=body, fontName=font_name, fontSize=9.5, leading=14, textColor=colors.white)
    link = ParagraphStyle("competitor-link", parent=body, fontName=font_name, fontSize=8.5, leading=13, textColor=colors.HexColor("#176548"))

    story = [
        Paragraph(_text(competitor.name), title),
        Paragraph(f"竞品档案 · 导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}", subtitle),
        Paragraph("基本信息", heading),
    ]
    info = Table(
        [
            [Paragraph("公司名称", body), Paragraph(_text(competitor.name), body)],
            [Paragraph("国家 / 地区", body), Paragraph(_text(competitor.country), body)],
            [Paragraph("调研备注", body), Paragraph(_text(competitor.notes), body)],
        ],
        colWidths=[34 * mm, 140 * mm],
    )
    info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF4EE")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6E5DC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([info, Paragraph(f"竞品网站（{len(websites)}）", heading)])

    website_rows = [[Paragraph("网站名称", header), Paragraph("类型", header), Paragraph("网址", header)]]
    website_rows.extend([
        [Paragraph(_text(item.name), body), Paragraph(_text(item.website_type), body), Paragraph(_text(item.url), link)]
        for item in websites
    ])
    if len(website_rows) == 1:
        website_rows.append([Paragraph("—", body), Paragraph("—", body), Paragraph("暂无网站资料", body)])
    website_table = LongTable(website_rows, colWidths=[43 * mm, 29 * mm, 102 * mm], repeatRows=1)
    website_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176548")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([website_table, Paragraph(f"竞品关键词（{len(keywords)}）", heading)])

    keyword_rows = [[Paragraph("关键词", header), Paragraph("语言", header), Paragraph("分类", header)]]
    keyword_rows.extend([
        [Paragraph(_text(item.keyword), body), Paragraph(_text(item.language), body), Paragraph(_text(item.category), body)]
        for item in keywords
    ])
    if len(keyword_rows) == 1:
        keyword_rows.append([Paragraph("暂无关键词资料", body), Paragraph("—", body), Paragraph("—", body)])
    keyword_table = LongTable(keyword_rows, colWidths=[92 * mm, 36 * mm, 46 * mm], repeatRows=1)
    keyword_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176548")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF8")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(keyword_table)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B8B7A"))
        canvas.drawString(document.leftMargin, 10 * mm, "Tophoo CRM · 竞品调研")
        canvas.drawRightString(A4[0] - document.rightMargin, 10 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def export_competitors_pdf(project_name: str, records: list[tuple]) -> bytes:
    """Build one printable archive containing every competitor in project order."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "CRMChineseArchive"
    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(Path("C:/Windows/Fonts/msyh.ttc"))))
    except Exception:
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title=f"{project_name} 竞品档案汇总",
    )
    styles = getSampleStyleSheet()
    cover_title = ParagraphStyle("archive-cover-title", parent=styles["Title"], fontName=font_name, fontSize=21, leading=30, textColor=colors.HexColor("#176548"), alignment=TA_LEFT, spaceAfter=5)
    subtitle = ParagraphStyle("archive-subtitle", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=16, textColor=colors.HexColor("#6B8778"), spaceAfter=14)
    company_title = ParagraphStyle("archive-company-title", parent=styles["Heading1"], fontName=font_name, fontSize=17, leading=24, textColor=colors.HexColor("#176548"), spaceAfter=4)
    heading = ParagraphStyle("archive-heading", parent=styles["Heading3"], fontName=font_name, fontSize=11.5, leading=17, textColor=colors.HexColor("#176548"), spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("archive-body", parent=styles["BodyText"], fontName=font_name, fontSize=9.3, leading=15, textColor=colors.HexColor("#294637"))
    header = ParagraphStyle("archive-table-header", parent=body, fontName=font_name, fontSize=9.2, leading=13, textColor=colors.white)
    link = ParagraphStyle("archive-link", parent=body, fontName=font_name, fontSize=8.2, leading=12, textColor=colors.HexColor("#176548"))

    story = [
        Paragraph(f"{_text(project_name)} 竞品档案汇总", cover_title),
        Paragraph(f"共收录 {len(records)} 家竞品 · 导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}", subtitle),
    ]
    for index, (competitor, websites, keywords) in enumerate(records, 1):
        if index > 1:
            story.append(PageBreak())
        story.extend([
            Paragraph(f"{index:02d}. {_text(competitor.name)}", company_title),
            Paragraph("基本信息", heading),
        ])
        info = Table([
            [Paragraph("公司名称", body), Paragraph(_text(competitor.name), body)],
            [Paragraph("国家 / 地区", body), Paragraph(_text(competitor.country), body)],
            [Paragraph("调研备注", body), Paragraph(_text(competitor.notes), body)],
        ], colWidths=[34 * mm, 140 * mm])
        info.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF4EE")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6E5DC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([info, Paragraph(f"竞品网站（{len(websites)}）", heading)])
        website_rows = [[Paragraph("网站名称", header), Paragraph("类型", header), Paragraph("网址", header)]]
        website_rows.extend([[Paragraph(_text(item.name), body), Paragraph(_text(item.website_type), body), Paragraph(_text(item.url), link)] for item in websites])
        if len(website_rows) == 1:
            website_rows.append([Paragraph("—", body), Paragraph("—", body), Paragraph("暂无网站资料", body)])
        website_table = LongTable(website_rows, colWidths=[43 * mm, 29 * mm, 102 * mm], repeatRows=1)
        website_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176548")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([website_table, Paragraph(f"竞品关键词（{len(keywords)}）", heading)])
        keyword_rows = [[Paragraph("关键词", header), Paragraph("语言", header), Paragraph("分类", header)]]
        keyword_rows.extend([[Paragraph(_text(item.keyword), body), Paragraph(_text(item.language), body), Paragraph(_text(item.category), body)] for item in keywords])
        if len(keyword_rows) == 1:
            keyword_rows.append([Paragraph("暂无关键词资料", body), Paragraph("—", body), Paragraph("—", body)])
        keyword_table = LongTable(keyword_rows, colWidths=[92 * mm, 36 * mm, 46 * mm], repeatRows=1)
        keyword_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176548")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF8")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(keyword_table)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B8B7A"))
        canvas.drawString(document.leftMargin, 10 * mm, "Tophoo CRM · 竞品调研汇总")
        canvas.drawRightString(A4[0] - document.rightMargin, 10 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
