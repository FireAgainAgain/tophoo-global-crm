import json
from fastapi.testclient import TestClient
from app.main import app
from app.models import MicProduct
from tests.test_global_access import db, headers
from tests.test_mic_products import create, data, BASE


def test_product_social_one_set_independent_of_titles_and_old_history(db):
    client=TestClient(app);first=create(client);second=create(client,'vex21-vex30')
    url=BASE+f"/{first['id']}"
    p=db.get(MicProduct,first['id']);history={'title_drafts':{'code:vex1':{'platforms':{'facebook':{'content':'Keep archived copy'}}}},'facebook':{'content':'Original legacy','published':True}}
    p.social_json=json.dumps(history);db.commit()
    initial=client.get(url+'/product-social',headers=headers(1)).json()
    assert initial['platforms']['facebook']['content']=='Original legacy'
    assert initial['platforms']['facebook']['published']
    result=client.put(url+'/product-social',headers=headers(1),json={'title':'Copper Tube Coil','parameters':'Copper; 2 rows','platforms':{'facebook':{'content':'Current product intro','translation':'当前产品介绍','published':True,'published_at':'2026-10-29'}}})
    assert result.status_code==200,result.text
    assert json.loads(p.social_json)['title_drafts']==history['title_drafts']
    assert json.loads(p.social_json)['facebook']==history['facebook']
    saved=client.get(url+'/product-social',headers=headers(1)).json()
    assert 'entries' not in saved and 'key' not in saved
    assert saved['platforms']['facebook']['translation']=='当前产品介绍'
    assert client.get(url,headers=headers(1)).json()['parameters']=='Copper; 2 rows'
    before=client.get(url+'/product-social',headers=headers(1)).json()
    updated=client.put(url,headers=headers(1),json={**data(),'parameters':'Revised parameters'})
    assert updated.status_code==200 and updated.json()['parameters']=='Revised parameters'
    assert client.get(url+'/product-social',headers=headers(1)).json()==before

    assert not client.get(BASE+f"/{second['id']}/product-social",headers=headers(1)).json()['platforms']['facebook']['content']
    # Changing/removing MIC names does not reset or create more product social sets.
    update=data();update['titles']=[]
    assert client.put(url,headers=headers(1),json=update).status_code==200
    assert client.get(url+'/product-social',headers=headers(1)).json()==saved
    result=client.get(BASE,headers=headers(1)).json()
    counts=next(e for e in result['dashboard']['social'] if e['platform']=='facebook')
    assert counts=={'platform':'facebook','published':1,'unpublished':1}
    assert next(e for e in result['items'] if e['id']==first['id'])['social_progress']['facebook']=={'total':1,'published':1,'ready':1}
    assert client.get(BASE+'?social_platform=facebook&social_status=published',headers=headers(1)).json()['total']==1
    assert client.get(BASE+'?social_platform=facebook&social_status=unpublished',headers=headers(1)).json()['total']==1
    # Older partial clients can still update a product without wiping translations or metadata.
    result=client.put(url+'/social',headers=headers(1),json={'facebook':{'published':False}})
    assert result.status_code==200
    final=client.get(url+'/product-social',headers=headers(1)).json()
    assert final['platforms']['facebook']['translation']=='当前产品介绍' and not final['platforms']['facebook']['published']
    assert final['platforms']['facebook']['published_at']==''


def test_product_social_permissions_and_removed_generation(db):
    client=TestClient(app);first=create(client);url=BASE+f"/{first['id']}"
    assert client.get(url+'/product-social',headers=headers(2)).status_code==403
    assert client.put(url+'/product-social',headers=headers(2),json={}).status_code==403
    assert client.get(url.replace('/projects/1/','/projects/2/')+'/product-social',headers=headers(1)).status_code==404
    assert client.post(url+'/product-social/generate',headers=headers(1),json={}).status_code==404
