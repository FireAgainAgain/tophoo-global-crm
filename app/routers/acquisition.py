"""Project-scoped API acquisition, persistent jobs, cooperative cancellation and review."""
import json
import hashlib
import hmac
from urllib.parse import quote
from base64 import urlsafe_b64encode
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.core.config import JWT_SECRET_KEY
from app.dependencies.auth import get_current_user, require_project_write
from app.models import AcquisitionConnection, AcquisitionConnectionTest, ProspectingJob, ProspectingCandidate, ProspectingEntry, Lead, SiteProject, User
from app.routers.customer import access, own, get_w, acquisition_job_data, acquisition_key, acquisition_existing_keys, AcquisitionJobPayload, AcquisitionCandidatePayload, clean
from app.services.acquisition_results import adopt_legacy_entries, non_company_reason, result_counts, merge_repeated_results
from app.services.company_type import save_company_type
from app.services.customer_social import COMPANY_SOCIAL_FIELDS, copy_company_social, save_company_social
from app.services.workflow_people import workflow_people, set_workflow_people
from app.services.acquisition_discovery import PROVIDERS, search, inspect_company, enrich_email, provider_json
from app.services.acquisition_filter import qualify

router=APIRouter(prefix='/api/acquisition/projects/{project_id}',tags=['Automatic acquisition'])
_cipher=Fernet(urlsafe_b64encode(hashlib.sha256(('acquisition-key:'+JWT_SECRET_KEY).encode()).digest()))

class ConnectionPayload(BaseModel):
    api_key: str | None=Field(default=None,max_length=1000)
    enabled: bool=True

class ConnectionTestPayload(BaseModel):
    api_key: str | None=Field(default=None,max_length=1000)

class TaskPayload(AcquisitionJobPayload):
    source: str=Field(default='serper',max_length=80)
    inspect_website: bool=True
    enrich_emails: bool=False
    enrichment_limit: int=Field(default=5,ge=1,le=20)
    auto_add: bool=False

class DeleteResultsPayload(BaseModel):
    ids: list[int]=Field(min_length=1,max_length=100)

class CandidateAction(BaseModel):
    ids: list[int]=Field(min_length=1,max_length=100)
    action: str=Field(pattern=r'^(import|ignore|to-leads)$')

def candidate_data(item,job):
    from app.services.customer_social import company_social_data
    return {'id':item.id,'job_id':job.id,'lead_id':item.lead_id,'source':job.source,
        'keyword':job.keyword or '', 'job_status':job.status, 'created_at':item.created_at.isoformat(),
        'company_address':item.company_address or '', 'company_name':item.company_name,'country':item.country or '', 'website':item.website or '',
        'company_type':item.company_type or '', 'contact_name':item.contact_name or '',
        'email':item.email or '', 'phone':item.phone or '', 'description':item.description or '',
        'contacts':workflow_people(item),**company_social_data(item),
        'status':item.status,'filter_reason':item.filter_reason or '', 'evidence':json.loads(item.evidence_json or '{}')}

@router.get('/results')
def all_results(project_id:int,owner_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    query=select(ProspectingCandidate,ProspectingJob).join(ProspectingJob,ProspectingJob.id==ProspectingCandidate.job_id).where(ProspectingJob.site_project_id==project_id)
    scoped=own(project_id,user,db)
    if scoped is None and owner_id is not None:scoped=owner_id
    if scoped is not None:query=query.where(ProspectingJob.owner_user_id==scoped)
    rows=db.execute(query.order_by(ProspectingCandidate.created_at.desc(),ProspectingCandidate.id.desc())).all()
    items=[candidate_data(item,job) for item,job in rows]
    return {'items':items,'counts':{status:sum(item['status']==status for item in items) for status in {'ready','pending_review','converted','filtered','duplicate','ignored'}}}

@router.post('/imports',status_code=201)
def import_results(project_id:int,payload:AcquisitionJobPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.routers.customer import create_acquisition_job
    access(project_id,user,db);require_project_write(project_id,user,db)
    # Reuse validation and audit creation, then retire the intermediate shortlist.
    payload.source='名单导入'
    result=create_acquisition_job(project_id,payload,user,db)
    adopt_legacy_entries(db,project_id)
    merge_repeated_results(db,project_id,user.id)
    job=db.get(ProspectingJob,result['id']);recount(db,job);db.commit()
    return acquisition_job_data(job)

@router.post('/records',status_code=201)
def create_record(project_id:int,payload:AcquisitionCandidatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    fingerprint=acquisition_key(payload.website,payload.company_name)
    if fingerprint in acquisition_existing_keys(db,project_id,candidate_owner_id=user.id):raise HTTPException(409,'该企业已有记录，请搜索并编辑原资料')
    reason=non_company_reason(payload.website)
    if reason:raise HTTPException(422,reason)
    job=ProspectingJob(site_project_id=project_id,owner_user_id=user.id,source='手动新增',keyword=payload.company_name,
        status='done',found_count=1,finished_at=datetime.now(),criteria_json=json.dumps({'manual':True,'processed':1,'phase':'手动新增'},ensure_ascii=False))
    db.add(job);db.flush()
    item=ProspectingCandidate(job_id=job.id,site_project_id=project_id,fingerprint=fingerprint,status='ready',filter_reason='手动新增企业，可直接转为线索')
    for key,value in payload.model_dump(exclude={'contacts','company_type',*COMPANY_SOCIAL_FIELDS}).items():setattr(item,key,clean(value))
    save_company_social(item,payload)
    save_company_type(item,payload)
    if payload.contacts is not None:set_workflow_people(item,payload.contacts)
    db.add(item);db.commit();db.refresh(item)
    return candidate_data(item,job)

@router.post('/results/delete')
def delete_all_results(project_id:int,payload:DeleteResultsPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    rows=db.scalars(select(ProspectingCandidate).where(ProspectingCandidate.site_project_id==project_id,ProspectingCandidate.id.in_(set(payload.ids))).with_for_update()).all()
    if len(rows)!=len(set(payload.ids)):raise HTTPException(404,'部分记录不存在')
    jobs={}
    for row in rows:
        job=get_w(db,ProspectingJob,project_id,row.job_id,own(project_id,user,db));jobs[job.id]=job
        if job.status in {'pending','running'}:raise HTTPException(409,'请先停止相关任务再删除结果')
    for row in rows:db.delete(row)
    for job in jobs.values():
        metadata=json.loads(job.criteria_json or '{}');metadata['deleted_count']=metadata.get('deleted_count',0)+sum(row.job_id==job.id for row in rows)
        job.criteria_json=json.dumps(metadata,ensure_ascii=False);recount(db,job)
    db.commit();return {'deleted_count':len(rows)}

def managed(project,user,db):
    access(project,user,db)

def provider_key(project,provider,db,user_id,include_disabled=False):
    definition=PROVIDERS.get(provider)
    if not definition:raise HTTPException(422,'该渠道尚未接入')
    connection=db.scalar(select(AcquisitionConnection).where(AcquisitionConnection.site_project_id==project,AcquisitionConnection.owner_user_id==user_id,AcquisitionConnection.provider==provider))
    if connection:
        if not connection.enabled and not include_disabled:return ''
        if connection.key_encrypted:
            try:return _cipher.decrypt(connection.key_encrypted.encode()).decode()
            except Exception:raise HTTPException(422,'连接密钥无法读取，请重新保存') from None
    return ''

def key_fingerprint(project,provider,key,user_id):
    return hmac.new(JWT_SECRET_KEY.encode(),json.dumps([project,user_id,provider,key]).encode(),hashlib.sha256).hexdigest()


def record_connection_test(project,provider,key,status,message,started_at,db,user_id):
    # Serialize result updates; a slower, earlier request must not replace a newer test.
    db.rollback()
    db.scalar(select(SiteProject).where(SiteProject.id==project).with_for_update())
    fingerprint=key_fingerprint(project,provider,key,user_id)
    row=db.scalar(select(AcquisitionConnectionTest).where(AcquisitionConnectionTest.site_project_id==project,AcquisitionConnectionTest.owner_user_id==user_id,AcquisitionConnectionTest.provider==provider,AcquisitionConnectionTest.key_fingerprint==fingerprint))
    now=datetime.now()
    if not row:
        row=AcquisitionConnectionTest(site_project_id=project,owner_user_id=user_id,provider=provider,key_fingerprint=fingerprint)
        db.add(row)
    elif row.started_at>started_at:
        db.commit();return now
    row.status=status;row.message=message[:500];row.started_at=started_at;row.tested_at=now
    db.commit();return now


def source_data(project,user,db):
    user_id=user.id
    can_manage=True
    results=[]
    for provider,definition in PROVIDERS.items():
        connection=db.scalar(select(AcquisitionConnection).where(AcquisitionConnection.site_project_id==project,AcquisitionConnection.owner_user_id==user_id,AcquisitionConnection.provider==provider))
        try:key=provider_key(project,provider,db,user_id,include_disabled=True)
        except HTTPException:key=''
        test=db.scalar(select(AcquisitionConnectionTest).where(AcquisitionConnectionTest.site_project_id==project,AcquisitionConnectionTest.owner_user_id==user_id,AcquisitionConnectionTest.provider==provider,AcquisitionConnectionTest.key_fingerprint==key_fingerprint(project,provider,key,user_id))) if key else None
        results.append({'test_status':test.status if test else 'untested','last_test_at':test.tested_at.isoformat() if test else None,'last_test_message':test.message if test else '',**{field:definition[field] for field in ('free_offer','requires_card','website_url','key_url','pricing_url','key_steps','cost_hint')},'checked_at':'2026-10-09','id':provider,'name':definition['name'],'kind':definition['kind'],'description':definition['description'],'configured':bool(key),'enabled':connection.enabled if connection else True,'key_masked':('••••'+key[-4:]) if key and can_manage else '', 'key_reveal_allowed':bool(can_manage and connection and connection.key_encrypted), 'origin':'我的连接' if connection else '未连接','max_candidates':20})
    return {'sources':results,'can_manage':can_manage,'project_id':project,'credential_scope':'user_project'}

@router.get('/sources')
def sources(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);return source_data(project_id,user,db)

@router.put('/connections/{provider}')
def save_connection(project_id:int,provider:str,payload:ConnectionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    managed(project_id,user,db)
    if provider not in PROVIDERS:raise HTTPException(422,'该渠道尚未接入')
    existing=db.scalar(select(AcquisitionConnection).where(AcquisitionConnection.site_project_id==project_id,AcquisitionConnection.owner_user_id==user.id,AcquisitionConnection.provider==provider))
    if not existing:existing=AcquisitionConnection(site_project_id=project_id,owner_user_id=user.id,provider=provider);db.add(existing)
    if payload.api_key and payload.api_key.strip():existing.key_encrypted=_cipher.encrypt(payload.api_key.strip().encode()).decode()
    elif not existing.key_encrypted:raise HTTPException(422,'请填写该平台 API Key')
    existing.enabled=payload.enabled;db.commit();return source_data(project_id,user,db)

@router.post('/connections/{provider}/reveal')
def reveal_connection(project_id:int,provider:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    managed(project_id,user,db)
    if provider not in PROVIDERS:raise HTTPException(422,'该渠道尚未接入')
    connection=db.scalar(select(AcquisitionConnection).where(AcquisitionConnection.site_project_id==project_id,AcquisitionConnection.owner_user_id==user.id,AcquisitionConnection.provider==provider))
    if not connection or not connection.key_encrypted:
        raise HTTPException(422,'你尚未保存该渠道的个人密钥')
    key=provider_key(project_id,provider,db,user.id,include_disabled=True)
    return JSONResponse({'api_key':key},headers={'Cache-Control':'no-store','Pragma':'no-cache'})

@router.post('/connections/{provider}/test')
def test_connection(project_id:int,provider:str,payload:ConnectionTestPayload | None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    managed(project_id,user,db)
    if provider not in PROVIDERS:raise HTTPException(422,'该渠道尚未接入')
    entered=(payload.api_key or '').strip() if payload else ''
    key=entered or provider_key(project_id,provider,db,user.id,include_disabled=True)
    if not key:raise HTTPException(422,'请填写你的 API Key，或先保存个人连接')
    started_at=datetime.now()
    label='当前输入的密钥' if entered else '已保存的密钥'
    try:
        if provider=='hunter':
            data=provider_json('https://api.hunter.io/v2/account?api_key='+quote(key),key,provider)
            if not isinstance(data.get('data'),dict):raise ValueError('Hunter 账户响应异常，请检查密钥和接口权限')
            message=label+'验证成功，Hunter 账户接口可用；未执行邮箱补全。'
            count=None
        else:
            rows=search(provider,key,'company',[],[],[],1)
            count=len(rows)
            message=label+'验证成功，搜索接口可用'+('（本次查询无结果）' if not count else '。')
    except ValueError as error:
        record_connection_test(project_id,provider,key,'failed',str(error),started_at,db,user.id)
        raise HTTPException(422,str(error)) from None
    tested_at=record_connection_test(project_id,provider,key,'success',message,started_at,db,user.id)
    return {'status':'success','tested_at':tested_at.isoformat(),'tested':'current_input' if entered else 'saved','result_count':count,'message':message+' 测试结果已保存；配置需单独保存。'}

@router.delete('/jobs/{job_id}')
def delete_job(project_id:int,job_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    job=get_w(db,ProspectingJob,project_id,job_id,own(project_id,user,db));db.refresh(job,with_for_update=True)
    if job.status in {'pending','running'}:raise HTTPException(409,'请先停止任务，再删除搜索记录')
    db.execute(delete(ProspectingCandidate).where(ProspectingCandidate.job_id==job.id))
    db.delete(job);db.commit();return {'deleted':True}

@router.post('/jobs/{job_id}/results/delete')
def delete_results(project_id:int,job_id:int,payload:DeleteResultsPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    job=get_w(db,ProspectingJob,project_id,job_id,own(project_id,user,db));db.refresh(job,with_for_update=True)
    if job.status in {'pending','running'}:raise HTTPException(409,'请等待任务结束或停止后删除结果')
    ids=set(payload.ids)
    rows=db.scalars(select(ProspectingCandidate).where(ProspectingCandidate.job_id==job.id,ProspectingCandidate.id.in_(ids)).with_for_update()).all()
    if len(rows)!=len(ids):raise HTTPException(404,'部分搜索结果不存在或不属于当前任务')
    for row in rows:db.delete(row)
    metadata=json.loads(job.criteria_json or '{}');metadata['deleted_count']=metadata.get('deleted_count',0)+len(rows)
    job.criteria_json=json.dumps(metadata,ensure_ascii=False)
    recount(db,job);db.commit();return {'deleted_count':len(rows)}

@router.get('/jobs/{job_id}')
def job_detail(project_id:int,job_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);return acquisition_job_data(get_w(db,ProspectingJob,project_id,job_id,own(project_id,user,db)))

@router.post('/jobs/{job_id}/cancel')
def cancel_job(project_id:int,job_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);job=get_w(db,ProspectingJob,project_id,job_id,own(project_id,user,db))
    db.refresh(job,with_for_update=True)
    if job.status in {'pending','running'}:job.status='cancelled';job.finished_at=datetime.now();db.commit()
    return acquisition_job_data(job)

def add_entry(db,job,candidate):
    db.add(entry:=ProspectingEntry(site_project_id=job.site_project_id,owner_user_id=job.owner_user_id,company_name=candidate.company_name,country=candidate.country,company_type=candidate.company_type,company_website=candidate.website,customer_source=job.source,source_type='自动获客',notes=candidate.description,contact_name=candidate.contact_name,email=candidate.email,phone=candidate.phone))
    set_workflow_people(entry,workflow_people(candidate));copy_company_social(entry,candidate);db.flush();candidate.prospecting_entry_id=entry.id;candidate.status='shortlisted';job.shortlisted_count+=1

@router.post('/tasks',status_code=202)
def start_task(project_id:int,payload:TaskPayload,background:BackgroundTasks,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    if payload.source not in PROVIDERS or PROVIDERS[payload.source]['kind']!='search':raise HTTPException(422,'请选择已接入的企业搜索渠道')
    if not (payload.keyword or '').strip():raise HTTPException(422,'请填写产品关键词')
    if payload.limit>20:raise HTTPException(422,'单次最多搜索 20 条候选，请分国家或行业运行')
    payload.auto_add=False
    key=provider_key(project_id,payload.source,db,user.id)
    if not key:raise HTTPException(422,'请先连接搜索渠道')
    hunter_key=provider_key(project_id,'hunter',db,user.id) if payload.enrich_emails else ''
    if payload.enrich_emails and not hunter_key:raise HTTPException(422,'邮箱补全需要连接 Hunter')
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    active=db.scalar(select(ProspectingJob.id).where(ProspectingJob.site_project_id==project_id,ProspectingJob.status.in_(['pending','running'])))
    if active:raise HTTPException(409,'已有任务执行中，请等待或停止后再开始')
    criteria=payload.model_dump(exclude={'candidates'});criteria.update({'phase':'等待执行','processed':0,'error':'','filter_version':'discovery-v2'})
    job=ProspectingJob(site_project_id=project_id,owner_user_id=user.id,source=PROVIDERS[payload.source]['name'],keyword=payload.keyword,target_countries=','.join(payload.target_countries),target_types=','.join(payload.target_types),criteria_json=json.dumps(criteria,ensure_ascii=False),status='pending',min_score=0)
    db.add(job);db.commit();db.refresh(job)
    background.add_task(run_task,job.id,payload.model_dump(exclude={'candidates'}),key,hunter_key)
    return acquisition_job_data(job)

def run_task(job_id,options,key,hunter_key='',session_factory=SessionLocal):
    """Commit each result so cancellation retains completed candidates."""
    with session_factory() as db:
        job=db.get(ProspectingJob,job_id)
        if not job or job.status=='cancelled':return
        def refresh(lock=False):
            db.rollback();db.expire_all()
            statement=select(ProspectingJob).where(ProspectingJob.id==job_id)
            return db.scalar(statement.with_for_update() if lock else statement)
        def progress(phase,processed=None,error=''):
            metadata=json.loads(job.criteria_json or '{}');metadata['phase']=phase
            if processed is not None:metadata['processed']=processed
            if error:metadata['error']=error
            job.criteria_json=json.dumps(metadata,ensure_ascii=False)
        try:
            job=refresh(True)
            if not job or job.status=='cancelled':return
            job.status='running';progress('搜索企业网页');db.commit()
            found=search(options['source'],key,options['keyword'],options['target_countries'],options['target_types'],options['target_industries'],options['limit'])
            job=refresh(True)
            if not job or job.status=='cancelled':return
            job.found_count=len(found);progress('整理企业官网资料');db.commit()
            existing=acquisition_existing_keys(db,job.site_project_id,candidate_owner_id=job.owner_user_id);seen=set();enriched=0
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures=[executor.submit(inspect_company,row) for row in found] if options['inspect_website'] else []
                for index,row in enumerate(found):
                    job=refresh()
                    if not job or job.status=='cancelled':
                        for future in futures:future.cancel()
                        return
                    data=futures[index].result() if futures else {**row,'evidence':{'source_url':row.get('source_url'),'identity_verified':False,'facts':[],'warnings':['未读取官网，需人工确认']}}
                    job=refresh()
                    if not job or job.status=='cancelled':
                        for future in futures:future.cancel()
                        return
                    fingerprint=acquisition_key(data.get('website'),data['company_name'])
                    if fingerprint in seen:
                        job=refresh(True)
                        if not job or job.status=='cancelled':return
                        job.duplicate_count+=1;progress('去重与整理',index+1);db.commit();continue
                    qualification={k:v for k,v in data.items() if k in AcquisitionCandidatePayload.model_fields}
                    if data.get('qualification_text'):qualification['description']=data['qualification_text']
                    status,reason=qualify(AcquisitionCandidatePayload(**qualification),options['target_countries'],options['target_types'],options['target_industries'],options['keyword'],options['exclude_keywords'],not data['evidence']['identity_verified'])
                    non_business=non_company_reason(data.get('source_url') or data.get('website'))
                    if non_business:status='filtered';reason=non_business
                    elif fingerprint in existing:status='duplicate';reason='与已有搜客结果、线索或客户重复'
                    elif status!='filtered':
                        if options['enrich_emails'] and enriched<options['enrichment_limit'] and data['evidence']['identity_verified'] and not data.get('email'):
                            enriched+=1
                            try:data=enrich_email(data,hunter_key)
                            except ValueError as error:data['evidence']['warnings'].append(str(error))
                        if status=='shortlisted':status='ready';reason='符合搜索条件，可核实后转为线索；尚未确认采购意向'
                    job=refresh(True)
                    if not job or job.status=='cancelled':return
                    if status=='duplicate':job.duplicate_count+=1
                    elif status=='filtered':job.filtered_count+=1
                    candidate=ProspectingCandidate(job_id=job.id,site_project_id=job.site_project_id,company_name=data['company_name'],website=data.get('website'),country=data.get('country'),company_type=data.get('company_type'),contact_name=data.get('contact_name'),email=data.get('email'),phone=data.get('phone'),description=data.get('description'),fingerprint=fingerprint,status=status,filter_reason=reason[:500],score=0,grade='',evidence_json=json.dumps(data['evidence'],ensure_ascii=False))
                    candidate.company_address=data.get('company_address')
                    if data.get('contacts') is not None:set_workflow_people(candidate,data['contacts'])
                    db.add(candidate)
                    if status=='ready' and options['auto_add']:add_entry(db,job,candidate);candidate.filter_reason='符合条件，按本次设置自动入清单';existing.add(fingerprint)
                    seen.add(fingerprint);progress('整理候选客户',index+1);db.commit()
            job=refresh(True)
            if job and job.status!='cancelled':
                job.status='done';job.finished_at=datetime.now();progress('任务完成')
                db.flush();merge_repeated_results(db,job.site_project_id,job.owner_user_id);recount(db,job);db.commit()
        except Exception as error:
            db.rollback();job=refresh(True)
            if job and job.status!='cancelled':
                job.status='failed';job.finished_at=datetime.now();progress('任务失败',error=str(error)[:300] if isinstance(error,ValueError) else '任务执行异常，请重试；已完成结果保留');db.commit()

@router.patch('/candidates/{candidate_id}')
def edit_candidate(project_id:int,candidate_id:int,payload:AcquisitionCandidatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    candidate=db.get(ProspectingCandidate,candidate_id)
    if not candidate or candidate.site_project_id!=project_id:raise HTTPException(404,'候选记录不存在')
    db.refresh(candidate,with_for_update=True)
    job=get_w(db,ProspectingJob,project_id,candidate.job_id,own(project_id,user,db))
    if job.status in {'pending','running'}:raise HTTPException(409,'任务仍在整理资料，请完成后编辑')
    if candidate.status=='converted':raise HTTPException(422,'已转为线索，请到线索列表维护')
    fingerprint=acquisition_key(payload.website,payload.company_name)
    if db.scalar(select(ProspectingCandidate.id).where(ProspectingCandidate.job_id==job.id,ProspectingCandidate.fingerprint==fingerprint,ProspectingCandidate.id!=candidate.id)):raise HTTPException(422,'该任务内已有相同企业')
    for name,value in payload.model_dump(exclude={'contacts','company_type',*COMPANY_SOCIAL_FIELDS}).items():setattr(candidate,name,clean(value))
    save_company_social(candidate,payload)
    save_company_type(candidate,payload)
    if payload.contacts is not None:set_workflow_people(candidate,payload.contacts)
    elif candidate.contacts_json is None:set_workflow_people(candidate,workflow_people(candidate))
    candidate.fingerprint=fingerprint
    reason=non_company_reason(payload.website)
    if reason:candidate.status='filtered';candidate.filter_reason=reason
    elif fingerprint in acquisition_existing_keys(db,project_id,exclude_candidate_id=candidate.id,candidate_owner_id=job.owner_user_id):candidate.status='duplicate';candidate.filter_reason='与已有业务记录重复'
    else:candidate.status='ready';candidate.filter_reason='已人工核实资料，可转为线索'
    evidence=json.loads(candidate.evidence_json or '{}');evidence['reviewed_at']=datetime.now().isoformat();evidence['reviewed_by']=user.id;candidate.evidence_json=json.dumps(evidence,ensure_ascii=False)
    recount(db,job);db.commit();return {'updated':True}

def recount(db,job):
    db.flush();items=db.scalars(select(ProspectingCandidate).where(ProspectingCandidate.job_id==job.id)).all()
    job.shortlisted_count=sum(item.status in {'shortlisted','converted'} for item in items);job.filtered_count=sum(item.status in {'filtered','ignored'} for item in items)
    counts=result_counts(db,job)
    job.duplicate_count=counts['collapsed_duplicates']+counts['duplicate']

@router.post('/candidates/actions')
def candidate_actions(project_id:int,payload:CandidateAction,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if payload.action == 'to-leads':
        require_project_write(project_id,user,db,"leads")
    access(project_id,user,db);require_project_write(project_id,user,db)
    db.scalar(select(SiteProject).where(SiteProject.id==project_id).with_for_update())
    changed=0;skipped=0;jobs={};existing=acquisition_existing_keys(db,project_id,include_candidates=False)
    for candidate_id in dict.fromkeys(payload.ids):
        candidate=db.get(ProspectingCandidate,candidate_id)
        if not candidate or candidate.site_project_id!=project_id:raise HTTPException(404,'候选记录不存在')
        db.refresh(candidate,with_for_update=True)
        job=get_w(db,ProspectingJob,project_id,candidate.job_id,own(project_id,user,db));jobs[job.id]=job
        if job.status in {'pending','running'}:raise HTTPException(409,'请等待任务结束再处理候选')
        if candidate.status not in {'ready','pending_review'}:skipped+=1;continue
        if payload.action=='ignore':candidate.status='ignored';candidate.filter_reason='已人工忽略'
        elif acquisition_key(candidate.website,candidate.company_name) in existing:candidate.status='duplicate';candidate.filter_reason='与已有业务记录重复'
        else:
            if candidate.status=='pending_review':raise HTTPException(422,'请先编辑核实待核实记录，再确认入清单')
            if payload.action=='to-leads':
                lead=Lead(site_project_id=project_id,owner_user_id=job.owner_user_id,company_name=candidate.company_name,
                    country=candidate.country,company_type=candidate.company_type,company_website=candidate.website,customer_source=job.source,
                    source_type='自主开发' if job.source=='手动新增' else '自动获客',notes=candidate.description)
                evidence=json.loads(candidate.evidence_json or '{}');lead.company_address=candidate.company_address or evidence.get('company_address')
                lead.customer_source=evidence.get('customer_source') or job.source
                lead.source_type=evidence.get('source_type') or lead.source_type
                set_workflow_people(lead,workflow_people(candidate));copy_company_social(lead,candidate)
                db.add(lead);db.flush();candidate.lead_id=lead.id
                if candidate.prospecting_entry_id:
                    entry=db.get(ProspectingEntry,candidate.prospecting_entry_id);candidate.prospecting_entry_id=None;db.flush()
                    if entry:db.delete(entry)
                candidate.status='converted';candidate.filter_reason='已转为线索，资料请在线索列表维护'
            else:
                add_entry(db,job,candidate);candidate.filter_reason='已确认进入搜客清单'
            existing.add(acquisition_key(candidate.website,candidate.company_name))
        changed+=1
    for job in jobs.values():recount(db,job)
    db.commit();return {'changed':changed,'skipped':skipped}


def recover_interrupted_tasks(db):
    """Called at startup: a stopped process cannot finish its in-memory jobs."""
    for job in db.scalars(select(ProspectingJob).where(ProspectingJob.status.in_(['pending','running']))).all():
        metadata=json.loads(job.criteria_json or '{}')
        if metadata.get('filter_version')!='discovery-v2':continue
        job.status='failed';job.finished_at=datetime.now()
        metadata.update(phase='任务中断',error='服务重启导致任务中断，已完成结果保留；请重新开始搜索')
        job.criteria_json=json.dumps(metadata,ensure_ascii=False)
    db.commit()
