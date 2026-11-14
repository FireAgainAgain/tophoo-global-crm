"""Inline grading changes only the grade and respects project ownership."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Customer, CustomerPerson, ProjectContact, ProjectMember
from tests.test_global_access import db, headers


def snapshot(row):
    return {col.name: getattr(row,col.name) for col in row.__table__.columns}


def create(client, owner=2):
    response=client.post('/api/contacts/projects/1',headers=headers(1),json={
        'company_name':'盘管客户','grade':'C',**({'owner_user_id':owner} if owner!=1 else {}),'notes':'保留公司备注',
        'contacts':[{'contact_name':'联系人','email':'buyer@example.test','notes':'保留联系人备注','is_primary':True}],
    })
    assert response.status_code==201,response.text
    return response.json()['id']


def test_grade_only_update_clear_validation_and_data_preservation(db):
    client=TestClient(app);cid=create(client)
    customer=db.get(Customer,cid)
    relation=db.scalar(select(ProjectContact).where(ProjectContact.contact_id==cid))
    person=db.scalar(select(CustomerPerson).where(CustomerPerson.customer_id==cid))
    before=snapshot(customer);rel_before=snapshot(relation);person_before=snapshot(person)
    url=f'/api/contacts/projects/1/{cid}/grade'
    for grade in ['B','E','D',None]:
        response=client.patch(url,headers=headers(2),json={'grade':grade})
        assert response.status_code==200,response.text
        assert response.json()['grade']==(grade or '')
        db.refresh(customer);db.refresh(relation);db.refresh(person)
        assert customer.grade==grade
        assert {k:v for k,v in snapshot(customer).items() if k not in {'grade','updated_at'}}=={k:v for k,v in before.items() if k not in {'grade','updated_at'}}
        assert snapshot(relation)==rel_before
        assert snapshot(person)==person_before
    for body in [{},{'grade':'H'},{'grade':1}]:
        assert client.patch(url,headers=headers(2),json=body).status_code==422
    assert db.get(Customer,cid).grade is None


def test_customer_workflow_status_is_separate_from_grade_and_pool(db):
    client = TestClient(app)
    customer_id = create(client, owner=1)
    url = f'/api/contacts/projects/1/{customer_id}/workflow-status'
    assert client.patch(url, headers=headers(2), json={'workflow_status': 'inquiring'}).status_code == 404
    assert client.patch(url, headers=headers(1), json={'workflow_status': 'quoted'}).status_code == 422
    for retired in ('developing', 'no_reply'):
        assert client.patch(url, headers=headers(1), json={'workflow_status': retired}).status_code == 422
    for status in ('following', 'won', 'inquiring', 'quoting', 'closed'):
        response = client.patch(url, headers=headers(1), json={'workflow_status': status})
        assert response.status_code == 200
        assert response.json()['workflow_status'] == status
    assert response.json()['status'] == 'active'
    assert response.json()['grade'] == 'C'
    listing = client.get('/api/contacts/projects/1', headers=headers(1)).json()['customers']
    assert next(item for item in listing if item['id'] == customer_id)['workflow_status'] == 'closed'


def test_grade_update_rejects_other_owner_project_viewer_and_pool(db):
    client=TestClient(app);cid=create(client,owner=1)
    url=f'/api/contacts/projects/1/{cid}/grade'
    assert client.patch(url,headers=headers(2),json={'grade':'A'}).status_code==404
    assert client.patch(f'/api/contacts/projects/2/{cid}/grade',headers=headers(2),json={'grade':'A'}).status_code==403
    assert client.patch(url,json={'grade':'A'}).status_code==401
    cid2=create(client,owner=2);url2=f'/api/contacts/projects/1/{cid2}/grade'
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.role='viewer';db.commit()
    assert client.patch(url2,headers=headers(2),json={'grade':'A'}).status_code==403
    assert db.get(Customer,cid2).grade=='C'
    assert client.post(f'/api/contacts/projects/1/{cid2}/release',headers=headers(1),json={'reason':'暂停'}).status_code==200
    assert client.patch(url2,headers=headers(1),json={'grade':'A'}).status_code==404


def test_product_category_free_text_persists_and_respects_access(db):
    client=TestClient(app)
    cid=create(client,owner=2)
    url=f'/api/contacts/projects/1/{cid}/product-category'
    for value, expected in [('  翅片换热器 / 制冷配件  ','翅片换热器 / 制冷配件'), ('定制盘管','定制盘管'), ('', '')]:
        result=client.patch(url,headers=headers(2),json={'product_category':value})
        assert result.status_code==200,result.text
        assert result.json()['product_category']==expected
        assert result.json()['grade']=='C'
    assert client.patch(url,headers=headers(2),json={'product_category':'x'*161}).status_code==422
    other=create(client,owner=1)
    assert client.patch(f'/api/contacts/projects/1/{other}/product-category',headers=headers(2),
                        json={'product_category':'test'}).status_code==404
    assert client.patch(url,json={'product_category':'test'}).status_code==401
    response=client.put(f'/api/contacts/projects/1/{cid}',headers=headers(2),
                        json={'company_name':'盘管客户','product_category':'冷凝器'})
    assert response.status_code==200,response.text
    assert response.json()['product_category']=='冷凝器'
