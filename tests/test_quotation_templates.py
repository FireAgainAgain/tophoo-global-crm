import json
from io import BytesIO
from openpyxl import load_workbook
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Quotation, QuotationTemplate, ProjectMember
from app.services.quotation_templates import seed_templates
from app.services.quotation_pdf import fonts
from tests.test_global_access import db, headers
from tests.test_quotations import payload

BASE='/api/quotations/projects/1'


def create(client,name='标准报价模板',**settings):
    response=client.post(BASE+'/templates',headers=headers(1),json=dict(name=name,settings=settings))
    assert response.status_code==201,response.text
    return response.json()


def test_template_defaults_scope_permissions_validation_and_preview(db):
    client=TestClient(app)
    refs=client.get(BASE+'/references',headers=headers(1)).json()
    assert refs['templates'][0]['name']=='标准报价模板'
    row=create(client,pdf_layout='compact',deposit_label='FULL PAYMENT')
    assert row['settings']['pdf_layout']=='compact'
    assert not {'buyer_company','quote_date','items'} & set(row['settings'])
    assert client.post(BASE+'/templates',headers=headers(1),json=dict(name='Bad',settings={'buyer_company':'Private customer'})).status_code==422
    assert client.post(BASE+'/templates',headers=headers(1),json=dict(name='Bad',settings={'pdf_logo_width':500})).status_code==422
    assert client.post(BASE+'/templates',headers=headers(1),json=dict(name='Bad',settings={'logo_data_url':'http://bad/logo.png'})).status_code==422
    assert client.post(BASE+'/templates',headers=headers(1),json=dict(name='标准报价模板')).status_code==409
    assert client.put(f'/api/quotations/projects/2/templates/{row["id"]}',headers=headers(1),json=row_payload(row)).status_code==404
    assert client.get(BASE+'/templates',headers=headers(2)).status_code==403
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.permissions_json='["quotations"]';member.write_permissions_json='[]';db.commit()
    assert client.get(BASE+'/templates',headers=headers(2)).status_code==200
    assert client.post(BASE+'/templates',headers=headers(2),json={'name':'Denied'}).status_code==403
    response=client.post(BASE+'/templates/preview-pdf',headers=headers(2),json=row_payload(row))
    assert response.status_code==403
    response=client.post(BASE+'/templates/preview-pdf',headers=headers(1),json=row_payload(row))
    assert response.status_code==200 and response.content.startswith(b'%PDF')


def row_payload(row,**patch):
    return {**{key:row[key] for key in ('name','revision','settings')},**patch}


def test_templates_are_equal_choices_and_creation_requires_selection(db):
    client=TestClient(app);first=create(client);second=create(client,'Second')
    legacy=db.get(QuotationTemplate,first['id'])
    legacy.is_active=False;legacy.default_slot=1;db.commit()
    rows=client.get(BASE+'/references',headers=headers(1)).json()['templates']
    assert [row['id'] for row in rows]==[first['id'],second['id']]
    assert all(not {'is_active','is_default'} & row.keys() for row in rows)
    body=payload()
    body['document']['template_id']=None
    assert client.post(BASE,headers=headers(1),json=body).status_code==422
    body['document'].update(template_id=first['id'],template_revision=first['revision'])
    assert client.post(BASE,headers=headers(1),json=body).status_code==201
    path=BASE+f'/templates/{first["id"]}'
    assert client.put(path,headers=headers(1),json=row_payload(first,name='Renamed')).status_code==200
    assert client.put(path,headers=headers(1),json=row_payload(first)).status_code==409


def test_template_excel_matches_quote_layout_with_blank_inputs(db):
    client=TestClient(app)
    template=create(client,'佛山 FOB',currency='CNY',seller_company='Demo EXPORT',
                    include_local_charge=True,local_charge_amount='2000',include_balance=True,
                    deposit_percent='50',local_charge_label='FOB FOSHAN CHARGE')
    path=BASE+f'/templates/{template["id"]}/xlsx'
    response=client.get(path,headers=headers(1))
    assert response.status_code==200 and '.xlsx' in response.headers['content-disposition']
    workbook=load_workbook(BytesIO(response.content))
    sheet=workbook.active
    assert sheet['E1'].value=='Demo EXPORT'
    assert all(sheet[cell].value is None for cell in ['C9','R9','B17','L17','N17'])
    assert 'ROUND(L17*N17,2)' in sheet['Q17'].value
    assert sheet['L19'].value=='FOB FOSHAN CHARGE' and sheet['Q19'].value==2000
    assert sheet['Q20'].value=='=Q18+Q19'
    assert sheet['Q21'].value=='=ROUND(Q20*50/100,2)'
    assert sheet['Q22'].value=='=Q20-Q21'
    body=payload();body['document'].update(template['settings'],template_id=template['id'],estimated_volume=None,
        items=[{'description':'Example','quantity':'1','unit_price':'100'}])
    quote=client.post(BASE,headers=headers(1),json=body)
    assert quote.status_code==201,quote.text
    exported=client.get(BASE+f'/{quote.json()["id"]}/xlsx',headers=headers(1))
    quote_sheet=load_workbook(BytesIO(exported.content)).active
    assert sheet.merged_cells==quote_sheet.merged_cells
    assert sheet.print_area==quote_sheet.print_area
    assert sheet['Q20'].number_format==quote_sheet['Q20'].number_format
    assert client.get(path.replace('/projects/1/','/projects/2/'),headers=headers(1)).status_code==404
    assert client.get(path,headers=headers(2)).status_code==403
    assert client.get(BASE+'/templates/0/xlsx',headers=headers(1)).status_code==200


def test_saved_quote_snapshot_survives_template_update(db):
    client=TestClient(app);template=create(client,pdf_layout='compact',seller_company='Demo COMPANY V1',deposit_label='FULL PAYMENT')
    body=payload();body['document'].update(template['settings'],template_id=template['id'],template_name=template['name'],template_revision=template['revision'])
    response=client.post(BASE,headers=headers(1),json=body)
    assert response.status_code==201,response.text
    quote=response.json();snapshot=quote['document'];totals=quote['totals']
    new_settings={**template['settings'],'seller_company':'Demo COMPANY V2','pdf_layout':'standard'}
    response=client.put(BASE+f'/templates/{template["id"]}',headers=headers(1),json=row_payload(template,settings=new_settings))
    assert response.status_code==200,response.text
    assert client.get(BASE,headers=headers(1)).json()[0]['document']==snapshot
    assert client.get(BASE+f'/{quote["id"]}/pdf',headers=headers(1)).status_code==200
    stale=client.post(BASE,headers=headers(1),json={**body,'number':'STALE'})
    assert stale.status_code==409
    body['document']['buyer_company']='Buyer changed in quote'
    body['revision']=quote['revision']
    response=client.put(BASE+f'/{quote["id"]}',headers=headers(1),json=body)
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['document']['seller_company']=='Demo COMPANY V1'
    assert saved['document']['pdf_layout']=='compact'
    assert saved['document']['template_revision']==snapshot['template_revision']
    assert saved['totals']==totals


def test_legacy_ever_migration_is_idempotent_and_preserves_business_fields(db):
    client=TestClient(app);quote=client.post(BASE,headers=headers(1),json=payload()).json()
    record=db.get(Quotation,quote['id']);original=json.loads(record.data_json)
    for key in ('template_id','template_name','template_revision'):original.pop(key,None)
    record.data_json=json.dumps(original);db.commit()
    revision=record.revision;updated=record.updated_at
    seed_templates(db);db.expire_all();record=db.get(Quotation,quote['id']);migrated=json.loads(record.data_json)
    for key,value in original.items():
        if key not in ('template_id','template_name','template_revision'):assert migrated[key]==value
    assert migrated['template_name']=='标准报价模板' and migrated['template_id']>0
    assert record.revision==revision and record.updated_at==updated
    snapshot=record.data_json
    seed_templates(db);db.expire_all()
    assert db.get(Quotation,quote['id']).data_json==snapshot
    assert len(db.scalars(select(QuotationTemplate).where(QuotationTemplate.site_project_id==1)).all())==1


def test_template_metadata_does_not_switch_english_pdf_to_chinese_font():
    document=payload()['document']
    assert fonts(document)==fonts({**document,'template_name':'标准报价模板'})
