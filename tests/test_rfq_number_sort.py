from datetime import date
from fastapi.testclient import TestClient
from app.main import app
from app.models import Rfq
from tests.test_global_access import db, headers


def test_rfq_numbers_descending_naturally_ignore_dates_and_refresh_after_edit(db):
    numbers=['v9','v1006','v10','v2','v010','v100','v1005']
    items=[Rfq(site_project_id=1,owner_user_id=1,number=number,inquiry_date=date(2026,10,31-index)) for index,number in enumerate(numbers)]
    db.add_all(items);db.commit()
    client=TestClient(app);url='/api/rfqs/projects/1'
    rows=client.get(url,headers=headers(1)).json()
    assert [r['number'] for r in rows]==['v1006','v1005','v100','v010','v10','v9','v2']
    item=items[-1]
    result=client.put(f'{url}/{item.id}',headers=headers(1),json={'number':'v2000','status':'待处理','inquiry_date':'2020-01-01'})
    assert result.status_code==200,result.text
    assert client.get(url,headers=headers(1)).json()[0]['number']=='v2000'
    created=client.post(url,headers=headers(1),json={'number':'v1500','status':'待处理','inquiry_date':'2020-01-01'})
    assert created.status_code==200,created.text
    assert [r['number'] for r in client.get(url,headers=headers(1)).json()][:3]==['v2000','v1500','v1006']
