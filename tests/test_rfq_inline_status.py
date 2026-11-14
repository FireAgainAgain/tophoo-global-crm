from fastapi.testclient import TestClient
from app.main import app
from app.models import Rfq, ProjectMember
from tests.test_global_access import db, headers


def test_inline_status_only_changes_status_and_checks_scope(db):
    member=db.get(ProjectMember,1);member.permissions_json='["rfq"]';member.write_permissions_json='["rfq"]'
    db.add_all([Rfq(id=901,site_project_id=1,owner_user_id=2,number='RFQ-1',status='待处理',
        contact_id=777,contact_snapshot_json='{"contact_name":"Original buyer"}',notes='Keep notes',
        parameters_json='{"request":"Original content"}',template_fields_json='[{"key":"request"}]',
        parameter_notes_json='{"request":"Original annotation"}'),
        Rfq(id=902,site_project_id=1,owner_user_id=1,number='RFQ-2'),
        Rfq(id=903,site_project_id=2,owner_user_id=2,number='RFQ-3')]);db.commit()
    client=TestClient(app);item=db.get(Rfq,901)
    before={c.name:getattr(item,c.name) for c in Rfq.__table__.columns if c.name not in ('status','updated_at')}
    url='/api/rfqs/projects/1/901/status'
    for status in ['推进中','已报价','已成交','已关闭','待处理']:
        result=client.patch(url,headers=headers(2),json={'status':status})
        assert result.status_code==200,result.text
        assert result.json()=={'id':901,'status':status}
        assert item.status==status
        assert all(getattr(item,k)==v for k,v in before.items())
    for status in ['Other','需求确认中','',None]:
        assert client.patch(url,headers=headers(2),json={'status':status}).status_code==422
    assert client.patch(url,headers=headers(2),json={'status':'已报价','notes':'Overwrite'}).status_code==422
    assert client.patch(url.replace('/901/','/902/'),headers=headers(2),json={'status':'已关闭'}).status_code==404
    assert client.patch(url.replace('/901/','/903/'),headers=headers(2),json={'status':'已关闭'}).status_code==404
    assert client.patch(url,json={'status':'已关闭'}).status_code==401
    assert client.patch(url.replace('/901/','/902/'),headers=headers(1),json={'status':'已关闭'}).status_code==200
    member.write_permissions_json='[]';db.commit()
    assert client.patch(url,headers=headers(2),json={'status':'已报价'}).status_code==403
    assert item.status=='待处理'
