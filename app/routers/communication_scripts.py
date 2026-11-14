"""Project knowledge-base APIs."""
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write
from app.models import CommunicationScript, CommunicationScriptCategory, User
from app.services.communication_script_pdf import export_knowledge_category_pdf, export_knowledge_script_pdf

router = APIRouter(prefix="/api/communication-scripts", tags=["Communication scripts"])


def require_access(project_id: int, user: User, db: Session):
    return require_project_module(project_id, user, db, "knowledge_base")


class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    parent_id: int | None = None


class ScriptPayload(BaseModel):
    category_id: int
    title: str = Field(min_length=1, max_length=260)
    content: str = Field(min_length=1, max_length=50000)
    content_format: str = Field(default="markdown",pattern=r"^(markdown|email)$")
    content_html: str = Field(default="",max_length=3000000)

    @field_validator("content_html")
    @classmethod
    def safe_html(cls,value):
        from app.services.mail_html import clean_mail_html
        return clean_mail_html(value)

    @field_validator('content')
    @classmethod
    def content_fits_storage(cls, value: str) -> str:
        # MySQL TEXT stores at most 65,535 bytes, independently of character count.
        if len(value.encode('utf-8')) > 65000:
            raise ValueError('内容过长，请拆分为多个知识条目后保存。')
        return value


class MovePayload(BaseModel):
    direction: str = Field(pattern=r"^(up|down)$")


def category_for(db: Session, project_id: int, category_id: int) -> CommunicationScriptCategory:
    item = db.scalar(select(CommunicationScriptCategory).where(CommunicationScriptCategory.id == category_id, CommunicationScriptCategory.site_project_id == project_id))
    if not item:
        raise HTTPException(404, "知识库分类不存在。")
    return item


def script_for(db: Session, project_id: int, script_id: int) -> CommunicationScript:
    item = db.scalar(select(CommunicationScript).where(CommunicationScript.id == script_id, CommunicationScript.site_project_id == project_id))
    if not item:
        raise HTTPException(404, "知识条目不存在。")
    return item


def validate_parent(db: Session, project_id: int, parent_id: int | None, item_id: int | None = None) -> int | None:
    if parent_id is None:
        return None
    parent = category_for(db, project_id, parent_id)
    if item_id is None:
        return parent.id
    if parent.id == item_id:
        raise HTTPException(400, "分类不能设为自己的父级。")
    parent_map = {row.id: row.parent_id for row in db.scalars(select(CommunicationScriptCategory).where(CommunicationScriptCategory.site_project_id == project_id))}
    cursor = parent.id
    while cursor is not None:
        if cursor == item_id:
            raise HTTPException(400, "不能移动到自己的下级分类中。")
        cursor = parent_map.get(cursor)
    return parent.id


def category_data(item: CommunicationScriptCategory) -> dict:
    return {"id": item.id, "name": item.name, "parent_id": item.parent_id, "sort_order": item.sort_order}


def script_data(item: CommunicationScript) -> dict:
    return {"id": item.id, "category_id": item.category_id, "title": item.title, "content": item.content, "content_format": item.content_format, "content_html": item.content_html, "sort_order": item.sort_order}


@router.get("/projects/{project_id}")
def list_library(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    categories = db.scalars(select(CommunicationScriptCategory).where(CommunicationScriptCategory.site_project_id == project_id).order_by(CommunicationScriptCategory.sort_order, CommunicationScriptCategory.id)).all()
    scripts = db.scalars(select(CommunicationScript).where(CommunicationScript.site_project_id == project_id).order_by(CommunicationScript.sort_order, CommunicationScript.id)).all()
    return {"categories": [category_data(item) for item in categories], "scripts": [script_data(item) for item in scripts]}


@router.get("/projects/{project_id}/categories/{category_id}/export/pdf")
def export_category_pdf(project_id: int, category_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    category = category_for(db, project_id, category_id)
    scripts = list(db.scalars(select(CommunicationScript).where(
        CommunicationScript.site_project_id == project_id,
        CommunicationScript.category_id == category.id,
    ).order_by(CommunicationScript.sort_order, CommunicationScript.id)))
    if not scripts:
        raise HTTPException(400, "该知识分类还没有可导出的条目。")
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', category.name).strip().rstrip('.') or f"knowledge-category-{category.id}"
    export_title = scripts[0].title if len(scripts) == 1 else '知识库合集'
    safe_title = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', export_title).strip().rstrip('.') or f"knowledge-{scripts[0].id}"
    date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    filename = f"{safe_name}_{safe_title}_{date}.pdf"
    return Response(export_knowledge_category_pdf(category, scripts), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})


@router.get("/projects/{project_id}/scripts/{script_id}/export/pdf")
def export_script_pdf(project_id: int, script_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    script = script_for(db, project_id, script_id)
    category = category_for(db, project_id, script.category_id)
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', script.title).strip().rstrip('.') or f"knowledge-{script.id}"
    safe_category = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', category.name).strip().rstrip('.') or f"category-{category.id}"
    date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    filename = f"{safe_category}_{safe_name}_{date}.pdf"
    return Response(export_knowledge_script_pdf(category, script), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})


@router.post("/projects/{project_id}/categories", status_code=201)
def create_category(project_id: int, payload: CategoryPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    parent_id = validate_parent(db, project_id, payload.parent_id)
    order = db.scalar(select(func.max(CommunicationScriptCategory.sort_order)).where(CommunicationScriptCategory.site_project_id == project_id, CommunicationScriptCategory.parent_id == parent_id)) or 0
    item = CommunicationScriptCategory(site_project_id=project_id, parent_id=parent_id, name=payload.name.strip(), sort_order=order + 1)
    db.add(item); db.commit(); db.refresh(item)
    return category_data(item)


@router.put("/projects/{project_id}/categories/{category_id}")
def update_category(project_id: int, category_id: int, payload: CategoryPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    item = category_for(db, project_id, category_id)
    old_parent = item.parent_id
    item.name, item.parent_id = payload.name.strip(), validate_parent(db, project_id, payload.parent_id, item.id)
    if old_parent != item.parent_id:
        item.sort_order = (db.scalar(select(func.max(CommunicationScriptCategory.sort_order)).where(CommunicationScriptCategory.site_project_id == project_id, CommunicationScriptCategory.parent_id == item.parent_id, CommunicationScriptCategory.id != item.id)) or 0) + 1
    db.commit(); db.refresh(item)
    return category_data(item)


@router.delete("/projects/{project_id}/categories/{category_id}")
def delete_category(project_id: int, category_id: int, confirmed: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db, 'knowledge_base')
    category_for(db, project_id, category_id)
    categories=list(db.scalars(select(CommunicationScriptCategory).where(CommunicationScriptCategory.site_project_id == project_id).with_for_update()))
    levels=[[category_id]];ids={category_id}
    while True:
        next_level=[item.id for item in categories if item.parent_id in levels[-1] and item.id not in ids]
        if not next_level:break
        levels.append(next_level);ids.update(next_level)
    script_scope=(CommunicationScript.site_project_id == project_id, CommunicationScript.category_id.in_(ids))
    script_count=db.scalar(select(func.count()).select_from(CommunicationScript).where(*script_scope))
    if not confirmed and (len(ids)>1 or script_count):
        raise HTTPException(409, '删除此分类会同时删除全部子分类和知识条目，请确认后再删除。')
    db.execute(CommunicationScript.__table__.delete().where(*script_scope))
    # Remove children before parents even when the database enforces self-FKs.
    for level in reversed(levels):
        db.execute(CommunicationScriptCategory.__table__.delete().where(CommunicationScriptCategory.site_project_id == project_id, CommunicationScriptCategory.id.in_(level)))
    db.commit()
    return {"deleted": True, "deleted_categories":len(ids), "deleted_scripts":script_count}


@router.post("/projects/{project_id}/categories/{category_id}/move")
def move_category(project_id: int, category_id: int, payload: MovePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    item = category_for(db, project_id, category_id)
    siblings = list(db.scalars(select(CommunicationScriptCategory).where(CommunicationScriptCategory.site_project_id == project_id, CommunicationScriptCategory.parent_id == item.parent_id).order_by(CommunicationScriptCategory.sort_order, CommunicationScriptCategory.id)))
    index = next(index for index, candidate in enumerate(siblings) if candidate.id == item.id); target = index - 1 if payload.direction == "up" else index + 1
    if 0 <= target < len(siblings): siblings[index], siblings[target] = siblings[target], siblings[index]
    for index, candidate in enumerate(siblings, 1): candidate.sort_order = index
    db.commit(); return {"moved": True}


@router.post("/projects/{project_id}/scripts", status_code=201)
def create_script(project_id: int, payload: ScriptPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db); category_for(db, project_id, payload.category_id)
    order = db.scalar(select(func.max(CommunicationScript.sort_order)).where(CommunicationScript.site_project_id == project_id, CommunicationScript.category_id == payload.category_id)) or 0
    item = CommunicationScript(site_project_id=project_id, category_id=payload.category_id, title=payload.title.strip(), content=payload.content.strip(), content_format=payload.content_format, content_html=payload.content_html if payload.content_format=="email" else "", sort_order=order + 1)
    db.add(item); db.commit(); db.refresh(item); return script_data(item)


@router.put("/projects/{project_id}/scripts/{script_id}")
def update_script(project_id: int, script_id: int, payload: ScriptPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db); item = script_for(db, project_id, script_id); category_for(db, project_id, payload.category_id)
    previous_content=item.content
    item.category_id, item.title, item.content = payload.category_id, payload.title.strip(), payload.content.strip()
    if "content_format" in payload.model_fields_set:
        item.content_format=payload.content_format
        item.content_html=payload.content_html if payload.content_format=="email" else ""
    elif previous_content != payload.content.strip():item.content_html=""
    db.commit(); db.refresh(item); return script_data(item)


@router.delete("/projects/{project_id}/scripts/{script_id}")
def delete_script(project_id: int, script_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db); db.delete(script_for(db, project_id, script_id)); db.commit(); return {"deleted": True}


@router.post("/projects/{project_id}/scripts/{script_id}/move")
def move_script(project_id: int, script_id: int, payload: MovePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_access(project_id, user, db)
    item = script_for(db, project_id, script_id)
    siblings = list(db.scalars(select(CommunicationScript).where(
        CommunicationScript.site_project_id == project_id,
        CommunicationScript.category_id == item.category_id,
    ).order_by(CommunicationScript.sort_order, CommunicationScript.id)))
    index = next(index for index, candidate in enumerate(siblings) if candidate.id == item.id)
    target = index - 1 if payload.direction == "up" else index + 1
    if 0 <= target < len(siblings):
        siblings[index], siblings[target] = siblings[target], siblings[index]
    for index, candidate in enumerate(siblings, 1):
        candidate.sort_order = index
    db.commit()
    return {"moved": True}
