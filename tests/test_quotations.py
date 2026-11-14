import json
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Quotation, ProjectMember, Customer, ProjectContact, Rfq
from app.services.quotation import QuoteDocument, calculate, defaults
from app.services.quotation_pdf import build_pdf
from app.services.quotation_access import enable_quotation_access
from tests.test_global_access import db, headers

BASE='/api/quotations/projects/1'


def test_two_statuses_and_legacy_migration(db):
    from app.services.quotation_status import migrate_quotation_statuses
    client=TestClient(app)
    body=payload()
    for status in ['已成交','已关闭']:
        assert client.post(BASE,headers=headers(1),json={**body,'status':status}).status_code==422
    row=client.post(BASE,headers=headers(1),json={**body,'status':'已报价'}).json()
    item=db.get(Quotation,row['id'])
    item.status='已关闭';db.commit()
    snapshot=item.data_json
    migrate_quotation_statuses(db);db.commit();db.refresh(item)
    assert item.status=='已报价' and item.revision==2 and item.data_json==snapshot
    migrate_quotation_statuses(db);db.commit();db.refresh(item)
    assert item.revision==2

def payload():
    document=defaults();document.update(template_id=0,buyer_company='Example Refrigeration Group',attention='Jamie Example',contact_line='For further details: sales@example.com',quote_date='2026-09-17',estimated_volume='6.82',items=[{'description':f'{hp} HP','quantity':'15','unit_price':str(price)} for hp,price in [(2,170),(3,255),(5,426),(7,596),(10,681)]])
    return {'number':'QT-TEST-001','document':document}

def grant(db,write=None):
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2,ProjectMember.site_project_id==1));member.permissions_json='["quotations"]';member.write_permissions_json=write;db.commit()


def test_quote_crud_decimal_export_revision_and_project_scope(db):
    client=TestClient(app);body=payload()
    body['document'].update(salesperson_phone='+86 138 0013 8000',salesperson_email='quote@example.com',deposit_label='FULL PAYMENT')
    response=client.post(BASE,headers=headers(1),json=body)
    assert response.status_code==201,response.text
    row=response.json();qid=row['id']
    assert row['document']['deposit_label']=='FULL PAYMENT'
    assert row['document']['salesperson_phone']=='+86 138 0013 8000'
    assert row['document']['salesperson_email']=='quote@example.com'
    assert row['totals']=={'line_amounts':['2550.00','3825.00','6390.00','8940.00','10215.00'],'total':'31920.00','quantity_total':'75','deposit':'9576.00','balance':'22344.00'}
    assert row['revision']==1
    assert client.post(BASE,headers=headers(1),json=body).status_code==409
    response=client.get(BASE+f'/{qid}/pdf',headers=headers(1))
    assert response.status_code==200 and response.content.startswith(b'%PDF')
    assert len(re.findall(rb'/Type\s*/Page\b',response.content))==1
    assert client.get(BASE.replace('/1','/2')+f'/{qid}/pdf',headers=headers(1)).status_code==404
    assert client.get(BASE).status_code==401
    updated={**body,'revision':1};updated['document']['items'][0]['unit_price']='180.00'
    response=client.put(BASE+f'/{qid}',headers=headers(1),json=updated)
    assert response.status_code==200 and response.json()['revision']==2
    assert response.json()['totals']['total']=='32070.00'
    assert client.put(BASE+f'/{qid}',headers=headers(1),json=updated).status_code==409
    assert client.delete(BASE+f'/{qid}?revision=1',headers=headers(1)).status_code==409
    assert client.delete(BASE+f'/{qid}?revision=2',headers=headers(1)).status_code==200
    assert not db.scalars(select(Quotation)).all()


def test_readonly_and_owner_scope(db):
    client=TestClient(app);grant(db)
    owner=client.post(BASE,headers=headers(1),json=payload()).json()
    assert client.get(BASE,headers=headers(2)).json()==[]
    assert client.get(BASE+f'/{owner["id"]}/pdf',headers=headers(2)).status_code==404
    assert client.delete(BASE+f'/{owner["id"]}?revision=1',headers=headers(2)).status_code==404
    grant(db,'[]')
    assert client.get(BASE+'/references',headers=headers(2)).status_code==200
    assert client.post(BASE,headers=headers(2),json=payload()).status_code==403
    assert client.post(BASE+'/import-excel',headers=headers(2),files={'file':('x.xlsx',b'x')}).status_code==405


def test_customer_and_rfq_scope_and_live_customer_data(db):
    client=TestClient(app);grant(db)
    customer=Customer(workspace_id=1,name='Buyer',company='Customer snapshot')
    db.add(customer);db.flush();db.add(ProjectContact(site_project_id=1,contact_id=customer.id,owner_user_id=1))
    rfq=Rfq(site_project_id=1,number='RFQ-TEST',owner_user_id=1,contact_id=customer.id);db.add(rfq);db.commit()
    body={**payload(),'customer_id':customer.id,'rfq_id':rfq.id}
    assert client.post(BASE,headers=headers(2),json=body).status_code==422
    row=client.post(BASE,headers=headers(1),json=body).json()
    customer.company='Changed customer master';db.commit()
    assert client.get(BASE,headers=headers(1)).json()[0]['document']['buyer_company']=='Changed customer master'
    assert row['customer_id']==customer.id
    assert row['rfq_id'] is None


def test_decimal_rounding_zero_deposit_invalid_values_and_pagination_pdf():
    d=payload()['document'];d.update(items=[{'description':'Decimal item','quantity':'1.005','unit_price':'1.00'}],deposit_percent='0')
    assert calculate(d)['total']=='1.01' and calculate(d)['deposit']=='0.00'
    for key,value in [('quantity','0'),('unit_price','-1')]:
        invalid={**d,'items':[{'description':'Invalid','quantity':'1','unit_price':'1',key:value}]}
        with pytest.raises(ValueError):QuoteDocument(**invalid)
    d['items']=[{'description':f'Line {i}: custom coil drawing dimensions and connection details','quantity':'1','unit_price':'1.00'} for i in range(100)]
    pdf=build_pdf(d)
    assert len(re.findall(rb'/Type\s*/Page\b',pdf))>1


def test_new_module_migration_preserves_explicit_readonly(db):
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["rfq"]';member.write_permissions_json='[]';db.commit()
    enable_quotation_access(db)
    assert json.loads(member.permissions_json)==['rfq','quotations']
    assert member.write_permissions_json=='[]'
    enable_quotation_access(db)
    assert json.loads(member.permissions_json)==['rfq','quotations']


def test_example_balance_calculated_from_quantity_and_price():
    d=payload()['document'];d.update(include_balance=True,items=[{'description':'Seamless tube','quantity':'120','unit_price':'45.25'}])
    totals=calculate(d)
    assert totals['total']=='5430.00'
    assert totals['deposit']=='1629.00'
    assert totals['balance']=='3801.00'
    assert build_pdf(d).startswith(b'%PDF')


def test_internal_notes_do_not_change_customer_pdf_font():
    from app.services.quotation_pdf import fonts
    d=payload()['document'];d['internal_notes']='内部说明仅内部保存'
    assert fonts(d)==fonts({**d,'internal_notes':''})


def logo_value(color='red'):
    from io import BytesIO
    from PIL import Image
    import base64
    output=BytesIO();Image.new('RGB',(64,24),color).save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')


def test_uploaded_logo_saved_replaced_removed_and_used_by_pdf(db):
    client=TestClient(app);body=payload();body['document']['logo_data_url']=logo_value()
    row=client.post(BASE,headers=headers(1),json=body).json()
    assert row['document']['logo_data_url']==body['document']['logo_data_url']
    pdf=client.get(BASE+f'/{row["id"]}/pdf',headers=headers(1)).content
    assert b'/Width 64' in pdf and b'/Height 24' in pdf
    body.update(revision=row['revision']);body['document']['logo_data_url']=logo_value('blue')
    row=client.put(BASE+f'/{row["id"]}',headers=headers(1),json=body).json()
    assert row['document']['logo_data_url']==logo_value('blue')
    legacy=json.loads(json.dumps(body));legacy['revision']=row['revision'];legacy['document'].pop('logo_data_url')
    row=client.put(BASE+f'/{row["id"]}',headers=headers(1),json=legacy).json()
    assert row['document']['logo_data_url']==logo_value('blue')
    body.update(revision=row['revision']);body['document']['logo_data_url']=''
    row=client.put(BASE+f'/{row["id"]}',headers=headers(1),json=body).json()
    assert row['document']['logo_data_url']==''
    assert b'/Subtype /Image' not in client.get(BASE+f'/{row["id"]}/pdf',headers=headers(1)).content


def test_logo_validation_and_new_quote_has_no_fixed_branding():
    assert defaults()['logo_data_url']==''
    assert b'/Subtype /Image' not in build_pdf(payload()['document'])
    for value in ['https://example.com/logo.png','data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,YmFk']:
        with pytest.raises(ValueError):QuoteDocument(**{**payload()['document'],'logo_data_url':value})


def test_legacy_logo_snapshot_does_not_reapply_after_removal(db, tmp_path, monkeypatch):
    import base64
    from app.services import quotation_logo
    from app.services.quotation_logo import legacy_logo_snapshots
    logo = tmp_path / 'logo.png'
    logo.write_bytes(base64.b64decode(logo_value().split(',')[1]))
    monkeypatch.setattr(quotation_logo, 'LEGACY_LOGO', logo)
    client=TestClient(app);row=client.post(BASE,headers=headers(1),json=payload()).json()
    stored=db.get(Quotation,row['id']);document=json.loads(stored.data_json);document.pop('logo_data_url');stored.data_json=json.dumps(document);db.commit()
    legacy_logo_snapshots(db);first_revision=stored.revision
    assert json.loads(stored.data_json)['logo_data_url'].startswith('data:image/png;base64,')
    legacy_logo_snapshots(db);assert stored.revision==first_revision
    document=json.loads(stored.data_json);document['logo_data_url']='';stored.data_json=json.dumps(document);db.commit()
    legacy_logo_snapshots(db);assert json.loads(stored.data_json)['logo_data_url']==''

def test_optional_local_charge_calculation_validation_and_roundtrip(db):
    from pydantic import ValidationError
    from app.services.quotation_templates import normalize_settings
    document=defaults()
    document.update(template_id=0,buyer_company='Local charge buyer',currency='RMB',
                    items=[dict(description='Heat exchanger',quantity='4',unit_price='3809.75')],
                    deposit_percent='50',include_balance=True,include_local_charge=True,
                    local_charge_amount='300.00')
    totals=calculate(document)
    assert totals['items_subtotal']=='15239.00' and totals['local_charge']=='300.00'
    assert totals['total']=='15539.00' and totals['deposit']=='7769.50' and totals['balance']=='7769.50'
    assert totals['quantity_total']=='4'
    document['include_local_charge']=False
    assert calculate(document)['total']=='15239.00'
    assert 'local_charge' not in calculate(document)
    document['include_local_charge']=True
    for amount in ('-1','1.001','NaN','Infinity'):
        with pytest.raises(ValidationError):
            QuoteDocument(**dict(document,local_charge_amount=amount))
    client=TestClient(app)
    row=client.post(BASE,headers=headers(1),json={'number':'QT-LOCAL','document':document})
    assert row.status_code==201,row.text
    assert row.json()['totals']==totals
    saved=next(item for item in client.get(BASE,headers=headers(1)).json() if item['id']==row.json()['id'])
    assert saved['document']['include_local_charge']
    assert saved['document']['local_charge_amount']=='300.00'
    settings=normalize_settings({'include_local_charge':True,'local_charge_amount':'300.00'})
    assert settings['include_local_charge'] and settings['local_charge_label']=='FOB FOSHAN CHARGE :'
    assert normalize_settings({})['include_local_charge'] is False
