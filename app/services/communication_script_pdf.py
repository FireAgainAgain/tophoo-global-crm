"""PDF exports for knowledge-base categories and individual entries."""
from html import escape
from io import BytesIO
from pathlib import Path
import re


def _inline(text: object) -> str:
    """Translate supported inline Markdown without treating user HTML as markup."""
    source = str(text or "")
    tokens = re.compile(r"`([^`\n]+)`|\[([^\]\n]+)\]\((https?://[^\s)]+)\)|\*\*([^\n]+?)\*\*|__([^\n]+?)__|~~([^\n]+?)~~|\*([^*\n]+)\*|_([^_\n]+)_")
    pieces, offset = [], 0
    for match in tokens.finditer(source):
        pieces.append(escape(source[offset:match.start()]))
        code, label, url, bold, under_bold, strike, italic, under_italic = match.groups()
        if code is not None:
            pieces.append('<font color="#843D40" backColor="#EDF4EF">' + escape(code) + '</font>')
        elif label is not None:
            pieces.append('<link href="' + escape(url, quote=True) + '" color="#13744F"><u>' + _inline(label) + '</u></link>')
        else:
            tag = 'b' if bold is not None or under_bold is not None else ('strike' if strike is not None else 'i')
            value = next(value for value in (bold, under_bold, strike, italic, under_italic) if value is not None)
            pieces.append('<' + tag + '>' + _inline(value) + '</' + tag + '>')
        offset = match.end()
    pieces.append(escape(source[offset:]))
    return ''.join(pieces)


def _cells(line):
    # Preserve escaped pipes and pipes inside inline code in table cells.
    source = line.strip()
    if source.startswith('|'):
        source = source[1:]
    if source.endswith('|') and not source.endswith('\\|'):
        source = source[:-1]
    cells, cell, in_code, escaped = [], [], False, False
    for char in source:
        if escaped:
            cell.append(char if char in '|\\`' else '\\' + char); escaped = False
        elif char == '\\':
            escaped = True
        elif char == '`':
            in_code = not in_code; cell.append(char)
        elif char == '|' and not in_code:
            cells.append(''.join(cell).strip()); cell = []
        else:
            cell.append(char)
    if escaped:
        cell.append('\\')
    cells.append(''.join(cell).strip())
    return cells


def _markdown_blocks(content: str, styles, font: str):
    """Build styled, paginated blocks for the Markdown used by the reader."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import HRFlowable, LongTable, Paragraph, Spacer, TableStyle, XPreformatted

    blocks, paragraph = [], []
    lines = str(content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    mm = styles["mm"]
    width = 176 * mm

    def flush_paragraph():
        if paragraph:
            blocks.append(Paragraph('<br/>'.join(_inline(line) for line in paragraph), styles['body']))
            blocks.append(Spacer(1, 2.5 * mm))
            paragraph.clear()

    def code_block(code):
        # Preformatted keeps intentional code literal; wrap before it can clip.
        wrapped = []
        for line in code:
            current = ''
            for char in line.expandtabs(4):
                if current and stringWidth(current + char, font, styles['code'].fontSize) > width - 16 * mm:
                    wrapped.append(current); current = ''
                current += char
            wrapped.append(current)
        blocks.append(XPreformatted(escape('\n'.join(wrapped)), styles['code']))
        blocks.append(Spacer(1, 3 * mm))

    while index < len(lines):
        line = lines[index].rstrip()
        fence = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            flush_paragraph(); marker = fence.group(1); code = []; index += 1
            while index < len(lines) and not re.match(r'^\s*' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}\s*$', lines[index]):
                code.append(lines[index]); index += 1
            code_block(code); index += 1; continue
        if not line.strip():
            flush_paragraph(); index += 1; continue
        separator = _cells(lines[index + 1]) if index + 1 < len(lines) else []
        if '|' in line and len(separator) > 1 and all(re.fullmatch(r':?-{3,}:?', cell) for cell in separator):
            flush_paragraph(); headers = _cells(line); count = len(headers)
            alignments = ['CENTER' if cell.startswith(':') and cell.endswith(':') else ('RIGHT' if cell.endswith(':') else 'LEFT') for cell in separator]
            rows = [headers]; index += 2
            while index < len(lines) and lines[index].strip() and '|' in lines[index]:
                cells = _cells(lines[index]); rows.append((cells + [''] * count)[:count]); index += 1
            data = []
            for row_index, row in enumerate(rows):
                cells = []
                for column, value in enumerate(row):
                    base = styles['table_head' if row_index == 0 else 'table_cell']
                    aligned = ParagraphStyle('table-cell', parent=base, alignment={'LEFT': 0, 'CENTER': 1, 'RIGHT': 2}.get(alignments[column] if column < len(alignments) else 'LEFT', 0))
                    cells.append(Paragraph(_inline(value), aligned))
                data.append(cells)
            table = LongTable(data, colWidths=[width / count] * count, repeatRows=1, splitInRow=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8F3EC')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F6FAF7')]),
                ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#CCDCD2')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ]))
            blocks.extend([table, Spacer(1, 3 * mm)]); continue
        heading = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', line)
        if heading:
            flush_paragraph(); level = min(len(heading.group(1)), 3)
            blocks.append(Paragraph(_inline(heading.group(2)), styles[f'heading_{level}'])); index += 1; continue
        if re.match(r'^\s*([-*_])(?:\s*\1){2,}\s*$', line):
            flush_paragraph(); blocks.append(HRFlowable(width='100%', thickness=.6, color=colors.HexColor('#CCDCD2'), spaceBefore=5, spaceAfter=8)); index += 1; continue
        quote = re.match(r'^\s*>\s?(.*)$', line)
        if quote:
            flush_paragraph(); quoted = []
            while index < len(lines):
                match = re.match(r'^\s*>\s?(.*)$', lines[index])
                if not match:
                    break
                quoted.append(_inline(match.group(1))); index += 1
            blocks.extend([Paragraph('<br/>'.join(quoted), styles['quote']), Spacer(1, 3 * mm)]); continue
        bullet = re.match(r'^(\s*)[-+*]\s+(.+)$', line)
        ordered = re.match(r'^(\s*)(\d+)[.)]\s+(.+)$', line)
        if bullet or ordered:
            flush_paragraph(); match = bullet or ordered
            depth = min(len(match.group(1).expandtabs(2)) // 2, 6)
            item_style = ParagraphStyle('nested-list', parent=styles['list'], leftIndent=(11 + depth * 5) * mm, bulletIndent=(4 + depth * 5) * mm)
            body = bullet.group(2) if bullet else ordered.group(3)
            marker = '•' if bullet else ordered.group(2) + '.'
            task = re.match(r'^\[([ xX])\]\s+(.*)$', body)
            if task:
                body = ('已完成：' if task.group(1).lower() == 'x' else '待完成：') + task.group(2)
            blocks.append(Paragraph(_inline(body), item_style, bulletText=marker)); index += 1; continue
        paragraph.append(line); index += 1
    flush_paragraph()
    return blocks or [Paragraph('暂无内容。', styles['muted'])]


def export_knowledge_category_pdf(category, scripts) -> bytes:
    return _export_knowledge_pdf(category, scripts)


def export_knowledge_script_pdf(category, script) -> bytes:
    return _export_knowledge_pdf(category, [script], single=True)


def _export_knowledge_pdf(category, scripts, single=False) -> bytes:
    """Share typography and pagination across category and entry exports."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = "KnowledgeChineseUI"
    bold_font = "KnowledgeChineseUIBold"
    try:
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, str(Path("C:/Windows/Fonts/msyh.ttc"))))
    except Exception:
        font = "STSong-Light"
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font))

    try:
        if bold_font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(bold_font, str(Path("C:/Windows/Fonts/msyhbd.ttc"))))
    except Exception:
        bold_font = font
    pdfmetrics.registerFontFamily(font, normal=font, bold=bold_font, italic=font, boldItalic=bold_font)

    output = BytesIO()
    title = scripts[0].title if single else category.name
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=17 * mm, bottomMargin=17 * mm, title=title)
    base = getSampleStyleSheet()
    styles = {
        "mm": mm,
        "title": ParagraphStyle("knowledge-title", parent=base["Title"], fontName=font, fontSize=23, leading=30, textColor=colors.HexColor("#155C42"), alignment=TA_LEFT, spaceAfter=4),
        "subtitle": ParagraphStyle("knowledge-subtitle", parent=base["BodyText"], fontName=font, fontSize=10, leading=15, textColor=colors.HexColor("#688477"), spaceAfter=14),
        "entry": ParagraphStyle("knowledge-entry", parent=base["Heading2"], fontName=font, fontSize=15, leading=22, textColor=colors.HexColor("#1B6347"), spaceBefore=10, spaceAfter=6, keepWithNext=True),
        "heading_1": ParagraphStyle("knowledge-h1", parent=base["Heading2"], fontName=font, fontSize=15, leading=21, textColor=colors.HexColor("#1B6347"), spaceBefore=7, spaceAfter=5, keepWithNext=True),
        "heading_2": ParagraphStyle("knowledge-h2", parent=base["Heading3"], fontName=font, fontSize=13, leading=19, textColor=colors.HexColor("#2A6C50"), spaceBefore=6, spaceAfter=4, keepWithNext=True),
        "heading_3": ParagraphStyle("knowledge-h3", parent=base["Heading4"], fontName=font, fontSize=11, leading=17, textColor=colors.HexColor("#386D56"), spaceBefore=5, spaceAfter=3, keepWithNext=True),
        "body": ParagraphStyle("knowledge-body", parent=base["BodyText"], fontName=font, fontSize=10, leading=16, textColor=colors.HexColor("#294637")),
        "list": ParagraphStyle("knowledge-list", parent=base["BodyText"], fontName=font, fontSize=10, leading=16, leftIndent=11 * mm, firstLineIndent=0, bulletIndent=4 * mm, textColor=colors.HexColor("#294637"), spaceAfter=1.5 * mm),
        "quote": ParagraphStyle("knowledge-quote", parent=base["BodyText"], fontName=font, fontSize=10, leading=16, leftIndent=7 * mm, borderColor=colors.HexColor("#79B494"), borderWidth=2, borderPadding=7, backColor=colors.HexColor("#F1F8F4"), textColor=colors.HexColor("#4E705E")),
        "code": ParagraphStyle("knowledge-code", fontName=font, fontSize=8.5, leading=13, leftIndent=5 * mm, rightIndent=5 * mm, borderColor=colors.HexColor("#D7E5DD"), borderWidth=.5, borderPadding=7, backColor=colors.HexColor("#F5F8F6"), textColor=colors.HexColor("#294637")),
        "muted": ParagraphStyle("knowledge-muted", parent=base["BodyText"], fontName=font, fontSize=10, leading=16, textColor=colors.HexColor("#7B9485")),
    }

    for value in styles.values():
        if isinstance(value, ParagraphStyle):
            value.wordWrap = 'CJK'
    styles['table_cell'] = ParagraphStyle('knowledge-table-cell', parent=styles['body'], fontSize=9, leading=14)
    styles['table_head'] = ParagraphStyle('knowledge-table-head', parent=styles['table_cell'], fontName=bold_font, textColor=colors.HexColor('#31533F'))

    story = [
        Paragraph(_inline(title), styles["title"]),
        Paragraph("知识库 · " + _inline(category.name) if single else "知识库分类导出 · 按当前条目顺序整理", styles["subtitle"]),
    ]
    overview = Table([["知识分类", category.name], ["知识条目", f"{len(scripts)} 条"]], colWidths=[35 * mm, 142 * mm])
    overview.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#31533F")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F3EC")),
        ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#D4E4DA")), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    if not single:
        story.extend([overview, Spacer(1, 5 * mm)])

    for index, script in enumerate(scripts, 1):
        if not single:
            story.append(Paragraph(_inline(script.title), styles["entry"]))
        story.extend(_markdown_blocks(script.content, styles, font))
        if index < len(scripts):
            story.append(Spacer(1, 2 * mm))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D4E4DA"))
        canvas.line(document.leftMargin, 12 * mm, A4[0] - document.rightMargin, 12 * mm)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#6B8B7A"))
        canvas.drawString(document.leftMargin, 7.5 * mm, "TOPHOO Global · 知识库（内部资料）")
        canvas.drawRightString(A4[0] - document.rightMargin, 7.5 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
