"""Contact interaction history and Markdown exports."""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write as require_write_permission
from app.models import ContactRecord, Customer, ProjectContact, User
from app.services.contact_record_pdf import export_contact_records_pdf
from app.routers.customer import get_c, top_admin
from app.services.followup_note import FollowupNote, check_revision, followup_rows, note_data, write_note
from app.services.contact_record_fields import ContactRecordPayload, clean, clean_record_content, record_data, save_record as save
from app.services.customer_people import people_for, person_data


router = APIRouter(tags=["CRM contact records"])

def require_project_access(project_id, user, db): return require_project_module(project_id, user, db, "customer_list")
def require_project_write(project_id, user, db):
    require_project_module(project_id,user,db,"customer_list")
    return require_write_permission(project_id,user,db,"customer_list")


def contact_for(db: Session, project_id: int, contact_id: int, user: User) -> Customer:
    query = (select(Customer)
        .join(ProjectContact, ProjectContact.contact_id == Customer.id)
        .where(Customer.id == contact_id, ProjectContact.site_project_id == project_id))
    if not top_admin(project_id, user, db):
        query = query.where(ProjectContact.owner_user_id == user.id)
    item = db.scalar(query)
    if not item:
        raise HTTPException(404, "联系人不存在。")
    return item


def markdown_text(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def markdown_quote(value: str | None) -> list[str]:
    """Keep original and translated text visually separate in rendered Markdown."""
    return [f"> {line}" if line else ">" for line in markdown_text(value).split("\n")]


def markdown_original_block(value: str | None) -> list[str]:
    """Render the source message as a monospaced block without altering its text."""
    return [f"    {line}" if line else "    " for line in markdown_text(value).split("\n")]


@router.get("/api/contacts/projects/{project_id}/{contact_id}/records")
def list_records(project_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    records = db.scalars(select(ContactRecord).where(ContactRecord.site_project_id == project_id, ContactRecord.contact_id == contact_id).order_by(ContactRecord.occurred_at.desc(), ContactRecord.id.desc())).all()
    return {"contact": {"id": contact.id, "name": contact.name, "company_name": contact.company or "", "company_website": contact.company_website or "", "company_address": contact.company_address or "", "email": contact.email or "", "phone": contact.phone or "", "whatsapp": contact.whatsapp or "", "contacts": [person_data(person) for person in people_for(db,contact.id)]}, "records": [record_data(item, db) for item in records]}


@router.post("/api/contacts/projects/{project_id}/{contact_id}/records", status_code=201)
def create_record(project_id: int, contact_id: int, payload: ContactRecordPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    item = ContactRecord(site_project_id=project_id, contact_id=contact_id, created_by_user_id=user.id, contact_name=contact.name)
    save(item, payload)
    db.add(item)
    contact.updated_at = datetime.now()
    db.commit(); db.refresh(item)
    return record_data(item, db)


@router.put("/api/contacts/projects/{project_id}/{contact_id}/records/{record_id}")
def update_record(project_id: int, contact_id: int, record_id: int, payload: ContactRecordPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    item = db.scalar(select(ContactRecord).where(ContactRecord.id == record_id, ContactRecord.site_project_id == project_id, ContactRecord.contact_id == contact_id))
    if not item:
        raise HTTPException(404, "跟进不存在。")
    save(item, payload)
    contact.updated_at = datetime.now(); db.commit()
    db.refresh(item)
    return record_data(item, db)


@router.delete("/api/contacts/projects/{project_id}/{contact_id}/records/{record_id}")
def delete_record(project_id: int, contact_id: int, record_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    item = db.scalar(select(ContactRecord).where(ContactRecord.id == record_id, ContactRecord.site_project_id == project_id, ContactRecord.contact_id == contact_id))
    if not item:
        raise HTTPException(404, "跟进不存在。")
    db.delete(item)
    contact.updated_at = datetime.now(); db.commit()
    return {"deleted": True}


@router.get("/api/contacts/projects/{project_id}/{contact_id}/records/export/md")
def export_records_markdown(project_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    records = db.scalars(select(ContactRecord).where(ContactRecord.site_project_id == project_id, ContactRecord.contact_id == contact_id).order_by(ContactRecord.occurred_at.asc(), ContactRecord.id.asc())).all()
    lines = [f"# {markdown_text(contact.name)} 的跟进", "", "## 客户", f"- 公司名称：{markdown_text(contact.company or '未填写')}", f"- 官网：{markdown_text(contact.company_website)}", f"- 公司地址：{markdown_text(contact.company_address)}", f"- 邮箱：{markdown_text(contact.email)}", f"- 电话：{markdown_text(contact.phone)}", "", "## 记录"]
    for index, item in enumerate(records, 1):
        if item.subject:lines.extend(["", f"**标题：{markdown_text(item.subject)}**"])
        lines.extend(["", f"### {index}. {item.occurred_at:%Y-%m-%d} · 联系人：{markdown_text(item.contact_name or '未填写')} · {markdown_text(item.channel)}", "", "**内容**", "", *markdown_original_block(item.content)])
        if item.content_translation:
            lines.extend(["", "**历史翻译（保留）**", "", *markdown_quote(item.content_translation)])
    if not records:
        lines.extend(["", "暂无跟进。"])
    safe_name = "".join("_" if char in '\\/:*?\"<>|' else char for char in contact.name).strip() or "联系人"
    filename = quote(f"{safe_name}_跟进.md")
    return Response("\n".join(lines) + "\n", media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.get("/api/contacts/projects/{project_id}/{contact_id}/records/export/pdf")
def export_records_pdf(project_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    contact = contact_for(db, project_id, contact_id, user)
    records = db.scalars(select(ContactRecord).where(ContactRecord.site_project_id == project_id, ContactRecord.contact_id == contact_id).order_by(ContactRecord.occurred_at.asc(), ContactRecord.id.asc())).all()
    safe_name = "".join("_" if char in '\\/:*?\"<>|' else char for char in contact.name).strip() or "联系人"
    return Response(export_contact_records_pdf(contact, records), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{safe_name}_跟进.pdf')}"})


@router.get("/api/contacts/projects/{project_id}/{contact_id}/followup-note")
def get_followup_note(project_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    contact_for(db, project_id, contact_id, user)
    return note_data(followup_rows(db, project_id, contact_id))


@router.put("/api/contacts/projects/{project_id}/{contact_id}/followup-note")
def save_followup_note(project_id: int, contact_id: int, payload: FollowupNote, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db)
    contact, _ = get_c(db, project_id, contact_id, None if top_admin(project_id, user, db) else user.id, lock=True)
    rows = followup_rows(db, project_id, contact_id, lock=True)
    check_revision(rows, payload.revision)
    result = write_note(db, rows, project_id, contact_id, payload.content, user.id)
    contact.updated_at = datetime.now()
    db.commit()
    return result
