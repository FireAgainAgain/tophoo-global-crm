"""Customer-facing A4 quotation matching the supplied standard layout."""
from html import escape
from io import BytesIO
from pathlib import Path
import json
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Table, LongTable, Paragraph, Spacer, KeepTogether, TableStyle
from app.services.quotation import QuoteDocument, calculate


CJK = re.compile(r'([\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60]+)')

def fonts(document):
    hidden={'internal_notes','logo_data_url','template_name','template_id','template_revision','pdf_layout','pdf_logo_width'}
    if not document.get('include_bank'):hidden.update({'beneficiary_name','beneficiary_address','beneficiary_bank','bank_address','bank_account','swift_code'})
    visible={key:value for key,value in document.items() if key not in hidden}
    if CJK.search(json.dumps(visible,ensure_ascii=False)):
        if 'STSong-Light' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    regular=Path('C:/Windows/Fonts/arial.ttf');bold=Path('C:/Windows/Fonts/arialbd.ttf')
    if regular.exists() and bold.exists():
        if 'QuoteArial' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('QuoteArial',str(regular)));pdfmetrics.registerFont(TTFont('QuoteArialBold',str(bold)))
        return 'QuoteArial','QuoteArialBold'
    return 'Helvetica','Helvetica-Bold'


def logo_for_pdf(raw):
    """Fit the visible mark, excluding uploaded white/transparent margins."""
    from PIL import Image, ImageChops
    with Image.open(BytesIO(raw)) as source:
        rgba=source.convert('RGBA')
        background=Image.new('RGBA',rgba.size,'white')
        background.alpha_composite(rgba)
        rgb=background.convert('RGB')
        difference=ImageChops.difference(rgb,Image.new('RGB',rgb.size,'white'))
        bounds=difference.convert('L').point(lambda value:255 if value>20 else 0).getbbox()
        image=rgba.crop(bounds) if bounds else rgba
        output=BytesIO();image.save(output,format='PNG');output.seek(0)
        return output


def build_pdf(document):
    doc=QuoteDocument(**document);d=doc.model_dump(mode='json');totals=calculate(doc)
    regular,bold=fonts(d);width=A4[0]-102
    compact=doc.pdf_layout=='compact'
    body=ParagraphStyle('QuoteBody',fontName=regular,fontSize=7.8 if compact else 8.2,leading=10 if compact else 10.5,spaceAfter=0,wordWrap='CJK')
    row_height=22 if compact else 25.5
    row_padding=4 if compact else 7
    strong=ParagraphStyle('QuoteStrong',parent=body,fontName=bold)
    centered=ParagraphStyle('QuoteCenter',parent=body,alignment=1)
    small=ParagraphStyle('QuoteSmall',parent=body,textColor=colors.black)
    def text(value):
        escaped=escape(str(value or '')).replace('\n','<br/>')
        return CJK.sub(lambda match:'<font name="STSong-Light">'+match.group(0)+'</font>',escaped)
    def p(value,style=body):return Paragraph(text(value),style)
    from reportlab.platypus import Image
    branding=None
    if doc.logo_data_url:
        import base64
        raw=base64.b64decode(doc.logo_data_url.split(',',1)[1])
        branding=Image(logo_for_pdf(raw),mask='auto')
        scale=min(doc.pdf_logo_width/branding.imageWidth,60/branding.imageHeight)
        branding.drawWidth=branding.imageWidth*scale;branding.drawHeight=branding.imageHeight*scale
    company_width=width-130 if branding else width
    # Match the supplied letterhead: title, address, paired email/web and tel/fax.
    company_text_width=sum(pdfmetrics.stringWidth(part,'STSong-Light' if CJK.fullmatch(part) else bold,1)
                           for part in CJK.split(doc.seller_company) if part)
    heading_size=max(11,min(16.5,company_width/max(company_text_width,1)))
    heading=ParagraphStyle('QuoteCompany',parent=strong,fontSize=heading_size,leading=heading_size+.5,spaceAfter=3,textColor=colors.black)
    letterhead_text=ParagraphStyle('QuoteLetterheadText',parent=body,fontSize=7.7,leading=11.5,textColor=colors.black)
    contact_rows=[]
    for pair in [(('Email','seller_email'),('Website','seller_website')),(('Tel','seller_phone'),('Fax','seller_fax'))]:
        if any(d[key] for _,key in pair):
            contact_rows.append([p(f'{label}: {d[key]}',letterhead_text) if d[key] else '' for label,key in pair])
    contacts=Table(contact_rows,colWidths=[company_width*.43,company_width*.57],style=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(0,-1),8),('RIGHTPADDING',(1,0),(1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]) if contact_rows else Spacer(1,0)
    company=[p(doc.seller_company,heading)]
    if doc.seller_address:company.extend([p('Add: '+doc.seller_address,letterhead_text),Spacer(1,3)])
    company.append(contacts)
    header=Table([[branding,company]] if branding else [[company]],colWidths=[130,company_width] if branding else [width],style=[('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(0,0),(0,0),'CENTER'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])
    _,header_height=header.wrap(width,0)
    if header_height>180:raise ValueError('卖方抬头信息过长，请精简公司名称、地址或联系方式后导出。')
    header_top=58
    top=A4[1]-header_top-header_height-35
    output=BytesIO()
    document_pdf=BaseDocTemplate(output,pagesize=A4,leftMargin=51,rightMargin=51,topMargin=A4[1]-top,bottomMargin=45,title='Heat Exchanger Quotation',author=doc.seller_company)
    def on_page(canvas,_):
        header.drawOn(canvas,51,A4[1]-header_top-header_height)
        line=A4[1]-header_top-header_height-4
        canvas.setStrokeColor(colors.black);canvas.setLineWidth(.45)
        canvas.line(51,line,A4[0]-51,line);canvas.line(51,line-1.5,A4[0]-51,line-1.5)
        canvas.setFillColor(colors.black);canvas.setFont(bold,13);canvas.drawCentredString(A4[0]/2,line-19,'QUOTATION')
        if document_pdf.page>1:
            canvas.setFont(regular,7);canvas.drawRightString(A4[0]-51,25,str(document_pdf.page))
    frame=Frame(51,45,width,top-45,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    document_pdf.addPageTemplates(PageTemplate(id='quotation',frames=[frame],onPage=on_page))
    meta_style=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),1),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),.8),('BOTTOMPADDING',(0,0),(-1,-1),.8)]
    buyer_rows=[('TO (BUYER):',doc.buyer_company),('ATTN:',doc.attention),('TEL:',doc.buyer_phone)]
    if doc.buyer_email:buyer_rows.append(('EMAIL:',doc.buyer_email))
    buyer_rows.append(('ADD:',doc.buyer_address))
    seller_rows=[('DATE:',f'{doc.quote_date.year}/{doc.quote_date.month}/{doc.quote_date.day}'),('FROM:',doc.salesperson)]
    metadata=[]
    for index,(label,value) in enumerate(buyer_rows):
        seller=seller_rows[index] if index<len(seller_rows) else ('','')
        metadata.append([p(label,small),p(value),p(seller[0],small),p(seller[1])])
    # Date/from occupy only the first two rows on the right. Contact and
    # address rows below them may use the full width of the document.
    metadata_style=meta_style+[('SPAN',(1,index),(3,index)) for index in range(2,len(metadata))]
    meta=Table(metadata,colWidths=[104,width-200,40,56],style=metadata_style)
    story=[meta,Spacer(1,10)]
    story.append(Table([[p('COMMODITY:'),p(doc.commodity)]],colWidths=[104,width-104],style=[('LEFTPADDING',(0,0),(-1,-1),1),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    currency=doc.currency
    rows=[[p('S/N',centered),p('SPECIFICATIONS MODEL',centered),p(f'{doc.quantity_label or "QUANTITY"}\n({doc.quantity_unit})',centered),p(f'UNIT PRICE\n({currency}/{doc.quantity_unit})',centered),p(f'AMOUNT\n({currency})',centered)]]
    specification=ParagraphStyle('QuoteSpecification',parent=body,alignment=0,leading=11.5)
    for i,line in enumerate(doc.items):
        qty=format(line.quantity,'f').rstrip('0').rstrip('.') if '.' in format(line.quantity,'f') else str(line.quantity)
        description='\n'.join(part.strip() for part in line.description.splitlines() if part.strip())
        description_style=specification if '\n' in description or len(description)>65 else centered
        rows.append([p(i+1,centered),p(description,description_style),p(qty,centered),p(f'{currency} {line.unit_price:.2f}',centered),p(f'{currency} {totals["line_amounts"][i]}',centered)])
    table=LongTable(rows,colWidths=[32,243,50,74,width-399],minRowHeights=[25.5]+[row_height]*len(doc.items),repeatRows=1,splitInRow=1)
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.8,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,0),2),('BOTTOMPADDING',(0,0),(-1,0),2),('TOPPADDING',(0,1),(-1,-1),row_padding),('BOTTOMPADDING',(0,1),(-1,-1),row_padding),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3)]))
    right=ParagraphStyle('QuoteRight',parent=strong,alignment=2)
    bold_center=ParagraphStyle('QuoteBoldCenter',parent=centered,fontName=bold)
    product_total=totals['items_subtotal'] if doc.include_local_charge else totals['total']
    product_label=(doc.subtotal_label or 'TOTAL') if doc.include_local_charge else (doc.total_label or 'TOTAL')
    total_rows=[[p(product_label,right),p(totals['quantity_total'],bold_center),'',p(f'{currency} {product_total}',right)]]
    totals_table=Table(total_rows,colWidths=[275,50,74,width-399],style=[('RIGHTPADDING',(0,0),(0,0),25),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)])
    payment_amount=totals['total' if doc.payment_mode=='full' else 'deposit']
    payment_table=Table([[Paragraph('<u>'+text(' '.join(doc.payment_label.split()))+'</u>',right),p(f'{currency} {payment_amount}',right)]],colWidths=[399,width-399],style=[('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)])
    tail=[totals_table]
    if doc.include_local_charge:
        for label,amount in ((doc.local_charge_label,totals['local_charge']),(doc.total_label or 'TOTAL:',totals['total'])):
            tail.append(Table([[Paragraph('<u>'+text(' '.join(label.split()))+'</u>',right),p(f'{currency} {amount}',right)]],
                              colWidths=[399,width-399],
                              style=[('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    tail.append(payment_table)
    if doc.shows_balance:
        tail.append(Table([[Paragraph('<u>'+text(doc.balance_label or 'BALANCE PAYMENT:')+'</u>',right),p(f'{currency} {totals["balance"]}',right)]],colWidths=[399,width-399],style=[('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    if doc.estimated_volume is not None:
        tail.append(Table([[p('ESTIMATED TOTAL EQUIPMENT VOLUME:',right),p(f'APPROX. {doc.estimated_volume.normalize():f} CBM',right)]],colWidths=[width-110,110],style=[('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
    tail.append(Spacer(1,3))
    terms=[]
    term_style=ParagraphStyle('QuoteTerm',parent=body,leading=10)
    for label,key in (('*Price Term:','price_term'),('*Payment term:','payment_term'),('*Delivery Time:','delivery_time'),('*Packing:','packing'),('*Origin:','origin'),('*Price validity:','price_validity')):
        style=ParagraphStyle('PriceTerm',parent=term_style,textColor=colors.red) if key=='price_term' else term_style
        terms.append([p(label,term_style),p(d[key],style)])
    if doc.include_bank:
        for label,key in (('Beneficiary Name:','beneficiary_name'),("Beneficiary Address:",'beneficiary_address'),('Beneficiary Bank:','beneficiary_bank'),('Bank Address:','bank_address'),('Beneficiary A/C No:','bank_account'),('Swift Code:','swift_code')):
            if d[key]:terms.append([p(label,term_style),p(d[key],term_style)])
    tail.append(Table(terms,colWidths=[104,width-104],style=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),1),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),.5),('BOTTOMPADDING',(0,0),(-1,-1),.5)]))
    tail.extend([Spacer(1,14),p(doc.contact_line,strong)])
    tail.extend([Spacer(1,12),Table([
        [p('Seller',strong),p(doc.seller_company,strong),p('Buyer',strong),p(doc.buyer_company,strong)],
    ],colWidths=[34,width/2-34,34,width/2-34],style=[
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
        ('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),2),
        ('BOTTOMPADDING',(0,0),(-1,-1),2),
    ])])
    # Move the last product together with normal totals/terms if they cannot
    # fit, rather than producing a separate page containing only the totals.
    tail_block=Table([[tail]],colWidths=[width],style=[('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])
    _,tail_height=tail_block.wrap(width,top-45)
    _,last_height=Table([rows[-1]],colWidths=[32,243,50,74,width-399]).wrap(width,top-45)
    rows_fit=all(Table([row],colWidths=[32,243,50,74,width-399]).wrap(width,top-45)[1]+40 < top-45 for row in rows[1:])
    if tail_height+last_height+40 < top-45 and rows_fit:
        combined=LongTable(rows+[[tail_block,'','','','']],colWidths=[32,243,50,74,width-399],minRowHeights=[25.5]+[row_height]*(len(rows)-1)+[0],repeatRows=1,splitInRow=0)
        combined.setStyle(TableStyle([
            ('GRID',(0,0),(-1,-2),.8,colors.black),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-2),3),('RIGHTPADDING',(0,0),(-1,-2),3),
            ('TOPPADDING',(0,0),(-1,0),2),('BOTTOMPADDING',(0,0),(-1,0),2),
            ('TOPPADDING',(0,1),(-1,-2),row_padding),('BOTTOMPADDING',(0,1),(-1,-2),row_padding),
            ('SPAN',(0,-1),(-1,-1)),('NOSPLIT',(0,-2),(-1,-1)),
            ('LEFTPADDING',(0,-1),(-1,-1),0),('RIGHTPADDING',(0,-1),(-1,-1),0),
            ('TOPPADDING',(0,-1),(-1,-1),0),('BOTTOMPADDING',(0,-1),(-1,-1),0),
        ]))
        story.append(combined)
    else:
        story.extend([table,KeepTogether(tail)])
    document_pdf.build(story)
    return output.getvalue()
