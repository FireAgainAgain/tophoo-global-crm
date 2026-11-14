"""A4 sales contract PDF and printable Excel layouts."""
from base64 import b64decode
from html import escape
from io import BytesIO
from math import ceil

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image as PillowImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.quotation_pdf import CJK, fonts
from app.services.sales_contract import contract_totals, document_terms, receipt_fields, rmb_upper


def contract_blocks(number, doc):
    domestic = doc.layout == "domestic"
    totals = contract_totals(doc)
    seller = ("供方", "联系人", "电话", "邮箱", "地址", "税号") if domestic else (
        "Seller", "From", "Tel", "Email", "Address", "Tax ID")
    buyer = ("需方", *seller[1:]) if domestic else ("Buyer", "Attn", *seller[2:])
    parties = [
        ((seller[0], doc.seller_company), (buyer[0], doc.buyer_company)),
        ((seller[1], doc.salesperson), (buyer[1], doc.attention)),
        ((seller[2], doc.seller_phone), (buyer[2], doc.buyer_phone)),
        ((seller[3], doc.seller_email), (buyer[3], doc.buyer_email)),
        ((seller[4], doc.seller_address), (buyer[4], doc.buyer_address)),
        ((seller[5], doc.seller_tax_id), (buyer[5], doc.buyer_tax_id)),
    ]
    parties = [(left, right) for left, right in parties if left[1] or right[1]]
    meta = [
        ("合同编号" if domestic else "S/C No.", number),
        ("签订日期" if domestic else "Date", doc.contract_date.isoformat()),
        ("签订地点" if domestic else "Signing Place", doc.signing_place),
        ("商品" if domestic else "Commodity", doc.commodity),
        ("HS 编码" if domestic else "HS Code", doc.hs_code),
    ]
    headers = ["序号", "名称 / 商标", "规格", "数量 / 单位", "单价", "金额", "备注"] if domestic else [
        "S/N", "Specifications / Model", "Quantity", "Unit Price", "Amount"]
    items = []
    for index, (item, amount) in enumerate(zip(doc.items, totals["lines"]), 1):
        if domestic:
            items.append([index, "\n".join(filter(None, (item.name, item.brand))), item.description,
                          item.quantity, item.unit_price, amount, item.remark])
        else:
            specs = "\n".join(filter(None, (item.name, item.description, item.brand, item.remark)))
            items.append([index, specs, item.quantity, item.unit_price, amount])
    units = [item.unit for item in doc.items]
    summary = []
    if doc.charge_amount:
        summary.extend([("产品小计" if domestic else "Items Subtotal", totals["subtotal"]),
                        (doc.charge_label or ("附加费用" if domestic else "Additional Charge"), doc.charge_amount)])
    summary.append(("合计" if domestic else "Total", totals["total"]))
    if doc.payment_mode == "deposit":
        summary.extend([("定金" if domestic else "Deposit Payment", totals["deposit"]),
                        ("尾款" if domestic else "Balance Payment", totals["balance"])])
    else:
        summary.append(("全款" if domestic else "Full Payment", totals["total"]))
    return parties, [(key, value) for key, value in meta if value], headers, items, units, summary


def png_image(uri):
    raw = BytesIO(b64decode(uri.split(",", 1)[1]))
    output = BytesIO()
    with PillowImage.open(raw) as image:
        image.convert("RGBA").save(output, format="PNG")
    output.seek(0)
    return output


def build_pdf(number, doc):
    domestic = doc.layout == "domestic"
    title = "产品购销合同" if domestic else "SALES CONTRACT"
    parties, meta, headers, items, units, summary = contract_blocks(number, doc)
    regular, bold = fonts({"labels": "合同"})
    output = BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=A4, leftMargin=39, rightMargin=39,
                            topMargin=36, bottomMargin=37, title=title + " " + number)
    width = A4[0] - 90
    ink = colors.HexColor("#202b36")
    body = ParagraphStyle("ContractBody", fontName=regular, fontSize=9, leading=13, textColor=ink, wordWrap="CJK")
    small = ParagraphStyle("ContractSmall", parent=body, fontSize=8.3, leading=11)
    strong = ParagraphStyle("ContractStrong", parent=body, fontName=bold)
    company_style = ParagraphStyle("ContractCompany", parent=strong, fontSize=15, leading=18)
    heading = ParagraphStyle("ContractTitle", parent=strong, alignment=TA_CENTER, fontSize=17, leading=24)
    right = ParagraphStyle("ContractRight", parent=small, alignment=TA_RIGHT)

    def p(value, style=body):
        value = escape(str(value)).replace("\n", "<br/>")
        return Paragraph(CJK.sub(lambda match: '<font name="STSong-Light">' + match[0] + "</font>", value), style)

    def image(uri, max_width, max_height):
        result = Image(png_image(uri), mask="auto")
        scale = min(max_width / result.imageWidth, max_height / result.imageHeight)
        result.drawWidth = result.imageWidth * scale
        result.drawHeight = result.imageHeight * scale
        return result

    def label(pair):
        return p(f"{pair[0]}  {pair[1]}", small) if pair[1] else ""

    company = [p(doc.seller_company, company_style), p(doc.seller_address, small)]
    branding = Table([[image(doc.logo_data_url, 103, 43), company]], colWidths=[120, width - 120]) if doc.logo_data_url else Table([[company]], colWidths=[width])
    branding.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LINEBELOW", (0, 0), (-1, -1), .6, ink)]))
    story = [branding, Spacer(1, 8), p(title, heading)]
    metadata = [[label(pair) for pair in meta[index:index + 2]] for index in range(0, len(meta), 2)]
    for row in metadata:
        if len(row) == 1:
            row.append("")
    story.append(Table(metadata, colWidths=[width / 2] * 2, hAlign="LEFT"))
    party_table = Table([[label(left), label(right_pair)] for left, right_pair in parties], colWidths=[width / 2] * 2)
    party_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f5f8"))]))
    story.extend([party_table, Spacer(1, 12)])

    numeric = {4, 5} if domestic else {3, 4}
    quantity_index = 3 if domestic else 2
    detail = [[p(title + (f" ({doc.currency})" if col in numeric else ""), small)
               for col, title in enumerate(headers)]]
    for cells, unit in zip(items, units):
        formatted = []
        for col, value in enumerate(cells):
            if col in numeric:
                formatted.append(p(f"{value:,.2f}", right))
            elif col == quantity_index:
                formatted.append(p(f"{value.normalize():f}" + (f"\n{unit}" if unit else ""), small))
            else:
                formatted.append(p(value, small))
        detail.append(formatted)
    fractions = (.06, .14, .36, .10, .11, .12, .11) if domestic else (.07, .51, .12, .15, .15)
    details = LongTable(detail, colWidths=[width * fraction for fraction in fractions], repeatRows=1, splitInRow=1)
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6edf4")),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#a9b6c4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([details, Spacer(1, 4)])
    amounts = [[p(key, right), p(f"{doc.currency} {value:,.2f}", right)] for key, value in summary]
    story.append(Table(amounts, colWidths=[width * .7, width * .3]))
    if domestic:
        story.append(p(rmb_upper(contract_totals(doc)["total"]), strong))
    story.append(Spacer(1, 8))
    for key, value in document_terms(doc):
        story.append(p(f"{key}  {value}"))
    if doc.receipt_mode != "none":
        story.extend([Spacer(1, 10), p("收款资料" if domestic else "Payment Details", strong)])
        for key, value in receipt_fields(doc):
            if value:
                story.append(p(f"{key}  {value}"))
        if doc.alipay_qr:
            qr = image(doc.alipay_qr, 111, 111)
            qr.hAlign = "LEFT"
            story.append(qr)
    story.append(Spacer(1, 15))
    signatures = [
        [p(f"{parties[0][0][0]}  {doc.seller_company}", strong), p(f"{parties[0][1][0]}  {doc.buyer_company}", strong)],
        [p("签名 / 盖章：" if domestic else "Signature / Stamp:"), p("签名 / 盖章：" if domestic else "Signature / Stamp:")],
        [p("日期：" if domestic else "Date:"), p("日期：" if domestic else "Date:")],
    ]
    signature = Table(signatures, colWidths=[width / 2] * 2, rowHeights=[None, 28, 18])
    signature.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), .5, ink),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(KeepTogether([signature]))

    def page_number(canvas, document):
        canvas.setFont(regular, 8)
        canvas.drawRightString(A4[0] - 40, 22, str(document.page))

    pdf.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()


def build_excel(number, doc):
    domestic = doc.layout == "domestic"
    title = "产品购销合同" if domestic else "SALES CONTRACT"
    parties, meta, headers, items, units, summary = contract_blocks(number, doc)
    book = Workbook()
    sheet = book.active
    sheet.title = "合同" if domestic else "Sales Contract"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    sheet.print_options.horizontalCentered = True
    for col in range(1, 13):
        sheet.column_dimensions[get_column_letter(col)].width = 10

    def put(row, first, last, value, *, kind="body", money=False):
        if last > first:
            sheet.merge_cells(start_row=row, end_row=row, start_column=first, end_column=last)
        cell = sheet.cell(row, first, value)
        if isinstance(value, str):
            cell.data_type = "s"
        if money:
            cell.number_format = "#,##0.00"
        cell.font = Font(name="等线", size=17 if kind == "title" else 11,
                         color="FFFFFF" if kind == "header" else "203142", bold=kind != "body")
        cell.alignment = Alignment(vertical="center", wrap_text=True, horizontal=(
            "right" if money else "center" if kind in {"title", "header"} else "left"))
        if kind == "header":
            cell.fill = PatternFill("solid", fgColor="334D65")
        if kind in {"header", "item"}:
            edge = Side(style="thin", color="CFDAE5")
            cell.border = Border(left=edge, right=edge, top=edge, bottom=edge)
        lines = sum(max(1, ceil(sum(2 if ord(char) > 255 else 1 for char in line) /
                                max(6, (last - first + 1) * 9))) for line in str(value).split("\n"))
        sheet.row_dimensions[row].height = min(409, max(sheet.row_dimensions[row].height or 0, lines * 15 + 8))

    def add_image(uri, anchor, max_width, max_height):
        image = ExcelImage(png_image(uri))
        scale = min(max_width / image.width, max_height / image.height)
        image.width *= scale
        image.height *= scale
        sheet.add_image(image, anchor)

    if doc.logo_data_url:
        add_image(doc.logo_data_url, "A1", 108, 51)
    put(1, 3 if doc.logo_data_url else 1, 12, doc.seller_company, kind="strong")
    put(2, 3 if doc.logo_data_url else 1, 12, doc.seller_address)
    put(3, 1, 12, title, kind="title")
    row = 4
    for i in range(0, len(meta), 2):
        for offset, (key, value) in enumerate(meta[i:i+2]):
            put(row, 1 + offset * 6, 6 + offset * 6, f"{key}  {value}")
        row += 1
    for left, right in parties:
        for (key, value), first in ((left, 1), (right, 7)):
            put(row, first, first + 5, f"{key}  {value}" if value else "")
        row += 1
    row += 1
    ranges = [(1, 1), (2, 3), (4, 7), (8, 8), (9, 9), (10, 10), (11, 12)] if domestic else [
        (1, 1), (2, 7), (8, 8), (9, 10), (11, 12)]
    numeric = {4, 5} if domestic else {3, 4}
    for index, ((first, last), label) in enumerate(zip(ranges, headers)):
        put(row, first, last, label + (f" ({doc.currency})" if index in numeric else ""), kind="header")
    sheet.freeze_panes = f"B{row+1}"
    sheet.print_title_rows = f"{row}:{row}"
    for cells, unit in zip(items, units):
        cells = list(cells)
        quantity = 3 if domestic else 2
        if unit:
            cells[quantity] = f"{cells[quantity].normalize():f} {unit}"
        sections = []
        for (first, last), value in zip(ranges, cells):
            sections.append(excel_text_parts(value, (last - first + 1) * 8) if isinstance(value, str) else [value])
        for part in range(max(map(len, sections))):
            row += 1
            for index, ((first, last), chunks) in enumerate(zip(ranges, sections)):
                put(row, first, last, chunks[part] if part < len(chunks) else "",
                    kind="item", money=index in numeric)
    for key, value in summary:
        row += 1
        put(row, 1, 10, f"{key}  {doc.currency}", kind="strong")
        put(row, 11, 12, value, money=True)
    if domestic:
        row += 1
        put(row, 1, 12, rmb_upper(contract_totals(doc)["total"]), kind="strong")
    row += 1
    for key, value in document_terms(doc):
        for index, part in enumerate(excel_text_parts(value, 70)):
            row += 1
            put(row, 1, 3, key if index == 0 else "", kind="strong")
            put(row, 4, 12, part)
    if doc.receipt_mode != "none":
        row += 2
        put(row, 1, 12, "收款资料" if domestic else "Payment Details", kind="strong")
        for key, value in receipt_fields(doc):
            if not value:
                continue
            row += 1
            put(row, 1, 3, key, kind="strong")
            put(row, 4, 12, value)
        if doc.alipay_qr:
            row += 1
            add_image(doc.alipay_qr, f"B{row}", 144, 144)
            sheet.row_dimensions[row].height = 116
    row += 2
    put(row, 1, 6, f"{parties[0][0][0]}  {doc.seller_company}", kind="strong")
    put(row, 7, 12, f"{parties[0][1][0]}  {doc.buyer_company}", kind="strong")
    for label in ("签名 / 盖章：", "日期：") if domestic else ("Signature / Stamp:", "Date:"):
        row += 1
        put(row, 1, 6, label)
        put(row, 7, 12, label)
    sheet.print_area = f"A1:L{row}"
    result = BytesIO()
    book.save(result)
    return result.getvalue()


def excel_text_parts(value, line_width):
    """Keep long content visible beyond Excel's per-row height limit."""
    lines = []
    for original in value.split("\n"):
        line = ""
        width = 0
        for char in original:
            size = 2 if ord(char) > 255 else 1
            if width + size > line_width:
                lines.append(line)
                line, width = "", 0
            line += char
            width += size
        lines.append(line)
    if len(lines) <= 20:
        return [value]
    return ["\n".join(lines[index:index + 20]) for index in range(0, len(lines), 20)]
