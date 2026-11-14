import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import MicProduct, ProjectMember
from tests.test_global_access import db,headers
from tests.test_mic_products import BASE,create,data


def test_complete_one_title_adopts_suggestion_and_preserves_progress_and_other_data(db):
    client=TestClient(app);p=create(client)
    item=db.get(MicProduct,p['id']);entries=json.loads(item.titles_json)
    entries[0]['optimization_suggestion']='建议标题：Copper Tube Heat Exchanger for HVAC\n\n修改产品词。'
    entries[1]['optimization_suggestion']='建议标题：Stainless Steel Heat Exchanger for Dryers'
    item.titles_json=json.dumps(entries);item.published_through='vex10';item.notes='Keep notes';item.social_json='{"keep":"original social content"}';db.commit()
    url=BASE+f"/{item.id}/titles/complete-optimization"
    payload={'code':entries[0]['code'],'expected_title':entries[0]['title'],'expected_suggestion':entries[0]['optimization_suggestion']}
    result=client.post(url,headers=headers(1),json=payload);assert result.status_code==200,result.text
    saved=result.json();title=saved['titles'][0]
    assert title['title']=='Copper Tube Heat Exchanger for HVAC' and title['optimization_suggestion']==''
    assert title['original_title']==entries[0]['title'] and title['review_status']=='optimized'
    assert title['optimization_completed_at'] and title['optimization_previous_title']==entries[0]['title']
    assert saved['titles'][1]==entries[1] and saved['published_through']=='vex10' and saved['status']=='optimizing'
    db.expire_all();assert item.social_json=='{"keep":"original social content"}' and item.notes=='Keep notes'
    assert client.post(url,headers=headers(1),json=payload).status_code==409
    dashboard=client.get(BASE,headers=headers(1)).json()['dashboard']['titles'];assert dashboard['optimizing']==1 and dashboard['published']==2
    second=entries[1];payload={'code':second['code'],'expected_title':second['title'],'expected_suggestion':second['optimization_suggestion']}
    result=client.post(url,headers=headers(1),json=payload);assert result.status_code==200,result.text
    assert result.json()['status']=='published'
    assert client.get(BASE+'?title_state=optimizing',headers=headers(1)).json()['total']==0


def test_completion_rejects_old_suggestion_duplicates_readonly_and_wrong_project(db):
    client=TestClient(app);p=create(client);item=db.get(MicProduct,p['id'])
    entries=json.loads(item.titles_json);entries[0]['optimization_suggestion']='建议标题：'+entries[1]['title'];item.titles_json=json.dumps(entries);db.commit()
    url=BASE+f"/{item.id}/titles/complete-optimization";payload={'code':entries[0]['code'],'expected_title':entries[0]['title'],'expected_suggestion':entries[0]['optimization_suggestion']}
    assert client.post(url,headers=headers(1),json=payload).status_code==409
    assert client.post(url,headers=headers(1),json={**payload,'expected_suggestion':'stale'}).status_code==409
    assert client.post(url.replace('/projects/1/','/projects/2/'),headers=headers(1),json=payload).status_code==404
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["mic_products"]';member.write_permissions_json='[]';db.commit()
    assert client.post(url,headers=headers(2),json=payload).status_code==403
    db.expire_all();assert json.loads(item.titles_json)==entries
