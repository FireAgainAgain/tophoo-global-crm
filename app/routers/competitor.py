"""Competitor research APIs, scoped to the selected CRM project."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module
from app.models import Competitor, CompetitorKeyword, CompetitorWebsite, SiteProject, User
from app.services.competitor_pdf import export_competitor_pdf, export_competitors_pdf

router = APIRouter(prefix="/api/competitors", tags=["Competitor research"])


class CompetitorPayload(BaseModel):
    name: str = Field(min_length=1, max_length=220)
    country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=12000)


class MovePayload(BaseModel):
    direction: str = Field(pattern=r"^(up|down)$")


class WebsitePayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=1000)
    website_type: str | None = Field(default=None, max_length=80)


class KeywordPayload(BaseModel):
    keyword: str = Field(min_length=1, max_length=300)
    language: str | None = Field(default=None, max_length=30)
    category: str | None = Field(default=None, max_length=80)


def clean(value: str | None) -> str | None:
    value = value.strip() if value else ""
    return value or None


def guard(project_id: int, user: User, db: Session) -> None:
    require_project_module(project_id, user, db, "competitor_research")


def competitor_for(db: Session, project_id: int, competitor_id: int) -> Competitor:
    item = db.scalar(select(Competitor).where(Competitor.id == competitor_id, Competitor.site_project_id == project_id))
    if not item:
        raise HTTPException(404, "竞品不存在。")
    return item


def item_payload(db: Session, item: Competitor) -> dict[str, object]:
    websites = list(db.scalars(select(CompetitorWebsite).where(CompetitorWebsite.competitor_id == item.id).order_by(CompetitorWebsite.id)))
    keywords = list(db.scalars(select(CompetitorKeyword).where(CompetitorKeyword.competitor_id == item.id).order_by(CompetitorKeyword.id)))
    return {
        "id": item.id, "name": item.name, "country": item.country or "", "notes": item.notes or "",
        "sort_order": item.sort_order, "updated_at": item.updated_at.isoformat() if item.updated_at else "",
        "websites": [{"id": value.id, "name": value.name, "url": value.url, "website_type": value.website_type or ""} for value in websites],
        "keywords": [{"id": value.id, "keyword": value.keyword, "language": value.language or "", "category": value.category or ""} for value in keywords],
    }


@router.get("/projects/{project_id}")
def list_competitors(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    guard(project_id, user, db)
    items = db.scalars(select(Competitor).where(Competitor.site_project_id == project_id).order_by(Competitor.sort_order, Competitor.id)).all()
    return [item_payload(db, item) for item in items]


@router.post("/projects/{project_id}", status_code=201)
def create_competitor(project_id: int, payload: CompetitorPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guard(project_id, user, db)
    order = db.scalar(select(func.max(Competitor.sort_order)).where(Competitor.site_project_id == project_id)) or 0
    item = Competitor(site_project_id=project_id, name=payload.name.strip(), country=clean(payload.country), notes=clean(payload.notes), sort_order=order + 1)
    db.add(item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "当前项目已存在同名竞品。")
    db.refresh(item)
    return item_payload(db, item)


@router.put("/projects/{project_id}/{competitor_id}")
def update_competitor(project_id: int, competitor_id: int, payload: CompetitorPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guard(project_id, user, db)
    item = competitor_for(db, project_id, competitor_id)
    item.name, item.country, item.notes = payload.name.strip(), clean(payload.country), clean(payload.notes)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "当前项目已存在同名竞品。")
    db.refresh(item)
    return item_payload(db, item)


@router.post("/projects/{project_id}/{competitor_id}/move")
def move_competitor(project_id: int, competitor_id: int, payload: MovePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    guard(project_id, user, db)
    item = competitor_for(db, project_id, competitor_id)
    siblings = list(db.scalars(select(Competitor).where(Competitor.site_project_id == project_id).order_by(Competitor.sort_order, Competitor.id)))
    index = next(position for position, candidate in enumerate(siblings) if candidate.id == item.id)
    target = index - 1 if payload.direction == "up" else index + 1
    if 0 <= target < len(siblings):
        siblings[index], siblings[target] = siblings[target], siblings[index]
        for order, candidate in enumerate(siblings, 1):
            candidate.sort_order = order
        db.commit()
    return [item_payload(db, candidate) for candidate in siblings]


@router.get("/projects/{project_id}/export/pdf")
def export_competitors_as_pdf(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    guard(project_id, user, db)
    project = db.scalar(select(SiteProject).where(SiteProject.id == project_id))
    items = list(db.scalars(select(Competitor).where(Competitor.site_project_id == project_id).order_by(Competitor.sort_order, Competitor.id)))
    records = [
        (
            item,
            list(db.scalars(select(CompetitorWebsite).where(CompetitorWebsite.competitor_id == item.id).order_by(CompetitorWebsite.id))),
            list(db.scalars(select(CompetitorKeyword).where(CompetitorKeyword.competitor_id == item.id).order_by(CompetitorKeyword.id))),
        )
        for item in items
    ]
    project_name = (project.name if project else "项目").replace("\r", " ").replace("\n", " ").strip() or "项目"
    filename = f"{project_name}_竞品档案汇总.pdf"
    return Response(export_competitors_pdf(project_name, records), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})


@router.get("/projects/{project_id}/{competitor_id}/export/pdf")
def export_competitor_as_pdf(project_id: int, competitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    guard(project_id, user, db)
    item = competitor_for(db, project_id, competitor_id)
    websites = list(db.scalars(select(CompetitorWebsite).where(CompetitorWebsite.competitor_id == item.id).order_by(CompetitorWebsite.id)))
    keywords = list(db.scalars(select(CompetitorKeyword).where(CompetitorKeyword.competitor_id == item.id).order_by(CompetitorKeyword.id)))
    safe_name = item.name.replace("\r", " ").replace("\n", " ").strip() or f"competitor-{item.id}"
    filename = f"{safe_name}_竞品档案.pdf"
    return Response(export_competitor_pdf(item, websites, keywords), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})


@router.delete("/projects/{project_id}/{competitor_id}")
def delete_competitor(project_id: int, competitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    # Keep the research note, but remove the pointer before deleting its master.
    guard(project_id, user, db)
    item = competitor_for(db, project_id, competitor_id)
    db.query(CompetitorWebsite).filter(CompetitorWebsite.competitor_id == item.id).delete()
    db.query(CompetitorKeyword).filter(CompetitorKeyword.competitor_id == item.id).delete()
    db.delete(item); db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/{competitor_id}/websites", status_code=201)
def add_website(project_id: int, competitor_id: int, payload: WebsitePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guard(project_id, user, db); item = competitor_for(db, project_id, competitor_id)
    value = CompetitorWebsite(competitor_id=item.id, name=payload.name.strip(), url=payload.url.strip(), website_type=clean(payload.website_type))
    db.add(value)
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(409, "该网站已存在。")
    return item_payload(db, item)


@router.put("/projects/{project_id}/{competitor_id}/websites/{website_id}")
def update_website(project_id: int, competitor_id: int, website_id: int, payload: WebsitePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guard(project_id, user, db); item = competitor_for(db, project_id, competitor_id)
    value = db.scalar(select(CompetitorWebsite).where(CompetitorWebsite.id == website_id, CompetitorWebsite.competitor_id == competitor_id))
    if not value: raise HTTPException(404, "竞品网站不存在。")
    value.name, value.url, value.website_type = payload.name.strip(), payload.url.strip(), None
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(409, "该网站已存在。")
    return item_payload(db, item)


@router.delete("/projects/{project_id}/{competitor_id}/websites/{website_id}")
def delete_website(project_id: int, competitor_id: int, website_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    guard(project_id, user, db); competitor_for(db, project_id, competitor_id)
    value = db.scalar(select(CompetitorWebsite).where(CompetitorWebsite.id == website_id, CompetitorWebsite.competitor_id == competitor_id))
    if not value: raise HTTPException(404, "竞品网站不存在。")
    db.delete(value); db.commit(); return {"deleted": True}


@router.post("/projects/{project_id}/{competitor_id}/keywords", status_code=201)
def add_keyword(project_id: int, competitor_id: int, payload: KeywordPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guard(project_id, user, db); item = competitor_for(db, project_id, competitor_id)
    value = CompetitorKeyword(competitor_id=item.id, keyword=payload.keyword.strip(), language=clean(payload.language), category=clean(payload.category))
    db.add(value)
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(409, "该关键词已存在。")
    return item_payload(db, item)


@router.delete("/projects/{project_id}/{competitor_id}/keywords/{keyword_id}")
def delete_keyword(project_id: int, competitor_id: int, keyword_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    guard(project_id, user, db); competitor_for(db, project_id, competitor_id)
    value = db.scalar(select(CompetitorKeyword).where(CompetitorKeyword.id == keyword_id, CompetitorKeyword.competitor_id == competitor_id))
    if not value: raise HTTPException(404, "竞品关键词不存在。")
    db.delete(value); db.commit(); return {"deleted": True}
