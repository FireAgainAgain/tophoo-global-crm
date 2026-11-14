import json
from fastapi.testclient import TestClient
from app.main import app
from app.models import MicProduct, AiModelConfiguration, AiFeatureBinding, ProjectMember
from app.services import mic_social
from app.routers import ai_config
from tests.test_global_access import db, headers
from tests.test_mic_products import create, data, BASE


def entry_payload(entry, **changes):
    return {**{k: entry[k] for k in ('key', 'title', 'parameters', 'contact', 'platforms')}, **changes}


def test_title_isolation_legacy_retention_and_partial_platform_updates(db):
    client=TestClient(app); product=create(client); url=BASE+f"/{product['id']}"
    client.put(url+'/social',headers=headers(1),json={'facebook':{'content':'Legacy copy','published':True}})
    entries=client.get(url+'/social-library',headers=headers(1)).json()['entries']
    assert len(entries)==2 and entries[0]['contact']==mic_social.CONTACT
    first,second=entries
    body=entry_payload(first,parameters='Copper tube, 2 rows',platforms={'facebook':{'content':'First English','translation':'第一条中文','published':True,'published_at':'2026-10-29'}})
    assert client.put(url+'/title-social',headers=headers(1),json=body).status_code==200
    body=entry_payload(second,platforms={'facebook':{'content':'Second English'}})
    assert client.put(url+'/title-social',headers=headers(1),json=body).status_code==200
    body=entry_payload(first,platforms={'youtube':{'content':'Video description','video_title':'Copper coil','tags':'coil, heat exchanger'}})
    assert client.put(url+'/title-social',headers=headers(1),json=body).status_code==200
    saved=client.get(url+'/social-library',headers=headers(1)).json()
    assert saved['legacy']['facebook']['content']=='Legacy copy'
    a,b=saved['entries']
    assert a['platforms']['facebook']['content']=='First English'
    assert a['platforms']['facebook']['published_at']=='2026-10-29'
    assert a['platforms']['youtube']['video_title']=='Copper coil'
    assert b['platforms']['facebook']['content']=='Second English'
    assert not b['platforms']['facebook']['published']
    # Updating the old API or title text must never erase independent drafts.
    client.put(url+'/social',headers=headers(1),json={'linkedin':{'content':'Other legacy'}})
    updated=data();updated['titles'][0]['title']='Edited factual title'
    assert client.put(url,headers=headers(1),json=updated).status_code==200
    saved=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0]
    assert saved['title_changed'] and saved['platforms']['facebook']['content']=='First English'
    assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(first)).status_code==409
    assert client.get(url.replace('/projects/1/','/projects/2/')+'/social-library',headers=headers(1)).status_code==404
    assert client.get(url+'/social-library',headers=headers(2)).status_code==403
    assert client.put(url+'/title-social',headers=headers(2),json=entry_payload(saved)).status_code==403


def test_counts_filter_partial_publication_and_validation(db):
    client=TestClient(app);product=create(client);url=BASE+f"/{product['id']}"
    entry=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0]
    bad=entry_payload(entry,platforms={'facebook':{'published':True}})
    assert client.put(url+'/title-social',headers=headers(1),json=bad).status_code==422
    assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(entry,key='missing')).status_code==409
    assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(entry,platforms={'bad':{}})).status_code==422
    for date in ('2026-99-01','wrong'):
        assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(entry,platforms={'facebook':{'content':'Copy','published':True,'published_at':date}})).status_code==422
    assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(entry,platforms={'facebook':{'content':'Copy','published':True}})).status_code==200
    # Earlier title publication marks remain history and do not publish the product set.
    assert client.get(BASE+'?social_platform=facebook&social_status=published',headers=headers(1)).json()['total']==0
    result=client.get(BASE+'?social_platform=facebook&social_status=unpublished',headers=headers(1)).json()
    assert result['total']==1
    assert result['items'][0]['social_progress']['facebook']=={'total':1,'published':0,'ready':0}



def bind_model(db):
    model=AiModelConfiguration(site_project_id=1,owner_user_id=1,name='Test',model='test',base_url='https://example.test/v1',api_key='private',enabled=True,last_test_status='success',max_tokens=4096)
    db.add(model);db.flush()
    db.add(AiFeatureBinding(site_project_id=1,owner_user_id=1,feature_key='mic_social',model_configuration_id=model.id));db.commit()
    return model


def test_generation_is_source_bound_unsaved_and_uses_personal_model(db,monkeypatch):
    client=TestClient(app);product=create(client);url=BASE+f"/{product['id']}"
    entry=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0]
    source={k:entry[k] for k in ('key','title','contact')};source.update(parameters='Copper tube; 2 rows',platform='facebook',contact='sales@example.com')
    assert client.post(url+'/title-social/generate',headers=headers(1),json=source).status_code==422
    bind_model(db);calls=[]
    def fake_chat(model,messages,max_tokens):
        calls.append((model,messages,max_tokens))
        return json.dumps({'content':'Two-row copper tube coil.\n'+source['contact'],'translation':'两排铜管盘管。\n'+source['contact'],'published':True})
    monkeypatch.setattr(ai_config,'chat',fake_chat)
    before=db.get(MicProduct,product['id']).social_json
    result=client.post(url+'/title-social/generate',headers=headers(1),json=source)
    assert result.status_code==200,result.text
    assert not result.json()['draft']['published']
    assert db.get(MicProduct,product['id']).social_json==before
    assert calls[0][0].owner_user_id==1
    assert 'Do not invent' in calls[0][1][0]['content']
    assert json.loads(calls[0][1][1]['content'])['product_parameters']=='Copper tube; 2 rows'
    assert client.post(url+'/title-social/generate',headers=headers(1),json={**source,'parameters':'  '}).status_code==422
    assert client.post(url+'/title-social/generate',headers=headers(1),json={**source,'title':'Stale title'}).status_code==409
    # A second user with module permission still cannot borrow the owner's AI binding.
    member=db.query(ProjectMember).filter_by(site_project_id=1,user_id=2).one();member.permissions_json='["mic_products"]';db.commit()
    assert client.post(url+'/title-social/generate',headers=headers(2),json=source).status_code==422
    assert len(calls)==1


def test_incomplete_generation_preserves_saved_content(db,monkeypatch):
    client=TestClient(app);product=create(client);url=BASE+f"/{product['id']}"
    entry=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0];bind_model(db)
    source={k:entry[k] for k in ('key','title','contact')};source.update(parameters='Copper tube',platform='youtube')
    for output in ('not JSON','{"content":"English only"}','{"content":"Description","translation":"说明"}','[]'):
        monkeypatch.setattr(ai_config,'chat',lambda *args,**kwargs:output)
        assert client.post(url+'/title-social/generate',headers=headers(1),json=source).status_code==422
    assert db.get(MicProduct,product['id']).social_json is None


def test_unnumbered_title_keeps_social_copy_when_renamed_and_numbered(db):
    client=TestClient(app)
    payload=data();payload['titles']=[{'code':'','title':'Unnumbered copper coil'}]
    product=client.post(BASE,headers=headers(1),json=payload).json();url=BASE+f"/{product['id']}"
    title=product['titles'][0]
    assert len(title['social_id'])==32
    entry=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0]
    assert client.put(url+'/title-social',headers=headers(1),json=entry_payload(entry,platforms={'facebook':{'content':'Keep this introduction'}})).status_code==200
    payload['titles']=[{**title,'code':'vex1','title':'Renamed copper coil'}]
    assert client.put(url,headers=headers(1),json=payload).status_code==200
    saved=client.get(url+'/social-library',headers=headers(1)).json()['entries'][0]
    assert saved['title_changed'] and saved['platforms']['facebook']['content']=='Keep this introduction'
