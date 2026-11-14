"""Customer export: commercial details survive the reference-layout renderer."""
from io import BytesIO

from pypdf import PdfReader

from app.services.quotation_pdf import build_pdf
from tests.test_quotations import payload, logo_value


def test_reference_form_one_page_and_optional_fields():
    document = payload()['document']
    document.update(logo_data_url=logo_value(), include_balance=True,
                    include_bank=True, beneficiary_bank='EXAMPLE BANK',
                    internal_notes='PRIVATE NOTE NEVER EXPORT',
                    salesperson_phone='+86 138 0013 8000',
                    salesperson_email='quote@example.com')
    reader = PdfReader(BytesIO(build_pdf(document)))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    for value in ['QUOTATION', '31920.00', '9576.00', '22344.00',
                  'APPROX. 6.82 CBM', 'EXAMPLE BANK']:
        assert value in text
    assert 'PRIVATE NOTE NEVER EXPORT' not in text
    assert '+86 138 0013 8000' not in text and 'quote@example.com' not in text
    document.update(estimated_volume=None, include_bank=False, include_balance=False)
    text = PdfReader(BytesIO(build_pdf(document))).pages[0].extract_text()
    assert 'CBM' not in text and 'EXAMPLE BANK' not in text
    assert 'BALANCE PAYMENT' not in text


def test_multipage_repeats_letterhead_and_product_header_without_losing_items():
    document = payload()['document']
    document['items'] = [dict(description=f'UNIQUE-MODEL-{i:03d}', quantity='1',
                              unit_price='1.00') for i in range(100)]
    reader = PdfReader(BytesIO(build_pdf(document)))
    pages = [page.extract_text() for page in reader.pages]
    assert len(pages) > 1
    for text in pages:
        assert 'QUOTATION' in text and document['seller_company'] in text
        if 'UNIQUE-MODEL-' in text:
            assert 'SPECIFICATIONS MODEL' in text
    text = '\n'.join(pages)
    for i in range(100):
        assert text.count(f'UNIQUE-MODEL-{i:03d}') == 1
    assert 'USD 100.00' in pages[-1]


def test_buyer_precedes_attention_and_multiline_specification_stays_compact():
    document=payload()['document']
    lines=['Overall dimensions: 1650 x 1170 x 1050 mm',
           'Finned tube: diameter 25 x 2.0 mm',
           'Fin type: Spiral wound fins',
           'Tube arrangement: 17 tubes per row x 8 rows',
           'Tube length: 1600 mm', 'Material: All carbon steel']
    document['items']=[dict(description='\n\n'.join(lines),quantity='1',unit_price='2200')]
    raw=build_pdf(document)
    reader=PdfReader(BytesIO(raw));text=reader.pages[0].extract_text()
    assert len(reader.pages)==1
    assert text.index('TO (BUYER):') < text.index('ATTN:')
    for line in lines:
        assert line in text
    # Export formatting must not rewrite the saved specification.
    assert document['items'][0]['description']=='\n\n'.join(lines)


def test_pdf_logo_fits_visible_content_without_uploaded_padding():
    from PIL import Image, ImageDraw
    from app.services.quotation_pdf import logo_for_pdf
    image=Image.new('RGBA',(400,200),'white')
    ImageDraw.Draw(image).rectangle((140,70,259,129),fill='black')
    raw=BytesIO();image.save(raw,format='PNG')
    with Image.open(logo_for_pdf(raw.getvalue())) as trimmed:
        assert trimmed.size==(120,60)


def test_summary_amounts_align_and_company_footer_is_present():
    document=payload()['document']
    document.update(deposit_percent='100',items=[dict(description='Finned tube coil',quantity='1',unit_price='2235')])
    page=PdfReader(BytesIO(build_pdf(document))).pages[0]
    positions=[]
    footer={}
    def visit(text,cm,tm,font,size):
        if text.strip() in ('Seller','Buyer',document['seller_company'],document['buyer_company']):
            footer[text.strip()]=(cm[4]+tm[4]*cm[0]+tm[5]*cm[2],cm[5]+tm[4]*cm[1]+tm[5]*cm[3])
        if text.strip()=='USD 2235.00':
            positions.append(cm[4]+tm[4]*cm[0]+tm[5]*cm[2])
    text=page.extract_text(visitor_text=visit)
    assert len(positions)==4  # Unit price, line amount, total, deposit.
    assert abs(positions[-1]-positions[-2]) < .01
    assert 'Seller' in text and 'Buyer' in text
    labels=['Seller',document['seller_company'],'Buyer',document['buyer_company']]
    assert max(footer[label][1] for label in labels)-min(footer[label][1] for label in labels)<.01
    assert [footer[label][0] for label in labels]==sorted(footer[label][0] for label in labels)
    assert document['buyer_company'] in text
    assert document['seller_company'] in text and 'For further details' in text


def test_custom_payment_label_and_legacy_default():
    document=payload()['document']
    document.update(deposit_percent='100',deposit_label='FULL PAYMENT')
    text=PdfReader(BytesIO(build_pdf(document))).pages[0].extract_text()
    assert 'FULL PAYMENT' in text and '100% DEPOSIT' not in text
    assert 'USD 31920.00' in text
    document['deposit_label']=''
    text=PdfReader(BytesIO(build_pdf(document))).pages[0].extract_text()
    assert '100% DEPOSIT:' in text


def test_date_from_on_right_and_address_uses_full_width():
    document=payload()['document']
    address='Jl. Boulevard Selatan Blok SCBS B No. 10, Sedayu City, Cakung 13910, East Jakarta, Indonesia'
    document.update(buyer_company='Indra Eng',attention='Indra Su',buyer_address=address)
    parts={}
    def visit(text,cm,tm,font,size):
        value=text.strip()
        if value:
            parts[value]=(cm[4]+tm[4]*cm[0]+tm[5]*cm[2],cm[5]+tm[4]*cm[1]+tm[5]*cm[3])
    page=PdfReader(BytesIO(build_pdf(document))).pages[0]
    page.extract_text(visitor_text=visit)
    assert address in parts  # Fits one line using space below the right block.
    assert parts['DATE:'][0]>parts['Indra Eng'][0]
    assert abs(parts['DATE:'][1]-parts['TO (BUYER):'][1])<.01
    assert abs(parts['FROM:'][1]-parts['ATTN:'][1])<.01

def test_chinese_content_keeps_english_summary_in_latin_font():
    document=payload()['document']
    document.update(buyer_company='测试买方公司',currency='RMB',include_local_charge=True,
                    local_charge_label='FOB FOSHAN CHARGE :',local_charge_amount='2000.00',
                    deposit_percent='50',include_balance=True,
                    items=[dict(description='换热器 Heat exchanger',quantity='4',unit_price='3809.75')])
    runs=[]
    def visit(text,cm,tm,font,size):
        if text.strip():
            runs.append((text.strip(),str(font.get('/BaseFont',''))))
    page=PdfReader(BytesIO(build_pdf(document))).pages[0]
    content=page.extract_text(visitor_text=visit)
    assert '测试买方公司' in content and '换热器' in content
    for label in ('FOB FOSHAN CHARGE :','TOTAL:','DEPOSIT PAYMENT:','BALANCE PAYMENT:','RMB 17239.00','RMB 8619.50'):
        matching=[font for text,font in runs if text==label]
        assert matching,label
        assert all('STSong' not in font for font in matching),matching
