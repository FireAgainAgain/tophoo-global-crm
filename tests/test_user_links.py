"""Personal links remain isolated and survive deleting projects and categories."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import User, UserLink, UserLinkMigration, ProjectLink
from tests.test_global_access import db, headers

BASE='/api/user-links'

def test_personal_links_are_available_without_any_workspace_or_project(db):
    db.add(User(id=3,email='personal@example.test',password_hash='unused',display_name='Personal'));db.commit()
    client=TestClient(app)
    assert client.get(BASE).status_code==401
    response=client.post(BASE,headers=headers(3),json={'name':'Search','url':'www.example.test'})
    assert response.status_code==201,response.text
    assert response.json()['url']=='https://www.example.test'
    assert len(client.get(BASE,headers=headers(3)).json()['items'])==1
    assert client.get(BASE,headers=headers(1)).json()['items']==[]

def test_no_user_including_admin_can_access_another_users_links_or_categories(db):
    client=TestClient(app)
    category=client.post(BASE+'/categories',headers=headers(2),json={'name':'Tools'}).json()
    link=client.post(BASE,headers=headers(2),json={'name':'Tools','url':'https://tools.test','category_id':category['id']}).json()
    db.get(User,1).is_admin=True;db.commit()
    assert client.get(BASE,headers=headers(1)).json()['items']==[]
    for method,path,payload in [('PUT',f"/{link['id']}",{'name':'Changed','url':'https://tools.test'}),('DELETE',f"/{link['id']}",None),('POST',f"/{link['id']}/move",{'direction':'up'}),('PUT',f"/categories/{category['id']}",{'name':'Changed'}),('DELETE',f"/categories/{category['id']}",None)]:
        assert client.request(method,BASE+path,headers=headers(1),json=payload).status_code==404
    assert client.post(BASE,headers=headers(1),json={'name':'Other','url':'https://other.test','category_id':category['id']}).status_code==404
    assert client.get(BASE,headers=headers(2)).json()['items'][0]['name']=='Tools'

def test_category_deletion_keeps_urls_and_reordering_and_export_work(db):
    client=TestClient(app)
    category=client.post(BASE+'/categories',headers=headers(2),json={'name':'Tools'}).json()
    assert client.post(BASE+'/categories',headers=headers(2),json={'name':'tools'}).status_code==409
    links=[client.post(BASE,headers=headers(2),json={'name':name,'url':'https://'+name+'.test','category_id':category['id']}).json() for name in ['a','b']]
    assert client.post(BASE+f"/{links[1]['id']}/move",headers=headers(2),json={'direction':'up'}).status_code==200
    assert [item['name'] for item in client.get(BASE,headers=headers(2)).json()['items']]==['b','a']
    response=client.get(BASE+'/export/pdf',headers=headers(2));assert response.status_code==200 and response.content.startswith(b'%PDF')
    assert client.delete(BASE+f"/categories/{category['id']}",headers=headers(2)).status_code==200
    listing=client.get(BASE,headers=headers(2)).json();assert len(listing['items'])==2 and all(item['category_id'] is None for item in listing['items'])
    assert not listing['categories']

def test_project_urls_never_appear_in_personal_navigation_even_for_admins(db):
    db.add_all([ProjectLink(site_project_id=1,name='One',url='https://one.test'),ProjectLink(site_project_id=2,name='Two',url='https://two.test')]);db.commit()
    db.get(User, 2).is_admin = True
    db.commit();client=TestClient(app)
    assert client.get(BASE,headers=headers(1)).json()['items']==[]
    assert client.get(BASE,headers=headers(2)).json()['items']==[]
    assert not db.scalars(select(UserLinkMigration)).all()



def test_deleting_project_does_not_delete_personal_links(db):
    client=TestClient(app)
    item=client.post(BASE,headers=headers(1),json={'name':'Personal','url':'https://personal.test'}).json()
    response=client.request('DELETE','/api/workspaces/1/projects/1',headers=headers(1),json={'confirm_name':'Demo'})
    assert response.status_code==200,response.text
    assert db.get(UserLink,item['id']) is not None

def test_invalid_links_cannot_be_saved(db):
    client=TestClient(app)
    for value in ['javascript:alert(1)','data:text/html,test','https://user:password@example.test','https://example.test:wrong','https://exa mple.test']:
        assert client.post(BASE,headers=headers(2),json={'name':'Bad','url':value}).status_code==422


def test_account_deletion_cleans_only_that_users_personal_data(db):
    client=TestClient(app)
    db.get(User,1).is_admin=True;db.commit()
    category=client.post(BASE+'/categories',headers=headers(2),json={'name':'Delete with user'}).json()
    client.post(BASE,headers=headers(2),json={'name':'User two','url':'https://two.test','category_id':category['id']})
    kept=client.post(BASE,headers=headers(1),json={'name':'User one','url':'http://localhost:8002'}).json()
    assert client.delete('/api/admin/users/2',headers=headers(1)).status_code==200
    assert db.get(UserLink,kept['id']) is not None
    assert client.get(BASE,headers=headers(1)).json()['items'][0]['name']=='User one'


def test_notes_are_retired_from_public_payload_and_legacy_data_stays_archived(db):
    client=TestClient(app)
    response=client.post(BASE,headers=headers(2),json={'name':'New','url':'https://new.test','notes':'Not a supported field'})
    assert response.status_code==201,response.text
    assert 'notes' not in response.json()
    item=db.get(UserLink,response.json()['id']);assert item.notes is None
    item.notes='Legacy archived note';db.commit()
    assert 'notes' not in client.get(BASE,headers=headers(2)).json()['items'][0]
    assert client.put(BASE+f'/{item.id}',headers=headers(2),json={'name':'Renamed','url':'https://new.test'}).status_code==200
    db.refresh(item);assert item.notes=='Legacy archived note'


def test_single_label_and_internal_hosts_are_accepted_without_domain_shape_restrictions(db):
    client=TestClient(app)
    for url in ['GSC', 'http://intranet:8002/tools', 'https://localhost:8002']:
        response=client.post(BASE,headers=headers(2),json={'name':'Internal','url':url})
        assert response.status_code==201,response.text
        assert response.json()['url']==(url if '://' in url else 'https://'+url)


def test_pdf_exports_all_personal_categories_and_uncategorized_links(db,monkeypatch):
    from app.routers import user_links
    client=TestClient(app)
    for name in ['SEO','Tools']:
        category=client.post(BASE+'/categories',headers=headers(2),json={'name':name}).json()
        client.post(BASE,headers=headers(2),json={'name':name,'url':'https://'+name.lower()+'.test','category_id':category['id']})
    client.post(BASE,headers=headers(2),json={'name':'Other','url':'https://other.test'})
    client.post(BASE,headers=headers(1),json={'name':'Private','url':'https://private.test'})
    captured=[]
    def export(profile,links,personal=False):
        assert personal
        captured.extend(link.url for link in links)
        return b'%PDF-fixture'
    monkeypatch.setattr(user_links,'export_project_links_pdf',export)
    response=client.get(BASE+'/export/pdf',headers=headers(2))
    assert response.status_code==200
    assert set(captured)=={'https://seo.test','https://tools.test','https://other.test'}
