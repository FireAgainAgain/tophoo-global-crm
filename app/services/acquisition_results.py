"""Unified prospect records, legacy adoption and transparent search accounting."""
import json
import re
from urllib.parse import urlsplit
from types import SimpleNamespace
from sqlalchemy import inspect, select, text
from app.models import ProspectingCandidate, ProspectingEntry, ProspectingJob, ProjectMember
from app.services.workflow_people import workflow_people, set_workflow_people
from app.services.customer_social import copy_company_social

def non_company_reason(url):
    parsed=urlsplit(url or '')
    host=(parsed.hostname or '').lower()
    if any(host==domain or host.endswith('.'+domain) for domain in ('wikipedia.org','wikihow.com')):
        return '百科或知识文章，不是企业官网'
    if host.endswith('.edu') or '.edu.' in host or re.search(r'\.ac\.[a-z]{2}$',host):
        return '学校或研究机构页面，不作为企业采购候选'
    if re.search(r'\.(pdf|docx?|pptx?)(?:$|/)',parsed.path,re.I):
        return '文档或实验资料，不是企业主页'
    return ''

def ensure_acquisition_results_schema(engine):
    with engine.begin() as connection:
        fields={c['name'] for c in inspect(connection).get_columns('crm_prospecting_candidates')}
        if 'lead_id' not in fields:connection.execute(text('ALTER TABLE crm_prospecting_candidates ADD COLUMN lead_id INTEGER NULL'))
        if 'company_address' not in fields:connection.execute(text('ALTER TABLE crm_prospecting_candidates ADD COLUMN company_address VARCHAR(500) NULL'))

def adopt_legacy_entries(db, project_id=None):
    """Move existing shortlist records into results, retaining edited facts and people."""
    query=select(ProspectingEntry).with_for_update()
    if project_id is not None:query=query.where(ProspectingEntry.site_project_id==project_id)
    for entry in db.scalars(query).all():
        candidate=db.scalar(select(ProspectingCandidate).where(ProspectingCandidate.prospecting_entry_id==entry.id))
        if candidate is None:
            from app.routers.customer import acquisition_key
            owner_id=entry.owner_user_id or db.scalar(select(ProjectMember.user_id).where(ProjectMember.site_project_id==entry.site_project_id,ProjectMember.is_active.is_(True)).order_by(ProjectMember.id))
            if owner_id is None:continue # Preserve unassigned records when no project member exists.
            job=ProspectingJob(site_project_id=entry.site_project_id,owner_user_id=owner_id,
                source='历史搜客资料',keyword=entry.company_name,status='done',found_count=1,shortlisted_count=0,
                created_at=entry.created_at,finished_at=entry.updated_at,
                criteria_json=json.dumps({'legacy_prospecting':True,'processed':1,'phase':'历史资料已合并'},ensure_ascii=False))
            db.add(job);db.flush()
            candidate=ProspectingCandidate(job_id=job.id,site_project_id=entry.site_project_id,
                company_name=entry.company_name,fingerprint=acquisition_key(entry.company_website,entry.company_name))
            db.add(candidate)
        candidate.company_name=entry.company_name;candidate.website=entry.company_website
        candidate.company_type=entry.company_type or candidate.company_type;candidate.country=entry.country;candidate.description=entry.notes;candidate.company_address=entry.company_address
        set_workflow_people(candidate,workflow_people(entry));copy_company_social(candidate,entry)
        evidence=json.loads(candidate.evidence_json or '{}')
        evidence.update(legacy_entry_id=entry.id,company_address=entry.company_address,
                       customer_source=entry.customer_source,source_type=entry.source_type)
        candidate.evidence_json=json.dumps(evidence,ensure_ascii=False)
        candidate.prospecting_entry_id=None;candidate.status='ready';candidate.filter_reason='原搜客清单资料，可直接转为线索'
        db.flush();db.delete(entry)
    db.flush()

def repair_historical_results(db):
    """Only reclassify clearly non-business pages; preserve their original source record."""
    for item in db.scalars(select(ProspectingCandidate)).all():
        if item.status in {'converted','shortlisted'}:continue
        evidence=json.loads(item.evidence_json or '{}')
        reason=non_company_reason(evidence.get('source_url') or item.website)
        if reason:
            item.status='filtered';item.filter_reason=reason
        if not evidence.get('reviewed_at') and evidence.get('pages') and '\n' in (item.description or '') and len(item.description)>1200:
            evidence['legacy_page_text']=item.description
            item.description=item.description.split('\n',1)[0][:1200]
            item.evidence_json=json.dumps(evidence,ensure_ascii=False)
        if item.company_name.strip().lower() in {'admin','administrator','wordpress','home','website','unknown'}:
            evidence['invalid_company_name']=item.company_name
            evidence['identity_verified']=False
            evidence.setdefault('warnings',[]).append('原名称是网页管理或站点文字，企业名称需人工核实')
            item.company_name=(urlsplit(item.website or '').hostname or '企业名称待核实')
            item.evidence_json=json.dumps(evidence,ensure_ascii=False)
        if item.status in {'ready','pending_review'} and not evidence.get('reviewed_at') and evidence.get('source_url'):
            from app.services.acquisition_filter import qualify
            metadata=json.loads(db.get(ProspectingJob,item.job_id).criteria_json or '{}')
            payload=SimpleNamespace(company_name=item.company_name,country=item.country,company_type=item.company_type,description=evidence.get('legacy_page_text') or item.description)
            state,why=qualify(payload,metadata.get('target_countries',metadata.get('countries',[])),metadata.get('target_types',metadata.get('types',[])),metadata.get('target_industries',metadata.get('industry',[])),metadata.get('keyword',''),metadata.get('exclude_keywords',metadata.get('exclude',[])),not evidence.get('identity_verified'))
            item.status='ready' if state=='shortlisted' else state
            item.filter_reason='符合搜索条件，可核实后转为线索；尚未确认采购意向' if state=='shortlisted' else why
        if item.company_type and item.company_type.strip().isdigit():
            evidence['invalid_company_type']=item.company_type
            item.company_type=None
            evidence.setdefault('warnings',[]).append('原客户类型不是有效的企业类型，已保留原值供核对')
            item.evidence_json=json.dumps(evidence,ensure_ascii=False)

def merge_repeated_results(db,project_id=None,owner_id=None):
    """Keep a canonical enterprise per owner; preserve every batch's audit row."""
    grouped={}
    query=select(ProspectingCandidate,ProspectingJob).join(ProspectingJob,ProspectingJob.id==ProspectingCandidate.job_id)
    if project_id is not None:query=query.where(ProspectingJob.site_project_id==project_id)
    if owner_id is not None:query=query.where(ProspectingJob.owner_user_id==owner_id)
    for item,job in db.execute(query):
        if item.status not in {'ready','pending_review','converted','duplicate'}:continue
        grouped.setdefault((item.site_project_id,job.owner_user_id,item.fingerprint),[]).append(item)
    for items in grouped.values():
        if len(items)<2:continue
        def priority(item):
            evidence=json.loads(item.evidence_json or '{}')
            return (item.status=='converted',bool(evidence.get('reviewed_at')),item.status=='ready',bool(evidence.get('identity_verified')),-item.id)
        canonical=max(items,key=priority)
        if canonical.status=='duplicate':continue
        sources=set(json.loads(canonical.evidence_json or '{}').get('additional_sources',[]))
        people=workflow_people(canonical)
        known={person['email'].casefold() for person in people if person['email']}
        for item in items:
            if item is canonical or item.status=='converted':continue
            evidence=json.loads(item.evidence_json or '{}')
            if evidence.get('source_url'):sources.add(evidence['source_url'])
            for person in workflow_people(item):
                if person['email'] and person['email'].casefold() not in known and len(people)<100:
                    people.append({**person,'is_primary':not people});known.add(person['email'].casefold())
            evidence['duplicate_of']=canonical.id
            item.evidence_json=json.dumps(evidence,ensure_ascii=False)
            item.status='duplicate';item.filter_reason='同一企业已保留在其他批次，重复来源记录保留'
        # Transferred records belong to the lead now; never mutate its historical snapshot.
        if canonical.status!='converted':set_workflow_people(canonical,people)
        evidence=json.loads(canonical.evidence_json or '{}');evidence['additional_sources']=sorted(sources)
        canonical.evidence_json=json.dumps(evidence,ensure_ascii=False)


def result_counts(db,job):
    states=list(db.scalars(select(ProspectingCandidate.status).where(ProspectingCandidate.job_id==job.id)))
    metadata=json.loads(job.criteria_json or '{}')
    processed=metadata.get('processed',job.found_count if job.status not in {'pending','running'} else len(states))
    deleted=metadata.get('deleted_count',0)
    collapsed=max(0,processed-len(states)-deleted)
    return {'raw':job.found_count,'stored':len(states),'processed':processed,'deleted':deleted,
        'collapsed_duplicates':collapsed,'ready':states.count('ready'),'pending_review':states.count('pending_review'),
        'converted':states.count('converted'),'filtered':states.count('filtered'),
        'duplicate':states.count('duplicate'),'ignored':states.count('ignored')}
