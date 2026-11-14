from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models.mail import MailConfiguration, MailAccount, MailDelivery
from app.services import mail as transport
from tests.test_global_access import db, headers
from tests.test_mail import config, lead, send


def test_multiple_mailboxes_keep_legacy_private_and_send_from_selected_account(db,monkeypatch):
    client=TestClient(app);config(client)
    legacy=db.get(MailConfiguration,1);before=(legacy.email,legacy.secret_encrypted,legacy.signature)
    body={'email':'second@example.com','sender_name':'Second mailbox','host':'smtp.example.com','port':465,'encryption':'ssl','username':'second@example.com','password':'new-app-secret','signature':'Second signature'}
    response=client.post('/api/mail/accounts',headers=headers(1),json=body)
    assert response.status_code==201,response.text
    account=response.json();aid=account['account_id'];assert aid>0
    assert 'new-app-secret' not in response.text
    encrypted=db.get(MailAccount,aid).secret_encrypted;assert encrypted!='new-app-secret'
    assert transport.decrypt_secret(encrypted)=='new-app-secret'
    rows=client.get('/api/mail/accounts',headers=headers(1)).json()
    assert len(rows['items'])==2 and rows['default_account_id']==0
    assert all('signature' not in row and 'secret_encrypted' not in row for row in rows['items'])
    assert client.get('/api/mail/accounts',headers=headers(2)).json()['items']==[]
    assert client.get(f'/api/mail/configuration?account_id={aid}',headers=headers(2)).status_code==404
    for method,path in [('put',f'/api/mail/accounts/{aid}'),('post',f'/api/mail/accounts/{aid}/default'),('delete',f'/api/mail/accounts/{aid}')]:
        assert getattr(client,method)(path,headers=headers(2),**({'json':body} if method=='put' else {})).status_code==404
    assert client.post('/api/mail/accounts',headers=headers(1),json=body).status_code==409
    monkeypatch.setattr(transport,'test_connection',lambda c:None)
    tested=client.post(f'/api/mail/configuration/test?account_id={aid}',headers=headers(1));assert tested.json()['last_test_status']=='passed'
    assert legacy.last_test_status is None
    body.pop('password');body['sender_name']='Updated sender'
    edited=client.put(f'/api/mail/accounts/{aid}',headers=headers(1),json=body);assert edited.status_code==200
    assert edited.json()['last_test_status']=='passed' and db.get(MailAccount,aid).secret_encrypted==encrypted
    assert client.post(f'/api/mail/accounts/{aid}/default',headers=headers(1)).status_code==200
    assert client.get('/api/mail/configuration',headers=headers(1)).json()['email']=='second@example.com'
    lid=lead(db);sent=[];monkeypatch.setattr(transport,'transmit',lambda c,m:sent.append((c.email,m)))
    key=str(uuid4());result=send(client,lid,key,account_id=aid);assert result.json()['status']=='accepted'
    assert sent[0][0]=='second@example.com' and 'second@example.com' in str(sent[0][1]['From'])
    assert send(client,lid,key,account_id=aid).json()['id']==result.json()['id'] and len(sent)==1
    assert send(client,lid,key,account_id=0).status_code==409 and len(sent)==1
    explicit_legacy=send(client,lid,account_id=0);assert explicit_legacy.json()['sender']=='sam@example.com'
    assert client.post('/api/mail/accounts/0/default',headers=headers(1)).status_code==200
    assert client.get('/api/mail/configuration',headers=headers(1)).json()['email']=='sam@example.com'
    assert (legacy.email,legacy.secret_encrypted,legacy.signature)==before
    assert client.delete(f'/api/mail/accounts/{aid}',headers=headers(1)).status_code==200
    assert db.scalar(select(MailDelivery).where(MailDelivery.id==result.json()['id']))
    assert send(client,lid,account_id=aid).status_code==404
    assert client.get('/api/mail/accounts').status_code==401


def test_first_extra_account_can_be_default_and_delete_falls_back_without_losing_history(db):
    client=TestClient(app)
    body={'email':'first@example.com','host':'smtp.example.com','port':465,'encryption':'ssl','username':'first@example.com','password':'example-app-secret'}
    first=client.post('/api/mail/accounts',headers=headers(1),json=body).json()
    assert first['account_id']>0
    assert client.get('/api/mail/accounts',headers=headers(1)).json()['default_account_id']==first['account_id']
    body['email']='next@example.com';body['username']='next@example.com'
    second=client.post('/api/mail/accounts',headers=headers(1),json=body).json()
    assert client.delete(f"/api/mail/accounts/{first['account_id']}",headers=headers(1)).status_code==200
    assert client.get('/api/mail/configuration',headers=headers(1)).json()['account_id']==second['account_id']
    assert client.delete(f"/api/mail/accounts/{second['account_id']}",headers=headers(1)).status_code==200
    assert not client.get('/api/mail/configuration',headers=headers(1)).json()['configured']
