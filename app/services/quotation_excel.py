"""Fill the packaged Cherry-style Excel layout without an office/runtime dependency.

The blank layout is authored with Artifact Tool. Dynamic rows are filled using
OpenXML; currency values stay numeric and formulas include server-calculated caches.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import base64
import math
import re
import textwrap
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from app.services.quotation import QuoteDocument, calculate
from app.services.quotation_pdf import logo_for_pdf

MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
DRAW='http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
ART='http://schemas.openxmlformats.org/drawingml/2006/main'
ET.register_namespace('',MAIN)
ET.register_namespace('r',REL)
LAYOUT=Path(__file__).resolve().parents[1]/'resources/quotation/cherry-layout.xlsx'


def tag(name):return '{'+MAIN+'}'+name


def xml(node):
    result=ET.tostring(node,encoding='utf-8',xml_declaration=True)
    # OPC package readers expect content-types and relationship roots to use
    # their default namespace; preserve the other drawing namespace prefixes.
    prefix=re.match(rb'<([A-Za-z0-9_]+):[A-Za-z]',result.split(b'?>',1)[-1].lstrip())
    if prefix:
        name=prefix[1]
        result=result.replace(b'<'+name+b':',b'<').replace(b'</'+name+b':',b'</').replace(b'xmlns:'+name+b'=',b'xmlns=')
    return result


def build_excel(document, *, blank_template=False):
    doc=QuoteDocument(**document);d=doc.model_dump(mode='json');totals=calculate(doc)
    if blank_template:totals['quantity_total']='0'
    with ZipFile(LAYOUT) as archive:parts={name:archive.read(name) for name in archive.namelist()}
    sheet=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
    sheet_data=sheet.find(tag('sheetData'))
    prototypes={int(row.get('r')):deepcopy(row) for row in sheet_data}
    sheet_data.clear()
    merges=sheet.find(tag('mergeCells'))
    if merges is None:merges=ET.SubElement(sheet,tag('mergeCells'))
    header_merges=[c.get('ref') for c in merges if int(re.search(r'\d+',c.get('ref'))[0])<=16]
    merges.clear()

    def merge(ref):ET.SubElement(merges,tag('mergeCell'),ref=ref)
    for ref in header_merges:merge(ref)

    def cell(row,column,value=None,formula=None):
        address=f'{column}{row.get("r")}'
        target=next((c for c in row if c.get('r')==address),None)
        if target is None:target=ET.SubElement(row,tag('c'),r=address)
        for child in list(target):target.remove(child)
        target.attrib.pop('t',None)
        if formula is not None:ET.SubElement(target,tag('f')).text=formula
        if value is None:return target
        if isinstance(value,(Decimal,int,float)):
            ET.SubElement(target,tag('v')).text=str(value)
        else:
            # Literal strings cannot execute as Excel formulas or external links.
            target.set('t','inlineStr');text=ET.SubElement(ET.SubElement(target,tag('is')),tag('t'))
            text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            text.text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))
        return target

    def row(number,prototype,height=None):
        result=deepcopy(prototypes[prototype]);result.set('r',str(number))
        for c in result:
            c.set('r',re.sub(r'\d+',str(number),c.get('r')))
            for child in list(c):c.remove(child)
            c.attrib.pop('t',None)
        if height is not None:result.set('ht',str(min(409.5,height)));result.set('customHeight','1')
        sheet_data.append(result);return result

    def height(value,capacity=112):
        return max(18,14*sum(max(1,math.ceil(len(line)/capacity)) for line in str(value).splitlines() or [''])+3)

    header={}
    for number in range(1,17):header[number]=row(number,number)
    for number,values in {
        1:{'E':doc.seller_company},2:{'E':'Add: '+doc.seller_address},
        3:{'E':'Email: '+doc.seller_email,'L':'Website: '+doc.seller_website},
        4:{'E':'Tel: '+doc.seller_phone,'L':'Fax: '+doc.seller_fax},7:{'A':'QUOTATION'},
        9:{'A':'TO (BUYER):','C':None if blank_template else doc.buyer_company,'Q':'DATE:','R':None if blank_template else (doc.quote_date-date(1899,12,30)).days},
        10:{'A':'ATTN:','C':doc.attention,'Q':'FROM:','R':doc.salesperson},
        11:{'A':'TEL:','C':doc.buyer_phone},12:{'A':'EMAIL:','C':doc.buyer_email},
        13:{'A':'ADD:','C':doc.buyer_address},15:{'A':'COMMODITY:','C':doc.commodity},
        16:{'A':'S/N','B':'SPECIFICATIONS MODEL','L':f'{doc.quantity_label or "QUANTITY"}\n({doc.quantity_unit})',
            'N':f'UNIT PRICE\n({doc.currency}/{doc.quantity_unit})','Q':f'AMOUNT\n({doc.currency})'},
    }.items():
        for column,value in values.items():cell(header[number],column,value)
    for number,key,capacity in [(1,'seller_company',48),(2,'seller_address',92),(9,'buyer_company',72),
                                (10,'attention',72),(11,'buyer_phone',112),(12,'buyer_email',112),(13,'buyer_address',112)]:
        header[number].set('ht',str(max(float(header[number].get('ht',19)),height(d[key],capacity)*(1.5 if number==1 else 1))))
    index=17
    for serial,item in enumerate(doc.items,1):
        description='' if blank_template else '\n'.join(line.strip() for line in item.description.splitlines() if line.strip())
        # Excel caps a row at 409.5pt. Split unusually long specifications into
        # continuation rows without repeating quantity or charging twice.
        lines=description.splitlines() or ['']
        chunks=[];chunk=[];line_count=0
        for line in lines:
            segments=textwrap.wrap(line,width=68,break_long_words=True,break_on_hyphens=False) or ['']
            for segment in segments:
                if line_count>=24:chunks.append('\n'.join(chunk));chunk=[];line_count=0
                chunk.append(segment);line_count+=1
        if chunk:chunks.append('\n'.join(chunk))
        for continuation,chunk in enumerate(chunks):
            current=row(index,17,max(28 if doc.pdf_layout=='compact' else 34,height(chunk,68)))
            for span in (f'B{index}:K{index}',f'L{index}:M{index}',f'N{index}:P{index}',f'Q{index}:R{index}'):merge(span)
            cell(current,'B',None if blank_template else chunk)
            if '\n' not in chunk and len(chunk)<=65:
                target=next(c for c in current if c.get('r')==f'B{index}')
                target.set('s',next(c.get('s','0') for c in prototypes[16] if c.get('r')=='B16'))
            if not continuation:
                cell(current,'A',serial);cell(current,'L',None if blank_template else item.quantity);cell(current,'N',None if blank_template else item.unit_price)
                formula=f'ROUND(L{index}*N{index},2)'
                if blank_template:formula=f'IF(COUNT(L{index},N{index})<2,"",{formula})'
                cell(current,'Q',None if blank_template else Decimal(totals['line_amounts'][serial-1]),formula)
            index+=1
    items_end=index-1
    current=row(index,18,24)
    for span in (f'I{index}:K{index}',f'L{index}:M{index}',f'Q{index}:R{index}'):merge(span)
    cell(current,'I',(doc.subtotal_label or 'TOTAL') if doc.include_local_charge else (doc.total_label or 'TOTAL'))
    cell(current,'L',Decimal(totals['quantity_total']),f'SUM(L17:L{items_end})')
    cell(current,'Q',Decimal(totals['items_subtotal'] if doc.include_local_charge else totals['total']),f'SUM(Q17:Q{items_end})')
    total_index=index
    if doc.include_local_charge:
        subtotal_index=index
        index+=1
        current=row(index,19,max(24,height(doc.local_charge_label,35)))
        merge(f'L{index}:P{index}');merge(f'Q{index}:R{index}')
        cell(current,'L',' '.join(doc.local_charge_label.split()))
        cell(current,'Q',doc.local_charge_amount)
        charge_index=index
        index+=1
        current=row(index,19,24)
        merge(f'L{index}:P{index}');merge(f'Q{index}:R{index}')
        cell(current,'L',doc.total_label or 'TOTAL:')
        cell(current,'Q',Decimal(totals['total']),f'Q{subtotal_index}+Q{charge_index}')
        total_index=index
    index+=1;deposit_index=index
    if doc.payment_mode=='full':
        payments=[(doc.payment_label,Decimal(totals['total']),f'Q{total_index}')]
    else:
        payments=[(doc.payment_label,Decimal(totals['deposit']),f'ROUND(Q{total_index}*{doc.deposit_percent}/100,2)')]
    if doc.shows_balance:payments.append((doc.balance_label or 'BALANCE PAYMENT:',Decimal(totals['balance']),f'Q{total_index}-Q{deposit_index}'))
    for label,value,formula in payments:
        current=row(index,19,max(24,height(label,35)));merge(f'L{index}:P{index}');merge(f'Q{index}:R{index}')
        cell(current,'L',' '.join(label.split()));cell(current,'Q',value,formula);index+=1
    if doc.estimated_volume is not None:
        current=row(index,19,24);merge(f'I{index}:P{index}');merge(f'Q{index}:R{index}')
        cell(current,'I','ESTIMATED TOTAL EQUIPMENT VOLUME:');cell(current,'Q',f'APPROX. {doc.estimated_volume.normalize():f} CBM');index+=1
    row(index,14,10);index+=1
    for label,key in (('*Price Term:','price_term'),('*Payment term:','payment_term'),('*Delivery Time:','delivery_time'),
                      ('*Packing:','packing'),('*Origin:','origin'),('*Price validity:','price_validity')):
        current=row(index,20,height(d[key]));merge(f'A{index}:B{index}');merge(f'C{index}:R{index}')
        cell(current,'A',label);cell(current,'C',d[key])
        if key!='price_term':
            target=next(c for c in current if c.get('r')==f'C{index}')
            target.set('s',next(c.get('s','0') for c in prototypes[13] if c.get('r')=='C13'))
        index+=1
    if doc.include_bank:
        row(index,14,12);index+=1
        for label,key in (('Beneficiary Name:','beneficiary_name'),('Beneficiary Address:','beneficiary_address'),
                          ('Beneficiary Bank:','beneficiary_bank'),('Bank Address:','bank_address'),
                          ('Beneficiary A/C No:','bank_account'),('Swift Code:','swift_code')):
            if not d[key]:continue
            current=row(index,22,height(d[key],95));merge(f'A{index}:C{index}');merge(f'E{index}:R{index}')
            cell(current,'A',label);cell(current,'E',d[key]);index+=1
    row(index,14,13);index+=1
    current=row(index,21,height(doc.contact_line,125)+4);merge(f'A{index}:R{index}');cell(current,'A',doc.contact_line)
    index+=1
    row(index,14,12);index+=1
    current=row(index,21,max(height(doc.seller_company,42),height(doc.buyer_company,42))+4)
    merge(f'B{index}:I{index}');merge(f'K{index}:R{index}')
    cell(current,'A','Seller');cell(current,'B',doc.seller_company)
    cell(current,'J','Buyer');cell(current,'K',None if blank_template else doc.buyer_company)
    last=index
    merges.set('count',str(len(merges)))
    dimension=sheet.find(tag('dimension'))
    if dimension is None:
        dimension=ET.Element(tag('dimension'));sheet.insert(0,dimension)
    dimension.set('ref',f'A1:R{last}')
    # Match the reference's Excel opening view: white printable pages with
    # blue page boundaries, and gray outside the defined print area.
    view=sheet.find(tag('sheetViews')+'/'+tag('sheetView'))
    if view is not None:
        view.set('view','pageBreakPreview')
        view.set('showGridLines','1')
        view.set('showRowColHeaders','1')
        view.set('zoomScale','85')
        view.set('zoomScaleSheetLayoutView','85')
        view.set('topLeftCell','A1')
    # Print one A4 page wide; long quotations may use more pages vertically.
    props=sheet.find(tag('sheetPr'))
    if props is None:props=ET.Element(tag('sheetPr'));sheet.insert(0,props)
    existing=props.find(tag('pageSetUpPr'))
    if existing is not None:props.remove(existing)
    ET.SubElement(props,tag('pageSetUpPr'),fitToPage='1')
    for name in ('pageMargins','pageSetup','printOptions'):
        existing=sheet.find(tag(name))
        if existing is not None:sheet.remove(existing)
    ET.SubElement(sheet,tag('printOptions'),horizontalCentered='1')
    ET.SubElement(sheet,tag('pageMargins'),left='0.35',right='0.35',top='0.4',bottom='0.4',header='0.15',footer='0.15')
    ET.SubElement(sheet,tag('pageSetup'),paperSize='9',orientation='portrait',fitToWidth='1',fitToHeight='0')
    workbook=ET.fromstring(parts['xl/workbook.xml'])
    names=workbook.find(tag('definedNames'))
    if names is None:names=ET.SubElement(workbook,tag('definedNames'))
    for child in list(names):names.remove(child)
    ET.SubElement(names,tag('definedName'),name='_xlnm.Print_Area',localSheetId='0').text=f"'Quotation'!$A$1:$R${last}"
    ET.SubElement(names,tag('definedName'),name='_xlnm.Print_Titles',localSheetId='0').text="'Quotation'!$1:$16"
    styles=ET.fromstring(parts['xl/styles.xml'])
    for number_format in styles.findall('.//'+tag('numFmt')):
        number_format.set('formatCode',number_format.get('formatCode','').replace('USD',doc.currency))
    drawing_node=sheet.find(tag('drawing'))
    if drawing_node is not None:sheet.remove(drawing_node)
    if doc.logo_data_url:
        from PIL import Image
        logo=logo_for_pdf(base64.b64decode(doc.logo_data_url.split(',',1)[1])).getvalue()
        with Image.open(BytesIO(logo)) as image:
            scale=min(doc.pdf_logo_width*1.7/image.width,95/image.height)
            width,height_px=image.width*scale,image.height*scale
        drawing=ET.fromstring(parts['xl/drawings/drawing1.xml'])
        extent=drawing.find('.//{'+DRAW+'}ext')
        extent.set('cx',str(int(width*9525)));extent.set('cy',str(int(height_px*9525)))
        parts['xl/drawings/drawing1.xml']=xml(drawing)
        parts['xl/media/image.png']=logo
        sheet.append(drawing_node)
    else:
        for name in list(parts):
            if name.startswith(('xl/drawings/','xl/media/')) or name=='xl/worksheets/_rels/sheet1.xml.rels':del parts[name]
        types=ET.fromstring(parts['[Content_Types].xml'])
        for child in list(types):
            if child.get('PartName','').startswith('/xl/drawings/'):types.remove(child)
        parts['[Content_Types].xml']=xml(types)
    parts['xl/styles.xml']=xml(styles);parts['xl/workbook.xml']=xml(workbook);parts['xl/worksheets/sheet1.xml']=xml(sheet)
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,value in parts.items():archive.writestr(name,value)
    return output.getvalue()
