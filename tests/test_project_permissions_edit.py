"""Permission editing accepts the whole catalog and updates linked users immediately."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import ProjectMember, ProjectRole
from app.core.modules import PROJECT_MODULES, CRM_CUSTOMER_MODULES
from tests.test_global_access import db, headers

BASE='/api/workspaces/1/projects/1'

def test_edit_full_catalog_syncs_assigned_member_and_revoke_effective_access(db):
    client=TestClient(app)
    response=client.post(BASE+'/roles',headers=headers(1),json={'name':'All features','permissions':sorted(PROJECT_MODULES)})
    assert response.status_code==201,response.text
    role=response.json();assert len(role['permissions'])>8
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2))
    response=client.patch(BASE+f'/members/{member.id}',headers=headers(1),json={'role':'custom','project_role_id':role['id']})
    assert response.status_code==200,response.text
    assert client.get('/api/contacts/projects/1',headers=headers(2)).status_code==200
    response=client.put(BASE+f"/roles/{role['id']}",headers=headers(1),json={'name':'Only RFQ','permissions':['rfq']})
    assert response.status_code==200,response.text
    db.refresh(member);assert json.loads(member.permissions_json)==['rfq']
    assert client.get('/api/contacts/projects/1',headers=headers(2)).status_code==403
    project=client.get('/api/workspaces/1/projects',headers=headers(2)).json()[0]
    assert project['permissions']==['rfq']
    response=client.put(BASE+f"/roles/{role['id']}",headers=headers(1),json={'name':'No access','permissions':[]})
    assert response.status_code==200,response.text
    assert client.get('/api/workspaces/1/projects',headers=headers(2)).json()[0]['permissions']==[]

def test_member_catalog_exposes_independent_crm_modules_and_legacy_privileges(db):
    client=TestClient(app)
    result=client.get(BASE+'/members',headers=headers(1)).json()
    assert set(CRM_CUSTOMER_MODULES).issubset({item['key'] for item in result['modules']})
    assert not any(item['key']=='contacts' for item in result['modules'])
    member=next(item for item in result['members'] if item['user_id']==2)
    assert member['access_source']=='项目角色' and member['effective_permissions']==sorted((*CRM_CUSTOMER_MODULES,'project_management','url_navigation','ai_configuration','mail_configuration'))

def test_direct_member_full_permission_payload_and_workspace_admin_override(db):
    from app.models import WorkspaceMember
    client=TestClient(app)
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2))
    response=client.patch(BASE+f'/members/{member.id}',headers=headers(1),json={'role':'custom','permissions':sorted(PROJECT_MODULES)})
    assert response.status_code==200,response.text
    wm=db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id==2));wm.role='admin';db.commit()
    response=client.patch(BASE+f'/members/{member.id}',headers=headers(1),json={'role':'custom','permissions':[]})
    assert response.status_code==200,response.text
    result=client.get(BASE+'/members',headers=headers(1)).json()
    member=next(item for item in result['members'] if item['user_id']==2)
    assert member['permissions']==[] and member['access_source']=='工作区管理员'
    assert set(member['effective_permissions'])==set(PROJECT_MODULES)
    assert client.get('/api/contacts/projects/1',headers=headers(2)).status_code==200
