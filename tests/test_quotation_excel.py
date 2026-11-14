from datetime import datetime
from io import BytesIO
from decimal import Decimal
from zipfile import ZipFile
from openpyxl import load_workbook
from fastapi.testclient import TestClient
from app.main import app
from app.models import Customer, ProjectContact, Quotation
from app.services.quotation_excel import build_excel
from tests.test_global_access import db, headers
from tests.test_quotations import payload, logo_value, grant


def test_payment_modes_export_matching_amounts_in_excel_and_pdf():
    from pypdf import PdfReader
    from app.services.quotation_pdf import build_pdf

    document = payload()['document']
    document.update(payment_mode='deposit', deposit_percent='40', include_balance=False,
                    items=[dict(description='Coil', quantity='2', unit_price='500')])
    for mode, expected in (
        ('deposit', {'DEPOSIT PAYMENT:': 400, 'BALANCE PAYMENT:': 600}),
        ('full', {'FULL PAYMENT:': 1000}),
    ):
        document['payment_mode'] = mode
        workbook = load_workbook(BytesIO(build_excel(document)), data_only=True)
        sheet = workbook.active
        labels = {'DEPOSIT PAYMENT:', 'BALANCE PAYMENT:', 'FULL PAYMENT:'}
        rows = {sheet[f'L{i}'].value: sheet[f'Q{i}'].value
                for i in range(1, sheet.max_row + 1) if sheet[f'L{i}'].value in labels}
        assert rows == expected
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(document))).pages)
        for label in labels:
            assert (label in text) == (label in expected)


def test_excel_layout_numeric_values_formulas_and_cached_totals():
    document=payload()['document'];document.update(logo_data_url=logo_value(),deposit_label='FULL PAYMENT',deposit_percent='100',internal_notes='PRIVATE INTERNAL NOTE')
    raw=build_excel(document)
    formulas=load_workbook(BytesIO(raw),data_only=False);values=load_workbook(BytesIO(raw),data_only=True)
    s=formulas.active;v=values.active
    assert formulas.sheetnames==['Quotation']
    assert s['A9'].value=='TO (BUYER):' and s['A10'].value=='ATTN:'
    assert v['C9'].value==document['buyer_company'] and v['C10'].value==document['attention']
    assert isinstance(v['R9'].value,datetime)
    assert v['L17'].value==15 and v['N17'].value==170
    assert s['Q17'].value=='=ROUND(L17*N17,2)' and v['Q17'].value==2550
    assert v['Q22'].value==31920 and v['Q23'].value==31920
    assert s['L23'].value=='FULL PAYMENT' and s['Q23'].number_format==s['Q22'].number_format
    assert 'USD' in s['Q23'].number_format and s['Q23'].alignment.horizontal=='right'
    assert str(s.page_setup.paperSize)==s.PAPERSIZE_A4 and s.page_setup.fitToWidth==1 and s.page_setup.fitToHeight==0
    assert str(s.print_area).endswith(f'$R${s.max_row}')
    assert s.print_title_rows=='$1:$16' and s.sheet_view.showGridLines
    assert s.sheet_view.view=='pageBreakPreview'
    assert s.sheet_view.zoomScale==85 and s.sheet_view.topLeftCell=='A1'
    assert len(s._images)==1
    text='\n'.join(str(c.value or '') for row in v for c in row)
    assert 'PRIVATE INTERNAL NOTE' not in text and 'Cherry' not in text
    assert 'Seller' in text and 'Buyer' in text
    assert v.cell(v.max_row,2).value==document['seller_company']
    assert v.cell(v.max_row,11).value==document['buyer_company']


def test_optional_bank_balance_currency_and_literal_formula_text():
    document=payload()['document']
    document.update(currency='EUR',include_balance=True,include_bank=False,bank_account='001234',beneficiary_name='Private bank name',buyer_company='=HYPERLINK("https://example.com")')
    s=load_workbook(BytesIO(build_excel(document)),data_only=True).active
    assert s['C9'].data_type=='s' and s['C9'].value.startswith('=HYPERLINK')
    assert 'EUR' in s['Q17'].number_format
    text='\n'.join(str(c.value or '') for row in s for c in row)
    assert 'BALANCE PAYMENT:' in text and 'Private bank name' not in text and '001234' not in text
    document['include_bank']=True
    raw=build_excel(document);s=load_workbook(BytesIO(raw),data_only=True).active
    cells=[c for row in s for c in row]
    assert any(c.value=='Private bank name' for c in cells)
    assert any(c.value=='001234' and c.data_type=='s' for c in cells)
    with ZipFile(BytesIO(raw)) as archive:
        assert not any(name.startswith('xl/externalLinks/') for name in archive.namelist())


def test_rounding_and_long_specifications_do_not_duplicate_quantities():
    document=payload()['document'];document['items']=[dict(description='\n'.join('Specification '+str(i) for i in range(70)),quantity='1.005',unit_price='1.00')]
    raw=build_excel(document);s=load_workbook(BytesIO(raw),data_only=True).active
    body=[c for row in s for c in row]
    assert sum(c.value==1.01 for c in body)>=2  # Line amount and total.
    assert sum(c.value==1.005 for c in body)==2  # Input quantity and total only.
    assert all((r.height or 0)<=409.5 for r in s.row_dimensions.values())
    text='\n'.join(str(c.value or '') for c in body)
    for index in range(70):assert 'Specification '+str(index) in text
    document['items']=[dict(description=f'Coil {i}',quantity='1',unit_price='1.00') for i in range(100)]
    s=load_workbook(BytesIO(build_excel(document)),data_only=True).active
    assert s['Q117'].value==100
    assert s.max_row>100 and s.page_setup.fitToHeight==0


def test_excel_export_scoped_and_uses_latest_customer_without_saving(db):
    client=TestClient(app);grant(db)
    customer=Customer(workspace_id=1,name='Buyer',company='Old buyer',company_address='Old address')
    db.add(customer);db.flush();db.add(ProjectContact(site_project_id=1,contact_id=customer.id,owner_user_id=1));db.commit()
    body=payload();body['customer_id']=customer.id
    row=client.post('/api/quotations/projects/1',headers=headers(1),json=body).json()
    quote=db.get(Quotation,row['id']);before=(quote.data_json,quote.revision,quote.updated_at)
    customer.company='Current buyer';customer.company_address='Current full address';db.commit()
    path=f'/api/quotations/projects/1/{quote.id}/xlsx'
    response=client.get(path,headers=headers(1))
    assert response.status_code==200
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert '.xlsx' in response.headers['content-disposition']
    s=load_workbook(BytesIO(response.content),data_only=True).active
    assert s['C9'].value=='Current buyer' and s['C13'].value=='Current full address'
    assert (quote.data_json,quote.revision,quote.updated_at)==before
    assert client.get(path,headers=headers(2)).status_code==404
    assert client.get(path.replace('/projects/1/','/projects/2/'),headers=headers(1)).status_code==404
    assert client.get(path).status_code==401

def test_local_charge_export_formula_and_cached_amounts():
    from pypdf import PdfReader
    from app.services.quotation_pdf import build_pdf
    from app.services.quotation import defaults
    document=defaults()
    document.update(buyer_company='Local charge buyer',currency='RMB',include_local_charge=True,
                    local_charge_amount='300.00',local_charge_label='FOB   Foshan  Charge :',deposit_label='deposit   payment:',deposit_percent='50',include_balance=True,
                    items=[dict(description='Heat exchanger',quantity='4',unit_price='3809.75')])
    raw=build_excel(document)
    formulas=load_workbook(BytesIO(raw),data_only=False).active
    values=load_workbook(BytesIO(raw),data_only=True).active
    assert values['I18'].value=='TOTAL' and values['Q18'].value==15239
    assert values['L19'].value=='FOB Foshan Charge :' and values['Q19'].value==300
    assert formulas['Q20'].value=='=Q18+Q19' and values['Q20'].value==15539
    assert formulas['L18'].value=='=SUM(L17:L17)' and values['L18'].value==4
    assert values['L20'].value=='TOTAL:'
    assert values['L21'].value=='deposit payment:'
    assert formulas['Q21'].value=='=ROUND(Q20*50/100,2)' and values['Q21'].value==7769.5
    assert formulas['Q22'].value=='=Q20-Q21' and values['Q22'].value==7769.5
    text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(document))).pages)
    assert 'FOB Foshan Charge :' in text
    assert '15539.00' in text and '7769.50' in text
    document['include_local_charge']=False
    text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(document))).pages)
    assert 'Local Charge' not in text

def test_custom_summary_names_are_saved_in_templates_and_exported_verbatim():
    from app.services.quotation_templates import normalize_settings
    document=payload()['document']
    labels=dict(quantity_label='Total Units',subtotal_label='Product Subtotal',
                total_label='Grand Total Due',deposit_label='Advance Payment',
                balance_label='Remaining Payment')
    document.update(**labels,include_local_charge=True,local_charge_label='Origin Handling',
                    local_charge_amount='2000.00',include_balance=True)
    settings=normalize_settings(labels)
    assert all(settings[key]==value for key,value in labels.items())
    raw=build_excel(document)
    values=load_workbook(BytesIO(raw),data_only=True).active
    text='\n'.join(str(cell.value or '') for row in values for cell in row)
    from app.services.quotation_pdf import build_pdf
    from pypdf import PdfReader
    pdf_text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(document))).pages)
    for label in [*labels.values(),'Origin Handling']:
        assert label in text
        assert label in pdf_text
    assert 'ADVANCE PAYMENT' not in pdf_text
    document.update(include_local_charge=False)
    pdf_text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(document))).pages)
    assert 'Grand Total Due' in pdf_text and 'Origin Handling' not in pdf_text
