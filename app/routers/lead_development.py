"""Owner-scoped lead contact records and customer conversion history."""
import json
from app.services.followup_note import FollowupNote, check_revision, followup_rows, note_data, write_note
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_write
from app.models import Lead, LeadInteraction, LeadConversionHistory, LeadOutreachDraft, User
from app.routers.customer import access, own, get_w, get_c, conversion_match, conversion_website_host, LeadConversionPayload
from app.services.contact_record_fields import ContactRecordPayload as InteractionPayload, save_record as save_interaction, record_data
from app.services.workflow_people import workflow_people
from app.services.acquisition_filter import normalized

router=APIRouter(tags=['CRM lead records'])
BASE='/api/customer-workflow/projects/{project_id}/leads'

def today():return datetime.now(timezone(timedelta(hours=8))).date()

def scoped_lead(project_id,lead_id,user,db,write=False):
    access(project_id,user,db)
    if write:require_project_write(project_id, user, db, "leads")
    return get_w(db,Lead,project_id,lead_id,own(project_id,user,db),lock=write)

class OutreachDraftPayload(BaseModel):
    recipient_name: str = Field(default='',max_length=160)
    recipient_email: str = Field(default='',max_length=260)

    @field_validator('recipient_email')
    @classmethod
    def validate_recipient(cls, value):
        value=value.strip()
        if value and (value.count('@')!=1 or any(char.isspace() for char in value) or not all(value.split('@'))):
            raise ValueError('请输入有效的收件人邮箱。')
        return value

    subject: str = Field(default='',max_length=260)
    content: str = Field(default='',max_length=50000)
    content_html: str = Field(default='',max_length=3000000)
    content_translation: str = Field(default='',max_length=50000)

def outreach_data(draft):
    return {'content_html':draft.content_html if draft else '', 'recipient_name':draft.recipient_name if draft else '', 'recipient_email':draft.recipient_email if draft else '', 'subject':draft.subject if draft else '', 'content':draft.content if draft else '', 'content_translation':draft.content_translation if draft else '', 'updated_at':draft.updated_at.isoformat() if draft else None}

@router.get(BASE+'/{lead_id}/outreach-draft')
def get_outreach_draft(project_id:int,lead_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    scoped_lead(project_id,lead_id,user,db)
    return outreach_data(db.get(LeadOutreachDraft,lead_id))

@router.put(BASE+'/{lead_id}/outreach-draft')
def save_outreach_draft(project_id:int,lead_id:int,payload:OutreachDraftPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    scoped_lead(project_id,lead_id,user,db,True)
    draft=db.get(LeadOutreachDraft,lead_id)
    if draft is None:
        draft=LeadOutreachDraft(lead_id=lead_id);db.add(draft)
    if 'subject' in payload.model_fields_set:draft.subject=payload.subject.strip()
    for key in ('recipient_name','recipient_email'):
        if key in payload.model_fields_set:setattr(draft,key,getattr(payload,key).strip())
    from app.services.mail_html import clean_mail_html
    if 'content_html' in payload.model_fields_set:draft.content_html=clean_mail_html(payload.content_html)
    elif payload.content != draft.content:draft.content_html=''
    draft.content=payload.content.replace('\r\n','\n').replace('\r','\n')
    draft.content_translation=payload.content_translation.replace('\r\n','\n').replace('\r','\n')
    db.commit();return outreach_data(draft)

class OutreachConversionPayload(InteractionPayload):
    note: FollowupNote | None = None
    clear_draft: bool = False
    expected_draft: OutreachDraftPayload
    request_key: str = Field(min_length=16,max_length=80)

@router.post(BASE+'/{lead_id}/outreach-draft/to-interaction',status_code=201)
def convert_outreach(project_id:int,lead_id:int,payload:OutreachConversionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    lead=scoped_lead(project_id,lead_id,user,db,True)
    # Serialize against draft edits via the lead lock and allow safe retries after clearing.
    rows=db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id==lead_id,LeadInteraction.source_outreach_json.is_not(None))).all()
    for row in rows:
        if json.loads(row.source_outreach_json).get('conversion_key')==payload.request_key:
            return record_data(row,db)
    note_rows = followup_rows(db, project_id, lead_id, lead=True, lock=True) if payload.note else []
    if payload.note:
        check_revision(note_rows, payload.note.revision)
    draft=db.get(LeadOutreachDraft,lead_id)
    if not draft:raise HTTPException(409,'开发信已变更或清除，请返回重新打开后转换。')
    snapshot=outreach_data(draft)
    if any(snapshot[key]!=value for key,value in payload.expected_draft.model_dump().items()):
        raise HTTPException(409,'开发信已被修改，请返回重新读取后转换，避免清除新的内容。')
    item=LeadInteraction(site_project_id=project_id,lead_id=lead_id,created_by_user_id=user.id)
    save_interaction(item,payload)
    if 'content_html' not in payload.model_fields_set and payload.content.strip()==(draft.content or '').strip():
        item.content_html=draft.content_html
    snapshot['conversion_key']=payload.request_key
    item.source_outreach_json=json.dumps(snapshot,ensure_ascii=False)
    db.add(item)
    if payload.clear_draft:
        for key in ('recipient_name','recipient_email','subject','content','content_html','content_translation'):
            setattr(draft,key,'')
    if payload.note:
        lead.updated_at = datetime.now()
        db.flush()
        write_note(db, [*note_rows, item], project_id, lead_id, payload.note.content, user.id, lead=True)
    # Converting a draft does not send a message or assert that contact occurred.
    db.commit();return record_data(item,db)

@router.get(BASE+'/{lead_id}/interactions')
def list_interactions(project_id:int,lead_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    lead=scoped_lead(project_id,lead_id,user,db)
    records=db.scalars(select(LeadInteraction).where(LeadInteraction.site_project_id==project_id,LeadInteraction.lead_id==lead_id).order_by(LeadInteraction.occurred_at.desc(),LeadInteraction.id.desc())).all()
    return {'contact':{'id':lead.id,'name':lead.contact_name or lead.company_name,'company_name':lead.company_name,'email':lead.email or '', 'phone':lead.phone or '', 'contacts':workflow_people(lead)},'records':[record_data(item,db) for item in records]}

@router.post(BASE+'/{lead_id}/interactions',status_code=201)
def add_interaction(project_id:int,lead_id:int,payload:InteractionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    lead=scoped_lead(project_id,lead_id,user,db,True)
    lead.updated_at=datetime.now()
    item=LeadInteraction(site_project_id=project_id,lead_id=lead_id,created_by_user_id=user.id);save_interaction(item,payload);db.add(item)
    # Recording a conversation must not override a manually selected lead status.
    db.commit();return record_data(item,db)

@router.put(BASE+'/{lead_id}/interactions/{record_id}')
def edit_interaction(project_id:int,lead_id:int,record_id:int,payload:InteractionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    lead=scoped_lead(project_id,lead_id,user,db,True)
    lead.updated_at=datetime.now()
    item=db.scalar(select(LeadInteraction).where(LeadInteraction.id==record_id,LeadInteraction.lead_id==lead_id))
    if not item:raise HTTPException(404,'跟进不存在。')
    save_interaction(item,payload);db.commit();return record_data(item,db)

@router.delete(BASE+'/{lead_id}/interactions/{record_id}')
def delete_interaction(project_id:int,lead_id:int,record_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    lead=scoped_lead(project_id,lead_id,user,db,True)
    lead.updated_at=datetime.now()
    item=db.scalar(select(LeadInteraction).where(LeadInteraction.id==record_id,LeadInteraction.lead_id==lead_id))
    if not item:raise HTTPException(404,'跟进不存在。')
    db.delete(item);db.commit();return {'deleted':True}

@router.post(BASE+'/batch/conversion-preview')
def preview_conversion(project_id:int,payload:LeadConversionPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=access(project_id,user,db);require_project_write(project_id, user, db, "leads")
    results=[];planned=[]
    for lead_id in payload.ids:
        lead=get_w(db,Lead,project_id,lead_id,own(project_id,user,db))
        try:
            customer,relation=conversion_match(db,project,lead)
            keys={('email',p['email'].casefold()) for p in workflow_people(lead) if p['email']}
            host=conversion_website_host(lead.company_website)
            if host:keys.add(('website',host))
            hits=[cluster for cluster in planned if keys & cluster['keys'] or customer and cluster['customer_id']==customer.id]
            if len(hits)>1 or hits and customer and hits[0]['customer_id']!=customer.id:
                raise HTTPException(409,'本批次的官网或邮箱关联不同客户，请先核实后分批转换。')
            result={'lead_id':lead_id,'company_name':lead.company_name,'mode':'merged' if customer else 'created','customer_name':customer.company if customer else '', 'message':'已有非空资料保留；原线索完整保存到转换历史。'}
            if hits:
                result.update(mode='merged',customer_name=hits[0]['name'])
                hits[0]['keys'].update(keys);hits[0]['names'].add(normalized(lead.company_name))
            else:
                if not customer and any(normalized(lead.company_name) in cluster['names'] for cluster in planned):
                    raise HTTPException(409,'本批次存在同名企业，但没有一致的官网或邮箱，请先核实后再转换。')
                planned.append({'keys':keys,'names':{normalized(lead.company_name)},'name':customer.company if customer else lead.company_name,'customer_id':customer.id if customer else None})
            results.append(result)
        except HTTPException as error:
            if error.status_code!=409:raise
            results.append({'lead_id':lead_id,'company_name':lead.company_name,'mode':'blocked','message':error.detail})
    return {'items':results,'can_convert':all(item['mode']!='blocked' for item in results)}

@router.get('/api/contacts/projects/{project_id}/{customer_id}/conversion-history')
def conversion_history(project_id:int,customer_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);get_c(db,project_id,customer_id,own(project_id,user,db))
    records=db.scalars(select(LeadConversionHistory).where(LeadConversionHistory.site_project_id==project_id,LeadConversionHistory.customer_id==customer_id).order_by(LeadConversionHistory.converted_at.desc(),LeadConversionHistory.id.desc())).all()
    result=[]
    for item in records:
        actor=db.get(User,item.converted_by_user_id) if item.converted_by_user_id else None
        result.append({'id':item.id,'source_lead_id':item.source_lead_id,'converted_at':item.converted_at.isoformat(),'converted_by':(actor.display_name or actor.email) if actor else '', 'mode':item.mode,'snapshot':json.loads(item.snapshot_json)})
    return {'items':result}


@router.get(BASE+'/{lead_id}/followup-note')
def get_followup_note(project_id: int, lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scoped_lead(project_id, lead_id, user, db)
    return note_data(followup_rows(db, project_id, lead_id, lead=True))


@router.put(BASE+'/{lead_id}/followup-note')
def save_followup_note(project_id: int, lead_id: int, payload: FollowupNote, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = scoped_lead(project_id, lead_id, user, db, True)
    rows = followup_rows(db, project_id, lead_id, lead=True, lock=True)
    check_revision(rows, payload.revision)
    result = write_note(db, rows, project_id, lead_id, payload.content, user.id, lead=True)
    lead.updated_at = datetime.now()
    db.commit()
    return result
