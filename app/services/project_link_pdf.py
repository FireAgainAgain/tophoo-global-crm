"""PDF export for a project's website navigation."""
from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path


def _text(value: str | None) -> str:
    return escape(str(value or "—")).replace("\n", "<br/>")


def export_project_links_pdf(project, links, *, personal=False) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "CRMProjectLinksChinese"
    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(Path("C:/Windows/Fonts/msyh.ttc"))))
    except Exception:
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm, title=f"{project.name} 网址导航")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("project-links-title", parent=styles["Title"], fontName=font_name, fontSize=20, leading=28, textColor=colors.HexColor("#176548"), spaceAfter=5)
    subtitle = ParagraphStyle("project-links-subtitle", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=15, textColor=colors.HexColor("#668575"), spaceAfter=13)
    body = ParagraphStyle("project-links-body", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=14, textColor=colors.HexColor("#294637"))
    header = ParagraphStyle("project-links-header", parent=body, fontName=font_name, fontSize=9, leading=13, textColor=colors.white)
    scope = "按个人账号保存" if personal else f"项目网站：{_text(project.site_url)}"
    story = [Paragraph(f"{_text(project.name)} · 网址导航", title), Paragraph(f"{scope}<br/>导出日期：{date.today():%Y-%m-%d} · 共 {len(links)} 个网址", subtitle), Spacer(1, 3)]
    rows = [[Paragraph("序号", header), Paragraph("网址名称", header), Paragraph("网址地址", header)]]
    for index, link in enumerate(links, 1):
        rows.append([Paragraph(str(index), body), Paragraph(_text(link.name), body), Paragraph(_text(link.url), body)])
    if len(rows) == 1:
        rows.append([Paragraph("—", body), Paragraph("暂无网址导航记录", body), Paragraph("—", body)])
    table = LongTable(rows, colWidths=[16 * mm, 52 * mm, 106 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176548")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF8")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E5DD")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    def footer(canvas, document):
        canvas.saveState(); canvas.setFont(font_name, 8); canvas.setFillColor(colors.HexColor("#6B8B7A"))
        canvas.drawString(document.leftMargin, 10 * mm, "Tophoo · 个人网址导航" if personal else "Tophoo CRM · 项目管理")
        canvas.drawRightString(A4[0] - document.rightMargin, 10 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
