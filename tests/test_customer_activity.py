"""Counts and customer document lists agree without leaking other users' work."""
from datetime import date, datetime
from fastapi.testclient import TestClient
from app.main import app
from app.models import Rfq, Quotation, ContactRecord, ProjectMember, SalesContract
from app.models.follow_up import FollowUpPlan
from tests.test_global_access import db, headers
from tests.test_customer_inline_grade import create


def seed(db, client):
    import json
    from sqlalchemy import select
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.permissions_json=json.dumps(['customer_list','rfq','quotations'])
    db.commit()
    cid = create(client, owner=2)
    for project, owner, suffix in [(1, 1, 'admin'), (1, 2, 'sales'), (2, 2, 'other-project')]:
        db.add(Rfq(site_project_id=project, owner_user_id=owner, contact_id=cid, number='RFQ-'+suffix))
        db.add(Quotation(site_project_id=project, owner_user_id=owner, customer_id=cid,
                         number='Q-'+suffix, quote_date=date(2026,10,31), buyer_company='Buyer', data_json='{}'))
        db.add(SalesContract(site_project_id=project, owner_user_id=owner, customer_id=cid,
                             number='SC-'+suffix, contract_date=date(2026,10,31), document_json='{}'))
        db.add(FollowUpPlan(site_project_id=project, owner_user_id=owner, customer_id=cid,
                            title=suffix, due_at=datetime(2026,11,1)))
        db.add(ContactRecord(site_project_id=project, contact_id=cid, created_by_user_id=owner,
                             content=suffix, channel='邮件'))
    db.add(FollowUpPlan(site_project_id=1, owner_user_id=2, customer_id=cid,
                        title='done', due_at=datetime(2026,10,30), status='completed'))
    db.commit()
    return cid


def test_counts_and_lists_are_customer_project_and_current_user_scoped(db):
    client=TestClient(app);cid=seed(db,client)
    for user_id, suffix in [(1,'admin'),(2,'sales')]:
        response=client.get('/api/contacts/projects/1',headers=headers(user_id))
        assert response.status_code==200,response.text
        customer=next(c for c in response.json()['customers'] if c['id']==cid)
        assert customer['activity_counts']=={'records':2,'rfqs':1,'quotations':1,'contracts':2,'followups':1}
        assert [d['number'] for d in customer['activity_documents']['rfqs']]==['RFQ-'+suffix]
        assert [d['number'] for d in customer['activity_documents']['quotations']]==['Q-'+suffix]
        for kind, prefix in [('rfqs','RFQ-'),('quotations','Q-')]:
            result=client.get(f'/api/contacts/projects/1/{cid}/documents/{kind}',headers=headers(user_id))
            assert result.status_code==200,result.text
            assert [r['number'] for r in result.json()['items']]==[prefix+suffix]
    assert client.get(f'/api/contacts/projects/2/{cid}/documents/rfqs',headers=headers(2)).status_code==403
    other=create(client,owner=1)
    assert client.get(f'/api/contacts/projects/1/{other}/documents/rfqs',headers=headers(2)).status_code==404
    assert client.get(f'/api/contacts/projects/1/{other}/documents/quotations',headers=headers(1)).json()['items']==[]
    assert client.get(f'/api/contacts/projects/1/{cid}/documents/rfqs').status_code==401


def test_module_permission_blocks_document_entries_and_hides_counts(db):
    from sqlalchemy import select
    import json
    client=TestClient(app);cid=seed(db,client)
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.permissions_json=json.dumps(['customer_list'])
    db.commit()
    response=client.get('/api/contacts/projects/1',headers=headers(2))
    assert response.status_code==200,response.text
    customer=next(c for c in response.json()['customers'] if c['id']==cid)
    assert customer['activity_counts']['rfqs'] is None
    assert customer['activity_counts']['quotations'] is None
    assert customer['activity_statuses']=={'rfqs':None,'quotations':None}
    assert customer['activity_documents']=={'rfqs':[],'quotations':[]}
    for kind in ['rfqs','quotations']:
        assert client.get(f'/api/contacts/projects/1/{cid}/documents/{kind}',headers=headers(2)).status_code==403


def test_lead_outreach_badge_counts_accepted_deliveries_for_current_user(db):
    from app.models import Lead
    from app.models.mail import MailDelivery
    client=TestClient(app)
    lead=Lead(site_project_id=1,owner_user_id=2,company_name='Lead buyer')
    db.add(lead);db.flush()
    for index, (project, owner, status) in enumerate([(1,2,'accepted'),(1,2,'accepted'),
                                                     (1,2,'failed'),(1,1,'accepted'),(2,2,'accepted')]):
        db.add(MailDelivery(site_project_id=project,lead_id=lead.id,owner_user_id=owner,
            request_key=f'test-{index}',payload_hash='x'*64,message_id=f'message-{index}',
            sender='seller@example.test',recipient='buyer@example.test',subject='Hello',content='Hello',status=status))
    db.commit()
    response=client.get('/api/customer-workflow/projects/1/leads',headers=headers(2))
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['activity_counts']['outreach']==2
    response=client.get('/api/customer-workflow/projects/1/leads',headers=headers(1))
    assert response.json()['items'][0]['activity_counts']['outreach']==1


def test_document_status_summaries_normalize_legacy_stages_and_match_scoped_totals(db):
    client=TestClient(app);cid=seed(db,client)
    for index,status in enumerate(['需求确认中','报价准备中','已报价','已成交','沟通失败']):
        db.add(Rfq(site_project_id=1,owner_user_id=2,contact_id=cid,
                   number=f'STAGE-{index}',status=status))
    db.add(Quotation(site_project_id=1,owner_user_id=2,customer_id=cid,
                     number='QUOTED',quote_date=date(2026,11,1),buyer_company='Buyer',
                     data_json='{}',status='已报价'))
    db.commit()
    customers=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers']
    customer=next(c for c in customers if c['id']==cid)
    assert customer['activity_statuses']=={
        'rfqs':{'待处理':1,'推进中':2,'已报价':1,'已成交':1,'已关闭':1},
        'quotations':{'草稿':1,'已报价':1}}
    for kind in ['rfqs','quotations']:
        assert sum(customer['activity_statuses'][kind].values())==customer['activity_counts'][kind]
        assert len(customer['activity_documents'][kind])==customer['activity_counts'][kind]
    assert customer['activity_documents']['rfqs'][0]['number']=='STAGE-4'
    assert customer['activity_documents']['rfqs'][0]['status']=='已关闭'
    other=create(client,owner=2)
    customers=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers']
    assert next(c for c in customers if c['id']==other)['activity_statuses']=={'rfqs':{},'quotations':{}}


def test_customer_workspace_full_lists_remain_scoped_to_customer_and_current_user(db):
    import json
    from sqlalchemy import select
    from tests.test_quotations import payload
    client=TestClient(app);cid=seed(db,client)
    for row in db.scalars(select(Quotation)):
        row.data_json=json.dumps(payload()['document'])
    db.commit()
    for uid,suffix in [(1,'admin'),(2,'sales')]:
        for path,prefix in [('rfqs','RFQ-'),('quotations','Q-')]:
            response=client.get(f'/api/{path}/projects/1?customer_id={cid}&mine=true',headers=headers(uid))
            assert response.status_code==200,response.text
            assert [row['number'] for row in response.json()]==[prefix+suffix]
    other=create(client,owner=1)
    for path in ['rfqs','quotations']:
        assert client.get(f'/api/{path}/projects/1?customer_id={other}&mine=true',headers=headers(2)).status_code==404
        assert client.get(f'/api/{path}/projects/2?customer_id={cid}&mine=true',headers=headers(1)).status_code==404
