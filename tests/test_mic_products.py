"""A physical MIC product owns many titles and exactly one replaceable image."""
from io import BytesIO
import json
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.models import MicProduct, MicProductImage, CommunicationScript, CommunicationScriptCategory, ProjectMember, Plan
from app.services.mic_catalogue import parse_catalogue, grouped_catalogue
from app.services.mic_group_schema import migrate_individual_products
from app.services.global_project_data import delete_all_project_data
from tests.test_global_access import db, headers

BASE = "/api/mic-products/projects/1"


def data(code="vex1-vex10"):
    return {"product_code":code,"product_name":"工业翅片换热器","product_group":"翅片换热器","titles":[{"code":"vex1","title":f"Custom Heat Exchanger for {code}"},{"code":"vex2","title":f"Industrial Heat Exchanger for {code}"}]}


def create(client, code="vex1-vex10"):
    response=client.post(BASE,headers=headers(1),json=data(code))
    assert response.status_code==201,response.text
    return response.json()


def picture(color="green"):
    data=BytesIO();Image.new("RGB",(800,600),color).save(data,"PNG");return data.getvalue()


def seed_source(db):
    db.add_all([CommunicationScriptCategory(id=1,site_project_id=1,name="平台"),CommunicationScriptCategory(id=2,site_project_id=1,name="MIC",parent_id=1)])
    db.flush()
    db.add(CommunicationScript(id=1,site_project_id=1,category_id=2,title="本地产品目录",content="## 【vex31-vex40】蒸发器\n\n【vex31】Original Heat Exchanger【待优化】\n建议标题：Suggested Title\n\n【vex32】Steam Air Heater\n"))
    db.commit()


def test_product_metadata_and_removed_import_routes(db):
    seed_source(db);client=TestClient(app)
    source=db.get(CommunicationScript,1)
    db.add(MicProduct(site_project_id=1,source_script_id=source.id,**grouped_catalogue(source.content)[0]));db.commit()
    assert not any(route.path.endswith(("/import-knowledge", "/knowledge-source")) for route in app.routes if hasattr(route,"path"))
    assert client.post(BASE+"/import-knowledge",headers=headers(1)).status_code not in (200,201)
    item=client.get(BASE,headers=headers(1)).json()["items"][0]
    assert item["product_code"]=="vex31-vex40" and item["product_group"]=="换热器"
    assert item["product_name"]=="蒸发器"
    assert item["status"]=="pending"
    assert item["titles"][0]["title"]=="Suggested Title"
    assert item["titles"][0]["original_title"]=="Original Heat Exchanger"
    assert item["titles"][0]["review_status"]=="corrected"
    assert item["titles"][1]=={"code":"vex32","title":"Steam Air Heater","optimization_suggestion":""}
    assert item["missing_codes"]==[f"vex{i}" for i in range(33,41)]
    assert set(item)=={"id","product_code","product_name","product_group","record_code","english_title","seo_description","description","content","classification","parameters","contact","status","titles","missing_codes","images","published_through","social","social_progress"}
    payload={**data("vex31-vex40"),"titles":[{"code":"vex31","title":"Edited title"}]}
    assert client.put(BASE+f"/{item['id']}",headers=headers(1),json=payload).status_code==200
    saved=client.get(BASE+f"/{item['id']}",headers=headers(1)).json()["titles"][0]
    assert saved["title"]=="Edited title" and saved["original_title"]=="Original Heat Exchanger" and saved["review_status"]=="edited"
    assert "建议标题：Suggested Title" in db.get(CommunicationScript,1).content


def test_migration_retains_titles_history_and_one_image(db):
    db.add_all([MicProduct(id=1,site_project_id=1,product_code="vex31",product_group="【vex31-vex40】蒸发器",title="Edited first name",original_title="Original first name",suggested_title="Suggested first name"),
        MicProduct(id=2,site_project_id=1,product_code="vex32",product_group="【vex31-vex40】蒸发器",title="Second name"),
        MicProduct(id=3,site_project_id=2,product_code="vex31",product_group="【vex31-vex40】蒸发器",title="Other project")])
    db.flush()
    db.add(MicProductImage(site_project_id=1,product_id=2,filename="old.webp",content=b"saved image",thumbnail=b"thumbnail",width=10,height=10,is_cover=True))
    db.commit()
    migrate_individual_products(db);db.commit()
    products=list(db.scalars(select(MicProduct).where(MicProduct.site_project_id==1,MicProduct.is_archived.is_(False))))
    assert len(products)==1
    assert json.loads(products[0].titles_json)==[{"code":"vex31","title":"Edited first name"},{"code":"vex32","title":"Second name"}]
    assert products[0].product_code=="vex31-vex40"
    assert db.scalar(select(MicProductImage.product_id))==products[0].id
    assert db.get(MicProduct,1).is_archived and db.get(MicProduct,1).suggested_title=="Suggested first name"
    assert db.get(MicProduct,1).original_title=="Original first name"
    migrate_individual_products(db);db.commit()
    assert db.scalar(select(func.count()).select_from(MicProduct).where(MicProduct.is_archived.is_(False)))==2
    assert TestClient(app).get(BASE+'/1',headers=headers(1)).status_code==404


def test_single_image_replacement_is_atomic_and_private(db):
    client=TestClient(app);row=create(client);url=BASE+f"/{row['id']}"
    first=client.post(url+"/images",headers=headers(1),files={"files":("one.png",picture(),"image/png")})
    assert first.status_code==201
    image=first.json()["images"][0]
    assert Image.open(BytesIO(client.get(image["url"],headers=headers(1)).content)).size==(800,600)
    assert max(Image.open(BytesIO(client.get(image["thumbnail_url"],headers=headers(1)).content)).size)<=240
    assert client.get(image["url"]).status_code==401
    assert client.get(image["url"],headers=headers(2)).status_code==403
    assert client.get(image["url"].replace('/projects/1/','/projects/2/'),headers=headers(1)).status_code==404
    assert client.post(url+"/images",headers=headers(1),files={"files":("bad.png",b"fake","image/png")}).status_code==400
    assert client.get(image["url"],headers=headers(1)).status_code==200
    assert client.post(url+"/images",headers=headers(1),files=[("files",("one.png",picture(),"image/png")),("files",("two.png",picture(),"image/png"))]).status_code==400
    assert client.post(url+"/images",headers=headers(1),files={"files":("huge.png",b"x"*(8*1024*1024+1),"image/png")}).status_code==400
    second=client.post(url+"/images",headers=headers(1),files={"files":("replacement.png",picture("red"),"image/png")}).json()["images"]
    assert len(second)==1 and second[0]["filename"]=="replacement.png"
    assert db.scalar(select(func.count()).select_from(MicProductImage))==1
    assert client.delete(second[0]["url"],headers=headers(1)).json()=={"images":[]}


def test_multiple_names_filtering_pagination_and_validation(db):
    client=TestClient(app)
    for i in range(1,15):create(client,f"vex{i}-vex{i+1}")
    first=client.get(BASE,headers=headers(1)).json()
    assert first["total"]==14 and first["title_count"]==28 and first["pages"]==2 and len(first["items"])==10
    assert first["items"][0]["product_code"]=="vex1-vex2" and first["items"][9]["product_code"]=="vex10-vex11"
    assert len(client.get(BASE+"?page=2",headers=headers(1)).json()["items"])==4
    custom=client.get(BASE+"?page_size=5&page=2",headers=headers(1)).json()
    assert custom["page_size"]==5 and custom["pages"]==3 and len(custom["items"])==5
    assert custom["items"][0]["product_code"]=="vex6-vex7"
    assert custom["dashboard"]==first["dashboard"]
    last=client.get(BASE+"?page_size=5&page=99",headers=headers(1)).json()
    assert last["page"]==3 and len(last["items"])==4
    assert len(client.get(BASE+"?page_size=100",headers=headers(1)).json()["items"])==14
    for invalid_size in ("0", "101", "-2", "1.5", "abc"):
        assert client.get(BASE+"?page_size="+invalid_size,headers=headers(1)).status_code==422
    assert client.get(BASE+"?q=工业翅片",headers=headers(1)).json()["total"]==14
    assert client.get(BASE+"?q=Industrial",headers=headers(1)).json()["total"]==14
    assert client.get(BASE+"?q=%25",headers=headers(1)).json()["total"]==0
    assert client.get(BASE+"?group=not-a-category",headers=headers(1)).json()["total"]==0
    assert client.get('/api/mic-products/projects/2',headers=headers(1)).json()["total"]==0
    assert client.post(BASE,headers=headers(1),json=data('VEX1 - VEX2')).status_code==409
    invalid=data('vex99-vex100');invalid['titles']=[]
    assert client.post(BASE,headers=headers(1),json=invalid).status_code==201
    invalid["product_code"]="vex101-vex110"
    invalid['titles']=[{"title":"   "}]
    assert client.post(BASE,headers=headers(1),json=invalid).status_code==422


def test_permissions_and_project_cleanup(db):
    client=TestClient(app);item=create(client)
    assert client.get(BASE).status_code==401
    assert client.get(BASE,headers=headers(2)).status_code==403
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["mic_products"]';member.role='viewer';db.commit()
    assert client.get(BASE,headers=headers(2)).status_code==200
    assert client.put(BASE+f"/{item['id']}",headers=headers(2),json=data()).status_code==403
    assert client.post(BASE+f"/{item['id']}/images",headers=headers(2),files={"files":("one.png",picture(),"image/png")}).status_code==403
    client.post(BASE+f"/{item['id']}/images",headers=headers(1),files={"files":("one.png",picture(),"image/png")})
    delete_all_project_data(db,1);db.commit()
    assert db.scalar(select(func.count()).select_from(MicProduct))==0 and db.scalar(select(func.count()).select_from(MicProductImage))==0


def test_duplicate_catalogue_codes_rejected():
    import pytest
    with pytest.raises(ValueError):parse_catalogue("【vex1】First\n【VEX1】Second")


def test_removed_manual_label_is_absent_from_api(db):
    client=TestClient(app)
    item=create(client)
    assert set(item)=={"id","product_code","product_name","product_group","record_code","english_title","seo_description","description","content","classification","parameters","contact","status","titles","missing_codes","images","published_through","social","social_progress"}
    result=client.get(BASE,headers=headers(1)).json()
    assert set(result)=={"dashboard","source_notice","items","total","page","pages","page_size","groups","title_count"}


def test_create_accepts_an_unassigned_mic_range_and_empty_details(db):
    client=TestClient(app)
    minimum={"product_code":"vex501-vex510","product_name":"Basic product"}
    for field in minimum:
        missing={key:value for key,value in minimum.items() if key!=field}
        assert client.post(BASE,headers=headers(1),json=missing).status_code==422
    assert client.post(BASE,headers=headers(1),json={**minimum,"product_name":"   "}).status_code==422
    for name in ("Unassigned one", "Unassigned two"):
        draft = client.post(BASE, headers=headers(1), json={"product_code":"", "product_name":name})
        assert draft.status_code == 201
        assert draft.json()["product_code"] == ""
    created=client.post(BASE,headers=headers(1),json=minimum)
    assert created.status_code==201,created.text
    item=created.json()
    assert item['record_code']=='' and item['product_group']=='' and item['titles']==[] and item['images']==[]
    assert item['status']=='pending' and item['published_through']==''
    assert all(product['titles']==[] for product in client.get(BASE,headers=headers(1)).json()['items'])
    updated=client.put(BASE+f"/{item['id']}",headers=headers(1),json={**minimum,"record_code":"HX001","english_title":"Heat Exchanger","description":"For cold rooms.","parameters":"Copper tubes","contact":"sales@example.com","classification":"Evaporator","product_group":"Heat exchanger","titles":[{"code":"vex501","title":"Custom Heat Exchanger"}]}).json()
    assert len(updated['titles'])==1 and updated['product_group']=='Heat exchanger'
    assert updated['record_code']=='HX001' and updated['english_title']=='Heat Exchanger' and updated['description']=='For cold rooms.'
    assert client.get(BASE,headers=headers(1),params={'q':'cold rooms'}).json()['total']==1
    cleared=client.put(BASE+f"/{item['id']}",headers=headers(1),json={**minimum,"titles":[]}).json()
    assert cleared['titles']==[] and cleared['product_group']==updated['product_group']
    assert cleared['english_title']==updated['english_title'] and cleared['description']==updated['description']
    assert cleared['parameters']=='Copper tubes' and cleared['contact']=='sales@example.com'
    assert cleared['content']=='For cold rooms.\n\n产品参数\nCopper tubes\n\n联系方式\nsales@example.com'
    unified=client.put(BASE+f"/{item['id']}",headers=headers(1),json={**minimum,"content":"Combined product brief"}).json()
    assert unified['content']=='Combined product brief' and unified['parameters']=='Copper tubes'
    assert client.get(BASE,headers=headers(1),params={'q':'Combined product brief'}).json()['total']==1

    assert client.get(BASE,headers=headers(1),params={'classification':'Evaporator'}).json()['total']==1
    assert client.get(BASE,headers=headers(1),params={'classification':'Condenser'}).json()['total']==0


def test_quick_progress_is_validated_and_preserves_product_and_social(db):
    client=TestClient(app);product=create(client)
    url=BASE+f"/{product['id']}";progress=url+'/progress'
    client.put(url+'/social',headers=headers(1),json={'linkedin':{'content':'Keep this draft','published':True}})
    original=client.get(url,headers=headers(1)).json()
    result=client.put(progress,headers=headers(1),json={'published_through':' VEX6 '})
    assert result.status_code==200 and result.json()['published_through']=='vex6' and result.json()['status']=='publishing'
    saved=client.get(url,headers=headers(1)).json()
    for key in ('product_name','product_code','product_group','titles','social','images'):
        assert saved[key]==original[key]
    for value in ('11','0','other6','x','vex6-vex7'):
        assert client.put(progress,headers=headers(1),json={'published_through':value}).status_code==422
    assert client.get(url,headers=headers(1)).json()['published_through']=='vex6'
    assert client.put(progress,headers=headers(1),json={'published_through':'10','product_name':'overwrite'}).status_code==422
    assert client.put(progress,headers=headers(2),json={'published_through':'10'}).status_code==403
    assert client.put(progress.replace('/projects/1/','/projects/2/'),headers=headers(1),json={'published_through':'10'}).status_code==404
    assert client.put(progress,json={'published_through':'10'}).status_code==401
    assert client.put(progress,headers=headers(1),json={'published_through':'10'}).json()['status']=='published'
    changed={**data(),'published_through':'10'};changed['titles'][0]['optimization_suggestion']='Needs review'
    client.put(url,headers=headers(1),json=changed)
    assert client.put(progress,headers=headers(1),json={'published_through':'10'}).json()['status']=='optimizing'
    assert client.put(progress,headers=headers(1),json={'published_through':''}).json()['status']=='pending'


def test_social_filters_counts_and_pagination(db):
    client=TestClient(app)
    first=create(client);second=create(client,'vex11-vex20');third=create(client,'vex21-vex30')
    def publish(product, platform, published=True):
        url=BASE+f"/{product['id']}"
        assert client.put(url+'/product-social',headers=headers(1),json={'platforms':{platform:{'content':'Existing introduction','published':published}}}).status_code==200
    publish(first,'linkedin');publish(second,'facebook')
    result=client.get(BASE+'?social_platform=linkedin&social_status=unpublished&page_size=1&page=2',headers=headers(1)).json()
    assert result['total']==2 and result['pages']==2 and result['items'][0]['id']==third['id']
    counts={entry['platform']:entry for entry in result['dashboard']['social']}
    assert counts['linkedin']['published']==1 and counts['linkedin']['unpublished']==2
    assert counts['facebook']['published']==1 and counts['instagram']['unpublished']==3
    found=client.get(BASE+'?social_platform=linkedin&social_status=published&status=pending&q=vex1',headers=headers(1)).json()
    assert found['total']==1 and found['items'][0]['id']==first['id']
    assert client.get(BASE+'?social_platform=facebook&social_status=published&q=vex21',headers=headers(1)).json()['total']==0
    publish(first,'linkedin',False)
    assert client.get(BASE+'?social_platform=linkedin&social_status=published',headers=headers(1)).json()['total']==0
    assert client.get('/api/mic-products/projects/2?social_platform=linkedin&social_status=unpublished',headers=headers(1)).json()['total']==0
    for query in ('social_platform=bad&social_status=published','social_platform=linkedin','social_status=published','social_platform=linkedin&social_status=bad'):
        assert client.get(BASE+'?'+query,headers=headers(1)).status_code==400


def test_social_copy_and_publication_states_are_independent_and_private(db):
    client=TestClient(app);product=create(client);url=BASE+f"/{product['id']}";social_url=url+'/social'
    assert set(product['social'])=={'linkedin','facebook','instagram','youtube'}
    assert all(item=={'content':'','published':False} for item in product['social'].values())
    content='Product copy\n#HeatExchanger 中文'
    response=client.put(social_url,headers=headers(1),json={'linkedin':{'content':content,'published':True},'youtube':{'content':'Video description'}})
    assert response.status_code==200,response.text
    entries=response.json()['social'];assert entries['linkedin']=={'content':content,'published':True}
    assert entries['youtube']=={'content':'Video description','published':False}
    assert entries['facebook']=={'content':'','published':False}
    assert client.get(url,headers=headers(1)).json()['social']==entries
    assert client.get(BASE,headers=headers(1)).json()['items'][0]['social']==entries
    # Editing product details must not reset social data.
    saved=client.put(url,headers=headers(1),json=data()).json()
    assert saved['social']==entries and saved['status']=='pending'
    partial=client.put(social_url,headers=headers(1),json={'linkedin':{'published':False}}).json()['social']
    assert partial['linkedin']=={'content':content,'published':False} and partial['youtube']==entries['youtube']
    assert client.put(social_url,headers=headers(1),json={'facebook':{'published':True}}).json()['social']['facebook']['published']
    assert client.put(social_url,headers=headers(1),json={'instagram':{'content':'x'*20001}}).status_code==422
    assert client.put(social_url,headers=headers(1),json={'unknown':{}}).status_code==422
    assert client.put(social_url,headers=headers(1),json={'linkedin':{'bad':'value'}}).status_code==422
    assert client.put(social_url,json={}).status_code==401
    assert client.put(social_url,headers=headers(2),json={}).status_code==403
    assert client.put(social_url.replace('/projects/1/','/projects/2/'),headers=headers(1),json={}).status_code==404
    # Unicode text across all four platforms can exceed the MySQL TEXT limit.
    large={key:{'content':'文'*20000} for key in ('linkedin','facebook','instagram','youtube')}
    assert client.put(social_url,headers=headers(1),json=large).status_code==200


def test_titles_are_unique_within_product_and_project(db):
    client=TestClient(app);first=create(client)
    body=data("vex21-vex30");body['titles']=[{'code':'vex21','title':first['titles'][0]['title'].upper().replace(' ','-')}]
    result=client.post(BASE,headers=headers(1),json=body)
    assert result.status_code==409 and 'vex1-vex10' in result.json()['detail']
    body['titles']=[{'code':'vex21','title':'Distinct New Coil'},{'code':'vex22','title':'distinct-new  coil'}]
    assert client.post(BASE,headers=headers(1),json=body).status_code==409
    assert client.put(BASE+f"/{first['id']}",headers=headers(1),json=data()).status_code==200
    second=create(client,'vex21-vex30')
    update=data('vex21-vex30');update['titles']=first['titles']
    assert client.put(BASE+f"/{second['id']}",headers=headers(1),json=update).status_code==409
    assert client.get(BASE+f"/{second['id']}",headers=headers(1)).json()['titles']==second['titles']
    # Other projects and archived migration history must not block a title.
    body=data('vex31-vex40');body['titles']=first['titles']
    assert client.post('/api/mic-products/projects/2',headers=headers(1),json=body).status_code==201
    row=db.get(MicProduct,first['id']);row.is_archived=True;db.commit()
    assert client.post(BASE,headers=headers(1),json=body).status_code==201


def test_title_core_keywords_roundtrip_validation_and_legacy_edits(db):
    client = TestClient(app)
    keywords = ['Heat Exchanger', 'Finned Tube Heat Exchanger', 'Copper Tube Coil',
                'Aluminum Fin Coil', 'Condenser Coil', 'Evaporator Coil',
                'Cooling Coil', 'HVAC Coil', 'Replacement Coil', 'Custom Heat Exchanger']
    payload = data()
    payload['titles'][0]['core_keywords'] = keywords
    response = client.post(BASE, headers=headers(1), json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    endpoint = BASE + f"/{item['id']}"
    assert item['titles'][0]['core_keywords'] == keywords
    assert not item['titles'][1].get('core_keywords')
    # Older clients updating unrelated data must retain saved per-title keywords.
    legacy = data()
    legacy['product_name'] = 'Updated product'
    response = client.put(endpoint, headers=headers(1), json=legacy)
    assert response.status_code == 200, response.text
    assert response.json()['titles'][0]['core_keywords'] == keywords
    for bad in [keywords[:9], keywords + ['Heating Coil'],
                [*keywords[:9], 'heat exchanger'],
                [*keywords[:9], 'Copper-Tube-Aluminum-Fin-Heat-Exchanger'],
                [*keywords[:9], '换热器'], [*keywords[:9], '']]:
        invalid = data()
        invalid['titles'][0]['core_keywords'] = bad
        assert client.put(endpoint, headers=headers(1), json=invalid).status_code == 422
        assert client.get(endpoint, headers=headers(1)).json()['titles'][0]['core_keywords'] == keywords
    reordered = data()
    reordered['titles'][0]['core_keywords'] = list(reversed(keywords))
    assert client.put(endpoint, headers=headers(1), json=reordered).json()['titles'][0]['core_keywords'] == list(reversed(keywords))
    cleared = data()
    cleared['titles'][0]['core_keywords'] = []
    assert client.put(endpoint, headers=headers(1), json=cleared).json()['titles'][0]['core_keywords'] == []


def test_product_sort_is_numeric_and_applied_before_pagination(db):
    client = TestClient(app)
    for code in ['vex100', 'vex2', 'vex10']:
        create(client, code)
    ascending = client.get(BASE + '?sort_order=asc&page_size=2', headers=headers(1)).json()
    descending = client.get(BASE + '?sort_order=desc&page_size=2', headers=headers(1)).json()
    assert [item['product_code'] for item in ascending['items']] == ['vex2', 'vex10']
    assert [item['product_code'] for item in descending['items']] == ['vex100', 'vex10']
    page_two = client.get(BASE + '?sort_order=desc&page_size=2&page=2', headers=headers(1)).json()
    assert [item['product_code'] for item in page_two['items']] == ['vex2']
    assert client.get(BASE + '?sort_order=invalid', headers=headers(1)).status_code == 422


def test_retired_manual_label_migration_preserves_remaining_data(db, tmp_path, monkeypatch):
    from sqlalchemy import inspect, text
    import app.services.mic_group_schema as schema
    client=TestClient(app)
    item=create(client)
    before=client.get(BASE+f"/{item['id']}",headers=headers(1)).json()
    db.execute(text("ALTER TABLE mic_products ADD COLUMN publishing_group VARCHAR(80)"))
    db.execute(text("UPDATE mic_products SET publishing_group='sam'"))
    db.commit()
    monkeypatch.setattr(schema, 'BACKUP_ROOT', tmp_path)
    schema.ensure_mic_group_columns(db.get_bind())
    assert 'publishing_group' not in {col['name'] for col in inspect(db.get_bind()).get_columns('mic_products')}
    backup=json.loads(next(tmp_path.glob('*/removed-field.json')).read_text(encoding='utf-8'))
    assert backup[0]['publishing_group']=='sam'
    schema.ensure_mic_group_columns(db.get_bind())
    assert len(list(tmp_path.glob('*/removed-field.json')))==1
    assert client.get(BASE+f"/{item['id']}",headers=headers(1)).json()==before

def test_default_page_size_and_removed_export(db):
    client=TestClient(app)
    assert client.get(BASE,headers=headers(1)).json()['page_size']==10
    assert client.get(BASE,headers=headers(1),params={'page_size':3}).json()['page_size']==3
    assert client.get(BASE+'/export/md',headers=headers(1)).status_code==404
