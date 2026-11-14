import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead
from app.services.country_names import chinese_country
from tests.test_global_access import db, headers


@pytest.mark.parametrize('original,expected',[
    ('Germany','德国'),('DEU','德国'),('China','中国'),('USA','美国'),
    ('Bosnia and Herzegovina','波斯尼亚和黑塞哥维那'),
    ('Czech Republic','捷克'),('Czechia','捷克'),('捷克共和国','捷克'),
    ('Iran, Islamic Republic of','伊朗'),('Türkiye','土耳其'),
    ('United Arab Emirates','阿联酋'),('阿拉伯联合酋长国','阿联酋'),
    ('中國','中国'),('Taiwan','中国台湾'),('Hong Kong','中国香港'),
    ('  United Kingdom  ','英国'),('',None),(None,None),('欧洲多国','欧洲多国'),
])
def test_country_labels(original,expected):
    assert chinese_country(original)==expected


def test_lead_country_save_and_catalog_without_changing_review_flag(db):
    client=TestClient(app)
    endpoint='/api/customer-workflow/projects/1/leads'
    created=client.post(endpoint,headers=headers(2),json={'company_name':'国家录入测试','country':'Germany'})
    assert created.status_code==201,created.text
    item=created.json();assert item['country']=='德国' and not item['is_manually_researched']
    assert db.get(Lead,item['id']).country=='德国'
    response=client.put(endpoint+f"/{item['id']}",headers=headers(2),json={'company_name':'国家录入测试','country':'Czech Republic'})
    assert response.status_code==200 and response.json()['country']=='捷克'
    assert not response.json()['is_manually_researched']
    listing=client.get(endpoint,headers=headers(2)).json()
    assert next(r for r in listing['country_options'] if r['code']=='CZ')['name']=='捷克'
    assert any('Germany' in r['aliases'] and r['name']=='德国' for r in listing['country_options'])
