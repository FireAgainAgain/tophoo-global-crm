"""Communication phrases are separate from knowledge-base articles."""
from typing import Literal
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, project_write_permissions
from app.models import User
from app.models.communication_phrase import PhraseCategory, PhraseScene, CommunicationPhrase

router=APIRouter(prefix='/api/phrases/projects/{project_id}',tags=['Communication phrases'])

class CategoryPayload(BaseModel):
    name: str = Field(min_length=1,max_length=180)
    @field_validator('name')
    @classmethod
    def trimmed(cls,value):
        value=value.strip()
        if not value:raise ValueError('分类名称不能为空。')
        return value

class PhrasePayload(BaseModel):
    category_id: int = Field(gt=0)
    scene_id: int | None = Field(default=None,gt=0)
    content: str = Field(min_length=1,max_length=15000)
    translation: str = Field(default='',max_length=15000)
    @field_validator('content','translation')
    @classmethod
    def trimmed(cls,value):
        value=value.strip()
        return value

    @field_validator('content')
    @classmethod
    def original_required(cls,value):
        if not value:raise ValueError('请填写原文。')
        return value

class MovePayload(BaseModel):
    direction: Literal[-1,1]
    category_id: int | None = Field(default=None,gt=0)
    scene_id: int | None = Field(default=None,ge=0)

class ScenePayload(CategoryPayload):
    category_id: int = Field(gt=0)

class SceneOrderPayload(BaseModel):
    category_id: int = Field(gt=0)
    ids: list[int] = Field(max_length=500)

class OrderPayload(BaseModel):
    ids: list[int] = Field(max_length=500)

def category(db,project_id,category_id):
    item=db.scalar(select(PhraseCategory).where(PhraseCategory.site_project_id==project_id,PhraseCategory.id==category_id).with_for_update())
    if not item:raise HTTPException(404,'分类不存在或已删除。')
    return item

def phrase(db,project_id,phrase_id):
    item=db.scalar(select(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.id==phrase_id).with_for_update())
    if not item:raise HTTPException(404,'话术不存在或已删除。')
    return item

def scene(db,project_id,scene_id,category_id=None):
    item=db.scalar(select(PhraseScene).where(PhraseScene.site_project_id==project_id,PhraseScene.id==scene_id).with_for_update())
    if not item or (category_id is not None and item.category_id!=category_id):
        raise HTTPException(404,'场景不存在或不属于当前分类。')
    return item

def validate_assignment(db,project_id,payload):
    category(db,project_id,payload.category_id)
    if payload.scene_id is not None:scene(db,project_id,payload.scene_id,payload.category_id)

def commit(db):
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'分类或场景名称重复，或数据已变更，请刷新后重试。')

def data(item):
    return {k:getattr(item,k) for k in ('id','category_id','scene_id','content','translation')}

@router.get('')
def listing(project_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    categories=db.scalars(select(PhraseCategory).where(PhraseCategory.site_project_id==project_id).order_by(PhraseCategory.sort_order,PhraseCategory.id)).all()
    phrases=db.scalars(select(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id).order_by(CommunicationPhrase.sort_order,CommunicationPhrase.id)).all()
    scenes=db.scalars(select(PhraseScene).where(PhraseScene.site_project_id==project_id).order_by(PhraseScene.sort_order,PhraseScene.id)).all()
    return {'categories':[{'id':c.id,'name':c.name} for c in categories],'scenes':[{'id':s.id,'category_id':s.category_id,'name':s.name} for s in scenes],'items':[data(item) for item in phrases],
        'can_edit':'communication_phrases' in project_write_permissions(project_id,user,db)}

@router.post('/categories',status_code=201)
def add_category(project_id:int,payload:CategoryPayload,db:Session=Depends(get_db)):
    rank=db.scalar(select(func.max(PhraseCategory.sort_order)).where(PhraseCategory.site_project_id==project_id)) or 0
    item=PhraseCategory(site_project_id=project_id,name=payload.name,sort_order=rank+1);db.add(item);commit(db)
    return {'id':item.id,'name':item.name}


@router.get('/export/pdf')
def export_all_pdf(project_id:int,db:Session=Depends(get_db)):
    from app.services.communication_phrase_pdf import export_phrases_pdf
    categories=list(db.scalars(select(PhraseCategory).where(PhraseCategory.site_project_id==project_id).order_by(PhraseCategory.sort_order,PhraseCategory.id)))
    phrases=list(db.scalars(select(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id).order_by(CommunicationPhrase.sort_order,CommunicationPhrase.id)))
    if not phrases:raise HTTPException(400,'还没有可导出的话术。')
    scenes=list(db.scalars(select(PhraseScene).where(PhraseScene.site_project_id==project_id).order_by(PhraseScene.sort_order,PhraseScene.id)))
    date=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
    filename=f'沟通话术_全部内容_{date}.pdf'
    return Response(export_phrases_pdf(categories,scenes,phrases),media_type='application/pdf',
                    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe=''),'Cache-Control':'no-store'})

@router.put('/categories/order')
def order_categories(project_id:int,payload:OrderPayload,db:Session=Depends(get_db)):
    items=db.scalars(select(PhraseCategory).where(PhraseCategory.site_project_id==project_id).with_for_update()).all()
    if len(payload.ids)!=len(set(payload.ids)) or set(payload.ids)!={c.id for c in items}:
        raise HTTPException(409,'分类列表已变更，请刷新后调整顺序。')
    ranks={key:index for index,key in enumerate(payload.ids)}
    for item in items:item.sort_order=ranks[item.id]
    commit(db);return {'saved':True}

@router.put('/categories/{category_id}')
def edit_category(project_id:int,category_id:int,payload:CategoryPayload,db:Session=Depends(get_db)):
    item=category(db,project_id,category_id);item.name=payload.name;commit(db);return {'id':item.id,'name':item.name}

@router.delete('/categories/{category_id}')
def delete_category(project_id:int,category_id:int,target_id:int|None=None,db:Session=Depends(get_db)):
    # Lock both categories in stable ID order before moving their phrases.
    for key in sorted({category_id,*([target_id] if target_id is not None else [])}):category(db,project_id,key)
    item=category(db,project_id,category_id)
    count=db.scalar(select(func.count()).select_from(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.category_id==category_id))
    if target_id==category_id:raise HTTPException(422,'请选择其他目标分类。')
    if count and target_id is None:raise HTTPException(409,'该分类有话术，请先选择迁移的目标分类。')
    scenes=db.scalars(select(PhraseScene).where(PhraseScene.site_project_id==project_id,PhraseScene.category_id==category_id).order_by(PhraseScene.sort_order,PhraseScene.id).with_for_update()).all()
    rank=db.scalar(select(func.max(PhraseScene.sort_order)).where(PhraseScene.category_id==target_id)) or 0
    for entry in scenes:
        match=db.scalar(select(PhraseScene).where(PhraseScene.site_project_id==project_id,PhraseScene.category_id==target_id,PhraseScene.name==entry.name)) if target_id else None
        if target_id and not match:
            rank+=1;entry.category_id=target_id;entry.sort_order=rank
        else:
            db.execute(update(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.scene_id==entry.id).values(scene_id=match.id if match else None))
            db.delete(entry)
    if count:
        db.execute(update(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.category_id==category_id).values(category_id=target_id))
    db.delete(item);commit(db);return {'deleted':True,'moved':count}

@router.post('/items',status_code=201)
def add_phrase(project_id:int,payload:PhrasePayload,db:Session=Depends(get_db)):
    validate_assignment(db,project_id,payload)
    rank=db.scalar(select(func.min(CommunicationPhrase.sort_order)).where(CommunicationPhrase.site_project_id==project_id))
    item=CommunicationPhrase(site_project_id=project_id,sort_order=(rank if rank is not None else 0)-1,**payload.model_dump());db.add(item);commit(db);return data(item)

@router.put('/items/{phrase_id}')
def edit_phrase(project_id:int,phrase_id:int,payload:PhrasePayload,db:Session=Depends(get_db)):
    validate_assignment(db,project_id,payload);item=phrase(db,project_id,phrase_id)
    for key,value in payload.model_dump().items():setattr(item,key,value)
    commit(db);return data(item)

@router.delete('/items/{phrase_id}')
def delete_phrase(project_id:int,phrase_id:int,db:Session=Depends(get_db)):
    db.delete(phrase(db,project_id,phrase_id));commit(db);return {'deleted':True}


@router.post('/items/{phrase_id}/move')
def move_phrase(project_id:int,phrase_id:int,payload:MovePayload,db:Session=Depends(get_db)):
    items=list(db.scalars(select(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id).order_by(CommunicationPhrase.sort_order,CommunicationPhrase.id).with_for_update()))
    item=next((x for x in items if x.id==phrase_id),None)
    if item is None:raise HTTPException(404,'话术不存在或已删除。')
    if payload.category_id is not None and item.category_id!=payload.category_id:raise HTTPException(409,'话术分类已变更，请刷新后重试。')
    if payload.scene_id is not None and item.scene_id!=(payload.scene_id or None):raise HTTPException(409,'话术场景已变更，请刷新后重试。')
    scope=[i for i,x in enumerate(items) if (payload.category_id is None or x.category_id==payload.category_id) and (payload.scene_id is None or x.scene_id==(payload.scene_id or None))]
    current=scope.index(items.index(item));target=current+payload.direction
    if target<0 or target>=len(scope):return {'moved':False}
    a,b=scope[current],scope[target];items[a],items[b]=items[b],items[a]
    for index,row in enumerate(items):row.sort_order=index
    commit(db);return {'moved':True}


@router.post('/scenes',status_code=201)
def add_scene(project_id:int,payload:ScenePayload,db:Session=Depends(get_db)):
    category(db,project_id,payload.category_id)
    rank=db.scalar(select(func.max(PhraseScene.sort_order)).where(PhraseScene.category_id==payload.category_id)) or 0
    item=PhraseScene(site_project_id=project_id,sort_order=rank+1,**payload.model_dump())
    db.add(item);commit(db);return {'id':item.id,'category_id':item.category_id,'name':item.name}


@router.put('/scenes/order')
def order_scenes(project_id:int,payload:SceneOrderPayload,db:Session=Depends(get_db)):
    category(db,project_id,payload.category_id)
    items=db.scalars(select(PhraseScene).where(PhraseScene.site_project_id==project_id,PhraseScene.category_id==payload.category_id).with_for_update()).all()
    if len(payload.ids)!=len(set(payload.ids)) or set(payload.ids)!={s.id for s in items}:
        raise HTTPException(409,'场景列表已变更，请刷新后调整顺序。')
    ranks={key:index for index,key in enumerate(payload.ids)}
    for item in items:item.sort_order=ranks[item.id]
    commit(db);return {'saved':True}


@router.put('/scenes/{scene_id}')
def edit_scene(project_id:int,scene_id:int,payload:CategoryPayload,db:Session=Depends(get_db)):
    item=scene(db,project_id,scene_id);item.name=payload.name;commit(db)
    return {'id':item.id,'category_id':item.category_id,'name':item.name}


@router.delete('/scenes/{scene_id}')
def delete_scene(project_id:int,scene_id:int,target_id:int|None=None,db:Session=Depends(get_db)):
    item=scene(db,project_id,scene_id)
    if target_id==scene_id:raise HTTPException(422,'请选择其他目标场景。')
    if target_id is not None:scene(db,project_id,target_id,item.category_id)
    count=db.scalar(select(func.count()).select_from(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.scene_id==scene_id))
    if count and target_id is None:raise HTTPException(409,'该场景有话术，请先选择迁移的目标场景。')
    db.execute(update(CommunicationPhrase).where(CommunicationPhrase.site_project_id==project_id,CommunicationPhrase.scene_id==scene_id).values(scene_id=target_id))
    db.delete(item);commit(db);return {'deleted':True,'moved':count}
