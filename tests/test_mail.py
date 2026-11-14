import json
import smtplib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Lead, LeadInteraction, ProjectMember
from app.models.mail import MailConfiguration, MailDelivery
from app.services import mail as transport
from tests.test_global_access import db, headers


@pytest.fixture(autouse=True)
def no_real_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Tests may not connect to real SMTP servers')
    monkeypatch.setattr(transport, 'test_connection', forbidden)
    monkeypatch.setattr(transport, 'transmit', forbidden)


def config(client, user=1, **changes):
    data={'sender_name':'Sam', 'email':'sam@example.com', 'host':'smtp.example.com', 'port':465,
          'encryption':'ssl', 'username':'sam@example.com', 'password':'super-private-secret', 'signature':'Best regards,\nVex'}
    data.update(changes)
    result=client.put('/api/mail/configuration',headers=headers(user),json=data)
    assert result.status_code==200,result.text
    return result.json()


def lead(db, owner=1):
    item=Lead(site_project_id=1,owner_user_id=owner,company_name='Mail buyer',workflow_status='ready')
    db.add(item);db.commit();return item.id


def send(client, lid, key=None, user=1, files=None, **changes):
    payload={'request_key':key or str(uuid4()),'recipient':'buyer@example.com','subject':'Coil supply',
             'content':'Dear Buyer,\nWe supply coils.','content_translation':'我们供应盘管。','contact_name':'Buyer'}
    payload.update(changes)
    return client.post(f'/api/mail/projects/1/leads/{lid}/send',headers=headers(user),data=payload,files=files)


def test_private_configuration_encrypted_secrets_and_test_invalidation(db,monkeypatch):
    client=TestClient(app)
    assert client.get('/api/mail/configuration').status_code==401
    assert client.get('/api/mail/configuration',headers=headers(1)).json()['configured'] is False
    assert client.put('/api/mail/configuration',headers=headers(1),json={'email':'sam@example.com', 'host':'smtp.example.com',
        'username':'sam@example.com','port':465,'encryption':'ssl'}).status_code==422
    result=config(client)
    assert result['has_password'] and 'password' not in result and 'secret_encrypted' not in result
    stored=db.get(MailConfiguration,1).secret_encrypted
    assert stored!='super-private-secret' and transport.decrypt_secret(stored)=='super-private-secret'
    assert client.get('/api/mail/configuration',headers=headers(2)).json()['configured'] is False
    monkeypatch.setattr(transport,'test_connection',lambda config:None)
    result=client.post('/api/mail/configuration/test',headers=headers(1)).json()
    assert result['last_test_status']=='passed' and result['last_tested_at']
    result=config(client,password='',sender_name='New name')
    assert result['last_test_status']=='passed' and db.get(MailConfiguration,1).secret_encrypted==stored
    assert config(client,password='',host='smtp2.example.com')['last_test_status']==''
    def fail(config):raise smtplib.SMTPAuthenticationError(535,b'credential super-private-secret')
    monkeypatch.setattr(transport,'test_connection',fail)
    result=client.post('/api/mail/configuration/test',headers=headers(1)).json()
    assert result['last_test_status']=='failed' and 'super-private-secret' not in json.dumps(result)
    assert client.put('/api/mail/configuration',headers=headers(1),json={'sender_name':'Injected\nBcc: x',
        'email':'sam@example.com','host':'smtp.example.com','port':465,'encryption':'ssl','username':'sam'}).status_code==422


def test_single_send_attachment_mime_record_and_idempotency(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db);sent=[]
    monkeypatch.setattr(transport,'transmit',lambda config,message:sent.append(message))
    key=str(uuid4());files=[('attachments',('目录.pdf',b'%PDF-test','application/pdf'))]
    result=send(client,lid,key,files=files)
    assert result.status_code==200,result.text
    data=result.json();assert data['status']=='accepted' and data['interaction_id'] is None
    assert len(sent)==1 and str(sent[0]['To'])=='buyer@example.com'
    assert sent[0].get_body(preferencelist=('plain',)).get_content().strip()=='Dear Buyer,\nWe supply coils.'
    assert next(sent[0].iter_attachments()).get_filename()=='目录.pdf'
    attachment=next(sent[0].iter_attachments())
    assert attachment.get_payload(decode=True)==b'%PDF-test'
    assert attachment.get_content_type()=='application/pdf'
    assert send(client,lid,key,files=files).json()['id']==data['id'] and len(sent)==1
    assert send(client,lid,key,subject='Different subject',files=files).status_code==409
    assert not db.scalars(select(LeadInteraction)).all()
    assert data['content']=='Dear Buyer,\nWe supply coils.'
    assert db.get(Lead,lid).workflow_status=='ready'
    assert client.get('/api/mail/deliveries',headers=headers(2)).json()['items']==[]
    assert len(client.get('/api/mail/deliveries',headers=headers(1)).json()['items'])==1


def test_multiple_contacts_are_independent_idempotent_and_queryable(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db);sent=[]
    monkeypatch.setattr(transport,'transmit',lambda config,message:sent.append(message))
    keys=[str(uuid4()),str(uuid4())]
    files=[('attachments',('catalog.pdf',b'%PDF-catalog-payload','application/pdf'))]
    first=send(client,lid,keys[0],recipient='buyer@example.com',contact_name='Buyer',files=files).json()
    second=send(client,lid,keys[1],recipient='engineer@example.com',contact_name='Engineer',files=files).json()
    assert first['status']==second['status']=='accepted'
    assert [str(message['To']) for message in sent]==['buyer@example.com','engineer@example.com']
    assert all(not message['Cc'] and not message['Bcc'] for message in sent)
    assert all(next(message.iter_attachments()).get_payload(decode=True)==b'%PDF-catalog-payload' for message in sent)
    assert send(client,lid,keys[0],files=files).json()['id']==first['id'] and len(sent)==2
    records=db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id==lid)).all()
    assert records==[]
    assert db.get(Lead,lid).workflow_status=='ready' and not db.get(Lead,lid).is_contacted
    assert client.get('/api/mail/deliveries/by-request/'+keys[0],headers=headers(1)).json()['id']==first['id']
    assert client.get('/api/mail/deliveries/by-request/'+keys[0],headers=headers(2)).status_code==404
    assert client.get('/api/mail/deliveries/by-request/'+keys[0]).status_code==401
    # Querying an uncertain send is read-only and cannot trigger another SMTP call.
    assert len(sent)==2


def test_exact_delivery_lookup_not_limited_to_recent_fifty(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db)
    monkeypatch.setattr(transport,'transmit',lambda *_:None)
    key=str(uuid4());original=send(client,lid,key).json()
    for _ in range(55):
        db.add(MailDelivery(owner_user_id=1,request_key=str(uuid4()),payload_hash='a'*64,message_id=str(uuid4()),sender='sam@example.com',recipient='example@example.com',subject='Fixture',content='Fixture',status='accepted'))
    db.commit()
    assert original['id'] not in [row['id'] for row in client.get('/api/mail/deliveries',headers=headers(1)).json()['items']]
    response=client.get('/api/mail/deliveries/by-request/'+key,headers=headers(1))
    assert response.status_code==200 and response.json()['id']==original['id']
    assert client.get('/api/mail/deliveries/by-request/'+str(uuid4()),headers=headers(1)).status_code==404


def test_unknown_or_failed_send_never_creates_summary_or_retries_same_key(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db);calls=[]
    def uncertain(*args):calls.append(1);raise transport.DeliveryError('unknown','结果待核实')
    monkeypatch.setattr(transport,'transmit',uncertain)
    key=str(uuid4());result=send(client,lid,key).json()
    assert result['status']=='unknown' and not result['interaction_id']
    assert send(client,lid,key).json()['status']=='unknown' and len(calls)==1
    assert not db.scalars(select(LeadInteraction)).all() and db.get(Lead,lid).workflow_status=='ready'
    def rejected(*args):raise transport.DeliveryError('failed','登录失败')
    monkeypatch.setattr(transport,'transmit',rejected)
    assert send(client,lid).json()['status']=='failed'


@pytest.mark.parametrize('status,contacted', [
    ('unviewed',False),('ready',False),('priority',False),('priority',True),
    ('contacted',True),('replied',True),('company_contacted',True),('unfit',False),('fake',False),
])
def test_successful_send_keeps_manual_status_and_contact_flag(db,monkeypatch,status,contacted):
    client=TestClient(app);config(client);lid=lead(db)
    item=db.get(Lead,lid);item.workflow_status=status;item.is_contacted=contacted;db.commit()
    before=(item.workflow_status,item.is_contacted,item.status_schema_version,item.updated_at)
    monkeypatch.setattr(transport,'transmit',lambda *_:None)
    key=str(uuid4());response=send(client,lid,key)
    assert response.status_code==200,response.text
    result=response.json();assert result['status']=='accepted' and result['interaction_id'] is None
    assert send(client,lid,key).json()['id']==result['id']
    db.refresh(item)
    assert (item.workflow_status,item.is_contacted,item.status_schema_version,item.updated_at)==before
    records=db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id==lid)).all()
    assert records==[]


def test_guards_validation_and_test_message_to_self(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db);sent=[]
    monkeypatch.setattr(transport,'transmit',lambda config,message:sent.append(message))
    assert send(client,lid,user=2).status_code==404
    assert send(client,lid,subject='Hello\nBcc: another@example.com').status_code==422
    assert send(client,lid,recipient='buyer@example.com,other@example.com').status_code==422
    assert send(client,lid,files=[('attachments',('a.bin',b'X'*(10*1024*1024+1),'application/octet-stream'))]).status_code==422
    assert send(client,lid,files=[('attachments',(f'{i}.txt',b'x','text/plain')) for i in range(6)]).status_code==422
    assert sent==[]
    mine=lead(db,2);config(client,2)
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.role='viewer';member.permissions_json='["leads"]';member.write_permissions_json='[]';db.commit()
    assert send(client,mine,user=2).status_code==403
    key=str(uuid4());result=client.post('/api/mail/test-message',headers=headers(1),json={'request_key':key})
    assert result.json()['status']=='accepted' and str(sent[-1]['To'])=='sam@example.com'
    client.post('/api/mail/test-message',headers=headers(1),json={'request_key':key})
    assert len(sent)==1 and not db.scalars(select(LeadInteraction)).all()


def test_smtp_data_disconnect_is_unknown_but_auth_failure_is_not(db,monkeypatch):
    client=TestClient(app);config(client);saved=db.get(MailConfiguration,1)
    monkeypatch.setattr(transport,'public_smtp_host',lambda *args:None)
    class FakeSMTP:
        def __init__(self,*args,**kwargs):pass
        def login(self,*args):pass
        def mail(self,*args):return (250,b'ok')
        def rcpt(self,*args):return (250,b'ok')
        def data(self,*args):raise TimeoutError('network timeout')
        def close(self):pass
    monkeypatch.setattr(transport.smtplib,'SMTP_SSL',FakeSMTP)
    # Use the real transport implementation saved on the module source, not network.
    import importlib.util
    spec=importlib.util.spec_from_file_location('mail_transport_for_test',transport.__file__)
    real=importlib.util.module_from_spec(spec);spec.loader.exec_module(real)
    monkeypatch.setattr(real,'public_smtp_host',lambda *args:None)
    message=real.build_message(saved,'buyer@example.com','Hello','Body',[],real.message_id())
    with pytest.raises(real.DeliveryError) as err:real.transmit(saved,message)
    assert err.value.status=='unknown'
    monkeypatch.setattr(FakeSMTP,'login',lambda *args:(_ for _ in ()).throw(smtplib.SMTPAuthenticationError(535,b'secret')))
    with pytest.raises(real.DeliveryError) as err:real.transmit(saved,message)
    assert err.value.status=='failed' and 'secret' not in err.value.message


def test_rich_signature_and_html_delivery_preserved(db,monkeypatch):
    client=TestClient(app);sent=[]
    signature='<table><tr><td style="color:blue"><b>Seller</b></td></tr></table>'
    assert config(client,signature=signature)['signature']==signature
    monkeypatch.setattr(transport,'transmit',lambda config,message:sent.append(message))
    result=send(client,lead(db),content_html='<p><b>Hello</b></p>'+signature)
    assert result.status_code==200,result.text
    assert result.json()['status']=='accepted'
    assert result.json()['content_html']=='<p><b>Hello</b></p>'+signature
    assert '<table>' in sent[0].get_body(preferencelist=('html',)).get_content()
    history=client.get('/api/mail/deliveries',headers=headers(1)).json()['items']
    assert history[0]['content_html']==result.json()['content_html']


def test_configuration_explains_web_address_and_wrong_tls_mode(db):
    client=TestClient(app)
    base={'email':'sam@163.com','host':'https://mail.163.com/','port':465,'encryption':'ssl','username':'sam@163.com','password':'private'}
    response=client.put('/api/mail/configuration',headers=headers(1),json=base)
    assert response.status_code==422
    assert response.json()['detail'][0]['loc'][-1]=='host'
    assert 'smtp.163.com' in response.json()['detail'][0]['msg']
    base.update(host='smtp.163.com',encryption='starttls')
    response=client.put('/api/mail/configuration',headers=headers(1),json=base)
    assert response.status_code==422 and 'SSL / TLS' in response.json()['detail'][0]['msg']
    assert db.get(MailConfiguration,1) is None
