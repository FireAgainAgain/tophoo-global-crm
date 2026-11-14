from fastapi.testclient import TestClient
from sqlalchemy import select,text
from app.main import app
from app.models import CommunicationScript,CommunicationScriptCategory,ProjectMember
from tests.test_global_access import db,headers


def test_confirmed_category_delete_removes_entire_subtree_and_preserves_other_data(db):
    client=TestClient(app);base='/api/communication-scripts/projects/1'
    def category(name,parent=None):
        r=client.post(base+'/categories',headers=headers(1),json={'name':name,'parent_id':parent});assert r.status_code==201;return r.json()['id']
    root=category('Root');child=category('Child',root);grandchild=category('Grandchild',child);keep=category('Keep')
    for category_id in [root,child,grandchild,keep]:
        assert client.post(base+'/scripts',headers=headers(1),json={'category_id':category_id,'title':'Knowledge','content':'Keep content'}).status_code==201
    other=CommunicationScriptCategory(site_project_id=2,name='Other project');db.add(other);db.flush()
    db.add(CommunicationScript(site_project_id=2,category_id=other.id,title='Other knowledge',content='Other content'));db.commit()
    url=base+f'/categories/{root}'
    assert client.delete(url,headers=headers(1)).status_code==409
    assert len(client.get(base,headers=headers(1)).json()['scripts'])==4
    db.execute(text('PRAGMA foreign_keys=ON'))
    result=client.delete(url+'?confirmed=true',headers=headers(1));assert result.status_code==200,result.text
    assert result.json()=={'deleted':True,'deleted_categories':3,'deleted_scripts':3}
    data=client.get(base,headers=headers(1)).json()
    assert [c['id'] for c in data['categories']]==[keep]
    assert len(data['scripts'])==1 and data['scripts'][0]['category_id']==keep
    assert db.scalar(select(CommunicationScript).where(CommunicationScript.site_project_id==2)).content=='Other content'


def test_category_delete_rejects_readonly_and_foreign_project(db):
    client=TestClient(app);base='/api/communication-scripts/projects/1'
    item=client.post(base+'/categories',headers=headers(1),json={'name':'Keep'}).json()
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["knowledge_base"]';member.write_permissions_json='[]';db.commit()
    assert client.delete(base+f"/categories/{item['id']}?confirmed=true",headers=headers(2)).status_code==403
    assert client.delete(f"/api/communication-scripts/projects/2/categories/{item['id']}?confirmed=true",headers=headers(1)).status_code==404
    assert db.get(CommunicationScriptCategory,item['id']) is not None
