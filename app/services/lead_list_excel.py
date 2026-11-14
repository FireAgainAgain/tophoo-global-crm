"""Company details, contacts and follow-up notes for the current lead search."""
from io import BytesIO
from urllib.parse import urlsplit

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
COLUMNS = [('公司名称', 36), ('公司官网', 42), ('国家', 16), ('公司备注', 80),
           ('联系人信息', 60), ('跟进', 68)]
CONTACT_FIELDS = (
    ('email', '邮箱'), ('phone', '电话'), ('whatsapp', 'WhatsApp'),
    ('linkedin', 'LinkedIn'), ('facebook', 'Facebook'),
    ('instagram', 'Instagram'), ('youtube', 'YouTube'),
)
DATA_ROW_HEIGHT = 48


def text(value):
    # Imported values such as company names starting with "=" remain literal text.
    return ILLEGAL_CHARACTERS_RE.sub('�', str(value or '')).strip()


def website(value):
    value = text(value)
    if not value:
        return '', None
    url = value if '://' in value else 'https://' + value
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or any(c.isspace() for c in url):
            return value, None
        return value, url
    except ValueError:
        return value, None


def contact_details(people):
    blocks = []
    for person in people:
        name = text(person.get('contact_name'))
        details = [f'{label}：{value}' for key, label in CONTACT_FIELDS
                   if (value := text(person.get(key)))]
        if not (name or details):
            continue
        heading = name or '未填写姓名'
        if person.get('is_primary'):
            heading += '（主联系人）'
        blocks.append('\n'.join([heading, *details]))
    return '\n\n'.join(blocks)


def export_lead_list_excel(items, scope=''):
    last = get_column_letter(len(COLUMNS))
    book = Workbook()
    sheet = book.active
    sheet.title = '线索列表'
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 85
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.sheet_properties.tabColor = '19724D'
    book.properties.title = '线索公司清单'
    book.properties.creator = 'TOPHOO'
    book.properties.description = scope

    for col, (label, width) in enumerate(COLUMNS, 1):
        cell = sheet.cell(1, col, label)
        cell.font = Font(name='Microsoft YaHei', size=10, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='19724D')
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = Border(right=Side(style='thin', color='3A8969'))
        sheet.column_dimensions[get_column_letter(col)].width = width
    sheet.row_dimensions[1].height = 30

    for index, item in enumerate(items, 2):
        site_label, site_url = website(item.get('company_website'))
        contacts = contact_details(item.get('contacts') or ())
        followup = text(item.get('followup'))
        values = (text(item.get('company_name')), site_label,
                  text(item.get('country')), text(item.get('notes')), contacts, followup)
        for col, value in enumerate(values, 1):
            cell = sheet.cell(index, col, value)
            cell.data_type = 's'
            cell.number_format = '@'
            cell.font = Font(name='Microsoft YaHei', size=10, color='33443D', bold=col == 1)
            cell.fill = PatternFill('solid', fgColor='F2F7F4' if index % 2 == 0 else 'FFFFFF')
            cell.alignment = Alignment(horizontal='center' if col == 3 else 'left',
                                       vertical='top' if col >= 4 else 'center',
                                       wrap_text=True, indent=1)
            cell.border = Border(bottom=Side(style='hair', color='E4ECE7'))
        sheet.row_dimensions[index].height = DATA_ROW_HEIGHT
        if site_url:
            sheet.cell(index, 2).hyperlink = site_url
            sheet.cell(index, 2).font = Font(name='Microsoft YaHei', size=10, color='19724D')

    end = 1 + len(items)
    sheet.auto_filter.ref = f'A1:{last}{end}'
    sheet.freeze_panes = 'B2'
    sheet.print_title_rows = '1:1'
    sheet.print_area = f'A1:{last}{end}'
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_margins = PageMargins(left=.25, right=.25, top=.35, bottom=.35, header=.15, footer=.15)
    sheet.oddFooter.center.text = '第 &P 页 / 共 &N 页'
    output = BytesIO()
    book.save(output)
    return output.getvalue()
