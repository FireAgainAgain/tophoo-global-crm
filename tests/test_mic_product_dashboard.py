"""Publication progress is validated, persisted and used for all status views."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import MicProduct, ProjectMember
from app.services.mic_product_labels import sync_publication_statuses
from tests.test_global_access import db, headers
from tests.test_mic_products import data, BASE


def add(client, code, category, through=""):
    response=client.post(BASE,headers=headers(1),json={**data(code),"product_group":category,"published_through":through})
    assert response.status_code==201,response.text
    return response.json()


def test_distribution_uses_project_products_and_derived_status(db):
    client=TestClient(app)
    add(client,"vex1-vex10","冷库","6")
    add(client,"vex11-vex20","冷库","20")
    add(client,"vex21-vex30","干燥机")
    result=client.get(BASE+'?group=冷库&status=publishing&q=vex1',headers=headers(1)).json()
    assert result["total"]==1 and result["items"][0]["published_through"]=="vex6"
    assert result["dashboard"]["total"]==3
    assert result["dashboard"]["categories"]==[{"name":"冷库","count":2,"percentage":66.7},{"name":"干燥机","count":1,"percentage":33.3}]
    assert {item["status"]:item["count"] for item in result["dashboard"]["labels"]}=={"published":1,"pending":1,"publishing":1,"optimizing":0}
    assert client.get('/api/mic-products/projects/2',headers=headers(1)).json()["dashboard"]["total"]==0
    assert client.get(BASE+'?group=干燥机&status=publishing',headers=headers(1)).json()["total"]==0
    for removed in ('invalid','ready','paused'):
        assert client.get(BASE+'?status='+removed,headers=headers(1)).status_code==400


def test_title_counts_use_existing_titles_and_include_optimizing_products(db):
    client=TestClient(app)
    first={**data('vex31-vex40'),'published_through':'32','titles':[{'code':f'vex{n}','title':f'Copper Fin Heat Exchanger {n}'} for n in (31,32,35)]}
    second={**data('vex41-vex50'),'published_through':'50','titles':[{'code':f'vex{n}','title':f'Heating Coil {n}','optimization_suggestion':'Review title'} for n in (41,42)]}
    third={**data('vex51-vex60'),'titles':[{'code':f'vex{n}','title':f'Cooling Coil {n}'} for n in (51,52)]}
    for payload in (first,second,third):
        assert client.post(BASE,headers=headers(1),json=payload).status_code==201
    result=client.get(BASE,headers=headers(1)).json()
    assert result['dashboard']['titles']=={'total':7,'published':4,'unpublished':3,'optimizing':2}
    assert result['dashboard']['total']==3
    published=client.get(BASE+'?title_state=published',headers=headers(1)).json()
    assert published['total']==2 and published['dashboard']['titles']==result['dashboard']['titles']
    pending=client.get(BASE+'?title_state=unpublished&page_size=1&page=2',headers=headers(1)).json()
    assert pending['total']==2 and pending['pages']==2
    assert pending['items'][0]['product_code']=='vex51-vex60'
    assert client.get(BASE+'?title_state=invalid',headers=headers(1)).status_code==400
    optimizing=client.get(BASE+'?title_state=optimizing',headers=headers(1)).json()
    assert optimizing['total']==1 and optimizing['title_count']==2
    assert optimizing['items'][0]['product_code']=='vex41-vex50'
    assert optimizing['dashboard']['titles']==result['dashboard']['titles']
    assert client.get('/api/mic-products/projects/2',headers=headers(1)).json()['dashboard']['titles']=={'total':0,'published':0,'unpublished':0,'optimizing':0}


def test_unassigned_products_are_excluded_only_from_mic_assistant(db):
    client = TestClient(app)
    add(client, "31-40", "换热器")
    unassigned = client.post(BASE, headers=headers(1), json={
        "product_code": "", "product_name": "Awaiting MIC range",
        "titles": [{"title": "Draft Coil Title", "optimization_suggestion": "Review title"}],
    })
    assert unassigned.status_code == 201
    regular = client.get(BASE, headers=headers(1)).json()
    assert regular["total"] == 2
    assert regular["dashboard"]["mic_total"] == 1
    assert regular["dashboard"]["titles"]["total"] == 2
    assert regular["dashboard"]["titles"]["optimizing"] == 0
    for params in ({"mic_only": True}, {"status": "pending"}, {"title_state": "unpublished"}):
        result = client.get(BASE, headers=headers(1), params=params).json()
        assert [product["product_code"] for product in result["items"]] == ["31-40"]


def test_progress_controls_status_and_suggestions_are_independent(db):
    client=TestClient(app);product=add(client,"vex1-vex10","换热器")
    url=BASE+f"/{product['id']}"
    assert product["status"]=="pending" and product["published_through"]==""
    payload={**data(),"published_through":" VEX6 ","status":"published"}
    payload["titles"][1]["optimization_suggestion"]="  修正中心词  "
    saved=client.put(url,headers=headers(1),json=payload).json()
    assert saved["status"]=="publishing" and saved["published_through"]=="vex6"
    assert saved["titles"][1]["optimization_suggestion"]=="修正中心词"
    # Older clients must preserve both current progress and optimization notes.
    saved=client.put(url,headers=headers(1),json=data()).json()
    assert saved["status"]=="publishing" and saved["published_through"]=="vex6"
    assert saved["titles"][1]["optimization_suggestion"]=="修正中心词"
    complete=client.put(url,headers=headers(1),json={**data(),"published_through":"10"}).json()
    assert complete["status"]=="optimizing" and complete["published_through"]=="vex10"
    assert complete["titles"][1]["optimization_suggestion"]=="修正中心词"
    cleared=client.put(url,headers=headers(1),json={**data(),"published_through":" "}).json()
    assert cleared["status"]=="pending" and cleared["published_through"]==""


def test_invalid_progress_rejected_without_modifying_product(db):
    client=TestClient(app);product=add(client,"vex1-vex10","换热器","6");url=BASE+f"/{product['id']}"
    for value in ("0","11","foo6","6.5","vex6-vex7"):
        assert client.put(url,headers=headers(1),json={**data(),"published_through":value}).status_code==422
    assert client.get(url,headers=headers(1)).json()["published_through"]=="vex6"
    assert client.put(url,headers=headers(1),json={**data('vex21-vex30')}).status_code==422
    assert client.get(url,headers=headers(1)).json()["product_code"]=="vex1-vex10"
    assert add(client,"vex100","换热器","100")["status"]=="published"


def test_sync_preserves_progress_and_title_history(db):
    client=TestClient(app);product=add(client,"vex1-vex10","换热器","10")
    record=db.get(MicProduct,product['id']);titles=json.loads(record.titles_json)
    titles[0].pop('optimization_suggestion');titles[0]['suggested_title']='Historical adopted title'
    record.titles_json=json.dumps(titles);record.status='pending';db.commit()
    sync_publication_statuses(db);db.commit();sync_publication_statuses(db);db.commit()
    assert record.status=='published' and record.published_through=='vex10'
    assert json.loads(record.titles_json)[0]['optimization_suggestion']==''
    assert json.loads(record.titles_json)[0]['suggested_title']=='Historical adopted title'


def test_filters_ignore_stale_storage_and_preserve_permissions(db):
    client=TestClient(app);product=add(client,"vex1-vex10","换热器","6")
    record=db.get(MicProduct,product['id']);record.status='published';db.commit()
    assert client.get(BASE+'?status=publishing',headers=headers(1)).json()['total']==1
    assert client.get(BASE+'?status=published',headers=headers(1)).json()['total']==0
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["mic_products"]';member.role='viewer';db.commit()
    assert client.get(BASE,headers=headers(2)).status_code==200
    assert client.put(BASE+f"/{product['id']}",headers=headers(2),json={**data(),"published_through":"10"}).status_code==403


def test_optimization_state_follows_current_suggestions_after_publication(db):
    client=TestClient(app);product=add(client,"vex1-vex10","换热器","10");url=BASE+f"/{product['id']}"
    payload={**data(),"published_through":"10"}
    payload['titles'][0]['optimization_suggestion']='Improve material wording'
    response=client.put(url,headers=headers(1),json=payload).json()
    assert response['status']=='optimizing'
    assert client.get(BASE+'?status=optimizing',headers=headers(1)).json()['total']==1
    assert client.get(BASE+'?status=published',headers=headers(1)).json()['total']==0
    record=db.get(MicProduct,product['id']);record.status='published';db.commit()
    assert client.get(BASE+'?status=optimizing',headers=headers(1)).json()['total']==1
    sync_publication_statuses(db);db.commit();assert record.status=='optimizing'
    payload['titles'][0]['optimization_suggestion']='  \n '
    assert client.put(url,headers=headers(1),json=payload).json()['status']=='published'
    payload['titles'][0]['optimization_suggestion']='Keep this note'
    payload['published_through']='6'
    assert client.put(url,headers=headers(1),json=payload).json()['status']=='publishing'
    payload['published_through']=''
    assert client.put(url,headers=headers(1),json=payload).json()['status']=='pending'
