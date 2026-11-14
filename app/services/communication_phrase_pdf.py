"""Complete PDF exports of plain-text, bilingual communication phrases."""
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from pathlib import Path


def export_phrases_pdf(categories, scenes, phrases):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, PageBreak

    font = 'PhraseChinese'
    if font not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(TTFont(font, str(Path('C:/Windows/Fonts/msyh.ttc'))))
        except Exception:
            font = 'STSong-Light'
            if font not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(font))
    pdfmetrics.registerFontFamily(font, normal=font, bold=font, italic=font, boldItalic=font)
    # The Chinese text font lacks some emoji used in saved phrases.
    symbol_font = None
    symbol_path = Path('C:/Windows/Fonts/seguisym.ttf')
    if symbol_path.exists():
        symbol_font = 'PhraseSymbols'
        if symbol_font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(symbol_font, str(symbol_path)))
    primary_glyphs = getattr(pdfmetrics.getFont(font).face, 'charToGlyph', None)
    symbol_glyphs = pdfmetrics.getFont(symbol_font).face.charToGlyph if symbol_font else {}
    style = dict(fontName=font, wordWrap='CJK', textColor=colors.HexColor('#304137'))
    title = ParagraphStyle('phrase-title', **style, fontSize=21, leading=28, spaceAfter=6)
    muted = ParagraphStyle('phrase-meta', **{**style, 'textColor':colors.HexColor('#738279')}, fontSize=9, leading=15, spaceAfter=10)
    heading = ParagraphStyle('phrase-scene', **style, fontSize=12, leading=19, spaceBefore=10, spaceAfter=12, keepWithNext=True)
    original = ParagraphStyle('phrase-original', **{**style, 'wordWrap':'LTR'}, fontSize=10.5, leading=16, leftIndent=9, rightIndent=9,
                              backColor=colors.HexColor('#F3F4F6'), borderPadding=7, spaceBefore=7, spaceAfter=10)
    translation = ParagraphStyle('phrase-translation', **{**style, 'textColor':colors.HexColor('#66766B')},
                                 fontSize=9.5, leading=15, spaceAfter=12)

    def plain(value):
        text = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
        parts = []
        for char in text:
            if char == '\n':
                parts.append('<br/>')
            elif primary_glyphs is not None and ord(char) not in primary_glyphs and ord(char) in symbol_glyphs:
                parts.append(f'<font name="{symbol_font}">{escape(char)}</font>')
            else:
                parts.append(escape(char))
        return ''.join(parts)

    class PhraseDocument(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            mark = getattr(flowable, '_outline', None)
            if mark:
                key, label, level = mark
                self.canv.bookmarkPage(key, fit='FitH', top=self.frame._y + flowable.height)
                self.canv.addOutlineEntry(label, key, level=level, closed=level == 1)

    output = BytesIO()
    doc = PhraseDocument(output, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                        topMargin=19*mm, bottomMargin=20*mm, title='沟通话术 - 全部内容')
    date = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
    story = [Paragraph('沟通话术', title), Paragraph(f'全部内容 / 共 {len(phrases)} 条 / {date}', muted)]
    index = 0

    def outline(label, level, text, paragraph_style):
        nonlocal index
        index += 1
        block = Paragraph(plain(text), paragraph_style)
        block._outline = (f'phrase-section-{index}', label, level)
        return block

    category_groups = [(category.id, category.name) for category in categories]
    known_categories = {category.id for category in categories}
    if any(item.category_id not in known_categories for item in phrases):
        category_groups.append((None, '未分类'))
    for category_index, (category_id, category_name) in enumerate(category_groups):
        if category_index:
            story.append(PageBreak())
        entries = [item for item in phrases if item.category_id == category_id or
                   (category_id is None and item.category_id not in known_categories)]
        story.append(outline(category_name, 0, category_name, title))
        story.append(Paragraph(f'共 {len(entries)} 条', muted))
        category_scenes = [scene for scene in scenes if scene.category_id == category_id]
        known_scenes = {scene.id for scene in category_scenes}
        groups = [('未分场景', [item for item in entries if item.scene_id not in known_scenes])]
        groups.extend((scene.name, [item for item in entries if item.scene_id == scene.id]) for scene in category_scenes)
        for name, items in groups:
            if not items:
                continue
            story.append(outline(name, 1, name + f' / {len(items)} 条', heading))
            for number, item in enumerate(items, 1):
                preview = ' '.join(item.content.split())[:60]
                story.append(outline(f'{number}. {preview}', 2, f'话术 {number}', heading))
                block = Paragraph(plain(item.content), original)
                block.keepWithNext = bool(item.translation) and len(item.content) < 800
                story.append(block)
                if item.translation:
                    story.append(Paragraph(plain(item.translation), translation))
                else:
                    story.append(Spacer(1, 3*mm))
        if not entries:
            story.append(Paragraph('暂无话术', muted))

    def footer(canvas, document):
        canvas.showOutline()
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#DFE6E1'))
        canvas.line(doc.leftMargin, 14*mm, A4[0]-doc.rightMargin, 14*mm)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#738279'))
        canvas.drawString(doc.leftMargin, 9*mm, '沟通话术')
        canvas.drawRightString(A4[0]-doc.rightMargin, 9*mm, f'第 {document.page} 页')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    content = output.getvalue()
    # ReportLab emits non-BMP CMap values as scalar hex; PDF requires UTF-16BE.
    # Keep both visible emoji and selectable/copyable original text intact.
    if any(ord(char) > 0xFFFF for item in phrases for char in item.content + (item.translation or '')):
        import re
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(BytesIO(content)))
        for page in writer.pages:
            for reference in page['/Resources'].get('/Font', {}).values():
                mapping = reference.get_object().get('/ToUnicode')
                if mapping:
                    stream = mapping.get_object()
                    raw = stream.get_data()
                    repaired = re.sub(rb'<([0-9A-Fa-f]{5,6})>',
                        lambda match: b'<' + chr(int(match[1], 16)).encode('utf-16-be').hex().upper().encode('ascii') + b'>', raw)
                    if repaired != raw:
                        stream.set_data(repaired)
        final = BytesIO()
        writer.write(final)
        content = final.getvalue()
    return content
