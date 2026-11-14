"""Owner-scoped asynchronous website scan and explicitly selected import."""
import hashlib
import json
from datetime import datetime, timedelta
from threading import BoundedSemaphore

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.dependencies.auth import get_current_user
from app.models import Lead, LeadContactScan, User
from app.routers.lead_development import scoped_lead
from app.services.lead_contact_scan import candidate_matches, merge_candidates, scan_site, website_url
from app.services.workflow_people import workflow_people, set_workflow_people

router = APIRouter(prefix='/api/customer-workflow/projects/{project_id}/leads/{lead_id}/contact-scans', tags=['Lead contact research'])
slots = BoundedSemaphore(3)


def contacts_version(people):
    return hashlib.sha256(json.dumps(people, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scan_data(job, lead):
    status = job.status
    progress = json.loads(job.progress_json)
    if status in ('pending', 'running') and job.updated_at < datetime.now() - timedelta(minutes=5):
        status = 'failed'
        progress = {**progress, 'message': '扫描已中断，请重新开始。'}
    people = workflow_people(lead)
    result = json.loads(job.result_json)
    for row in result.get('items',[]):
        row['matches'] = candidate_matches(row, people)
    return {'id':job.id, 'website':job.website, 'status':status, 'progress':progress, 'result':result, 'created_at':job.created_at.isoformat(), 'contacts':people, 'contacts_version':contacts_version(people)}


def get_scan(db, lead, scan_id):
    job = db.get(LeadContactScan, scan_id)
    if not job or job.lead_id != lead.id:
        raise HTTPException(404, '扫描记录不存在。')
    return job


def run_scan(scan_id):
    try:
        if not slots.acquire(blocking=False):
            with SessionLocal() as db:
                job = db.get(LeadContactScan, scan_id)
                if job:
                    job.status = 'failed'
                    job.progress_json = json.dumps({'message':'当前扫描任务较多，请稍后重试。'}, ensure_ascii=False)
                    db.commit()
            return
        try:
            with SessionLocal() as db:
                job = db.get(LeadContactScan, scan_id)
                if not job:
                    return
                lead = db.get(Lead, job.lead_id)
                if not lead:
                    return
                names = [p['contact_name'] for p in workflow_people(lead) if p['contact_name']]
                site = job.website
                job.status = 'running'
                db.commit()

            def progress(value):
                with SessionLocal() as db:
                    job = db.get(LeadContactScan, scan_id)
                    if not job:
                        raise ValueError('线索已删除。')
                    job.progress_json = json.dumps(value, ensure_ascii=False)
                    db.commit()

            result = scan_site(site, names, progress)
            with SessionLocal() as db:
                job = db.get(LeadContactScan, scan_id)
                if job:
                    job.result_json = json.dumps(result, ensure_ascii=False)
                    job.status = 'completed'
                    db.commit()
        finally:
            slots.release()
    except Exception as error:
        with SessionLocal() as db:
            job = db.get(LeadContactScan, scan_id)
            if job:
                job.status = 'failed'
                # Only our own bounded error messages are presented, never raw HTTP/parser errors.
                message = str(error) if isinstance(error, ValueError) and len(str(error)) < 180 else '扫描失败，网站可能限制读取，请稍后重试。'
                job.progress_json = json.dumps({'message':message}, ensure_ascii=False)
                db.commit()


class StartPayload(BaseModel):
    website: str = Field(default='', max_length=500)


class Choice(BaseModel):
    candidate_id: str = Field(max_length=10)
    target_index: int | None = Field(default=None, ge=0, le=99)


class ImportPayload(BaseModel):
    contacts_version: str = Field(min_length=64, max_length=64)
    choices: list[Choice] = Field(min_length=1, max_length=100)


class DiscardPayload(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=100)


@router.get('')
def latest_scan(project_id:int, lead_id:int, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db)
    job = db.scalar(select(LeadContactScan).where(LeadContactScan.lead_id == lead.id).order_by(LeadContactScan.id.desc()).limit(1))
    return scan_data(job, lead) if job else {'id':None, 'contacts':workflow_people(lead), 'contacts_version':contacts_version(workflow_people(lead))}


@router.post('', status_code=202)
def start_scan(project_id:int, lead_id:int, payload:StartPayload, background_tasks:BackgroundTasks, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db, True)
    if not (payload.website.strip() or lead.company_website):
        raise HTTPException(422, '请先填写公司官网。')
    try:
        site = website_url(payload.website or lead.company_website)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    job = db.scalar(select(LeadContactScan).where(LeadContactScan.lead_id == lead.id, LeadContactScan.status.in_(('pending','running')), LeadContactScan.updated_at > datetime.now()-timedelta(minutes=5)).order_by(LeadContactScan.id.desc()).limit(1))
    if job:
        return scan_data(job, lead)
    job = LeadContactScan(lead_id=lead.id, created_by_user_id=user.id, website=site)
    db.add(job)
    db.commit()
    db.refresh(job)
    data = scan_data(job, lead)
    background_tasks.add_task(run_scan, job.id)
    return data


@router.get('/{scan_id:int}')
def read_scan(project_id:int, lead_id:int, scan_id:int, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db)
    return scan_data(get_scan(db, lead, scan_id), lead)


@router.post('/{scan_id:int}/import')
def import_scan(project_id:int, lead_id:int, scan_id:int, payload:ImportPayload, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db, True)
    job = get_scan(db, lead, scan_id)
    if job.status != 'completed':
        raise HTTPException(409, '请等待扫描完成后再添加联系人。')
    people = workflow_people(lead)
    if contacts_version(people) != payload.contacts_version:
        raise HTTPException(409, '联系人已被修改，请关闭并重新打开查找窗口后再选择。')
    choices = [choice.model_dump() for choice in payload.choices]
    if len({choice['candidate_id'] for choice in choices}) != len(choices):
        raise HTTPException(422, '不能重复选择同一结果。')
    result = json.loads(job.result_json)
    try:
        merged, conflicts, applied = merge_candidates(people, result.get('items',[]), choices, result['scanned_at'])
        if conflicts:
            return {'saved':False, 'conflicts':conflicts}
        set_workflow_people(lead, merged)
        db.commit()
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {'saved':True, 'applied':len(applied), 'contacts_version':contacts_version(workflow_people(lead)), 'contacts':workflow_people(lead), 'result':scan_data(job,lead)['result']}


@router.post('/{scan_id:int}/discard')
def discard_results(project_id:int, lead_id:int, scan_id:int, payload:DiscardPayload, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db, True)
    job = get_scan(db,lead,scan_id)
    if job.status != 'completed':
        raise HTTPException(409,'请等待扫描完成后再删除结果。')
    result = json.loads(job.result_json)
    ids = set(payload.candidate_ids)
    result['items'] = [row for row in result.get('items',[]) if row['id'] not in ids]
    job.result_json = json.dumps(result,ensure_ascii=False)
    db.commit()
    return scan_data(job,lead)
