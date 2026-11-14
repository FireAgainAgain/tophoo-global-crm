import json
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead, ProjectMember
from tests.test_global_access import db, headers


def test_lead_contacts_only_update_people_and_reject_stale_or_unauthorized_writes(db):
    lead=Lead(site_project_id=1,owner_user_id=2,company_name='Acme',country='捷克',workflow_status='contacted',is_manually_researched=True,notes='Keep research')
    db.add(lead);db.commit()
    member=db.get(ProjectMember,1);member.permissions_json='["leads"]';member.write_permissions_json='["leads"]';db.commit()
    client=TestClient(app);url=f'/api/customer-workflow/projects/1/leads/{lead.id}/contacts'
    initial=client.get(url,headers=headers(2));assert initial.status_code==200,initial.text
    before={c.name:getattr(lead,c.name) for c in Lead.__table__.columns if c.name not in ('contacts_json','contact_name','email','phone','whatsapp','other_channels','updated_at')}
    payload={'version':initial.json()['version'],'contacts':[{'contact_name':'Buyer','email':'buyer@example.com','is_primary':True},{'contact_name':'Engineer','phone':'123'}]}
    saved=client.put(url,headers=headers(2),json=payload);assert saved.status_code==200,saved.text
    assert len(saved.json()['contacts'])==2
    assert lead.email=='buyer@example.com'
    assert all(getattr(lead,k)==v for k,v in before.items())
    assert client.put(url,headers=headers(2),json=payload).status_code==409
    payload={'version':saved.json()['version'],'contacts':[{'contact_name':'Engineer updated','email':'engineer@example.com'}]}
    changed=client.put(url,headers=headers(2),json=payload);assert changed.status_code==200
    assert changed.json()['contacts'][0]['is_primary']
    cleared=client.put(url,headers=headers(2),json={'version':changed.json()['version'],'contacts':[]});assert cleared.status_code==200
    assert cleared.json()['contacts']==[] and lead.email is None
    assert client.get(url).status_code==401
    assert client.get(url.replace('/projects/1/','/projects/2/'),headers=headers(2)).status_code in (403,404)
    other=Lead(site_project_id=1,owner_user_id=1,company_name='Other');db.add(other);db.commit()
    assert client.get(url.replace(f'/{lead.id}/contacts',f'/{other.id}/contacts'),headers=headers(2)).status_code==404
    member.write_permissions_json='[]';db.commit()
    assert client.get(url,headers=headers(2)).status_code==200
    assert client.put(url,headers=headers(2),json={'version':cleared.json()['version'],'contacts':[]}).status_code==403
    member.write_permissions_json='["leads"]';db.commit()
    assert client.put(url,headers=headers(2),json={'version':cleared.json()['version'],'contacts':[],'is_manually_researched':False}).status_code==422
    assert all(getattr(lead,k)==v for k,v in before.items())
