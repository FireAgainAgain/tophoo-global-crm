"""Phrase library isolation, access control, migrations and lossless category moves."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import ProjectMember, Plan, ProjectRole
from app.models.communication_phrase import CommunicationPhrase, PhraseCategory, PhraseScene
from app.services.global_project_data import delete_all_project_data
from app.services.phrase_module_setup import enable_existing_phrase_access
from tests.test_global_access import db,headers

BASE='/api/phrases/projects/1'

def test_categories_phrases_search_payload_and_lossless_move(db):
 c=TestClient(app);h=headers(1)
 a=c.post(BASE+'/categories',headers=h,json={'name':' 需求确认 '});assert a.status_code==201;a=a.json()['id']
 b=c.post(BASE+'/categories',headers=h,json={'name':'后续跟进'}).json()['id']
 assert c.post(BASE+'/categories',headers=h,json={'name':'需求确认'}).status_code==409
 assert c.post(BASE+'/categories',headers=h,json={'name':'   '}).status_code==422
 item=c.post(BASE+'/items',headers=h,json={'category_id':a,'content':'Dear customer, please share drawings.','translation':'请提供图纸 <尺寸> & 温度。'});assert item.status_code==201;item=item.json();assert 'title' not in item and item['translation']=='请提供图纸 <尺寸> & 温度。'
 assert c.delete(BASE+f'/categories/{a}',headers=h).status_code==409
 assert c.delete(BASE+f'/categories/{a}?target_id={a}',headers=h).status_code==422
 assert c.delete(BASE+f'/categories/{a}?target_id={b}',headers=h).json()['moved']==1
 data=c.get(BASE,headers=h).json();assert data['can_edit'];assert data['items'][0]['content']==item['content'];assert data['items'][0]['category_id']==b;assert data['items'][0]['translation']==item['translation']
 assert c.put(BASE+f'/items/{item["id"]}',headers=h,json={'category_id':b,'content':'New original','translation':'新翻译'}).status_code==200
 assert c.delete(BASE+f'/items/{item["id"]}',headers=h).status_code==200
 assert c.delete(BASE+f'/categories/{b}',headers=h).status_code==200


def test_project_scope_readonly_and_full_project_cleanup(db):
 c=TestClient(app);h=headers(1)
 a=c.post(BASE+'/categories',headers=h,json={'name':'首次联系'}).json()['id']
 item=c.post(BASE+'/items',headers=h,json={'category_id':a,'content':'Original','translation':'译文'}).json()
 assert c.get(BASE).status_code==401
 assert c.get(BASE,headers=headers(2)).status_code==403
 member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["communication_phrases"]';member.write_permissions_json='[]';db.commit()
 assert c.get(BASE,headers=headers(2)).json()['can_edit'] is False
 assert c.post(BASE+'/categories',headers=headers(2),json={'name':'不可新增'}).status_code==403
 assert c.delete(BASE+f'/items/{item["id"]}',headers=headers(2)).status_code==403
 other='/api/phrases/projects/2'
 assert c.get(other,headers=headers(2)).status_code==403
 assert c.post(other+'/items',headers=h,json={'category_id':a,'content':'不可关联'}).status_code==404
 assert c.delete(other+f'/items/{item["id"]}',headers=h).status_code==404
 delete_all_project_data(db,1);db.commit()
 assert not db.scalars(select(CommunicationPhrase)).all() and not db.scalars(select(PhraseCategory)).all()


def test_order_and_one_time_access_inheritance_preserve_readonly(db):
 c=TestClient(app);h=headers(1)
 ids=[c.post(BASE+'/categories',headers=h,json={'name':name}).json()['id'] for name in ['甲','乙']]
 assert c.put(BASE+'/categories/order',headers=h,json={'ids':[ids[0],ids[0]]}).status_code==409
 assert c.put(BASE+'/categories/order',headers=h,json={'ids':ids[::-1]}).status_code==200
 assert [x['id'] for x in c.get(BASE,headers=h).json()['categories']]==ids[::-1]
 member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["knowledge_base"]';member.write_permissions_json='[]';db.get(Plan,1).module_keys_json='["knowledge_base"]';db.commit()
 enable_existing_phrase_access(db);db.commit()
 assert 'communication_phrases' in json.loads(member.permissions_json)
 assert json.loads(member.write_permissions_json)==[]
 assert 'communication_phrases' in json.loads(db.get(Plan,1).module_keys_json)
 # Later removal must remain authoritative; installation is called only on first create.
 role=ProjectRole(site_project_id=1,name='知识编辑',permissions_json='["knowledge_base"]',write_permissions_json='["knowledge_base"]');db.add(role);db.commit()
 enable_existing_phrase_access(db);db.commit();assert 'communication_phrases' in json.loads(role.write_permissions_json)


def test_original_required_and_translation_optional(db):
 c=TestClient(app);h=headers(1)
 a=c.post(BASE+'/categories',headers=h,json={'name':'首次询盘'}).json()['id']
 assert c.post(BASE+'/items',headers=h,json={'category_id':a,'content':'   ','translation':'只有翻译'}).status_code==422
 result=c.post(BASE+'/items',headers=h,json={'category_id':a,'content':'Original only'}).json()
 assert result['content']=='Original only' and result['translation']=='' and 'title' not in result


def test_legacy_pair_migration_is_lossless_and_idempotent(tmp_path,monkeypatch):
 from sqlalchemy import create_engine,text,inspect
 from app.services.phrase_content_schema import ensure_phrase_translation_schema
 monkeypatch.chdir(tmp_path)
 engine=create_engine('sqlite://')
 with engine.begin() as connection:
  connection.execute(text('CREATE TABLE crm_communication_phrases (id INTEGER PRIMARY KEY,title TEXT,content TEXT)'))
  connection.execute(text('INSERT INTO crm_communication_phrases VALUES (1,:title,:content)'),{'title':'旧标题','content':'Hello customer.\n您好，客户。'})
  connection.execute(text('INSERT INTO crm_communication_phrases VALUES (2,:title,:content)'),{'title':'保留内容','content':'Line one\nLine two\n中文说明'})
 ensure_phrase_translation_schema(engine);ensure_phrase_translation_schema(engine)
 assert 'title' not in {x['name'] for x in inspect(engine).get_columns('crm_communication_phrases')}
 with engine.connect() as connection:
  rows=connection.execute(text('SELECT content,translation FROM crm_communication_phrases ORDER BY id')).all()
 assert rows==[('Hello customer.','您好，客户。'),('Line one\nLine two\n中文说明','')]
 assert len(list((tmp_path/'backups').glob('*/before.json')))==1

def test_phrase_moves_persist_without_editing_changing_manual_order(db):
 c=TestClient(app);h=headers(1)
 a=c.post(BASE+'/categories',headers=h,json={'name':'甲'}).json()['id']
 b=c.post(BASE+'/categories',headers=h,json={'name':'乙'}).json()['id']
 ids=[]
 for index,category in enumerate([a,b,a,b]):
  ids.append(c.post(BASE+'/items',headers=h,json={'category_id':category,'content':f'Original {index}','translation':f'翻译 {index}'}).json()['id'])
 before=c.get(BASE,headers=h).json()['items'];before_ids=[x['id'] for x in before]
 top=before_ids[0]
 assert c.post(BASE+f'/items/{top}/move',headers=h,json={'direction':-1}).json()['moved'] is False
 assert c.post(BASE+f'/items/{top}/move',headers=h,json={'direction':1}).json()['moved'] is True
 after=c.get(BASE,headers=h).json()['items'];assert [x['id'] for x in after]==[before_ids[1],before_ids[0],*before_ids[2:]]
 assert 'updated_at' not in after[0] and 'created_at' not in after[0]
 current=next(x for x in after if x['id']==top)
 assert c.put(BASE+f'/items/{top}',headers=h,json={'category_id':current['category_id'],'content':'Edited original','translation':'修改翻译'}).status_code==200
 assert [x['id'] for x in c.get(BASE,headers=h).json()['items']]==[x['id'] for x in after]
 scoped=[x['id'] for x in after if x['category_id']==a]
 assert c.post(BASE+f'/items/{scoped[0]}/move',headers=h,json={'direction':1,'category_id':a}).status_code==200
 result=c.get(BASE,headers=h).json()['items'];assert [x['id'] for x in result if x['category_id']==a]==scoped[::-1]
 assert [x['id'] for x in result if x['category_id']==b]==[x['id'] for x in after if x['category_id']==b]
 assert c.post(BASE+f'/items/{scoped[0]}/move',headers=h,json={'direction':1,'category_id':b}).status_code==409
 assert c.post(BASE+f'/items/{scoped[0]}/move',headers=h,json={'direction':0}).status_code==422
 member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["communication_phrases"]';member.write_permissions_json='[]';db.commit()
 assert c.post(BASE+f'/items/{top}/move',headers=headers(2),json={'direction':1}).status_code==403
 assert c.post('/api/phrases/projects/2/items/'+str(top)+'/move',headers=h,json={'direction':1}).status_code==404


def test_scene_lifecycle_scope_sorting_and_lossless_category_merge(db):
 db.connection().exec_driver_sql('PRAGMA foreign_keys=ON')
 c=TestClient(app);h=headers(1)
 a=c.post(BASE+'/categories',headers=h,json={'name':'询价沟通'}).json()['id']
 b=c.post(BASE+'/categories',headers=h,json={'name':'报价跟进'}).json()['id']
 def add_scene(category,name):
  r=c.post(BASE+'/scenes',headers=h,json={'category_id':category,'name':name});assert r.status_code==201;return r.json()['id']
 s=add_scene(a,'收到询价');t=add_scene(a,'缺少图纸');u=add_scene(b,'收到询价')
 assert c.post(BASE+'/scenes',headers=h,json={'category_id':a,'name':' 收到询价 '}).status_code==409
 assert c.post(BASE+'/scenes',headers=h,json={'category_id':a,'name':' '}).status_code==422
 assert c.put(BASE+'/scenes/order',headers=h,json={'category_id':a,'ids':[t,s]}).status_code==200
 assert c.put(BASE+'/scenes/order',headers=h,json={'category_id':a,'ids':[s,u]}).status_code==409
 assert c.put(BASE+f'/scenes/{t}',headers=h,json={'name':'补充图纸'}).status_code==200
 assert c.put(BASE+f'/scenes/{t}',headers=h,json={'name':'收到询价'}).status_code==409
 assert c.post(BASE+'/items',headers=h,json={'category_id':a,'scene_id':u,'content':'wrong category'}).status_code==404
 assert c.post('/api/phrases/projects/2/items',headers=h,json={'category_id':a,'scene_id':s,'content':'wrong project'}).status_code==404
 def add_phrase(scene_id,content):
  return c.post(BASE+'/items',headers=h,json={'category_id':a,'scene_id':scene_id,'content':content}).json()['id']
 ids=[add_phrase(s,'First'),add_phrase(t,'Other scene'),add_phrase(s,'Second'),add_phrase(None,'Unassigned')]
 data=c.get(BASE,headers=h).json()
 assert [x['id'] for x in data['scenes'] if x['category_id']==a]==[t,s]
 before=[x['id'] for x in data['items'] if x['scene_id']==s]
 assert c.post(BASE+f'/items/{before[0]}/move',headers=h,json={'direction':1,'category_id':a,'scene_id':s}).json()['moved']
 data=c.get(BASE,headers=h).json()
 assert [x['id'] for x in data['items'] if x['scene_id']==s]==before[::-1]
 assert c.post(BASE+f'/items/{ids[0]}/move',headers=h,json={'direction':1,'scene_id':0}).status_code==409
 assert c.delete(BASE+f'/scenes/{t}?target_id={u}',headers=h).status_code==404
 assert c.delete(BASE+f'/scenes/{t}?target_id={t}',headers=h).status_code==422
 assert c.delete(BASE+f'/scenes/{t}?target_id={s}',headers=h).json()['moved']==1
 # A populated scene requires migration; an empty scene can be deleted.
 empty=add_scene(a,'临时场景');unassigned=add_phrase(empty,'Keep original')
 assert c.delete(BASE+f'/scenes/{empty}',headers=h).status_code==409
 assert next(x for x in c.get(BASE,headers=h).json()['items'] if x['id']==unassigned)['scene_id']==empty
 assert c.delete(BASE+f'/scenes/{empty}?target_id={s}',headers=h).json()['moved']==1
 blank=add_scene(a,'空场景');assert c.delete(BASE+f'/scenes/{blank}',headers=h).json()['moved']==0
 # Matching scene names merge; unique scenarios move to the receiving category.
 unique=add_scene(a,'技术确认');add_phrase(unique,'Technical review')
 assert c.delete(BASE+f'/categories/{a}?target_id={b}',headers=h).status_code==200
 data=c.get(BASE,headers=h).json()
 assert all(x['category_id']==b for x in data['items']+data['scenes'])
 assert next(x for x in data['items'] if x['id']==ids[0])['scene_id']==u
 assert any(x['id']==unique for x in data['scenes'])
 assert len(data['items'])==6
 member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["communication_phrases"]';member.write_permissions_json='[]';db.commit()
 assert c.get(BASE,headers=headers(2)).json()['scenes']
 for method,path,payload in [('post','/scenes',{'category_id':b,'name':'forbidden'}),('put',f'/scenes/{u}',{'name':'forbidden'}),('put','/scenes/order',{'category_id':b,'ids':[u,unique]}),('delete',f'/scenes/{u}',None)]:
  assert getattr(c,method)(BASE+path,headers=headers(2),**({'json':payload} if payload else {})).status_code==403
 assert c.put('/api/phrases/projects/2/scenes/'+str(u),headers=h,json={'name':'wrong project'}).status_code==404
 delete_all_project_data(db,1);db.commit();assert not db.scalars(select(PhraseScene)).all()


def test_scene_upgrade_keeps_existing_content_and_is_idempotent():
 from sqlalchemy import create_engine,text,inspect,event
 from app.models import Base
 from app.services.phrase_scene_schema import ensure_phrase_scene_schema
 engine=create_engine('sqlite://')
 @event.listens_for(engine,'connect')
 def foreign_keys(connection,_):connection.execute('PRAGMA foreign_keys=ON')
 Base.metadata.create_all(engine)
 with engine.begin() as connection:
  connection.execute(text('DROP TABLE crm_communication_phrases'))
  connection.execute(text('CREATE TABLE crm_communication_phrases (id INTEGER PRIMARY KEY,content TEXT,translation TEXT)'))
  connection.execute(text("INSERT INTO crm_communication_phrases VALUES (1,'Original','译文')"))
 ensure_phrase_scene_schema(engine);ensure_phrase_scene_schema(engine)
 with engine.connect() as connection:
  assert connection.execute(text('SELECT content,translation,scene_id FROM crm_communication_phrases')).one()==('Original','译文',None)
 assert len([x for x in inspect(engine).get_indexes('crm_communication_phrases') if x['column_names']==['scene_id']])==1
