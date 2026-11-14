import base64
from types import SimpleNamespace
from app.services.mail_html import clean_mail_html
from app.services.mail import build_message
from fastapi.testclient import TestClient
from app.main import app
from tests.test_global_access import db, headers
from tests.test_lead_outreach import lead, BASE

PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5X8AAAAASUVORK5CYII='

def test_html_sanitizer_keeps_signature_layout_and_removes_active_content():
    result=clean_mail_html('<script>alert(1)</script><table style="border-collapse:collapse"><tr><td onclick="bad()" style="color:red;background-image:url(x)"><b>Name</b><img src="javascript:bad()"><a href="javascript:bad()">link</a></td></tr></table>')
    assert '<table style="border-collapse:collapse">' in result
    assert '<b>Name</b>' in result and 'color:red' in result
    for forbidden in ('script','onclick','javascript','background-image','alert('):assert forbidden not in result

def test_html_message_has_plain_fallback_inline_image_and_attachment():
    config=SimpleNamespace(sender_name='Seller',email='seller@example.com')
    message=build_message(config,'buyer@example.com','Supply','Hello Buyer',[('spec.txt','text/plain',b'spec')],'<test@example.com>',content_html=f'<p><b>Hello</b></p><img src="data:image/png;base64,{PNG}">')
    assert message.get_body(preferencelist=('plain',)).get_content().strip()=='Hello Buyer'
    html=message.get_body(preferencelist=('html',)).get_content()
    assert '<b>Hello</b>' in html and 'cid:tophoo-inline-1' in html and 'base64,' not in html
    images=[part for part in message.walk() if part.get_content_type()=='image/png']
    assert len(images)==1 and images[0].get_payload(decode=True)==base64.b64decode(PNG)
    assert images[0]['Content-ID']=='<tophoo-inline-1>'
    assert list(message.iter_attachments())[0].get_filename()=='spec.txt'

def test_rich_draft_roundtrip_legacy_update_and_conversion(db):
    from sqlalchemy import select
    import json
    from app.models import LeadConversionHistory
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    markup=f'<table><tr><td style="color:blue"><strong>Seller</strong><img src="data:image/png;base64,{PNG}"></td></tr></table>'
    response=client.put(url,headers=headers(2),json={'content':'Seller','content_html':markup})
    assert response.status_code==200,response.text
    assert client.get(url,headers=headers(2)).json()['content_html']==markup
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2))
    assert response.status_code==200,response.text
    row=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==response.json()['customer_id']))
    assert json.loads(row.snapshot_json)['outreach_draft']['content_html']==markup
    lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    client.put(url,headers=headers(2),json={'content':'Seller','content_html':markup})
    assert client.put(url,headers=headers(2),json={'content':'Plain update'}).json()['content_html']==''
