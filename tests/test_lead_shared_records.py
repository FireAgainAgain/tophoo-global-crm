"""Lead/customer record parity, conversion integrity and retired data cleanup."""
import json
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from app.main import app
from app.models import Base, ContactRecord, Customer, CustomerPerson, Lead, LeadInteraction, FollowUpPlan, ProjectMember
from app.services.lead_development import retire_lead_followup_data
from tests.test_global_access import db, headers

BASE='/api/customer-workflow/projects/1/leads'
BODY={'direction':'inbound','contact_name':'Engineer','occurred_at':'2026-10-14T16:35:47','channel':'WhatsApp','subject':'Technical inquiry','content':'  Please send specifications.\r\nThank you.  ','content_translation':' 请发送技术参数。\r\n谢谢。 '}


def create_lead(client,name='Record buyer',**extra):
    return client.post(BASE,headers=headers(2),json={'company_name':name,**extra}).json()['id']


def test_same_record_fields_and_precise_transfer_with_translations(db):
    client=TestClient(app);lid=create_lead(client)
    source=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=BODY)
    assert source.status_code==201,source.text
    source=source.json()
    assert source['occurred_at']=='2026-10-14T16:35:47'
    assert source['content']=='Please send specifications.\nThank you.'
    assert source['content_translation']=='请发送技术参数。\n谢谢。'
    assert db.get(Lead,lid).workflow_status=='unviewed'
    original=db.get(LeadInteraction,source['id']);created,updated=original.created_at,original.updated_at
    cid=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).json()['customer_id']
    target=client.get(f'/api/contacts/projects/1/{cid}/records',headers=headers(2)).json()['records'][0]
    for key in ('direction','contact_name','occurred_at','channel','subject','content','content_translation','created_by_name','created_at','updated_at'):
        assert target[key]==source[key],key
    stored=db.scalar(select(ContactRecord));assert stored.created_at==created and stored.updated_at==updated
    assert '主题：' not in stored.content and not db.scalars(select(FollowUpPlan)).all()
    assert client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).status_code==404
    assert len(db.scalars(select(ContactRecord)).all())==1
    ordinary=client.post(f'/api/contacts/projects/1/{cid}/records',headers=headers(2),json=BODY).json()
    assert set(ordinary)==set(source)


def test_edit_and_permissions_match_customer_records(db):
    client=TestClient(app);lid=create_lead(client)
    rid=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=BODY).json()['id']
    payload={key:value for key,value in BODY.items() if key!='subject'};payload['content_translation']='Updated translation'
    result=client.put(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2),json=payload).json()
    assert result['subject']=='Technical inquiry' and result['content_translation']=='Updated translation'
    older_payload={key:value for key,value in payload.items() if key!='content_translation'}
    unchanged=client.put(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2),json=older_payload).json()
    assert unchanged['content_translation']=='Updated translation'
    assert client.put(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2),json={**payload,'content':'   '}).status_code==422
    denied=client.get(f'{BASE}/{lid}/interactions'.replace('/projects/1/','/projects/2/'),headers=headers(2))
    assert denied.status_code in (403,404)
    assert client.get(f'{BASE}/{lid}/development',headers=headers(2)).status_code==404
    assert 'development' not in client.get(BASE,headers=headers(2)).json()['items'][0]
    assert 'crm_lead_development' not in Base.metadata.tables


def test_shared_platform_urls_do_not_merge_distinct_companies(db):
    client=TestClient(app)
    first=create_lead(client,'Company A',company_website='https://www.facebook.com/company-a')
    second=create_lead(client,'Company B',company_website='https://www.facebook.com/company-b')
    a=client.post(f'{BASE}/{first}/to-customers',headers=headers(2)).json()['customer_id']
    b=client.post(f'{BASE}/{second}/to-customers',headers=headers(2)).json()['customer_id']
    assert a!=b and len(db.scalars(select(Customer)).all())==2


def test_merge_fills_matching_person_without_duplicate_or_primary_change(db):
    client=TestClient(app)
    c=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Known buyer','company_website':'https://known.test','contacts':[{'contact_name':'Alice','phone':'+49 (123) 456','is_primary':True},{'contact_name':'Bob','email':'bob@known.test'}]}).json()
    primary=db.scalar(select(CustomerPerson).where(CustomerPerson.customer_id==c['id'],CustomerPerson.primary_slot==1)).id
    lid=create_lead(client,company_website='https://known.test',contacts=[{'contact_name':'Alice','phone':'+49 123456','email':'alice@known.test','is_primary':True}])
    assert client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).json()['customer_id']==c['id']
    people=db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id==c['id'])).all()
    assert len(people)==2
    assert next(p for p in people if p.primary_slot==1).id==primary
    assert next(p for p in people if p.id==primary).email=='alice@known.test'


def test_batch_preview_catches_internal_conflicts_without_writing(db):
    client=TestClient(app);a=create_lead(client,'Same company');b=create_lead(client,'Same company')
    preview=client.post(BASE+'/batch/conversion-preview',headers=headers(2),json={'ids':[a,b]}).json()
    assert not preview['can_convert'] and preview['items'][1]['mode']=='blocked'
    assert not db.scalars(select(Customer)).all() and len(db.scalars(select(Lead)).all())==2


def test_batch_preview_shared_identity_matches_atomic_merge(db):
    client=TestClient(app);a=create_lead(client,'Company A',company_website='https://shared.test');b=create_lead(client,'Company A branch',company_website='https://shared.test')
    preview=client.post(BASE+'/batch/conversion-preview',headers=headers(2),json={'ids':[a,b]}).json()
    assert preview['can_convert'] and [x['mode'] for x in preview['items']]==['created','merged']
    assert client.post(BASE+'/batch/to-customers',headers=headers(2),json={'ids':[a,b]}).status_code==200
    assert len(db.scalars(select(Customer)).all())==1 and not db.scalars(select(Lead)).all()


def test_retired_arrangement_data_removed_without_touching_customer_plans():
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_lead_development (id INTEGER,priority TEXT)'))
        conn.execute(text("INSERT INTO crm_lead_development VALUES (1,'high')"))
        conn.execute(text('CREATE TABLE crm_lead_conversion_history (id INTEGER,snapshot_json TEXT)'))
        conn.execute(text('INSERT INTO crm_lead_conversion_history VALUES (1,:snapshot)'),{'snapshot':json.dumps({'notes':'keep','development':{'priority':'high'},'interactions':[{'content_translation':'keep translation'}]})})
        conn.execute(text('CREATE TABLE crm_follow_up_plans (id INTEGER,title TEXT)'))
        conn.execute(text("INSERT INTO crm_follow_up_plans VALUES (1,'Customer plan')"))
    retire_lead_followup_data(engine);retire_lead_followup_data(engine)
    assert 'crm_lead_development' not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        snapshot=json.loads(conn.scalar(text('SELECT snapshot_json FROM crm_lead_conversion_history')))
        assert 'development' not in snapshot and snapshot['notes']=='keep'
        assert snapshot['interactions'][0]['content_translation']=='keep translation'
        assert conn.scalar(text('SELECT title FROM crm_follow_up_plans'))=='Customer plan'
    engine.dispose()


def test_both_record_editors_enforce_read_only_project_role(db):
    client=TestClient(app);lid=create_lead(client)
    c=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Customer records'}).json()
    url=f"/api/contacts/projects/1/{c['id']}/records"
    rid=client.post(url,headers=headers(2),json=BODY).json()['id']
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2));member.role='viewer';db.commit()
    read=client.get(url,headers=headers(2));assert read.status_code==200
    denied=client.post(url,headers=headers(2),json=BODY);assert denied.status_code==403
    denied=client.put(f'{url}/{rid}',headers=headers(2),json=BODY);assert denied.status_code==403
    denied=client.delete(f'{url}/{rid}',headers=headers(2));assert denied.status_code==403
    denied=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=BODY);assert denied.status_code==403
    assert len(db.scalars(select(ContactRecord)).all())==1 and not db.scalars(select(LeadInteraction)).all()


def test_five_field_summary_preserves_legacy_history_and_lists_contacts(db):
    client=TestClient(app)
    customer=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Summary Buyer','contacts':[{'contact_name':'Alice','is_primary':True},{'contact_name':'Bob'}]}).json()
    endpoint=f"/api/contacts/projects/1/{customer['id']}/records"
    old=client.post(endpoint,headers=headers(2),json={**BODY,'contact_name':'Alice'}).json()
    five={'contact_name':'Bob','occurred_at':old['occurred_at'],'channel':'WhatsApp','subject':'确认电源和数量','content':'三相 AC 200V；等待除湿量和采购数量。'}
    updated=client.put(endpoint+f"/{old['id']}",headers=headers(2),json=five)
    assert updated.status_code==200,updated.text
    updated=updated.json()
    assert updated['subject']==five['subject'] and updated['content']==five['content']
    assert updated['direction']=='inbound' and updated['content_translation']==old['content_translation']
    assert updated['occurred_at']==old['occurred_at'] and updated['created_at']==old['created_at']
    fetched=client.get(endpoint,headers=headers(2)).json()
    assert [p['contact_name'] for p in fetched['contact']['contacts']]==['Alice','Bob']
    exported=client.get(endpoint+'/export/md',headers=headers(2))
    assert exported.status_code==200 and '## 记录' in exported.text and '确认电源和数量' in exported.text and '请发送技术参数' in exported.text
    lid=create_lead(client,'Summary Lead')
    posted=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=five)
    assert posted.status_code==201,posted.text
    cid=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).json()['customer_id']
    moved=client.get(f'/api/contacts/projects/1/{cid}/records',headers=headers(2)).json()['records']
    assert len(moved)==1 and all(moved[0][key]==five[key] for key in five)
