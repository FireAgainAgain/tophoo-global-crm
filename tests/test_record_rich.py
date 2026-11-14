from fastapi.testclient import TestClient
from app.main import app
from app.models import LeadInteraction
from tests.test_global_access import db, headers
from tests.test_lead_shared_records import create_lead, BODY, BASE
from tests.test_mail_html import PNG


def test_rich_record_sanitized_roundtrip_edit_and_customer_transfer(db):
    client=TestClient(app);lid=create_lead(client)
    html=f'<table><tr><td style="color:blue"><b>Seller</b></td><td><img src="data:image/png;base64,{PNG}"></td></tr></table>'
    response=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json={**BODY,'content_html':html+'<script>bad()</script>'})
    assert response.status_code==201,response.text
    rid=response.json()['id'];assert response.json()['content_html']==html
    # An older client may edit metadata without erasing the existing HTML.
    updated=client.put(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2),json=BODY)
    assert updated.json()['content_html']==html
    cid=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).json()['customer_id']
    base=f'/api/contacts/projects/1/{cid}/records'
    record=client.get(base,headers=headers(2)).json()['records'][0]
    assert record['content_html']==html
    response=client.put(base+'/'+str(record['id']),headers=headers(2),json={**BODY,'content':'Updated','content_html':'<p><i>Updated</i></p>'})
    assert response.json()['content_html']=='<p><i>Updated</i></p>'
    # Plain-text body replacement must not leave stale HTML in view.
    response=client.put(base+'/'+str(record['id']),headers=headers(2),json={**BODY,'content':'Plain update'})
    assert response.json()['content_html']==''


def test_existing_conversion_snapshot_displays_as_rich_body_without_rewriting(db):
    import json
    client=TestClient(app);lid=create_lead(client)
    response=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=BODY)
    row=db.get(LeadInteraction,response.json()['id'])
    row.source_outreach_json=json.dumps({'content':row.content,'content_html':'<p><b>Original</b></p>'})
    row.content_html=None;db.commit()
    record=client.get(f'{BASE}/{lid}/interactions',headers=headers(2)).json()['records'][0]
    assert record['content_html']=='<p><b>Original</b></p>' and row.content_html is None
    response=client.put(f'{BASE}/{lid}/interactions/{row.id}',headers=headers(2),json={**BODY,'content':'Different content'})
    assert response.json()['content_html']==''
