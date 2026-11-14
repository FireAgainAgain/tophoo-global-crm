"""Customer communication reference tools; reading never creates business rows."""
import json
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write, project_write_permissions
from app.models import Customer, CustomerPerson, Lead, ProjectContact, User
from app.models.communication import CommunicationPreference, CommunicationSetting
from app.routers.customer import get_c, get_w, own
from app.schemas.communication import PlaceConfig, Preferences
from app.services import communication as service
from app.services.workflow_people import workflow_people


def access(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_module(project_id,user,db,'communication_assistant')


router=APIRouter(prefix='/api/communication/projects/{project_id}',tags=['Communication assistant'],dependencies=[Depends(access)])


def commit_settings(db):
    try:db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'设置或联系人已被其他操作更新，请刷新后重试。') from None


def preferences(db,project_id,user):
    row=db.scalar(select(CommunicationPreference).where(CommunicationPreference.site_project_id==project_id,CommunicationPreference.user_id==user.id))
    return Preferences.model_validate_json(row.settings_json) if row else Preferences(favorites=service.catalog()['recommended'])


@router.get('/catalog')
def catalog(project_id:int):return service.catalog()


@router.get('/subdivisions/{country}')
def get_subdivisions(project_id:int,country:str):
    if country not in {c['code'] for c in service.catalog()['countries']}:raise HTTPException(422,'国家代码无效。')
    return service.subdivisions(country)


@router.get('/preferences')
def get_preferences(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return preferences(db,project_id,user).model_dump(mode='json')


@router.put('/preferences')
def save_preferences(project_id:int,payload:Preferences,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    # Watchlists and regional reference schedules are private, even for read-only members.
    if len(payload.favorites)!=len(set(payload.favorites)):raise HTTPException(422,'关注地区不能重复。')
    for key in payload.favorites:service.place_from_key(key)
    if payload.home_timezone not in {p['timezone'] for p in service.catalog()['places']}:raise HTTPException(422,'本人时区无效。')
    for key,config in payload.overrides.items():
        service.validate_place(config)
        if key!=config.country+':'+config.timezone:raise HTTPException(422,'参考作息与地区不匹配。')
        config.confirmed=False
    row=db.scalar(select(CommunicationPreference).where(CommunicationPreference.site_project_id==project_id,CommunicationPreference.user_id==user.id).with_for_update())
    if not row:row=CommunicationPreference(site_project_id=project_id,user_id=user.id);db.add(row)
    row.settings_json=payload.model_dump_json();commit_settings(db)
    return payload.model_dump(mode='json')


@router.get('/overview')
def overview(project_id:int,keys:str='',days:int=Query(7,ge=1,le=90),at:datetime|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if at is not None and (at.tzinfo is None or not 2000<=at.year<=2100):
        raise HTTPException(422,'请选择 2000–2100 年之间带时区的对照时间。')
    prefs=preferences(db,project_id,user);selected=list(dict.fromkeys(keys.split(','))) if keys else prefs.favorites
    if len(selected)>80:raise HTTPException(422,'一次最多查看 80 个地区。')
    overrides={k:v.model_dump(mode='json') for k,v in prefs.overrides.items()}
    return {'items':[service.overview(service.place_from_key(key,overrides),now=at,days=days) for key in selected], 'sources':service.catalog()['sources']}


class PreviewPayload(BaseModel):
    config:PlaceConfig
    days:int=Field(default=30,ge=1,le=90)


@router.post('/preview')
def preview(project_id:int,payload:PreviewPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    prefs=preferences(db,project_id,user)
    return service.overview(service.validate_place(payload.config),days=payload.days,details=True,home_timezone=prefs.home_timezone,home_schedule=prefs.home_schedule)


class ConvertPayload(BaseModel):
    config:PlaceConfig
    value:str=Field(min_length=10,max_length=30)
    source:Literal['local','beijing']='local'
    fold:int|None=Field(default=None,ge=0,le=1)


@router.post('/convert')
def convert(project_id:int,payload:ConvertPayload):
    config=service.validate_place(payload.config)
    if payload.source=='local':return service.convert_wall(config,payload.value,payload.fold)
    converted=service.convert_wall(PlaceConfig(country='CN',timezone='Asia/Shanghai'),payload.value)
    instant=datetime.fromisoformat(converted['utc'])
    return {**service.time_data(instant,config.timezone),'state':service.current_state(config,instant),'ambiguous':False}


def entity_context(db,project_id,kind,entity_id,user,write=False):
    module = 'leads' if kind == 'leads' else 'customer_list'
    (require_project_write if write else require_project_module)(project_id,user,db,module)
    if kind=='leads':
        entity=get_w(db,Lead,project_id,entity_id,own(project_id,user,db))
        people=[{**person,'key':service.person_key(person)} for person in workflow_people(entity)]
    else:
        entity,_=get_c(db,project_id,entity_id,own(project_id,user,db))
        people=[{'key':str(p.id),'contact_name':p.contact_name or p.email or '未填写联系人'} for p in db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id==entity_id).order_by(CustomerPerson.primary_slot.desc(),CustomerPerson.id))]
    return entity,people


def selected_key(kind,entity_id,person,people):
    if person and sum(p['key']==person for p in people)!=1:raise HTTPException(422,'联系人不存在或无法唯一识别，请刷新或补充联系人资料。')
    return service.target_key(kind,entity_id,person)


def setting_row(db,project_id,key):
    return db.scalar(select(CommunicationSetting).where(CommunicationSetting.site_project_id==project_id,CommunicationSetting.target_key==key))


def resolved_config(db,project_id,kind,entity,person,prefs):
    key=service.target_key(kind,entity.id,person)
    row=setting_row(db,project_id,key)
    if row:return PlaceConfig.model_validate_json(row.settings_json),'person' if person else 'company',True
    if person:
        row=setting_row(db,project_id,service.target_key(kind,entity.id))
        if row:return PlaceConfig.model_validate_json(row.settings_json),'company',False
    place,origin=service.infer_place(entity.country,entity.company_address)
    if not place:return None,'unconfigured',False
    key=place['key']
    override=prefs.overrides.get(key)
    return override or service.place_from_key(key),origin,False


@router.get('/entities/{kind}/{entity_id}')
def entity_profile(project_id:int,kind:Literal['leads','customers'],entity_id:int,person:str=Query('',max_length=40),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    entity,people=entity_context(db,project_id,kind,entity_id,user)
    selected_key(kind,entity_id,person,people);prefs=preferences(db,project_id,user)
    config,origin,explicit=resolved_config(db,project_id,kind,entity,person,prefs)
    return {'entity_id':entity_id,'kind':kind,'company_name':entity.company_name if kind=='leads' else entity.company or entity.name,
        'country_text':entity.country or '', 'country_code':service.country_code(entity.country),'person':person,
        'people':[{'key':p['key'],'name':p.get('contact_name') or p.get('email') or '未填写联系人'} for p in people],
        'origin':origin,'has_override':explicit,'can_edit':{'communication_assistant', 'leads' if kind == 'leads' else 'customer_list'} <= project_write_permissions(project_id,user,db),
        'overview':service.overview(config,details=True,home_timezone=prefs.home_timezone,home_schedule=prefs.home_schedule) if config else None}


@router.put('/entities/{kind}/{entity_id}')
def save_entity_profile(project_id:int,kind:Literal['leads','customers'],entity_id:int,payload:PlaceConfig,person:str=Query('',max_length=40),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db,'communication_assistant');service.validate_place(payload)
    entity,people=entity_context(db,project_id,kind,entity_id,user,write=True);key=selected_key(kind,entity_id,person,people)
    row=setting_row(db,project_id,key)
    if not row:
        row=CommunicationSetting(site_project_id=project_id,target_key=key,lead_id=entity_id if kind=='leads' else None,customer_id=entity_id if kind=='customers' else None,person_id=int(person) if person and kind=='customers' else None)
        db.add(row)
    row.settings_json=payload.model_dump_json();commit_settings(db)
    return entity_profile(project_id,kind,entity_id,person,user,db)


@router.delete('/entities/{kind}/{entity_id}')
def reset_entity_profile(project_id:int,kind:Literal['leads','customers'],entity_id:int,person:str=Query('',max_length=40),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db,'communication_assistant')
    _,people=entity_context(db,project_id,kind,entity_id,user,write=True);key=selected_key(kind,entity_id,person,people)
    db.execute(delete(CommunicationSetting).where(CommunicationSetting.site_project_id==project_id,CommunicationSetting.target_key==key));db.commit()
    return entity_profile(project_id,kind,entity_id,person,user,db)


@router.get('/related-customers')
def related_customers(project_id:int,key:str=Query(max_length=120),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_module(project_id,user,db,'customer_list')
    service.place_from_key(key)
    query=select(Customer.id,Customer.company,Customer.name,Customer.country,Customer.company_address).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id,ProjectContact.status.is_distinct_from('pool'))
    owner=own(project_id,user,db)
    if owner is not None:query=query.where(ProjectContact.owner_user_id==owner)
    # One settings query for the entire list; no customer count or contact record is changed.
    stored={row.customer_id:PlaceConfig.model_validate_json(row.settings_json) for row in db.scalars(select(CommunicationSetting).where(CommunicationSetting.site_project_id==project_id,CommunicationSetting.customer_id.is_not(None),CommunicationSetting.person_id.is_(None)))}
    code,zone=key.split(':',1)
    matches=[]
    for customer in db.execute(query.order_by(Customer.company,Customer.id)):
        config=stored.get(customer.id)
        inferred,_=service.infer_place(customer.country,customer.company_address) if not config else (None,None)
        if (config and config.country==code and config.timezone==zone) or (inferred and inferred['key']==key):
            matches.append({'id':customer.id,'company_name':customer.company or customer.name})
    return {'items':matches[:20],'total':len(matches)}
