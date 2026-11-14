"""Plans remain scoped; completion and the next plan are one transaction."""
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import ContactRecord, CustomerPerson, ProjectContact, ProjectMember, User
from app.models.follow_up import FollowUpPlan
from tests.test_global_access import db as base_db, headers

@pytest.fixture
def db(base_db):
    base_db.add(ProjectMember(site_project_id=1,user_id=1,role="top_admin"))
    base_db.commit()
    return base_db

BASE='/api/followups/projects/1'


def test_simple_todo_only_requires_content_and_completion_deletes_it(db):

    client=TestClient(app);c=customer(client)
    response=client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json={'title':'  跟进报价反馈  '})
    assert response.status_code==201,response.text
    task=response.json()
    assert task['title']=='跟进报价反馈' and task['owner_user_id']==2
    assert task['due_at']
    listing=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers'][0]
    assert listing['activity_counts']['followups']==1
    assert client.delete(f"{BASE}/{task['id']}?completed=true",headers=headers(2)).status_code==200
    assert db.get(FollowUpPlan,task['id']) is None
    assert client.get(BASE,headers=headers(2)).json()['total']==0
    listing=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers'][0]
    assert listing['activity_counts']['followups']==0 and listing['next_followup'] is None
    assert not db.scalars(select(ContactRecord)).all()


    assert client.delete(f"{BASE}/{task['id']}?completed=true",headers=headers(2)).status_code==404


def test_simple_edit_preserves_existing_plan_metadata(db):
    client=TestClient(app);c=customer(client)
    person=db.scalar(select(CustomerPerson).where(CustomerPerson.customer_id==c['id']))
    task=plan(client,c['id'],person_id=person.id,notes='已有的补充内容',due_at='2026-12-20T09:00:00+08:00')
    # An administrator edits content without reassigning the customer's todo to themselves.
    response=client.put(f"{BASE}/{task['id']}",headers=headers(1),json={'title':'确认报价反馈'})
    assert response.status_code==200,response.text
    updated=response.json()
    assert updated['title']=='确认报价反馈'
    for key in ['person_id','owner_user_id','notes','due_at']:
        assert updated[key]==task[key]


def customer(client, owner=2):
    response=client.post('/api/contacts/projects/1',headers=headers(1),json={'company_name':'Heat Pump Factory','owner_user_id':owner,'contacts':[{'contact_name':'采购经理','email':'buyer@example.test','is_primary':True}]})
    assert response.status_code==201,response.text
    return response.json()


def plan(client, customer_id, user=2, **extra):
    body={'title':'确认换热器工况','due_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),**extra}
    response=client.post(f'{BASE}/customers/{customer_id}',headers=headers(user),json=body)
    assert response.status_code==201,response.text
    return response.json()


def test_multiple_plans_and_nearest_pending_date_are_project_scoped(db):
    client=TestClient(app);c=customer(client)
    later=plan(client,c['id'],title='发送资料',due_at='2026-12-20T09:00:00+08:00')
    earlier=plan(client,c['id'],due_at='2026-12-19T09:00:00+08:00')
    listing=client.get(BASE+'?bucket=pending',headers=headers(2)).json()
    assert [row['id'] for row in listing['items']]==[earlier['id'],later['id']]
    rows=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers']
    assert rows[0]['next_followup']['id']==earlier['id']
    assert earlier['due_at']=='2026-12-19T01:00:00Z'
    assert client.get('/api/followups/projects/2',headers=headers(2)).status_code==403


def test_other_customer_contacts_owners_and_readonly_members_are_rejected(db):
    client=TestClient(app);c=customer(client)
    other=customer(client,1)
    person=db.scalar(select(CustomerPerson).where(CustomerPerson.customer_id==other['id']))
    body={'title':'联系','due_at':'2026-12-20T09:00:00+08:00','person_id':person.id}
    assert client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json=body).status_code==422
    body.pop('person_id');body['owner_user_id']=1
    assert client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json=body).status_code==403
    assert client.post(f"{BASE}/customers/{other['id']}",headers=headers(2),json=body).status_code==404
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.role='viewer';db.commit()
    assert client.get(BASE,headers=headers(2)).json()['can_write'] is False
    assert client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json=body).status_code==403


def test_complete_creates_one_record_and_optional_next_plan_atomically(db):
    client=TestClient(app);c=customer(client)
    person=db.scalar(select(CustomerPerson).where(CustomerPerson.customer_id==c['id']))
    task=plan(client,c['id'],person_id=person.id)
    result={'result':'客户要求补充工况表','channel':'WhatsApp','occurred_at':datetime.now(timezone.utc).isoformat(),'next_plan':{'title':'跟进工况表','due_at':(datetime.now(timezone.utc)+timedelta(days=3)).isoformat(),'person_id':person.id}}
    response=client.post(f"{BASE}/{task['id']}/complete",headers=headers(2),json=result)
    assert response.status_code==200,response.text
    assert response.json()['status']=='completed'
    records=db.scalars(select(ContactRecord)).all()
    assert len(records)==1 and records[0].contact_name=='采购经理' and records[0].content==result['result']
    assert records[0].channel=='WhatsApp'
    pending=client.get(BASE,headers=headers(2)).json()
    assert pending['total']==1 and pending['items'][0]['title']=='跟进工况表'
    assert client.post(f"{BASE}/{task['id']}/complete",headers=headers(2),json=result).status_code==409
    assert len(db.scalars(select(ContactRecord)).all())==1


def test_invalid_completion_keeps_plan_pending_and_no_partial_records(db):
    client=TestClient(app);c=customer(client);task=plan(client,c['id'])
    body={'result':'确认中','channel':'邮件','occurred_at':datetime.now(timezone.utc).isoformat(),'next_plan':{'title':'下一次','due_at':'2026-12-20T09:00:00+08:00','person_id':999999}}
    assert client.post(f"{BASE}/{task['id']}/complete",headers=headers(2),json=body).status_code==422
    assert db.get(FollowUpPlan,task['id']).status=='pending'
    assert not db.scalars(select(ContactRecord)).all()
    body.pop('next_plan');body['result']='   '
    assert client.post(f"{BASE}/{task['id']}/complete",headers=headers(2),json=body).status_code==422


def test_overdue_cancel_and_pagination_do_not_create_contact_records(db):
    client=TestClient(app);c=customer(client)
    task=plan(client,c['id'],due_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
    plan(client,c['id']);plan(client,c['id'])
    listing=client.get(BASE+'?bucket=overdue',headers=headers(2)).json()
    assert listing['total']==1 and listing['items'][0]['is_overdue']
    assert client.get(BASE+'?page_size=1&page=2',headers=headers(2)).json()['total']==3
    assert client.post(f"{BASE}/{task['id']}/cancel",headers=headers(2),json={'reason':'暂不采购'}).status_code==200
    assert client.get(BASE+'?bucket=cancelled',headers=headers(2)).json()['items'][0]['cancellation_reason']=='暂不采购'
    assert not db.scalars(select(ContactRecord)).all()


def test_release_cancels_tasks_restore_does_not_resurrect_them(db):
    client=TestClient(app);c=customer(client);task=plan(client,c['id'])
    assert client.post(f"/api/contacts/projects/1/{c['id']}/release",headers=headers(2),json={'reason':'暂不跟进'}).status_code==200
    assert db.get(FollowUpPlan,task['id']).status=='cancelled'
    assert client.get(BASE,headers=headers(2)).json()['total']==0
    assert client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json={'title':'不应创建','due_at':'2026-12-20T09:00:00+08:00'}).status_code==409
    assert client.post(f"/api/customer-workflow/projects/1/pool/{c['id']}/restore",headers=headers(2),json={}).status_code==200
    assert db.get(FollowUpPlan,task['id']).status=='cancelled'


def test_transfer_and_project_delete_preserve_shared_customer(db):
    client=TestClient(app);c=customer(client);task=plan(client,c['id'])
    response=client.put(f"/api/contacts/projects/1/{c['id']}",headers=headers(1),json={'company_name':'Heat Pump Factory','owner_user_id':1})
    assert response.status_code==200,response.text
    assert db.get(FollowUpPlan,task['id']).owner_user_id==1
    assert client.get(BASE,headers=headers(2)).json()['total']==0
    response=client.put(f"/api/contacts/projects/1/{c['id']}",headers=headers(1),json={'company_name':'Heat Pump Factory','owner_user_id':2,'transfer_followups':False})
    assert response.status_code==200,response.text
    assert db.get(FollowUpPlan,task['id']).status=='cancelled'
    response=client.request('DELETE','/api/workspaces/1/projects/1',headers=headers(1),json={'confirm_name':'Demo'})
    assert response.status_code==200,response.text
    assert not db.scalars(select(FollowUpPlan)).all()


@pytest.mark.parametrize('status', ['pending', 'cancelled', 'completed'])
def test_delete_removes_plan_from_all_history_but_preserves_contact_records(db, status):
    client = TestClient(app)
    c = customer(client)
    task = plan(client, c['id'])
    if status == 'cancelled':
        assert client.post(f"{BASE}/{task['id']}/cancel", headers=headers(2), json={}).status_code == 200
    elif status == 'completed':
        assert client.post(f"{BASE}/{task['id']}/complete", headers=headers(2), json={
            'result': '已联系客户', 'occurred_at': datetime.now(timezone.utc).isoformat(),
        }).status_code == 200
    record_ids = list(db.scalars(select(ContactRecord.id)))
    response = client.delete(f"{BASE}/{task['id']}", headers=headers(2))
    assert response.status_code == 200
    assert db.get(FollowUpPlan, task['id']) is None
    listing = client.get(BASE, headers=headers(2)).json()
    assert all(count == 0 for count in listing['counts'].values())
    assert list(db.scalars(select(ContactRecord.id))) == record_ids
    assert client.get('/api/contacts/projects/1', headers=headers(2)).json()['customers'][0]['next_followup'] is None
    assert client.delete(f"{BASE}/{task['id']}", headers=headers(2)).status_code == 404


def test_delete_checks_project_customer_owner_and_write_permissions(db):
    client = TestClient(app)
    c = customer(client)
    task = plan(client, c['id'])
    assert client.delete(f"/api/followups/projects/2/{task['id']}", headers=headers(1)).status_code == 404
    other_customer = customer(client, owner=1)
    other_task = plan(client, other_customer['id'], user=1)
    assert client.delete(f"{BASE}/{other_task['id']}", headers=headers(2)).status_code == 404
    own_customer_other_plan = plan(client, c['id'], user=1)
    assert client.delete(f"{BASE}/{own_customer_other_plan['id']}", headers=headers(2)).status_code == 403
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.role = 'viewer'
    db.commit()
    assert client.delete(f"{BASE}/{task['id']}", headers=headers(2)).status_code == 403
    assert db.get(FollowUpPlan, task['id']) is not None
    assert client.delete(f"{BASE}/{task['id']}", headers=headers(1)).status_code == 200


def test_day_only_schedule_and_today_is_not_overdue(db):
    from app.routers.follow_up import CHINA
    from datetime import time
    client=TestClient(app);c=customer(client)
    today=datetime.now(CHINA).date()
    task=client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json={'title':'按日跟进','due_date':today.isoformat()}).json()
    assert task['due_date']==today.isoformat() and not task['is_overdue']
    assert task['due_at']==datetime.combine(today,time.min,tzinfo=CHINA).astimezone(timezone.utc).replace(tzinfo=None).isoformat()+'Z'
    assert client.get(BASE+'?bucket=overdue',headers=headers(2)).json()['total']==0
    tomorrow=today+timedelta(days=1)
    changed=client.put(BASE+f"/{task['id']}",headers=headers(2),json={'title':'改到明天','due_date':tomorrow.isoformat()}).json()
    assert changed['due_date']==tomorrow.isoformat()
    assert client.get(BASE+'?bucket=future',headers=headers(2)).json()['total']==1
    assert client.post(f"{BASE}/customers/{c['id']}",headers=headers(2),json={'title':'错误日期','due_date':'2026-02-30'}).status_code==422
    # A historical time earlier today remains today's task, not overdue.
    plan=db.get(FollowUpPlan,task['id']);plan.due_at=datetime.combine(today,time.min,tzinfo=CHINA).astimezone(timezone.utc).replace(tzinfo=None);db.commit()
    result=client.get(BASE+'?bucket=today',headers=headers(2)).json()
    assert result['total']==1 and not result['items'][0]['is_overdue']
