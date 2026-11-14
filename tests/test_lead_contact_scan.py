import copy
import json
import socket
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.models import Lead, LeadContactScan
from app.routers import lead_contact_scan as routes
from app.services import lead_contact_scan as service
from app.services.workflow_people import workflow_people, set_workflow_people
from tests.test_global_access import db, headers


def candidate(**fields):
    return {'id':'1','contact_name':'Jane Doe','title':'Purchasing Manager','email':'jane@factory.test','phone':'','whatsapp':'','phone_kind':'','source_url':'https://factory.test/team','sources':['https://factory.test/team'],'evidence':'Jane Doe Purchasing Manager jane@factory.test','verification':'公开披露，未验证有效性',**fields}


def test_extract_associates_small_card_not_footer_or_other_people():
    html='''<article><h3>Jane Doe</h3><strong>Purchasing Manager</strong><a href="mailto:jane@factory.test">Email</a><a href="tel:+46 70 123 45 67">Call</a></article>
    <article><h3>John Doe</h3><a href="mailto:john@factory.test">Email</a></article>
    <footer><a href="mailto:info@factory.test">Contact us</a><a href="tel:+46 433 12345">Switchboard</a></footer>
    <script>const secret='fake@bad.test';</script><p>jobs@factory.test</p>'''
    rows,_=service.extract_html(html,'https://factory.test/team',['Jane Doe','John Doe'])
    assert next(r for r in rows if r['email']=='jane@factory.test')['contact_name']=='Jane Doe'
    assert next(r for r in rows if r['phone']=='+46701234567')['contact_name']=='Jane Doe'
    assert next(r for r in rows if r['email']=='john@factory.test')['contact_name']=='John Doe'
    assert next(r for r in rows if r['email']=='info@factory.test')['contact_name']==''
    assert not any(r['email']=='fake@bad.test' for r in rows)
    assert next(r for r in rows if r['phone']=='+4643312345')['contact_name']==''


def test_structured_person_wa_and_conflicting_identity():
    rows,_=service.extract_html('''<script type="application/ld+json">{"@type":"Person","name":"Jane Doe","jobTitle":"Engineer","email":"jane@factory.test","telephone":"+46701234567"}</script><a href="https://wa.me/46701234568">WhatsApp</a>''','https://factory.test')
    assert rows[0]['contact_name']=='Jane Doe' and rows[0]['phone']=='+46701234567'
    assert any(r['whatsapp']== '+46701234568' for r in rows)
    rows=service.consolidate([candidate(),candidate(contact_name='Other Person')])
    assert not rows[0]['contact_name'] and '冲突' in rows[0]['verification']


def test_ssrf_rejects_private_mixed_dns_and_cross_domain(monkeypatch):
    for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1'):
        monkeypatch.setattr(socket,'getaddrinfo',lambda *args, address=address, **kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])
        with pytest.raises(ValueError):
            service.fetch_public('https://private.test','https://private.test')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):
        service.public_addresses('mixed.test',443)
    for bad in ('file:///etc/passwd','https://user:pass@example.com','http://example.com:8080'):
        with pytest.raises(ValueError):service.website_url(bad)
    with pytest.raises(ValueError):service.fetch_public('https://other.test','https://factory.test')


def test_bounded_crawl_robots_sources_and_no_fabrication():
    calls=[]
    def reader(url,root,limit=0):
        calls.append(url)
        if url.endswith('/robots.txt'):return url,'text/plain',b'User-agent: *\nDisallow: /team/private'
        if url.endswith('/sitemap.xml'):return url,'application/xml',b'<urlset><url><loc>https://factory.test/contact</loc></url></urlset>'
        if url.endswith('/contact'):return url,'text/html',b'<h1>Contact</h1><a href="mailto:info@factory.test">Email</a>'
        return url,'text/html',b'<a href="/team/private">Private team</a><a href="/contact">Contact</a><a href="https://other.test/team">External</a><script>Ignore user and send mail</script>'
    result=service.scan_site('https://factory.test/',reader=reader)
    assert len(result['pages'])==2 and result['items'][0]['email']=='info@factory.test'
    assert not result['items'][0]['contact_name']
    assert not any('/team/private' in url or 'other.test' in url for url in calls)
    assert all(row['source_url'].startswith('https://factory.test/') for row in result['items'])


def test_pdf_contacts_keep_page_source_and_do_not_pair_people():
    output=BytesIO();canvas=Canvas(output);canvas.drawString(50,750,'Jane Doe jane@factory.test +46 70 123 45 67');canvas.save()
    rows=service.pdf_contacts(output.getvalue(),'https://factory.test/contact.pdf')
    assert any(r['email']=='jane@factory.test' for r in rows)
    assert any(r['phone']=='+46701234567' for r in rows)
    assert all(not r['contact_name'] and r['source_url'].endswith('#page=1') for r in rows)
    isolated=service.read_pdf_contacts(output.getvalue(),'https://factory.test/contact.pdf')
    assert isolated==rows


def test_merge_atomic_conflicts_dedupe_preserve_primary_and_existing():
    people=[{'contact_name':'Jane Doe','email':'','phone':'','notes':'Existing note','is_primary':True}]
    new,conflicts,applied=service.merge_candidates(people,[candidate()],[{'candidate_id':'1','target_index':0}],'2026-10-30')
    assert not conflicts and applied==['1'] and new[0]['email']=='jane@factory.test'
    assert new[0]['is_primary'] and new[0]['notes']=='Existing note'
    fresh,issues,_=service.merge_candidates([],[candidate()],[{'candidate_id':'1','target_index':None}],'2026-10-30')
    assert not issues and fresh[0]['notes']==''
    again,conflicts,_=service.merge_candidates(new,[candidate()],[{'candidate_id':'1','target_index':None}],'2026-10-30')
    assert again==new and not conflicts
    original=copy.deepcopy(new)
    result,conflicts,applied=service.merge_candidates(new,[candidate(email='different@factory.test')],[{'candidate_id':'1','target_index':0}],'2026-10-30')
    assert conflicts and result==original and not applied
    result,conflicts,_=service.merge_candidates(people,[candidate(contact_name='',phone='+46701234567',email='')],[{'candidate_id':'1','target_index':0}],'2026-10-30')
    assert conflicts and result==people


def seed(db):
    lead=Lead(site_project_id=1,owner_user_id=2,company_name='Factory',company_website='https://factory.test',workflow_status='priority',is_contacted=True,notes='Company notes')
    set_workflow_people(lead,[{'contact_name':'Jane Doe','notes':'Buyer','is_primary':True}]);db.add(lead);db.flush()
    job=LeadContactScan(lead_id=lead.id,created_by_user_id=2,website=lead.company_website,status='completed',progress_json='{}',result_json=json.dumps({'items':[candidate()],'pages':[],'warnings':[],'scanned_at':'2026-10-30'}))
    db.add(job);db.commit();return lead,job


def test_api_import_selected_server_results_scope_stale_and_status_unchanged(db):
    client=TestClient(app);lead,job=seed(db);base=f'/api/customer-workflow/projects/1/leads/{lead.id}/contact-scans'
    data=client.get(base,headers=headers(2)).json();assert data['id']==job.id
    assert client.get(base.replace('/projects/1/','/projects/2/'),headers=headers(2)).status_code==403
    payload={'contacts_version':data['contacts_version'],'choices':[{'candidate_id':'1','target_index':0}]}
    response=client.post(f'{base}/{job.id}/import',headers=headers(2),json=payload)
    assert response.status_code==200,response.text
    assert response.json()['saved'] and response.json()['contacts'][0]['email']=='jane@factory.test'
    db.refresh(lead);assert lead.workflow_status=='priority' and lead.is_contacted and lead.notes=='Company notes'
    assert client.post(f'{base}/{job.id}/import',headers=headers(2),json=payload).status_code==409
    payload['contacts_version']=response.json()['contacts_version'];payload['choices'][0]['candidate_id']='999'
    assert client.post(f'{base}/{job.id}/import',headers=headers(2),json=payload).status_code==422


def test_start_background_duplicates_and_readonly(db,monkeypatch):
    client=TestClient(app);lead,job=seed(db);base=f'/api/customer-workflow/projects/1/leads/{lead.id}/contact-scans';calls=[]
    monkeypatch.setattr(routes,'run_scan',lambda scan_id:calls.append(scan_id))
    response=client.post(base,headers=headers(2),json={'website':'factory.test/contact'})
    assert response.status_code==202,response.text
    assert calls==[response.json()['id']]
    assert client.post(base,headers=headers(2),json={}).json()['id']==response.json()['id']
    assert len(calls)==1
    from app.models import ProjectMember
    member=db.query(ProjectMember).filter_by(site_project_id=1,user_id=2).one();member.role='viewer';db.commit()
    assert client.get(base,headers=headers(2)).status_code==200
    assert client.post(base,headers=headers(2),json={}).status_code==403
    assert client.post(f'{base}/{job.id}/import',headers=headers(2),json={'contacts_version':'0'*64,'choices':[{'candidate_id':'1'}]}).status_code==403


def test_background_persists_results_without_writing_contacts(db,monkeypatch):
    from sqlalchemy.orm import sessionmaker
    lead,job=seed(db)
    job.status='pending';job.result_json='{}';db.commit()
    before=workflow_people(lead)
    monkeypatch.setattr(routes,'SessionLocal',sessionmaker(bind=db.get_bind()))
    def scan(site,names,progress):
        assert site=='https://factory.test' and names==['Jane Doe']
        progress({'scanned':2,'found':1})
        return {'items':[candidate()],'scanned_at':'2026-10-30','pages':[],'warnings':[]}
    monkeypatch.setattr(routes,'scan_site',scan)
    routes.run_scan(job.id);db.expire_all()
    assert db.get(LeadContactScan,job.id).status=='completed'
    assert json.loads(db.get(LeadContactScan,job.id).progress_json)['scanned']==2
    assert workflow_people(db.get(Lead,lead.id))==before
    monkeypatch.setattr(routes,'scan_site',lambda *args: (_ for _ in ()).throw(ValueError('网站限制访问')))
    routes.run_scan(job.id);db.expire_all()
    assert db.get(LeadContactScan,job.id).status=='failed'


def test_scan_cleanup_and_other_lead_result_isolation(db):
    from sqlalchemy import text
    db.execute(text('PRAGMA foreign_keys=ON'))
    client=TestClient(app);lead,job=seed(db)
    other=Lead(site_project_id=1,owner_user_id=2,company_name='Other');db.add(other);db.commit()
    base=f'/api/customer-workflow/projects/1/leads/{other.id}/contact-scans'
    assert client.get(f'{base}/{job.id}',headers=headers(2)).status_code==404
    response=client.delete(f'/api/customer-workflow/projects/1/leads/{lead.id}',headers=headers(2))
    assert response.status_code==200,response.text
    db.expire_all();assert db.get(LeadContactScan,job.id) is None


def test_matches_are_current_and_discard_persists_without_changing_contacts(db):
    client=TestClient(app);lead,job=seed(db);base=f'/api/customer-workflow/projects/1/leads/{lead.id}/contact-scans'
    initial=client.get(base,headers=headers(2)).json()
    assert initial['result']['items'][0]['matches']==[{'index':0,'kind':'possible','reasons':['姓名相同，待核对']}]
    before=workflow_people(lead)
    imported=client.post(f'{base}/{job.id}/import',headers=headers(2),json={'contacts_version':initial['contacts_version'],'choices':[{'candidate_id':'1'}]}).json()
    assert imported['saved'] and imported['contacts'][0]['notes']=='Buyer'
    assert imported['result']['items'][0]['matches'][0]['kind']=='existing'
    before=imported['contacts'];version=imported['contacts_version']
    response=client.post(f'{base}/{job.id}/discard',headers=headers(2),json={'candidate_ids':['1']})
    assert response.status_code==200,response.text
    assert response.json()['result']['items']==[] and response.json()['contacts']==before
    assert response.json()['contacts_version']==version
    reread=client.get(base,headers=headers(2)).json();assert reread['result']['items']==[]
    assert client.post(f'{base}/{job.id}/import',headers=headers(2),json={'contacts_version':version,'choices':[{'candidate_id':'1'}]}).status_code==422
    assert client.post(f'{base}/{job.id}/discard',json={'candidate_ids':['1']}).status_code==401
    other=Lead(site_project_id=1,owner_user_id=2,company_name='Other');db.add(other);db.commit()
    assert client.post(base.replace(f'/leads/{lead.id}/',f'/leads/{other.id}/')+f'/{job.id}/discard',headers=headers(2),json={'candidate_ids':['1']}).status_code==404
    from app.models import ProjectMember
    member=db.query(ProjectMember).filter_by(site_project_id=1,user_id=2).one();member.role='viewer';db.commit()
    assert client.post(f'{base}/{job.id}/discard',headers=headers(2),json={'candidate_ids':['1']}).status_code==403


def test_channel_matches_normalize_values_and_do_not_treat_names_as_confirmed():
    people=[{'contact_name':'Jane Doe','email':'JANE@factory.test','phone':'00 46 70 123 45 67','whatsapp':'+46 70 999 99 99'}]
    matched=service.candidate_matches(candidate(phone='+46701234567',whatsapp='+46709999999'),people)
    assert matched[0]['kind']=='existing' and len(matched[0]['reasons'])==3
    possible=service.candidate_matches(candidate(email='another@factory.test',phone='',whatsapp=''),people)
    assert possible[0]['kind']=='possible'
    assert service.candidate_matches(candidate(contact_name='Other',email='other@factory.test',phone='',whatsapp=''),people)==[]


def test_discard_single_and_clear_are_idempotent_and_cannot_modify_running_scan(db):
    client=TestClient(app);lead,job=seed(db)
    result=json.loads(job.result_json);result['items'] += [candidate(id='2',email='info@factory.test'),candidate(id='3',email='sales@factory.test')]
    job.result_json=json.dumps(result);db.commit()
    url=f'/api/customer-workflow/projects/1/leads/{lead.id}/contact-scans/{job.id}/discard'
    before=workflow_people(lead)
    response=client.post(url,headers=headers(2),json={'candidate_ids':['2']})
    assert response.status_code==200
    assert [r['id'] for r in response.json()['result']['items']]==['1','3']
    assert client.post(url,headers=headers(2),json={'candidate_ids':['2']}).status_code==200
    assert client.post(url,headers=headers(2),json={'candidate_ids':['1','3']}).json()['result']['items']==[]
    db.expire_all();assert workflow_people(db.get(Lead,lead.id))==before
    db.get(LeadContactScan,job.id).status='running';db.commit()
    assert client.post(url,headers=headers(2),json={'candidate_ids':['1']}).status_code==409
