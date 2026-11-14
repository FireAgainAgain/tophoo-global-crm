from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import app
from tests.test_global_access import db, headers
from app.services.knowledge_schema import ensure_knowledge_rich_schema


def test_email_knowledge_roundtrip_and_project_access(db):
    client=TestClient(app);base='/api/communication-scripts/projects/1'
    category=client.post(base+'/categories',headers=headers(1),json={'name':'邮件签名'}).json()
    html='<table><tr><td style="color:blue"><b>Seller</b></td></tr></table>'
    payload={'category_id':category['id'],'title':'邮件签名','content':'Seller','content_format':'email','content_html':html+'<script>bad()</script>'}
    response=client.post(base+'/scripts',headers=headers(1),json=payload)
    assert response.status_code==201,response.text
    item=response.json();assert item['content_html']==html and item['content_format']=='email'
    assert client.get(base,headers=headers(1)).json()['scripts'][0]['content_html']==html
    assert client.get(base,headers=headers(2)).status_code==403
    response=client.put(base+'/scripts/'+str(item['id']),headers=headers(1),json={**payload,'content_html':html})
    assert response.json()['content_html']==html
    response=client.put(base+'/scripts/'+str(item['id']),headers=headers(1),json={**payload,'content_format':'markdown','content':'# Seller'})
    assert response.json()['content_html']=='' and response.json()['content']=='# Seller'


def test_upgrade_preserves_markdown_and_repeats():
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE crm_communication_scripts (id INTEGER PRIMARY KEY, content TEXT NOT NULL)'))
        connection.execute(text("INSERT INTO crm_communication_scripts VALUES (1,'# Old knowledge')"))
    ensure_knowledge_rich_schema(engine);ensure_knowledge_rich_schema(engine)
    with engine.connect() as connection:
        row=connection.execute(text('SELECT * FROM crm_communication_scripts')).mappings().one()
        assert row['content']=='# Old knowledge' and row['content_html']=='' and row['content_format']=='markdown'
    engine.dispose()
