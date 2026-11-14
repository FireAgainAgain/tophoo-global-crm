"""Authenticated bookmarks scoped to current user and selected project."""
from urllib.parse import urlsplit, quote
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write
from app.models import User, UserLink, UserLinkCategory, SiteProject
from app.services.project_link_pdf import export_project_links_pdf

router=APIRouter(prefix='/api/user-links',tags=['Personal website navigation'])

class CategoryPayload(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    @field_validator('name')
    @classmethod
    def name_valid(cls,value):
        value=value.strip()
        if not value:raise ValueError('请输入分类名称。')
        return value

class LinkPayload(BaseModel):
    name: str = Field(min_length=1,max_length=150)
    url: str = Field(min_length=1,max_length=1000)
    category_id: int | None = Field(default=None,gt=0)
    @field_validator('name')
    @classmethod
    def name_valid(cls,value):
        value=value.strip()
        if not value:raise ValueError('请输入网址名称。')
        return value
    @field_validator('url')
    @classmethod
    def url_valid(cls,value):
        value=value.strip()
        if '://' not in value:value='https://'+value
        parsed=urlsplit(value)
        _=parsed.port
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise ValueError('请输入有效的 HTTP 或 HTTPS 网址。')
        if len(value)>1000:raise ValueError('网址过长。')
        return value

class MovePayload(BaseModel):
    direction: str = Field(pattern='^(up|down)$')

def link_scope(request: Request, project_id: int | None = Query(default=None,gt=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    header=request.headers.get('X-Project-ID')
    if header:
        try: selected=int(header)
        except ValueError: raise HTTPException(422,'项目编号无效。') from None
        if project_id is not None and project_id != selected:
            raise HTTPException(409,'项目已切换，请重新加载。')
        project_id=selected
    if project_id is not None:
        (require_project_module if request.method in {'GET','HEAD','OPTIONS'} else require_project_write)(project_id,user,db,'url_navigation')
    return project_id


def owned(db,model,user,item_id,scope):
    item=db.scalar(select(model).where(model.id==item_id,model.owner_user_id==user.id,model.site_project_id==scope))
    if not item:raise HTTPException(404,'记录不存在。')
    return item

def lock(db,user):
    db.scalar(select(User).where(User.id==user.id).with_for_update())

def link_data(item):
    return {'id':item.id,'name':item.name,'url':item.url,'category_id':item.category_id}

@router.get('')
def listing(user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    categories=db.scalars(select(UserLinkCategory).where(UserLinkCategory.owner_user_id==user.id,UserLinkCategory.site_project_id==scope).order_by(UserLinkCategory.sort_order,UserLinkCategory.id)).all()
    links=db.scalars(select(UserLink).where(UserLink.owner_user_id==user.id,UserLink.site_project_id==scope).order_by(UserLink.sort_order,UserLink.id)).all()
    return {'categories':[{'id':item.id,'name':item.name} for item in categories],'items':[link_data(item) for item in links]}

@router.post('/categories',status_code=201)
def create_category(payload:CategoryPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user)
    if db.scalar(select(UserLinkCategory.id).where(UserLinkCategory.owner_user_id==user.id,UserLinkCategory.site_project_id==scope,func.lower(UserLinkCategory.name)==payload.name.lower())):
        raise HTTPException(409,'已有同名分类。')
    order=db.scalar(select(func.max(UserLinkCategory.sort_order)).where(UserLinkCategory.owner_user_id==user.id,UserLinkCategory.site_project_id==scope)) or 0
    item=UserLinkCategory(owner_user_id=user.id,site_project_id=scope,name=payload.name,sort_order=order+1);db.add(item);db.commit()
    return {'id':item.id,'name':item.name}

@router.put('/categories/{category_id}')
def edit_category(category_id:int,payload:CategoryPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user);item=owned(db,UserLinkCategory,user,category_id,scope)
    if db.scalar(select(UserLinkCategory.id).where(UserLinkCategory.owner_user_id==user.id,UserLinkCategory.site_project_id==scope,UserLinkCategory.id!=item.id,func.lower(UserLinkCategory.name)==payload.name.lower())):
        raise HTTPException(409,'已有同名分类。')
    item.name=payload.name;db.commit();return {'id':item.id,'name':item.name}

@router.delete('/categories/{category_id}')
def delete_category(category_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user);item=owned(db,UserLinkCategory,user,category_id,scope)
    db.execute(update(UserLink).where(UserLink.owner_user_id==user.id,UserLink.site_project_id==scope,UserLink.category_id==item.id).values(category_id=None))
    db.delete(item);db.commit();return {'deleted':True}

@router.post('',status_code=201)
def create_link(payload:LinkPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user)
    if payload.category_id:owned(db,UserLinkCategory,user,payload.category_id,scope)
    order=db.scalar(select(func.max(UserLink.sort_order)).where(UserLink.owner_user_id==user.id,UserLink.site_project_id==scope)) or 0
    item=UserLink(owner_user_id=user.id,site_project_id=scope,sort_order=order+1,**payload.model_dump());db.add(item);db.commit();return link_data(item)

@router.put('/{link_id:int}')
def edit_link(link_id:int,payload:LinkPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user);item=owned(db,UserLink,user,link_id,scope)
    if payload.category_id:owned(db,UserLinkCategory,user,payload.category_id,scope)
    if item.category_id!=payload.category_id:
        order=db.scalar(select(func.max(UserLink.sort_order)).where(UserLink.owner_user_id==user.id,UserLink.site_project_id==scope,UserLink.category_id==payload.category_id)) or 0
        item.sort_order=order+1
    for key,value in payload.model_dump().items():setattr(item,key,value)
    db.commit();return link_data(item)

@router.delete('/{link_id:int}')
def delete_link(link_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user);db.delete(owned(db,UserLink,user,link_id,scope));db.commit();return {'deleted':True}

@router.post('/{link_id:int}/move')
def move_link(link_id:int,payload:MovePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    lock(db,user);item=owned(db,UserLink,user,link_id,scope)
    links=db.scalars(select(UserLink).where(UserLink.owner_user_id==user.id,UserLink.site_project_id==scope,UserLink.category_id==item.category_id).order_by(UserLink.sort_order,UserLink.id)).all()
    index=links.index(item);target=index+(-1 if payload.direction=='up' else 1)
    if 0<=target<len(links):links[index],links[target]=links[target],links[index]
    for position,link in enumerate(links):link.sort_order=position+1
    db.commit();return {'moved':True}

@router.get('/export/pdf')
def export_links(user:User=Depends(get_current_user),db:Session=Depends(get_db),scope:int|None=Depends(link_scope)):
    data=listing(user,db,scope);categories={item['id']:item['name'] for item in data['categories']}
    links=[SimpleNamespace(name=(categories.get(item['category_id'],'未分类')+' · '+item['name']),url=item['url']) for item in data['items']]
    project=db.get(SiteProject,scope) if scope is not None else None
    profile=SimpleNamespace(name=project.name if project else '未归属项目',site_url='当前用户 · 当前项目的网址')
    return Response(export_project_links_pdf(profile,links,personal=True),media_type='application/pdf',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote('个人网址导航.pdf')})
