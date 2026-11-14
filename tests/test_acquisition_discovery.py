import json
from types import SimpleNamespace
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import AcquisitionConnection, ProspectingJob, ProspectingCandidate, ProspectingEntry
from app.routers import acquisition
from app.services import acquisition_discovery as discovery
from tests.test_global_access import db, headers

ROOT='/api/acquisition/projects/1'

def test_connection_encrypted_scoped_and_manager_only(db,monkeypatch):
    monkeypatch.delenv('ACQUISITION_SERPER_API_KEY',raising=False)
    client=TestClient(app)
    assert not next(s for s in client.get(ROOT+'/sources',headers=headers(2)).json()['sources'] if s['id']=='serper')['configured']
    response=client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'test-secret'})
    assert response.status_code==200
    assert 'test-secret' not in response.text
    connection=db.scalar(select(AcquisitionConnection))
    assert connection.key_encrypted!='test-secret'
    assert acquisition.provider_key(1,'serper',db,1)=='test-secret'
    assert not client.get('/api/acquisition/projects/2/sources',headers=headers(1)).json()['sources'][0]['configured']
    assert client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':None,'enabled':False}).status_code==200
    assert acquisition.provider_key(1,'serper',db,1)==''
    assert client.post(ROOT+'/tasks',headers=headers(1),json={'keyword':'heat exchanger'}).status_code==422


def create_task(db,monkeypatch,**options):
    TestClient(app).put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'fixture-key'})
    monkeypatch.setattr(acquisition,'run_task',lambda *args:None)
    response=TestClient(app).post(ROOT+'/tasks',headers=headers(1),json={'keyword':'heat exchanger','target_countries':['德国'],'target_types':['distributor'],**options})
    assert response.status_code==202,response.text
    return response.json()['id']

# Save the worker reference before endpoint tests replace its background invocation.
WORKER=acquisition.run_task

def run(db,monkeypatch,id,rows,auto_add=False,enrich=False):
    monkeypatch.setattr(acquisition,'search',lambda *args:rows)
    monkeypatch.setattr(acquisition,'inspect_company',lambda row:{**row,'evidence':{'identity_verified':row.get('verified',True),'facts':['官网企业资料'],'warnings':[]}})
    @contextmanager
    def session():yield db
    options={'source':'serper','keyword':'heat exchanger','target_countries':['德国'],'target_types':['distributor'],'target_industries':[],'exclude_keywords':[],'limit':20,'inspect_website':True,'enrich_emails':enrich,'enrichment_limit':5,'auto_add':auto_add}
    WORKER(id,options,'fixture-key','fixture-hunter',session)
    return db.get(ProspectingJob,id)


def company(host,**changes):return {'company_name':'Example heat exchanger distributor','website':'https://'+host,'country':'DE','company_type':'distributor',**changes}


def test_worker_review_edit_import_duplicate_and_ignore(db,monkeypatch):
    id=create_task(db,monkeypatch)
    # Duplicate search URLs and explicit mismatches are retained in accounting.
    job=run(db,monkeypatch,id,[company('a.test'),company('a.test'),company('b.test',country='US'),company('c.test',country=None,verified=False)])
    assert job.status=='done'
    assert (job.found_count,job.duplicate_count,job.filtered_count,job.shortlisted_count)==(4,1,1,0)
    assert not db.scalars(select(ProspectingEntry)).all()
    items=db.scalars(select(ProspectingCandidate).order_by(ProspectingCandidate.id)).all()
    assert [item.status for item in items]==['ready','filtered','pending_review']
    client=TestClient(app)
    assert client.post(ROOT+'/candidates/actions',headers=headers(1),json={'ids':[items[2].id],'action':'import'}).status_code==422
    response=client.patch(ROOT+'/candidates/'+str(items[2].id),headers=headers(1),json={'company_name':'Reviewed company','country':'Germany','company_type':'distributor','website':'https://c.test','description':'核实产品需求'})
    assert response.status_code==200
    assert client.post(ROOT+'/candidates/actions',headers=headers(1),json={'ids':[items[0].id,items[2].id],'action':'import'}).status_code==200
    assert len(db.scalars(select(ProspectingEntry)).all())==2
    assert client.post(ROOT+'/candidates/actions',headers=headers(1),json={'ids':[items[0].id],'action':'import'}).json()['changed']==0
    second=create_task(db,monkeypatch)
    run(db,monkeypatch,second,[company('a.test'),company('fresh.test')])
    other=db.scalars(select(ProspectingCandidate).where(ProspectingCandidate.job_id==second).order_by(ProspectingCandidate.id)).all()
    assert [item.status for item in other]==['duplicate','ready']
    assert client.post(ROOT+'/candidates/actions',headers=headers(1),json={'ids':[other[1].id],'action':'ignore'}).status_code==200
    assert db.get(ProspectingJob,second).filtered_count==1


def test_auto_add_skips_pending_and_existing_email_cost(db,monkeypatch):
    id=create_task(db,monkeypatch,auto_add=True)
    calls=[]
    monkeypatch.setattr(acquisition,'enrich_email',lambda *args:calls.append(args))
    job=run(db,monkeypatch,id,[company('a.test',email='sales@a.test'),company('b.test',verified=False)],True,True)
    assert job.status=='done' and job.shortlisted_count==1
    assert not calls
    assert len(db.scalars(select(ProspectingEntry)).all())==1


def test_cancellation_and_restart_recovery(db,monkeypatch):
    id=create_task(db,monkeypatch)
    client=TestClient(app)
    assert client.post(ROOT+'/tasks',headers=headers(1),json={'keyword':'coil'}).status_code==409
    assert client.post(ROOT+'/jobs/'+str(id)+'/cancel',headers=headers(1)).status_code==200
    monkeypatch.setattr(acquisition,'search',lambda *args:pytest.fail('Cancelled job must not search'))
    @contextmanager
    def session():yield db
    WORKER(id,{},'key',session_factory=session)
    second=create_task(db,monkeypatch)
    acquisition.recover_interrupted_tasks(db)
    assert db.get(ProspectingJob,second).status=='failed'
    assert '中断' in json.loads(db.get(ProspectingJob,second).criteria_json)['error']


def test_api_failure_does_not_leak_keys(db,monkeypatch):
    id=create_task(db,monkeypatch)
    monkeypatch.setattr(acquisition,'search',lambda *args:(_ for _ in ()).throw(RuntimeError('SECRET-KEY')))
    @contextmanager
    def session():yield db
    WORKER(id,{'source':'serper','keyword':'coil','target_countries':[],'target_types':[],'target_industries':[],'limit':20},'SECRET-KEY',session_factory=session)
    job=db.get(ProspectingJob,id)
    assert job.status=='failed' and 'SECRET-KEY' not in job.criteria_json


def test_extraction_preserves_facts_and_unknown_country():
    html='<script type="application/ld+json">'+json.dumps({'@type':'Organization','name':'Coil Co','address':{'addressCountry':'DE'}})+'</script><p>Heat exchanger distributor for HVAC</p><a href="/contact">Contact</a>'
    def reader(url):return url,html if url.endswith('/') else '<a href="mailto:sales@coil.test">Email</a>'
    result=discovery.inspect_company({'company_name':'Search title','website':'https://coil.test/product','description':'snippet'},reader)
    assert result['company_name']=='Coil Co' and result['country']=='DE' and result['email']=='sales@coil.test'
    assert result['company_type']=='distributor' and result['evidence']['identity_verified']
    unknown=discovery.inspect_company({'company_name':'Search title','website':'https://unknown.test'},lambda url:(url,'<meta property="og:site_name" content="Unknown Co">'))
    assert not unknown.get('country') and not unknown['evidence']['identity_verified']
    directory=discovery.inspect_company({'company_name':'Listing','website':'https://www.alibaba.com/x'},lambda url:pytest.fail('Directory must not be read'))
    assert not directory['evidence']['identity_verified']


def test_search_country_is_query_only_and_hunter_rejects_invalid(monkeypatch):
    calls=[]
    def request(url,key,provider,payload=None):
        calls.append((url,payload));return {'organic':[{'title':'Company','link':'https://coil.test','snippet':'HVAC'}]}
    monkeypatch.setattr(discovery,'provider_json',request)
    result=discovery.search('serper','key','heat exchanger',['英国','阿联酋'],['经销商'],[],10)
    assert 'united kingdom' in calls[0][1]['q'] and 'united arab emirates' in calls[0][1]['q']
    assert not result[0].get('country')
    monkeypatch.setattr(discovery,'provider_json',lambda *args:{'data':{'emails':[{'value':'bad@test.com','confidence':100,'verification':{'status':'invalid'}},{'value':'good@test.com','confidence':90,'verification':{'status':'valid'}}]}})
    assert discovery.enrich_email({'website':'https://test.com','evidence':{'facts':[]}},'key')['email']=='good@test.com'


@pytest.mark.parametrize('url',['http://127.0.0.1','http://169.254.169.254','file:///etc/passwd','https://user:pass@example.com'])
def test_private_and_nonweb_urls_rejected(url):
    with pytest.raises(ValueError):discovery.public_url(url)


def test_stop_during_search_prevents_inspection(db,monkeypatch):
    id=create_task(db,monkeypatch)
    def stopped_search(*args):
        db.get(ProspectingJob,id).status='cancelled';db.commit()
        return [company('a.test')]
    monkeypatch.setattr(acquisition,'search',stopped_search)
    monkeypatch.setattr(acquisition,'inspect_company',lambda *args:pytest.fail('Must not inspect after stop'))
    @contextmanager
    def session():yield db
    WORKER(id,{'source':'serper','keyword':'coil','target_countries':[],'target_types':[],'target_industries':[],'limit':20},'key',session_factory=session)
    assert db.get(ProspectingJob,id).status=='cancelled'
    assert not db.scalars(select(ProspectingCandidate)).all()


def test_failure_retains_completed_candidates(db,monkeypatch):
    id=create_task(db,monkeypatch)
    monkeypatch.setattr(acquisition,'search',lambda *args:[company('a.test'),company('b.test')])
    def inspect(row):
        if row['website'].endswith('b.test'):raise RuntimeError('fixture failure')
        return {**row,'evidence':{'identity_verified':True,'facts':[],'warnings':[]}}
    monkeypatch.setattr(acquisition,'inspect_company',inspect)
    @contextmanager
    def session():yield db
    options={'source':'serper','keyword':'heat exchanger','target_countries':['德国'],'target_types':['distributor'],'target_industries':[],'exclude_keywords':[],'limit':20,'inspect_website':True,'enrich_emails':False,'enrichment_limit':5,'auto_add':False}
    WORKER(id,options,'key',session_factory=session)
    assert db.get(ProspectingJob,id).status=='failed'
    assert len(db.scalars(select(ProspectingCandidate)).all())==1


@pytest.mark.parametrize('provider,body',[
    ('tavily',{'results':[{'title':'Coil Co','url':'https://coil.test','content':'HVAC distributor'}]}),
    ('exa',{'results':[{'title':'Coil Co','url':'https://coil.test'}]}),
    ('firecrawl',{'success':True,'data':{'web':[{'title':'Coil Co','url':'https://coil.test','description':'HVAC distributor'}]}}),
])
def test_free_search_adapters_and_cost_controls(monkeypatch,provider,body):
    calls=[]
    def request(url,key,name,payload=None):
        calls.append((url,key,name,payload));return body
    monkeypatch.setattr(discovery,'provider_json',request)
    rows=discovery.search(provider,'fixture','heat exchanger',['Germany'],['distributor'],[],20)
    assert len(rows)==1 and rows[0]['website']=='https://coil.test'
    assert not rows[0].get('country')
    payload=calls[0][3]
    if provider=='tavily':
        assert payload['search_depth']=='basic' and payload['max_results']==20
        assert payload['auto_parameters'] is False and payload['include_raw_content'] is False
    elif provider=='exa':
        assert payload['type']=='fast' and payload['category']=='company' and payload['numResults']==20
        assert 'contents' not in payload
    else:
        assert payload['limit']==20 and payload['sources']==['web']
        assert payload['domainTools'] is False and 'scrapeOptions' not in payload


@pytest.mark.parametrize('provider,header', [('tavily','Authorization'),('exa','X-api-key'),('firecrawl','Authorization')])
def test_search_request_authentication(monkeypatch,provider,header):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return b'{"results":[]}'
    requests=[]
    def open(request,timeout):requests.append(request);return Response()
    monkeypatch.setattr(discovery,'urlopen',open)
    discovery.provider_json('https://example.test/search','fixture-key',provider,{'query':'coil'})
    assert requests[0].get_header(header)==('Bearer fixture-key' if provider!='exa' else 'fixture-key')
    assert requests[0].get_header('Content-type')=='application/json'
    assert 'fixture-key' not in requests[0].full_url


def test_source_guides_and_new_channels_can_create_jobs(db,monkeypatch):
    client=TestClient(app)
    monkeypatch.setattr(acquisition,'run_task',lambda *args:None)
    for provider in ('tavily','exa','firecrawl'):
        response=client.put(ROOT+'/connections/'+provider,headers=headers(1),json={'api_key':'fixture-key'})
        assert response.status_code==200
        row=next(row for row in response.json()['sources'] if row['id']==provider)
        assert row['configured'] and len(row['key_steps'])==3 and row['key_url'].startswith('https://')
        assert row['requires_card'] is False and row['free_offer'] and row['checked_at']=='2026-10-09'
        task=client.post(ROOT+'/tasks',headers=headers(1),json={'source':provider,'keyword':'heat exchanger'})
        assert task.status_code==202,task.text
        assert client.post(ROOT+'/jobs/'+str(task.json()['id'])+'/cancel',headers=headers(1)).status_code==200


def test_unknown_and_enrichment_providers_cannot_search(monkeypatch):
    monkeypatch.setattr(discovery,'provider_json',lambda *args:pytest.fail('Do not call an unsupported provider'))
    for provider in ('hunter','unknown'):
        with pytest.raises(ValueError):discovery.search(provider,'key','coil',[],[],[])


def test_draft_test_does_not_save_and_blank_uses_disabled_saved_key(db,monkeypatch):
    client=TestClient(app);calls=[]
    monkeypatch.setattr(acquisition,'search',lambda provider,key,*args:calls.append(key) or [])
    assert client.post(ROOT+'/connections/serper/test',headers=headers(2)).status_code==422
    response=client.post(ROOT+'/connections/serper/test',headers=headers(1),json={'api_key':'draft-key'})
    assert response.status_code==200 and response.json()['tested']=='current_input'
    assert response.json()['result_count']==0 and calls==['draft-key']
    assert not db.scalars(select(AcquisitionConnection)).all()
    client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'stored-key','enabled':False})
    response=client.post(ROOT+'/connections/serper/test',headers=headers(1),json={'api_key':None})
    assert response.status_code==200 and response.json()['tested']=='saved' and calls[-1]=='stored-key'
    assert not db.scalar(select(AcquisitionConnection)).enabled
    client.post(ROOT+'/connections/serper/test',headers=headers(1),json={'api_key':'replacement-key'})
    assert calls[-1]=='replacement-key'
    assert acquisition.provider_key(1,'serper',db,1,include_disabled=True)=='stored-key'


def test_project_key_reveal_permission_cache_and_server_shared_key(db,monkeypatch):
    client=TestClient(app)
    client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'stored-key'})
    response=client.post(ROOT+'/connections/serper/reveal',headers=headers(1))
    assert response.status_code==200 and response.json()['api_key']=='stored-key'
    assert 'no-store' in response.headers['cache-control']
    assert client.post(ROOT+'/connections/serper/reveal',headers=headers(2)).status_code==422
    assert 'stored-key' not in client.get(ROOT+'/sources',headers=headers(1)).text
    monkeypatch.setenv('ACQUISITION_BRAVE_API_KEY','server-shared-key')
    shared=client.post(ROOT+'/connections/brave/reveal',headers=headers(1))
    assert shared.status_code==422 and 'server-shared-key' not in shared.text
    assert client.post('/api/acquisition/projects/2/connections/serper/reveal',headers=headers(1)).status_code==422


def test_hunter_probe_does_not_enrich_and_malformed_search_is_not_success(db,monkeypatch):
    monkeypatch.setattr(acquisition,'provider_json',lambda *args:{'data':{'requests':{'searches':{'available':50}}}})
    monkeypatch.setattr(acquisition,'enrich_email',lambda *args:pytest.fail('Connection test must not enrich'))
    response=TestClient(app).post(ROOT+'/connections/hunter/test',headers=headers(1),json={'api_key':'draft'})
    assert response.status_code==200 and '未执行邮箱补全' in response.json()['message']
    monkeypatch.setattr(discovery,'provider_json',lambda *args:{'message':'unknown error with fake secret'})
    with pytest.raises(ValueError,match='响应格式'):discovery.search('tavily','key','company',[],[],[],1)


@pytest.mark.parametrize('code,text',[(401,'密钥无效'),(403,'接口权限'),(402,'额度不足'),(429,'频率或额度限制')])
def test_connection_error_is_actionable_and_never_includes_key(monkeypatch,code,text):
    from urllib.error import HTTPError
    def failed(*args,**kwargs):raise HTTPError('https://example.test?api_key=SECRET',code,'SECRET',{},None)
    monkeypatch.setattr(discovery,'urlopen',failed)
    with pytest.raises(ValueError) as caught:discovery.provider_json('https://example.test?api_key=SECRET','SECRET','hunter')
    assert text in str(caught.value) and 'SECRET' not in str(caught.value)


def test_test_result_persists_and_is_bound_to_project_provider_and_key(db,monkeypatch):
    from app.models import AcquisitionConnectionTest
    client=TestClient(app)
    monkeypatch.delenv('ACQUISITION_SERPER_API_KEY',raising=False)
    monkeypatch.setattr(acquisition,'search',lambda *args:[])
    def source(project=1):
        return next(s for s in client.get(f'/api/acquisition/projects/{project}/sources',headers=headers(1)).json()['sources'] if s['id']=='serper')
    assert client.post(ROOT+'/connections/serper/test',headers=headers(1),json={'api_key':'draft-success'}).status_code==200
    assert source()['test_status']=='untested' and not source()['configured']
    saved=client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'draft-success'})
    assert saved.status_code==200
    assert source()['test_status']=='success' and source()['last_test_at']
    assert source(2)['test_status']=='untested'
    record=db.scalar(select(AcquisitionConnectionTest))
    assert record.key_fingerprint!='draft-success' and 'draft-success' not in source()['last_test_message']
    def failed(*args):raise ValueError('测试接口额度不足')
    monkeypatch.setattr(acquisition,'search',failed)
    # A failed draft must not replace the saved key's successful result.
    assert client.post(ROOT+'/connections/serper/test',headers=headers(1),json={'api_key':'different-draft'}).status_code==422
    assert source()['test_status']=='success'
    assert client.post(ROOT+'/connections/serper/test',headers=headers(1)).status_code==422
    assert source()['test_status']=='failed' and '额度不足' in source()['last_test_message']
    client.put(ROOT+'/connections/serper',headers=headers(1),json={'enabled':False})
    assert source()['test_status']=='failed' and not source()['enabled']
    client.put(ROOT+'/connections/serper',headers=headers(1),json={'api_key':'new-untested'})
    assert source()['test_status']=='untested' and source()['last_test_at'] is None


def test_older_completion_cannot_replace_newer_key_test(db):
    from datetime import datetime,timedelta
    now=datetime.now()
    acquisition.record_connection_test(1,'serper','key','failed','较新的失败',now,db,1)
    acquisition.record_connection_test(1,'serper','key','success','较早的成功',now-timedelta(seconds=1),db,1)
    from app.models import AcquisitionConnectionTest
    assert db.scalar(select(AcquisitionConnectionTest)).status=='failed'


def test_worker_with_existing_customers_deduplicates_company_fields(db,monkeypatch):
    from app.models import Customer,ProjectContact
    db.add_all([
        Customer(id=20,workspace_id=1,name='Buyer',company='Example heat exchanger distributor',company_website='https://www.existing.test/contact'),
        Customer(id=21,workspace_id=1,name='Another Buyer',company='Other project',company_website='https://other-project.test'),
        Customer(id=22,workspace_id=1,name='Person only',company=''),
    ])
    db.flush()
    db.add_all([ProjectContact(site_project_id=1,contact_id=20),ProjectContact(site_project_id=2,contact_id=21),ProjectContact(site_project_id=1,contact_id=22)])
    db.commit()
    id=create_task(db,monkeypatch)
    job=run(db,monkeypatch,id,[company('existing.test'),company('other-project.test'),company('new.test')])
    assert job.status=='done' and job.found_count==3 and job.duplicate_count==1
    items=db.scalars(select(ProspectingCandidate).order_by(ProspectingCandidate.id)).all()
    assert [item.status for item in items]==['duplicate','ready','ready']
    assert len(db.scalars(select(Customer)).all())==3


def test_delete_results_and_job_preserve_imported_business_and_counters(db,monkeypatch):
    id=create_task(db,monkeypatch)
    job=run(db,monkeypatch,id,[company('a.test'),company('a.test'),company('b.test'),company('c.test',country='US')],auto_add=True)
    rows=db.scalars(select(ProspectingCandidate).order_by(ProspectingCandidate.id)).all()
    client=TestClient(app)
    # Wrong task/project access must not remove records.
    wrong=client.post(f'/api/acquisition/projects/2/jobs/{id}/results/delete',headers=headers(1),json={'ids':[rows[0].id]})
    assert wrong.status_code==404
    assert client.delete(ROOT+f'/jobs/{id}',headers=headers(2)).status_code in (403,404)
    invalid=client.post(ROOT+f'/jobs/{id}/results/delete',headers=headers(1),json={'ids':[rows[0].id,999999]})
    assert invalid.status_code==404
    assert len(db.scalars(select(ProspectingCandidate)).all())==3
    response=client.post(ROOT+f'/jobs/{id}/results/delete',headers=headers(1),json={'ids':[rows[0].id]})
    assert response.status_code==200 and response.json()['deleted_count']==1
    db.refresh(job)
    assert job.found_count==4 and job.duplicate_count==1 and job.shortlisted_count==1 and job.filtered_count==1
    assert json.loads(job.criteria_json)['deleted_count']==1
    assert len(db.scalars(select(ProspectingEntry)).all())==2
    assert client.delete(ROOT+f'/jobs/{id}',headers=headers(1)).status_code==200
    assert not db.scalars(select(ProspectingCandidate)).all()
    assert not db.scalars(select(ProspectingJob)).all()
    assert len(db.scalars(select(ProspectingEntry)).all())==2


def test_running_search_cannot_be_deleted(db,monkeypatch):
    id=create_task(db,monkeypatch)
    client=TestClient(app)
    assert client.delete(ROOT+f'/jobs/{id}',headers=headers(1)).status_code==409
    assert client.post(ROOT+f'/jobs/{id}/results/delete',headers=headers(1),json={'ids':[1]}).status_code==409
    assert db.get(ProspectingJob,id)


def test_personal_search_keys_tests_and_billing_do_not_cross_users(db,monkeypatch):
    from app.models.acquisition import LegacyAcquisitionConnection
    client=TestClient(app);calls=[]
    db.add(LegacyAcquisitionConnection(site_project_id=1,provider='serper',key_encrypted=acquisition._cipher.encrypt(b'legacy-shared').decode()))
    db.commit();monkeypatch.setenv('ACQUISITION_SERPER_API_KEY','server-shared')
    def source(user):return next(s for s in client.get(ROOT+'/sources',headers=headers(user)).json()['sources'] if s['id']=='serper')
    assert not source(1)['configured'] and not source(2)['configured']
    assert client.post(ROOT+'/tasks',headers=headers(1),json={'keyword':'coil'}).status_code==422
    for user,key in [(1,'user-one'),(2,'user-two')]:
        assert client.put(ROOT+'/connections/serper',headers=headers(user),json={'api_key':key}).status_code==200
    monkeypatch.setattr(acquisition,'search',lambda provider,key,*args:calls.append(key) or [])
    assert client.post(ROOT+'/connections/serper/test',headers=headers(2)).status_code==200
    assert source(2)['test_status']=='success' and source(1)['test_status']=='untested'
    assert client.post(ROOT+'/connections/serper/reveal',headers=headers(1)).json()['api_key']=='user-one'
    assert client.post(ROOT+'/connections/serper/reveal',headers=headers(2)).json()['api_key']=='user-two'
    used=[];monkeypatch.setattr(acquisition,'run_task',lambda job,options,key,hunter:used.append(key))
    task=client.post(ROOT+'/tasks',headers=headers(2),json={'keyword':'coil'})
    assert task.status_code==202 and used==['user-two']
    client.post(ROOT+'/jobs/'+str(task.json()['id'])+'/cancel',headers=headers(2))
    task=client.post(ROOT+'/tasks',headers=headers(1),json={'keyword':'coil'})
    assert task.status_code==202 and used==['user-two','user-one']
    assert calls==['user-two']
