"""A bookmark belongs to one user in one project, including categories and PDF."""
from fastapi.testclient import TestClient
from sqlalchemy import select, text, create_engine
from app.main import app
from app.models import UserLink, UserLinkCategory, ProjectMember
from app.services.user_link_schema import ensure_user_link_project_schema
from tests.test_global_access import db, headers


def test_user_project_isolation_for_all_bookmark_operations(db):
    client=TestClient(app)
    category=lambda project:client.post('/api/user-links/categories',params={'project_id':project},headers=headers(1),json={'name':'Tools'})
    one,two=category(1),category(2)
    assert one.status_code==two.status_code==201
    def link(project,name,cat):
        return client.post('/api/user-links',params={'project_id':project},headers=headers(1),json={'name':name,'url':'https://'+name+'.test','category_id':cat})
    a=link(1,'one',one.json()['id']);b=link(2,'two',two.json()['id'])
    assert a.status_code==b.status_code==201
    assert link(2,'foreign',one.json()['id']).status_code==404
    for project,expected in [(1,'one'),(2,'two')]:
        data=client.get('/api/user-links',params={'project_id':project},headers=headers(1)).json()
        assert [x['name'] for x in data['items']]==[expected]
        assert len(data['categories'])==1
    assert client.get('/api/user-links',params={'project_id':1},headers=headers(2)).json()['items']==[]
    assert client.get('/api/user-links',params={'project_id':2},headers=headers(2)).status_code==403
    for method,path,payload in [('PUT',f"/{a.json()['id']}",{'name':'changed','url':'https://changed.test'}),('DELETE',f"/{a.json()['id']}",None),('POST',f"/{a.json()['id']}/move",{'direction':'up'}),('PUT',f"/categories/{one.json()['id']}",{'name':'changed'}),('DELETE',f"/categories/{one.json()['id']}",None)]:
        assert client.request(method,'/api/user-links'+path,params={'project_id':2},headers=headers(1),json=payload).status_code==404
    export=client.get('/api/user-links/export/pdf',params={'project_id':1},headers=headers(1))
    from pypdf import PdfReader
    from io import BytesIO
    content=''.join(p.extract_text() for p in PdfReader(BytesIO(export.content)).pages)
    assert 'one.test' in content and 'two.test' not in content
    assert client.delete('/api/user-links/categories/'+str(one.json()['id']),params={'project_id':1},headers=headers(1)).status_code==200
    assert db.get(UserLink,a.json()['id']).category_id is None
    assert db.get(UserLink,b.json()['id']).category_id==two.json()['id']
    assert client.get('/api/user-links',headers={**headers(1),'X-Project-ID':'1'},params={'project_id':2}).status_code==409


def test_project_readonly_applies_to_personal_bookmarks(db):
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2))
    member.permissions_json='["url_navigation"]';member.write_permissions_json='[]';db.commit()
    client=TestClient(app)
    assert client.get('/api/user-links?project_id=1',headers=headers(2)).status_code==200
    assert client.post('/api/user-links?project_id=1',headers=headers(2),json={'name':'blocked','url':'https://blocked.test'}).status_code==403
    assert client.get('/api/user-links?project_id=999',headers=headers(1)).status_code==404


def test_schema_migration_preserves_legacy_records_and_allows_same_category_per_project():
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        c.execute(text('CREATE TABLE site_projects (id INTEGER PRIMARY KEY)'))
        c.execute(text('CREATE TABLE user_link_categories (id INTEGER PRIMARY KEY, owner_user_id INTEGER, name VARCHAR(80), sort_order INTEGER, CONSTRAINT uq_user_link_category UNIQUE(owner_user_id,name))'))
        c.execute(text('CREATE TABLE user_links (id INTEGER PRIMARY KEY, owner_user_id INTEGER, category_id INTEGER, name TEXT, url TEXT)'))
        c.execute(text("INSERT INTO user_link_categories VALUES (1,4,'Tools',1)"))
        c.execute(text("INSERT INTO user_links VALUES (1,4,1,'Search','https://search.test')"))
    ensure_user_link_project_schema(engine);ensure_user_link_project_schema(engine)
    with engine.begin() as c:
        assert c.execute(text('SELECT owner_user_id,category_id,name,url,site_project_id FROM user_links')).one()==(4,1,'Search','https://search.test',None)
        c.execute(text("INSERT INTO user_link_categories VALUES (2,4,7,'Tools',1),(3,4,8,'Tools',1)"))
    engine.dispose()


def test_market_research_is_retired_everywhere(db):
    from app.core.modules import MODULE_CATALOG,normalize_module_keys
    assert 'market_research' not in MODULE_CATALOG
    assert normalize_module_keys(['market_research'])==[]
    client=TestClient(app)
    for method,path in [('GET',''),('PUT',''),('POST','/export/pdf')]:
        assert client.request(method,'/api/market-research/projects/1'+path,headers=headers(1),json={} if method!='GET' else None).status_code==404
    html=client.get('/').text
    assert 'data-crm-section="market-research"' not in html
    assert '/static/js/market-research.js' not in html
