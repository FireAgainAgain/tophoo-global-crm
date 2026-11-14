"""Project-scoped prospect, lead, customer and customer-pool workflow."""
from app.services.local_clocks import add_local_clocks
from datetime import date, datetime
from hashlib import sha256
import json
import os
import re
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_access, require_project_write
from app.models import ContactRecord, Customer, CustomerPoolAudit, Lead, ProjectContact, ProjectMember, ProspectingCandidate, ProspectingEntry, ProspectingJob, Quotation, Rfq, SalesContract, SiteProject, User, WorkspaceMember
from app.services.lead_development import retain_conversion, remove_lead_development
from app.services.lead_contact_status import lead_status, set_lead_status
from app.models.lead_development import LeadConversionHistory, LeadInteraction
from app.services.followup_note import note_data
from app.services.rfq_ownership import transfer_open_rfqs
from app.services.follow_up import cancel_pending, transfer_pending
from app.models.follow_up import FollowUpPlan
from app.services.company_type import save_company_type
from app.services.customer_grades import GRADE_NAMES, PRODUCT_MATCH_NAMES
from app.services.country_names import chinese_country, country_hue, country_options
from app.services.customer_social import CompanySocialPayload, SOCIAL_FIELDS, company_social_data, save_company_social, copy_company_social
from app.services.workflow_people import workflow_people, set_workflow_people
from app.services.customer_people import PersonPayload, people_for, people_by_customer, person_data, save_people, save_legacy_primary, mutate_person
from app.services.acquisition_filter import qualify, terms, normalized

router = APIRouter(tags=["CRM customer workflow"])

def access(project_id, user, db):
    # The router-level dependency checks the exact sidebar module for every route.
    return require_project_access(project_id, user, db)
def clean(value): return (value.strip() if value else "") or None

def top_admin(project_id, user, db):
    if user.is_admin: return True
    project = db.get(SiteProject, project_id)
    wm = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == project.workspace_id, WorkspaceMember.user_id == user.id)) if project else None
    if wm and wm.role in {"owner", "admin"}: return True
    pm = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    return bool(pm and pm.role == "top_admin")

def own(project_id, user, db): return None if top_admin(project_id, user, db) else user.id
def owners(project_id, db):
    items = db.scalars(select(User).join(ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.site_project_id == project_id, ProjectMember.is_active.is_(True)).order_by(User.display_name, User.email)).all()
    return [{"id": x.id, "name": x.display_name or x.email} for x in items]
def owner_name(db, user_id):
    x = db.get(User, user_id) if user_id else None
    return (x.display_name or x.email) if x else "未分配"
def target_owner(project_id, wanted, user, db):
    if not top_admin(project_id, user, db): return user.id
    if wanted is None: return user.id
    if wanted not in {x["id"] for x in owners(project_id, db)}: raise HTTPException(422, "归属用户不是当前项目成员。")
    return wanted

class WorkflowPayload(CompanySocialPayload):
    is_manually_researched: bool | None = Field(default=None, strict=True)
    contacts: list[PersonPayload] | None = Field(default=None, max_length=100)
    company_name: str = Field(min_length=1, max_length=260)
    country: str | None = Field(default=None, max_length=120)
    company_website: str | None = Field(default=None, max_length=500)
    company_address: str | None = Field(default=None, max_length=500)
    customer_source: str | None = Field(default=None, max_length=160)
    source_type: str = Field(default="自主开发", max_length=40)
    notes: str | None = Field(default=None, max_length=20000)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=260)
    phone: str | None = Field(default=None, max_length=80)
    whatsapp: str | None = Field(default=None, max_length=80)
    other_channels: str | None = Field(default=None, max_length=5000)
    owner_user_id: int | None = None
    @field_validator("source_type")
    @classmethod
    def source_type_valid(cls, value):
        value = value.strip()
        if value.casefold().replace(" ", "") == "micrfq": return "MIC RFQ"
        return "RFQ" if value.casefold() == "rfq" else value
    @field_validator("company_name")
    @classmethod
    def company_name_valid(cls, value):
        value = clean(value)
        if not value: raise ValueError("请填写公司名称。")
        return value
    @field_validator("owner_user_id", mode="before")
    @classmethod
    def owner_user_id_valid(cls, value):
        if isinstance(value, str):
            text = value.strip()
            return int(text) if text.isdigit() else None
        return value
    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = clean(value)
        if value and ("@" not in value or value.startswith("@") or value.endswith("@")): raise ValueError("请输入有效的邮箱地址。")
        return value

class GradedWorkflowPayload(WorkflowPayload):
    grade: str | None = Field(default=None, max_length=20)

    @field_validator("grade")
    @classmethod
    def grade_valid(cls, value):
        value = clean(value)
        if value and value not in GRADE_NAMES: raise ValueError("分级仅支持 A、B、C、D、E。")
        return value

class LeadPayload(GradedWorkflowPayload):
    development_date: date | None = None


class LeadDevelopmentDatePayload(BaseModel):
    development_date: date | None


class CustomerPayload(GradedWorkflowPayload):
    product_category: str | None = Field(default=None, max_length=160)
    product_match: Literal['A','B','C','D'] | None = None
    @field_validator("product_match", mode="before")
    @classmethod
    def product_match_blank(cls,value): return None if value=="" else value
    transfer_followups: bool = True
    contacts: list[PersonPayload] | None = Field(default=None, max_length=100)
    deleted_contact_ids: list[int] = Field(default_factory=list, max_length=100)
class GradePayload(BaseModel):
    grade: Literal['A', 'B', 'C', 'D', 'E'] | None = Field(...)

class CustomerCategoryPayload(BaseModel):
    product_category: str | None = Field(..., max_length=160)


class CustomerWorkflowStatusPayload(BaseModel):
    workflow_status: Literal['following', 'won', 'quoting', 'inquiring', 'closed'] | None

class CustomerMatchPayload(BaseModel):
    product_match: Literal['A','B','C','D'] | None = Field(...)

class BatchPayload(BaseModel): ids: list[int] = Field(min_length=1, max_length=200)
class LeadConversionPayload(BatchPayload):
    @field_validator("ids")
    @classmethod
    def unique_ids(cls, values):
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise ValueError("请选择有效且不重复的线索。")
        return values
class ReleasePayload(BaseModel): reason: str = Field(min_length=1, max_length=5000)

class AcquisitionCandidatePayload(CompanySocialPayload):
    contacts: list[PersonPayload] | None = Field(default=None, max_length=100)
    company_name: str = Field(min_length=1, max_length=260)
    country: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=500)
    company_address: str | None = Field(default=None, max_length=500)
    company_type: str | None = Field(default=None, max_length=80)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=260)
    phone: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    @field_validator("company_name")
    @classmethod
    def company_required(cls, value):
        value = value.strip()
        if not value: raise ValueError("候选公司名称不能为空。")
        return value

class AcquisitionJobPayload(BaseModel):
    source: str = Field(default="名单导入", min_length=1, max_length=80)
    keyword: str | None = Field(default=None, max_length=260)
    target_countries: list[str] = Field(default_factory=list, max_length=30)
    target_types: list[str] = Field(default_factory=list, max_length=20)
    target_industries: list[str] = Field(default_factory=list, max_length=20)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=20, ge=1, le=100)
    candidates: list[AcquisitionCandidatePayload] = Field(default_factory=list, max_length=1000)
    @field_validator("target_countries", "target_types", "target_industries", "exclude_keywords")
    @classmethod
    def bounded_conditions(cls, values):
        values = terms(values)
        if len(",".join(values)) > 500: raise ValueError("每组搜索条件合计不能超过 500 字。")
        return values
class RestorePayload(BaseModel): owner_user_id: int | None = None

class LeadContactStatusPayload(BaseModel):
    is_contacted: bool = Field(strict=True)

class ManualResearchPayload(BaseModel):
    is_manually_researched: bool = Field(strict=True)

class LeadStatusPayload(BaseModel):
    workflow_status: Literal['unviewed', 'checking', 'ready', 'low_match', 'contacted', 'priority_developing', 'company_contacted', 'replied', 'unfit', 'checked']

def wd(item, db, reveal):
    data = {"id":item.id,"company_name":item.company_name,"country":item.country or "","company_website":item.company_website or "","company_address":item.company_address or "","customer_source":item.customer_source or "","source_type":item.source_type or "","notes":item.notes or "","contact_name":item.contact_name or "","email":item.email or "","phone":item.phone or "","whatsapp":item.whatsapp or "","other_channels":item.other_channels or "","created_at":item.created_at.isoformat(),"updated_at":item.updated_at.isoformat()}
    if isinstance(item, Lead):
        data["is_manually_researched"] = bool(item.is_manually_researched)
        data["development_date"] = item.development_date.isoformat() if item.development_date else None
        data['country'] = chinese_country(item.country) or ''
    data["added_at"] = item.created_at.isoformat()
    if isinstance(item, Lead):
        data["workflow_status"] = lead_status(item)
        data["grade"] = item.grade or ""
        data["is_contacted"] = data["workflow_status"] in ('contacted','priority_developing')
    data.update(company_social_data(item))
    data["company_type"] = item.company_type or ""
    data["contacts"] = workflow_people(item)
    if reveal: data.update(owner_user_id=item.owner_user_id, owner_name=owner_name(db,item.owner_user_id))
    return data
def cd(item, rel, db, reveal, people=None):
    data = {"id":item.id,"company_name":item.company or item.name,"company":item.company or "","name":item.name,"contact_name":item.name,"country":item.country or "","company_website":item.company_website or "","company_address":item.company_address or "","customer_source":rel.source or "","source":rel.source or "","source_type":item.source_type or "","notes":item.notes or "","email":item.email or "","phone":item.phone or "","whatsapp":item.whatsapp or "","other_channels":item.other_channels or "","grade":item.grade or "","product_match":item.product_match or "","product_category":item.product_category or "","status":rel.status or "active","release_reason":rel.release_reason or "","released_at":rel.released_at.isoformat() if rel.released_at else "","released_by_name":owner_name(db,rel.released_by_user_id) if rel.released_by_user_id else "","created_at":item.created_at.isoformat(),"updated_at":max(item.updated_at, rel.updated_at).isoformat()}
    data["is_manually_researched"] = bool(item.is_manually_researched)
    data["added_at"] = rel.created_at.isoformat()
    data["workflow_status"] = rel.workflow_status or ""
    data.update(company_social_data(item))
    data["company_type"] = item.company_type or ""
    data["contacts"] = [person_data(person) for person in (people if people is not None else people_for(db, item.id))]
    if not data['contacts'] and item.people_initialized:
        data.update(contact_name='', email='', phone='', whatsapp='', other_channels='')
    if reveal: data.update(owner_user_id=rel.owner_user_id, owner_name=owner_name(db,rel.owner_user_id))
    return data
def save_w(item,payload,owner_id):
    if isinstance(item, Lead):
        if payload.is_manually_researched is not None:
            item.is_manually_researched = payload.is_manually_researched
        if "grade" in payload.model_fields_set:
            item.grade = payload.grade
        if "development_date" in payload.model_fields_set:
            item.development_date = payload.development_date
    previous=workflow_people(item)
    save_company_social(item,payload)
    save_company_type(item,payload)
    item.company_name=payload.company_name.strip(); item.country=clean(payload.country); item.company_website=clean(payload.company_website); item.company_address=clean(payload.company_address); item.customer_source=clean(payload.customer_source); item.source_type=payload.source_type; item.notes=clean(payload.notes); item.contact_name=clean(payload.contact_name); item.email=payload.email; item.phone=clean(payload.phone); item.whatsapp=clean(payload.whatsapp); item.other_channels=clean(payload.other_channels); item.owner_user_id=owner_id
    if payload.contacts is not None: set_workflow_people(item, payload.contacts)
    else:
        primary={key:getattr(item,key,None) or '' for key in ('contact_name','email','phone','whatsapp')}
        primary.update(notes=item.other_channels or '',is_primary=True)
        old_primary=next((person for person in previous if person['is_primary']),{})
        primary.update({key:old_primary.get(key,'') for key in SOCIAL_FIELDS})
        set_workflow_people(item,[primary,*[person for person in previous if not person['is_primary']]])

def get_w(db,model,project_id,item_id,owner_id,lock=False):
    q=select(model).where(model.id==item_id,model.site_project_id==project_id)
    if owner_id is not None:q=q.where(model.owner_user_id==owner_id)
    if lock:q=q.with_for_update()
    x=db.scalar(q)
    if not x: raise HTTPException(404,"数据不存在，或不属于当前归属用户。")
    return x
def get_c(db,project_id,cid,owner_id,status="active",lock=False):
    if lock and db.get_bind().dialect.name == 'sqlite':
        db.execute(update(ProjectContact).where(
            ProjectContact.site_project_id==project_id, ProjectContact.contact_id==cid,
        ).values(id=ProjectContact.id, updated_at=ProjectContact.updated_at))
    q=select(Customer,ProjectContact).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id,Customer.id==cid)
    if owner_id is not None:q=q.where(ProjectContact.owner_user_id==owner_id)
    if status:q=q.where(ProjectContact.status==status)
    if lock:q=q.with_for_update()
    row=db.execute(q).first()
    if not row:raise HTTPException(404,"客户不存在，或不属于当前归属用户。")
    return row



def list_w(model,project_id,owner_id,user,db):
    access(project_id,user,db); admin=top_admin(project_id,user,db); scoped=owner_id if admin else user.id
    q=select(model).where(model.site_project_id==project_id).order_by(model.created_at.desc(),model.id.desc())
    if scoped is not None:q=q.where(model.owner_user_id==scoped)
    items=db.scalars(q).all()
    rows=[wd(x,db,admin) for x in items]
    if model is Lead:
        add_local_clocks(items, rows, project_id, db, 'leads')
        from sqlalchemy import func
        from app.models.mail import MailDelivery
        ids = [item.id for item in items]
        sent = dict(db.execute(select(MailDelivery.lead_id, func.count()).where(
            MailDelivery.site_project_id == project_id, MailDelivery.lead_id.in_(ids),
            MailDelivery.owner_user_id == user.id, MailDelivery.status == 'accepted'
        ).group_by(MailDelivery.lead_id)).all()) if ids else {}
        for row in rows:
            row['country_hue'] = country_hue(row['country'])
            row['activity_counts'] = {'outreach': sent.get(row['id'], 0)}
    return {"items":rows,"is_top_admin":admin,"owners":owners(project_id,db) if admin else [],**({'country_options':country_options()} if model is Lead else {})}

def acquisition_key(website, company_name):
    raw=(website or "").strip()
    if raw:
        parsed=urlsplit(raw if "://" in raw else f"https://{raw}")
        host=parsed.hostname or ""
        host=host.lower().removeprefix("www.")
        if host:return sha256(f"domain:{host}".encode()).hexdigest()
    name="".join(char for char in normalized(company_name) if char.isalnum())
    if not name: name=normalized(company_name)
    return sha256(f"company:{name}".encode()).hexdigest()

def acquisition_existing_keys(db, project_id, exclude_candidate_id=None, include_candidates=True, candidate_owner_id=None):
    entries=db.scalars(select(ProspectingEntry).where(ProspectingEntry.site_project_id==project_id)).all()
    leads=db.scalars(select(Lead).where(Lead.site_project_id==project_id)).all()
    customers=db.scalars(select(Customer).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id)).all()
    keys={acquisition_key(x.company_website,x.company_name) for x in [*entries,*leads]}
    keys.update(acquisition_key(x.company_website,x.company) for x in customers if x.company_website or x.company.strip())
    if include_candidates:
        query=select(ProspectingCandidate).join(ProspectingJob,ProspectingJob.id==ProspectingCandidate.job_id).where(ProspectingCandidate.site_project_id==project_id,ProspectingCandidate.status.in_(['ready','pending_review','converted','shortlisted']))
        if candidate_owner_id is not None:query=query.where(ProspectingJob.owner_user_id==candidate_owner_id)
        if exclude_candidate_id is not None:query=query.where(ProspectingCandidate.id!=exclude_candidate_id)
        keys.update(acquisition_key(item.website,item.company_name) for item in db.scalars(query))
    return keys

def acquisition_job_data(item):
    return {"id":item.id,"source":item.source,"keyword":item.keyword or "","target_countries":item.target_countries or "","target_types":item.target_types or "","criteria":json.loads(item.criteria_json or "{}"),"pending_count":max(0,item.found_count-item.shortlisted_count-item.filtered_count-item.duplicate_count),"status":item.status,"found_count":item.found_count,"shortlisted_count":item.shortlisted_count,"filtered_count":item.filtered_count,"duplicate_count":item.duplicate_count,"created_at":item.created_at.isoformat(),"finished_at":item.finished_at.isoformat() if item.finished_at else ""}

ACQUISITION_SOURCES = (
    {"id":"import","name":"名单导入","category":"导入","env":"","enabled":True,"description":"粘贴或导入你有权使用的客户名单。"},
    {"id":"serper","name":"Serper (Google)","category":"Web 搜索","env":"ACQUISITION_SERPER_API_KEY","enabled":True,"description":"通过 Serper 的 Google 搜索 API 发现企业官网。"},
    {"id":"brave","name":"Brave Search","category":"Web 搜索","env":"ACQUISITION_BRAVE_API_KEY","enabled":True,"description":"通过 Brave Search API 发现企业官网。"},
    {"id":"google_places","name":"Google Places","category":"地图企业","env":"ACQUISITION_GOOGLE_PLACES_API_KEY","enabled":False,"description":"预留给本地经销商、工程商和服务商搜索。"},
    {"id":"trade_data","name":"海关 / 贸易数据","category":"贸易数据","env":"ACQUISITION_TRADE_DATA_API_KEY","enabled":False,"description":"预留给已授权的贸易数据服务商。"},
    {"id":"hunter","name":"Hunter.io","category":"联系补全","env":"ACQUISITION_HUNTER_API_KEY","enabled":False,"description":"预留给企业邮箱验证与联系人补全。"},
)

def acquisition_sources():
    return [{**item,"configured":not item["env"] or bool(os.getenv(item["env"])),"max_candidates":100 if item["id"]=="import" else 20,"mode":"可执行" if item["enabled"] else "即将支持"} for item in ACQUISITION_SOURCES]

def external_acquisition_candidates(source, keyword, countries, types=(), industries=(), limit=20, api_key=None):
    group=lambda values: "(" + " OR ".join(values) + ")" if values else ""
    query=" ".join(filter(None,[keyword,group(countries),group(types),group(industries)])).strip()
    if not query:raise HTTPException(422,"外部搜索请至少填写产品关键词或目标国家。")
    try:
        if source=="Serper (Google)":
            key=api_key
            if not key:raise HTTPException(422,"Serper 请使用个人 API Key。")
            request=Request("https://google.serper.dev/search",data=json.dumps({"q":query,"num":min(limit,20)}).encode(),headers={"X-API-KEY":key,"Content-Type":"application/json"},method="POST")
            with urlopen(request,timeout=20) as response:data=json.load(response)
            rows=data.get("organic",[])
            return [AcquisitionCandidatePayload(company_name=(row.get("title") or row.get("link") or "")[:260],website=row.get("link"),description=row.get("snippet")) for row in rows if row.get("link")][:limit]
        if source=="Brave Search":
            key=api_key
            if not key:raise HTTPException(422,"Brave Search 请使用个人 API Key。")
            request=Request(f"https://api.search.brave.com/res/v1/web/search?{urlencode({'q':query,'count':min(limit,20)})}",headers={"X-Subscription-Token":key,"Accept":"application/json"})
            with urlopen(request,timeout=20) as response:data=json.load(response)
            rows=data.get("web",{}).get("results",[])
            return [AcquisitionCandidatePayload(company_name=(row.get("title") or row.get("url") or "")[:260],website=row.get("url"),description=row.get("description")) for row in rows if row.get("url")][:limit]
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502,f"{source} 搜索失败：{str(error)[:180]}") from error
    return []

@router.get("/api/customer-workflow/projects/{project_id}/auto-prospecting/sources")
def list_acquisition_sources(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    return {"sources":acquisition_sources()}

@router.get("/api/customer-workflow/projects/{project_id}/auto-prospecting/jobs")
def list_acquisition_jobs(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),owner_id:int|None=None):
    access(project_id,user,db); scoped=own(project_id,user,db)
    if scoped is None and owner_id is not None:scoped=owner_id
    q=select(ProspectingJob).where(ProspectingJob.site_project_id==project_id).order_by(ProspectingJob.created_at.desc(),ProspectingJob.id.desc())
    if scoped is not None:q=q.where(ProspectingJob.owner_user_id==scoped)
    return {"items":[acquisition_job_data(x) for x in db.scalars(q).all()]}

@router.get("/api/customer-workflow/projects/{project_id}/auto-prospecting/jobs/{job_id}/candidates")
def list_acquisition_candidates(project_id:int,job_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db); job=get_w(db,ProspectingJob,project_id,job_id,own(project_id,user,db))
    rows=db.scalars(select(ProspectingCandidate).where(ProspectingCandidate.job_id==job.id).order_by(ProspectingCandidate.id)).all()
    from app.services.acquisition_results import result_counts
    return {"job":{**acquisition_job_data(job),"result_counts":result_counts(db,job)},"items":[{"id":x.id,"job_id":x.job_id,"lead_id":x.lead_id,"source":job.source,"job_status":job.status,"created_at":x.created_at.isoformat(),"company_address":x.company_address or "","company_name":x.company_name,"country":x.country or "","website":x.website or "","company_type":x.company_type or "",**company_social_data(x),"contacts":workflow_people(x),"contact_name":x.contact_name or "","email":x.email or "","phone":x.phone or "","description":x.description or "","evidence":json.loads(x.evidence_json or "{}"),"status":x.status,"filter_reason":x.filter_reason or ""} for x in rows]}

@router.post("/api/customer-workflow/projects/{project_id}/auto-prospecting/jobs",status_code=201)
def create_acquisition_job(project_id:int,payload:AcquisitionJobPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db); owner_id=target_owner(project_id,None,user,db)
    countries=payload.target_countries; types=payload.target_types; industries=payload.target_industries; excluded=payload.exclude_keywords
    keyword=(payload.keyword or "").strip()
    source=next((item for item in acquisition_sources() if item["name"]==payload.source.strip()),None)
    if not source or not source["enabled"] or not source["configured"]:raise HTTPException(422,"请选择已配置且可执行的数据源。")
    if payload.limit>source["max_candidates"]:raise HTTPException(422,f"该数据源单次最多处理 {source['max_candidates']} 条候选；不保证入清单数量。")
    external=source["id"]!="import"
    if external:raise HTTPException(422,"外部搜索请使用个人数据源连接与自动获客任务接口。")
    if external and not keyword:raise HTTPException(422,"外部搜索请填写产品关键词。")
    candidates=(external_acquisition_candidates(source["name"],keyword,countries,types,industries,payload.limit) if external else payload.candidates)[:payload.limit]
    if not candidates:raise HTTPException(422,"没有可处理的候选数据；请导入名单，或选择已配置的 Web 搜索来源。")
    criteria={"keyword":keyword,"countries":countries,"types":types,"industry":industries,"exclude":excluded,"limit":payload.limit,"filter_version":"conditions-v1"}
    job=ProspectingJob(site_project_id=project_id,owner_user_id=owner_id,source=source["name"],keyword=keyword or None,target_countries=",".join(countries),target_types=",".join(types),criteria_json=json.dumps(criteria,ensure_ascii=False),min_score=0,status="running",found_count=len(candidates))
    db.add(job);db.flush()
    existing=acquisition_existing_keys(db,project_id); seen=set()
    for row in candidates:
        key=acquisition_key(row.website,row.company_name)
        if key in seen:
            job.duplicate_count+=1
            continue  # One audit row per identity; avoid the unique-key violation.
        status,reason=qualify(row,countries,types,industries,keyword,excluded,external)
        candidate=ProspectingCandidate(job_id=job.id,site_project_id=project_id,company_name=row.company_name.strip(),country=clean(row.country),website=clean(row.website),company_type=clean(row.company_type),contact_name=clean(row.contact_name),email=clean(row.email),phone=clean(row.phone),description=clean(row.description),fingerprint=key,score=0,grade="",status=status,filter_reason=reason)
        candidate.company_address=clean(row.company_address)
        save_company_social(candidate,row)
        if row.contacts is not None: set_workflow_people(candidate,row.contacts)
        if key in existing:
            candidate.status="duplicate";candidate.filter_reason="与搜客清单、线索或客户重复";job.duplicate_count+=1
        elif status=="filtered":
            job.filtered_count+=1
        elif status=="shortlisted":
            entry=ProspectingEntry(site_project_id=project_id,owner_user_id=owner_id,company_name=row.company_name.strip(),country=clean(row.country),company_website=clean(row.website),customer_source=payload.source.strip(),source_type="自动获客",notes=clean(row.description),contact_name=clean(row.contact_name),email=clean(row.email),phone=clean(row.phone))
            set_workflow_people(entry,workflow_people(candidate));copy_company_social(entry,candidate);db.add(entry);db.flush();candidate.prospecting_entry_id=entry.id;job.shortlisted_count+=1;existing.add(key)
        seen.add(key);db.add(candidate)
    job.status="done";job.finished_at=datetime.now();db.commit();db.refresh(job)
    return acquisition_job_data(job)

@router.get("/api/customer-workflow/projects/{project_id}/prospecting")
def lp(project_id:int,owner_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return list_w(ProspectingEntry,project_id,owner_id,user,db)
@router.get("/api/customer-workflow/projects/{project_id}/leads")
def ll(project_id:int,owner_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return list_w(Lead,project_id,owner_id,user,db)

@router.get("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}")
def read_lead(project_id: int, item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db)
    item = get_w(db, Lead, project_id, item_id, own(project_id, user, db))
    return wd(item, db, top_admin(project_id, user, db))

class LeadListExportPayload(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    scope: str = Field(default='', max_length=4000)


@router.post("/api/customer-workflow/projects/{project_id}/leads/export/xlsx")
def export_lead_results(project_id:int,payload:LeadListExportPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    admin=top_admin(project_id,user,db)
    ids=list(dict.fromkeys(payload.ids))
    query=select(Lead).where(Lead.site_project_id==project_id,Lead.id.in_(ids))
    if not admin:query=query.where(Lead.owner_user_id==user.id)
    found={item.id:item for item in db.scalars(query).all()}
    if len(found)!=len(ids):
        raise HTTPException(409,"部分线索已变更或无权访问，请刷新列表后重新检索导出。")
    followups = {}
    rows = db.execute(select(
        LeadInteraction.lead_id, LeadInteraction.channel, LeadInteraction.subject,
        LeadInteraction.content, LeadInteraction.content_translation,
    ).where(
        LeadInteraction.site_project_id == project_id,
        LeadInteraction.lead_id.in_(ids),
    ).order_by(LeadInteraction.id))
    for row in rows:
        followups.setdefault(row.lead_id, []).append(row)
    items = [{**wd(found[lead_id], db, admin),
              'followup': note_data(followups.get(lead_id, ()))['content']} for lead_id in ids]
    from app.services.lead_list_excel import export_lead_list_excel, MIME
    content=export_lead_list_excel(items,payload.scope)
    filename=quote(f"线索列表_检索结果_{datetime.now():%Y-%m-%d}.xlsx")
    return Response(content,media_type=MIME,headers={"Content-Disposition":f"attachment; filename*=UTF-8''{filename}"})

def write_w(model,project_id,payload,user,db,item_id=None,force_source=None):
    access(project_id,user,db); x=get_w(db,model,project_id,item_id,own(project_id,user,db)) if item_id else model(site_project_id=project_id)
    save_w(x,payload,target_owner(project_id,payload.owner_user_id,user,db));
    if force_source:x.source_type=force_source
    if not item_id:db.add(x)
    db.commit();db.refresh(x);return wd(x,db,top_admin(project_id,user,db))
@router.post("/api/customer-workflow/projects/{project_id}/prospecting",status_code=201)
def cp(project_id:int,payload:WorkflowPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return write_w(ProspectingEntry,project_id,payload,user,db,force_source="自主开发")
@router.put("/api/customer-workflow/projects/{project_id}/prospecting/{item_id}")
def up(project_id:int,item_id:int,payload:WorkflowPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return write_w(ProspectingEntry,project_id,payload,user,db,item_id)
@router.post("/api/customer-workflow/projects/{project_id}/leads",status_code=201)
def cl(project_id:int,payload:LeadPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return write_w(Lead,project_id,payload,user,db)


@router.patch("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}/development-date")
def change_lead_development_date(project_id: int, item_id: int, payload: LeadDevelopmentDatePayload,
                                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db)
    require_project_write(project_id, user, db, "leads")
    item = get_w(db, Lead, project_id, item_id, own(project_id, user, db), lock=True)
    item.development_date = payload.development_date
    db.commit()
    db.refresh(item)
    return wd(item, db, top_admin(project_id, user, db))


@router.patch("/api/customer-workflow/projects/{project_id}/leads/{item_id}/contact-status")
def update_lead_contact_status(project_id:int,item_id:int,payload:LeadContactStatusPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id, user, db, "leads")
    item=get_w(db,Lead,project_id,item_id,own(project_id,user,db))
    set_lead_status(item,'contacted' if payload.is_contacted else 'unviewed')
    db.commit();db.refresh(item)
    return wd(item,db,top_admin(project_id,user,db))
@router.patch("/api/customer-workflow/projects/{project_id}/leads/{item_id}/status")
def update_lead_status(project_id:int,item_id:int,payload:LeadStatusPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id, user, db, "leads")
    item=get_w(db,Lead,project_id,item_id,own(project_id,user,db))
    set_lead_status(item,payload.workflow_status)
    db.commit();db.refresh(item)
    return wd(item,db,top_admin(project_id,user,db))
@router.patch("/api/customer-workflow/projects/{project_id}/leads/{item_id}/grade")
def change_lead_grade(project_id:int,item_id:int,payload:GradePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id,user,db,"leads")
    item=get_w(db,Lead,project_id,item_id,own(project_id,user,db),lock=True)
    item.grade=payload.grade
    db.commit();db.refresh(item)
    return wd(item,db,top_admin(project_id,user,db))
@router.put("/api/customer-workflow/projects/{project_id}/leads/{item_id}")
def ul(project_id:int,item_id:int,payload:LeadPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return write_w(Lead,project_id,payload,user,db,item_id)
def delete_w(model,project_id,item_id,user,db):
    access(project_id,user,db);item=get_w(db,model,project_id,item_id,own(project_id,user,db))
    if model is Lead:
        remove_lead_development(db,[item.id])
        db.execute(update(ProspectingCandidate).where(ProspectingCandidate.lead_id==item.id).values(lead_id=None))
    db.delete(item);db.commit();return {"deleted":True}
@router.delete("/api/customer-workflow/projects/{project_id}/prospecting/{item_id}")
def dp(project_id:int,item_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return delete_w(ProspectingEntry,project_id,item_id,user,db)
@router.delete("/api/customer-workflow/projects/{project_id}/leads/{item_id}")
def dl(project_id:int,item_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):return delete_w(Lead,project_id,item_id,user,db)

def move_to_lead(db,x):
    lead=Lead(site_project_id=x.site_project_id,owner_user_id=x.owner_user_id,company_name=x.company_name,company_type=x.company_type,country=x.country,company_website=x.company_website,company_address=x.company_address,customer_source=x.customer_source,source_type=x.source_type,notes=x.notes,contact_name=x.contact_name,email=x.email,phone=x.phone,whatsapp=x.whatsapp,other_channels=x.other_channels);set_workflow_people(lead,workflow_people(x));copy_company_social(lead,x);db.add(lead)
    db.execute(update(ProspectingCandidate).where(ProspectingCandidate.prospecting_entry_id==x.id).values(prospecting_entry_id=None))
    db.delete(x);return lead
@router.post("/api/customer-workflow/projects/{project_id}/prospecting/{item_id:int}/to-leads")
def ptl(project_id:int,item_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);lead=move_to_lead(db,get_w(db,ProspectingEntry,project_id,item_id,own(project_id,user,db)));db.commit();db.refresh(lead);return wd(lead,db,top_admin(project_id,user,db))
@router.post("/api/customer-workflow/projects/{project_id}/prospecting/batch/to-leads")
def bptl(project_id:int,payload:BatchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);[move_to_lead(db,get_w(db,ProspectingEntry,project_id,i,own(project_id,user,db))) for i in payload.ids];db.commit();return {"moved":len(payload.ids)}
@router.post("/api/customer-workflow/projects/{project_id}/prospecting/batch/delete")
def bdp(project_id:int,payload:BatchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);[db.delete(get_w(db,ProspectingEntry,project_id,i,own(project_id,user,db))) for i in payload.ids];db.commit();return {"deleted":len(payload.ids)}


class LeadContactsPayload(BaseModel):
    model_config = {"extra": "forbid"}
    contacts: list[PersonPayload] = Field(max_length=100)
    version: str = Field(min_length=64, max_length=64)


def lead_contacts_data(item, db=None):
    people = workflow_people(item)
    data = {"contacts": people, "version": sha256(json.dumps(people, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    if db is not None:
        from app.services.lead_outreach_stats import outreach_stats
        data['outreach_stats'] = outreach_stats(db, item.site_project_id, item.id)
    return data


@router.get("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}/contacts")
def read_lead_contacts(project_id:int,item_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    return lead_contacts_data(get_w(db,Lead,project_id,item_id,own(project_id,user,db)),db)


@router.put("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}/contacts")
def save_lead_contacts(project_id:int,item_id:int,payload:LeadContactsPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db,"leads")
    item=get_w(db,Lead,project_id,item_id,own(project_id,user,db))
    if lead_contacts_data(item)['version'] != payload.version:
        raise HTTPException(409,"联系人已被更新，请关闭后重新打开，再修改。")
    from types import SimpleNamespace
    fields=('contacts_json','contact_name','email','phone','whatsapp','other_channels')
    original={key:getattr(item,key) for key in fields}
    draft=SimpleNamespace(**original)
    set_workflow_people(draft,payload.contacts)
    result=db.execute(update(Lead).where(Lead.id==item.id,Lead.site_project_id==project_id,
        *[getattr(Lead,key).is_(None) if value is None else getattr(Lead,key)==value for key,value in original.items()])
        .values(**{key:getattr(draft,key) for key in fields}).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback();raise HTTPException(409,"联系人已被更新，请关闭后重新打开，再修改。")
    db.commit();db.refresh(item)
    return lead_contacts_data(item,db)


@router.patch("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}/manual-research")
def mark_lead_manual_research(project_id:int,item_id:int,payload:ManualResearchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db,"leads")
    item=get_w(db,Lead,project_id,item_id,own(project_id,user,db),lock=True)
    item.is_manually_researched=payload.is_manually_researched
    db.commit();db.refresh(item)
    return wd(item,db,top_admin(project_id,user,db))

@router.patch("/api/contacts/projects/{project_id}/{customer_id:int}/manual-research")
def mark_customer_manual_research(project_id:int,customer_id:int,payload:ManualResearchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);require_project_write(project_id,user,db,"customer_list")
    item,rel=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    item.is_manually_researched=payload.is_manually_researched
    db.commit();db.refresh(item)
    return cd(item,rel,db,top_admin(project_id,user,db))

def conversion_website_host(value):
    """Malformed URLs must never fall back to an empty company fingerprint."""
    raw=(value or "").strip()
    if not raw:return None
    try:
        parsed=urlsplit(raw if "://" in raw else f"https://{raw}")
        host=parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http","https"} or not host or any(char.isspace() for char in host):return None
    host=host.casefold().removeprefix("www.").rstrip(".")
    shared={'facebook.com','linkedin.com','instagram.com','youtube.com','youtu.be','sites.google.com','made-in-china.com'}
    if host in shared:
        path=parsed.path.rstrip('/')
        return host+path if path else None
    return host or None

def conversion_match(db,project,x,lock=False):
    incoming=workflow_people(x)
    emails={person['email'].casefold() for person in incoming if person['email']}
    query=select(Customer).join(ProjectContact, ProjectContact.contact_id==Customer.id).where(
        ProjectContact.site_project_id==project.id, Customer.workspace_id==project.workspace_id)
    candidates=db.scalars(query.with_for_update() if lock else query).all()
    matches=[]
    grouped_people=people_by_customer(db,[customer.id for customer in candidates])
    incoming_host=conversion_website_host(x.company_website)
    for customer in candidates:
        website_match=bool(incoming_host and incoming_host==conversion_website_host(customer.company_website))
        existing_people=grouped_people[customer.id]
        known_emails={person.email.casefold() for person in existing_people if person.email}
        if customer.email:known_emails.add(customer.email.casefold())
        if website_match or emails & known_emails:matches.append(customer)
    if len(matches)>1:raise HTTPException(409,'官网或联系人邮箱对应多个客户，请先核实并合并重复客户。')
    c=matches[0] if matches else None
    if not c and any(normalized(customer.company)==normalized(x.company_name) for customer in candidates):
        raise HTTPException(409,'已有同名客户，请补充一致的公司官网或联系人邮箱后再转换。')
    r=db.scalar(select(ProjectContact).where(ProjectContact.site_project_id==project.id,ProjectContact.contact_id==c.id)) if c else None
    if r and r.owner_user_id!=x.owner_user_id:
        raise HTTPException(409,'该企业已有其他负责人，请先协调客户归属，避免自动覆盖。')
    if r and r.status=='pool':
        raise HTTPException(409,'该企业已在客户公池，请先恢复客户，再转换线索。')
    return c,r

def lead_to_customer(db,project,x,actor_id=None):
    # SQLite ignores FOR UPDATE. Acquire its write lock before matching and creating.
    if db.get_bind().dialect.name == 'sqlite':
        db.execute(update(SiteProject).where(SiteProject.id==project.id).values(id=SiteProject.id))
    else:
        db.scalar(select(SiteProject.id).where(SiteProject.id==project.id).with_for_update())
    if db.get(Lead, x.id, populate_existing=True) is None:
        raise HTTPException(404, '线索已被转换或删除，请刷新列表。')
    incoming=workflow_people(x)
    c,r=conversion_match(db,project,x,lock=True)
    mode='merged' if c else 'created'
    if not c:
        c=Customer(workspace_id=project.workspace_id,name=x.company_name,company=x.company_name)
        db.add(c);db.flush()
    if not c.grade and x.grade:
        c.grade=x.grade
    for key,source in [('company_type','company_type'),('company_website','company_website'),('company_address','company_address'),('country','country'),('source_type','source_type'),('notes','notes')]:
        if not getattr(c,key):setattr(c,key,getattr(x,source))
    c.is_manually_researched = bool(c.is_manually_researched or x.is_manually_researched)
    if not c.people_initialized and (c.email or c.phone or c.whatsapp or c.name!=c.company):save_legacy_primary(db,c)
    copy_company_social(c,x,fill_only=True)
    existing=people_for(db,c.id)
    payloads=[]
    for person in incoming:
        match=next((old for old in existing if person['email'] and old.email and old.email.casefold()==person['email'].casefold()),None)
        if not match:
            phone=lambda value:re.sub(r'[\s()\-]','',value or '')
            candidates=[old for old in existing if person['phone'] and phone(old.phone)==phone(person['phone']) and (old.contact_name or '').strip().casefold()==person['contact_name'].strip().casefold() and (not person['email'] or not old.email)]
            if len(candidates)>1:raise HTTPException(409,'同名联系人及电话对应多条记录，请先核实后再转换。')
            match=candidates[0] if candidates else None
        if match:
            for key in ('contact_name','email','phone','whatsapp','notes',*SOCIAL_FIELDS):
                if not getattr(match,key) and person[key]:setattr(match,key,person[key])
        else:
            payloads.append(PersonPayload(**{**person,'is_primary':not existing and not payloads}))
    if payloads:
        primary=next((old for old in existing if old.primary_slot==1),None)
        if primary:payloads.insert(0,PersonPayload(**person_data(primary)))
        save_people(db,c,payloads)
    else:
        from app.services.customer_people import sync_primary
        sync_primary(c,next((old for old in existing if old.primary_slot==1),None))
    if not r:
        r=ProjectContact(site_project_id=project.id,contact_id=c.id,owner_user_id=x.owner_user_id,source=x.customer_source,status='active');db.add(r)
    r.updated_at=datetime.now()
    db.execute(update(ProspectingCandidate).where(ProspectingCandidate.lead_id==x.id).values(lead_id=None))

    retain_conversion(db,project,x,c,actor_id,mode)
    db.delete(x);db.flush();return c
@router.post("/api/customer-workflow/projects/{project_id}/leads/{item_id:int}/to-customers")
def ltc(project_id:int,item_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=access(project_id,user,db);require_project_write(project_id, user, db, "leads")
    try:
        c=lead_to_customer(db,project,get_w(db,Lead,project_id,item_id,own(project_id,user,db),lock=True),user.id)
        db.commit();return {"customer_id":c.id}
    except Exception:
        db.rollback();raise
@router.post("/api/customer-workflow/projects/{project_id}/leads/batch/to-customers")
def bltc(project_id:int,payload:LeadConversionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=access(project_id,user,db);require_project_write(project_id, user, db, "leads")
    try:
        owner=own(project_id,user,db)
        # Check and lock every selected lead before modifying any customer.
        leads={i:get_w(db,Lead,project_id,i,owner,lock=True) for i in sorted(payload.ids)}
        for i in payload.ids:lead_to_customer(db,project,leads[i],user.id)
        db.commit();return {"moved":len(payload.ids)}
    except Exception:
        db.rollback();raise
@router.post("/api/customer-workflow/projects/{project_id}/leads/batch/delete")
def bdl(project_id:int,payload:BatchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);[get_w(db,Lead,project_id,i,own(project_id,user,db)) for i in payload.ids];db.execute(update(ProspectingCandidate).where(ProspectingCandidate.lead_id.in_(payload.ids)).values(lead_id=None));remove_lead_development(db,payload.ids);[db.delete(get_w(db,Lead,project_id,i,own(project_id,user,db))) for i in payload.ids];db.commit();return {"deleted":len(payload.ids)}

def save_c(x,p):
    if "product_category" in p.model_fields_set: x.product_category=clean(p.product_category)
    if "product_match" in p.model_fields_set: x.product_match=p.product_match
    if p.is_manually_researched is not None: x.is_manually_researched = p.is_manually_researched
    save_company_social(x,p)
    save_company_type(x,p)
    x.name=clean(p.contact_name) or p.company_name.strip();x.company=p.company_name.strip();x.company_id=None;x.country=clean(p.country);x.company_website=clean(p.company_website);x.company_address=clean(p.company_address);x.source_type=p.source_type;x.notes=clean(p.notes);x.email=p.email;x.phone=clean(p.phone);x.whatsapp=clean(p.whatsapp);x.other_channels=clean(p.other_channels)
    if "grade" in p.model_fields_set: x.grade=p.grade
@router.get("/api/contacts/projects/{project_id}")
def lc(project_id:int,owner_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);admin=top_admin(project_id,user,db);scoped=owner_id if admin else user.id;q=select(Customer,ProjectContact).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id,ProjectContact.status.is_distinct_from("pool")).order_by(ProjectContact.created_at.desc(),ProjectContact.id.desc())
    if scoped is not None:q=q.where(ProjectContact.owner_user_id==scoped)
    rows=db.execute(q).all();people=people_by_customer(db,[c.id for c,r in rows])
    upcoming = {}
    tasks = db.scalars(select(FollowUpPlan).where(FollowUpPlan.site_project_id==project_id,FollowUpPlan.customer_id.in_([c.id for c,r in rows]),FollowUpPlan.status=='pending').order_by(FollowUpPlan.due_at,FollowUpPlan.id)).all() if rows else []
    for task in tasks:
        if task.owner_user_id!=user.id:continue
        upcoming.setdefault(task.customer_id,{'id':task.id,'title':task.title,'due_at':task.due_at.isoformat()+'Z'})
    customers = [{**cd(c,r,db,admin,people[c.id]),'next_followup':upcoming.get(c.id)} for c,r in rows]
    from app.services.customer_activity import activity_counts
    counts, statuses, documents = activity_counts(db, project_id, [c.id for c,r in rows], user, with_statuses=True)
    for customer in customers:
        customer['country_hue'] = country_hue(customer['country'])
        customer['activity_counts'] = counts[customer['id']]
        customer['activity_statuses'] = statuses[customer['id']]
        customer['activity_documents'] = documents[customer['id']]
    add_local_clocks([c for c,r in rows], customers, project_id, db, 'customers')
    return {"customers":customers,"is_top_admin":admin,"owners":owners(project_id,db) if admin else []}
@router.get('/api/contacts/projects/{project_id}/{customer_id}/documents/{kind}')
def customer_documents(project_id: int, customer_id: int, kind: Literal['rfqs', 'quotations'], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.dependencies.auth import require_project_module
    from app.models import Quotation
    require_project_module(project_id, user, db, 'customer_list')
    customer, relation = get_c(db, project_id, customer_id, own(project_id, user, db))
    require_project_module(project_id, user, db, 'rfq' if kind == 'rfqs' else 'quotations')
    model, column = (Rfq, Rfq.contact_id) if kind == 'rfqs' else (Quotation, Quotation.customer_id)
    items = db.scalars(select(model).where(model.site_project_id == project_id,
        column == customer_id, model.owner_user_id == user.id).order_by(model.id.desc())).all()
    return {'customer_id': customer_id, 'company_name': customer.company, 'items': [
        {'id': item.id, 'number': item.number, 'status': item.status,
         'date': str((item.inquiry_date if kind == 'rfqs' else item.quote_date) or ''),
         'description': (item.application or '') if kind == 'rfqs' else item.buyer_company}
        for item in items]}


@router.post("/api/contacts/projects/{project_id}",status_code=201)
def cc(project_id:int,payload:CustomerPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id, user, db, "customer_list")
    project=access(project_id,user,db);x=Customer(workspace_id=project.workspace_id);save_c(x,payload);db.add(x);db.flush();r=ProjectContact(site_project_id=project_id,contact_id=x.id,owner_user_id=target_owner(project_id,payload.owner_user_id,user,db),source=clean(payload.customer_source),status="active");db.add(r)
    if payload.contacts is not None:save_people(db,x,payload.contacts,payload.deleted_contact_ids)
    else:save_legacy_primary(db,x)
    db.commit();db.refresh(x);db.refresh(r);return cd(x,r,db,top_admin(project_id,user,db))
@router.put("/api/contacts/projects/{project_id}/{customer_id}")
def uc(project_id:int,customer_id:int,payload:CustomerPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id, user, db, "customer_list")
    access(project_id,user,db);x,r=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    new_owner = r.owner_user_id
    if payload.owner_user_id is not None and payload.owner_user_id != new_owner:
        new_owner = target_owner(project_id,payload.owner_user_id,user,db)
    if new_owner!=r.owner_user_id:
        transfer_pending(db,project_id,customer_id,new_owner,payload.transfer_followups)
        transfer_open_rfqs(db,project_id,customer_id,new_owner)
        transfer_customer_quotes(db,project_id,customer_id,new_owner)
    save_c(x,payload);r.source=clean(payload.customer_source);r.owner_user_id=new_owner
    if payload.contacts is not None:save_people(db,x,payload.contacts,payload.deleted_contact_ids)
    else:save_legacy_primary(db,x)
    r.updated_at=datetime.now()
    db.commit();db.refresh(x);db.refresh(r);return cd(x,r,db,top_admin(project_id,user,db))

@router.patch('/api/contacts/projects/{project_id}/{customer_id:int}/grade')
def change_customer_grade(project_id:int,customer_id:int,payload:GradePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id,user,db,'customer_list')
    item,relation=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    item.grade=payload.grade
    db.commit();db.refresh(item)
    return cd(item,relation,db,top_admin(project_id,user,db))


@router.patch('/api/contacts/projects/{project_id}/{customer_id:int}/workflow-status')
def change_customer_workflow_status(project_id: int, customer_id: int, payload: CustomerWorkflowStatusPayload,
                                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db)
    require_project_write(project_id, user, db, 'customer_list')
    item, relation = get_c(db, project_id, customer_id, own(project_id, user, db), lock=True)
    relation.workflow_status = payload.workflow_status
    db.commit()
    db.refresh(relation)
    return cd(item, relation, db, top_admin(project_id, user, db))


@router.patch('/api/contacts/projects/{project_id}/{customer_id:int}/product-category')
def change_customer_category(project_id:int,customer_id:int,payload:CustomerCategoryPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id,user,db,'customer_list')
    item,relation=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    item.product_category=clean(payload.product_category)
    db.commit();db.refresh(item)
    return cd(item,relation,db,top_admin(project_id,user,db))


@router.patch('/api/contacts/projects/{project_id}/{customer_id:int}/product-match')
def change_customer_match(project_id:int,customer_id:int,payload:CustomerMatchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    require_project_write(project_id,user,db,'customer_list')
    item,relation=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    item.product_match=payload.product_match
    db.commit();db.refresh(item)
    return cd(item,relation,db,top_admin(project_id,user,db))


def change_customer_person(project_id,customer_id,user,db,operation,person_id=None,payload=None,replacement_id=None):
    access(project_id,user,db)
    require_project_write(project_id, user, db, "customer_list")
    x,r=get_c(db,project_id,customer_id,own(project_id,user,db),status=None,lock=True)
    if r.status == 'pool':raise HTTPException(409,'请先恢复客户，再管理联系人。')
    mutate_person(db,x,operation,person_id,payload,replacement_id)
    r.updated_at=datetime.now()
    db.commit();db.refresh(x);db.refresh(r)
    return cd(x,r,db,top_admin(project_id,user,db))

@router.post('/api/contacts/projects/{project_id}/{customer_id}/people',status_code=201)
def add_customer_person(project_id:int,customer_id:int,payload:PersonPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return change_customer_person(project_id,customer_id,user,db,'add',payload=payload)

@router.put('/api/contacts/projects/{project_id}/{customer_id}/people/{person_id}')
def edit_customer_person(project_id:int,customer_id:int,person_id:int,payload:PersonPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return change_customer_person(project_id,customer_id,user,db,'edit',person_id,payload)

@router.post('/api/contacts/projects/{project_id}/{customer_id}/people/{person_id}/primary')
def set_customer_primary(project_id:int,customer_id:int,person_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return change_customer_person(project_id,customer_id,user,db,'primary',person_id)

@router.delete('/api/contacts/projects/{project_id}/{customer_id}/people/{person_id}')
def delete_customer_person(project_id:int,customer_id:int,person_id:int,replacement_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return change_customer_person(project_id,customer_id,user,db,'delete',person_id,replacement_id=replacement_id)
@router.post("/api/contacts/projects/{project_id}/{customer_id}/release")
def rc(project_id:int,customer_id:int,payload:ReleasePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id, user, db, "customer_list")
    access(project_id,user,db);_,r=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True);
    if r.status == "pool": raise HTTPException(409,"该客户已在公池中。")
    cancel_pending(db,project_id,customer_id,"客户已释放至公池，原跟进计划已取消")
    now=datetime.now();reason=payload.reason.strip();r.status="pool";r.release_reason=reason;r.released_at=now;r.released_by_user_id=user.id
    db.add(CustomerPoolAudit(site_project_id=project_id,contact_id=customer_id,original_owner_user_id=r.owner_user_id,released_by_user_id=user.id,release_reason=reason,released_at=now));db.commit();return {"released":True}
@router.delete("/api/contacts/projects/{project_id}/{customer_id}")
def dc(project_id:int,customer_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);x,r=get_c(db,project_id,customer_id,own(project_id,user,db),lock=True)
    require_customer_without_documents(db,project_id,customer_id)
    db.query(FollowUpPlan).filter(FollowUpPlan.site_project_id==project_id,FollowUpPlan.customer_id==customer_id).delete(synchronize_session=False)
    db.query(ContactRecord).filter(ContactRecord.site_project_id==project_id,ContactRecord.contact_id==customer_id).delete(synchronize_session=False);db.query(LeadConversionHistory).filter(LeadConversionHistory.site_project_id==project_id,LeadConversionHistory.customer_id==customer_id).delete(synchronize_session=False);db.delete(r);db.commit();return {"deleted":True}
@router.get("/api/customer-workflow/projects/{project_id}/pool")
def pool(project_id:int,owner_id:int|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);admin=top_admin(project_id,user,db);scoped=owner_id if admin else None;q=select(Customer,ProjectContact).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id,ProjectContact.status=="pool").order_by(ProjectContact.released_at.desc())
    if scoped is not None:q=q.where(ProjectContact.owner_user_id==scoped)
    rows=db.execute(q).all();people=people_by_customer(db,[c.id for c,r in rows])
    archived_ids = set(db.scalars(select(SalesContract.customer_id).where(
        SalesContract.site_project_id==project_id,
        SalesContract.customer_id.in_([c.id for c, r in rows if admin or r.owner_user_id==user.id]),
    ).distinct()))
    return {"items":[{**cd(c,r,db,admin,people[c.id]), "has_archived_contracts": c.id in archived_ids}
                     for c,r in rows],"is_top_admin":admin,"owners":owners(project_id,db) if admin else []}
@router.post("/api/customer-workflow/projects/{project_id}/pool/{customer_id}/restore")
def restore(project_id:int,customer_id:int,payload:RestorePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);_,r=get_c(db,project_id,customer_id,None,"pool",lock=True);admin=top_admin(project_id,user,db)
    restored_owner=target_owner(project_id,payload.owner_user_id,user,db) if (admin and payload.owner_user_id is not None) else (r.owner_user_id if admin else user.id)
    audit=db.scalar(select(CustomerPoolAudit).where(CustomerPoolAudit.site_project_id==project_id,CustomerPoolAudit.contact_id==customer_id,CustomerPoolAudit.restored_at.is_(None)).order_by(CustomerPoolAudit.released_at.desc()))
    if audit:audit.restored_at=datetime.now();audit.restored_by_user_id=user.id;audit.restored_to_user_id=restored_owner
    transfer_open_rfqs(db,project_id,customer_id,restored_owner)
    if restored_owner is not None and restored_owner != r.owner_user_id:
        transfer_customer_quotes(db,project_id,customer_id,restored_owner)
    r.status="active";r.owner_user_id=restored_owner;r.release_reason=None;r.released_at=None;r.released_by_user_id=None
    db.commit();return {"restored":True,"owner_user_id":restored_owner}


def transfer_customer_quotes(db, project_id, customer_id, owner_id):
    db.execute(update(Quotation).where(
        Quotation.site_project_id==project_id, Quotation.customer_id==customer_id,
        Quotation.owner_user_id!=owner_id,
    ).values(owner_user_id=owner_id, revision=Quotation.revision + 1))


def require_customer_without_documents(db, project_id, customer_id):
    for model, customer_field, label in ((Rfq, Rfq.contact_id, '询价'),
                                        (Quotation, Quotation.customer_id, '报价'),
                                        (SalesContract, SalesContract.customer_id, '合同')):
        if db.scalar(select(model.id).where(model.site_project_id==project_id, customer_field==customer_id).limit(1)) is not None:
            raise HTTPException(409, f'该客户已有{label}，无法删除客户档案。')


@router.delete("/api/customer-workflow/projects/{project_id}/pool/{customer_id}")
def delete_pool_customer(project_id:int,customer_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);_,relation=get_c(db,project_id,customer_id,None,"pool",lock=True)
    require_customer_without_documents(db,project_id,customer_id)
    db.query(FollowUpPlan).filter(FollowUpPlan.site_project_id==project_id,FollowUpPlan.customer_id==customer_id).delete(synchronize_session=False)
    db.query(ContactRecord).filter(ContactRecord.site_project_id==project_id,ContactRecord.contact_id==customer_id).delete(synchronize_session=False)
    db.query(LeadConversionHistory).filter(LeadConversionHistory.site_project_id==project_id,LeadConversionHistory.customer_id==customer_id).delete(synchronize_session=False)
    db.delete(relation);db.commit();return {"deleted":True}
@router.post("/api/customer-workflow/projects/{project_id}/pool/batch/delete")
def delete_pool_customers(project_id:int,payload:BatchPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    for customer_id in sorted(payload.ids):
        _,relation=get_c(db,project_id,customer_id,None,"pool",lock=True)
        require_customer_without_documents(db,project_id,customer_id)
        db.query(FollowUpPlan).filter(FollowUpPlan.site_project_id==project_id,FollowUpPlan.customer_id==customer_id).delete(synchronize_session=False)
        db.query(ContactRecord).filter(ContactRecord.site_project_id==project_id,ContactRecord.contact_id==customer_id).delete(synchronize_session=False)
        db.query(LeadConversionHistory).filter(LeadConversionHistory.site_project_id==project_id,LeadConversionHistory.customer_id==customer_id).delete(synchronize_session=False)
        db.delete(relation)
    db.commit();return {"deleted":len(payload.ids)}
@router.get("/api/contacts/projects/{project_id}/{customer_id}/preview")
def preview(project_id:int,customer_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);x,r=get_c(db,project_id,customer_id,own(project_id,user,db));return cd(x,r,db,top_admin(project_id,user,db))
