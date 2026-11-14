import json
from sqlalchemy import create_engine, text
from fastapi.testclient import TestClient
from app.main import app
from app.services.customer_classification_schema import ensure_customer_classification_schema
from tests.test_global_access import db, headers


def test_split_migration_is_semantic_backed_up_and_idempotent(tmp_path):
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE crm_customers (id INTEGER PRIMARY KEY,grade VARCHAR(20))'))
        for i,grade in enumerate('ABCDEFG',1):c.execute(text('INSERT INTO crm_customers VALUES (:id,:grade)'),{'id':i,'grade':grade})
    ensure_customer_classification_schema(engine,tmp_path)
    with engine.begin() as c:
        rows=c.execute(text('SELECT legacy_grade,product_match,grade FROM crm_customers ORDER BY id')).all()
        assert rows==[('A',None,None),('B',None,None),('C','A',None),('D','C',None),('E','B',None),('F','D',None),('G',None,None)]
        c.execute(text("UPDATE crm_customers SET grade='B',product_match='D' WHERE id=1"))
    ensure_customer_classification_schema(engine,tmp_path)
    with engine.connect() as c:assert c.execute(text('SELECT grade,product_match FROM crm_customers WHERE id=1')).one()==('B','D')
    backups=list(tmp_path.glob('*.json'));assert len(backups)==1
    assert len(json.loads(backups[0].read_text(encoding='utf-8')))==7


def test_two_classifications_save_independently_and_reject_invalid_values(db):
    client=TestClient(app)
    created=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Example','grade':'C','product_match':'A'}).json()
    cid=created['id'];url=f'/api/contacts/projects/1/{cid}'
    response=client.patch(url+'/product-match',headers=headers(2),json={'product_match':'D'})
    assert response.status_code==200 and response.json()['grade']=='C'
    response=client.patch(url+'/grade',headers=headers(2),json={'grade':'B'})
    assert response.json()['product_match']=='D' and response.json()['grade']=='B'
    assert client.patch(url+'/product-match',headers=headers(2),json={'product_match':'E'}).status_code==422
    assert client.patch(url+'/grade',headers=headers(2),json={'grade':'F'}).status_code==422
    assert client.patch(url+'/product-match',json={'product_match':'A'}).status_code==401
    assert client.patch(url.replace('/1/','/2/')+'/product-match',headers=headers(2),json={'product_match':'A'}).status_code==403
    # A partial company edit must retain the independently chosen product match.
    result=client.put(url,headers=headers(2),json={'company_name':'Renamed'})
    assert result.json()['product_match']=='D' and result.json()['grade']=='B'
