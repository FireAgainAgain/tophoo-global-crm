"""A shared editable follow-up note backed by the existing CRM history."""
from datetime import datetime
from hashlib import sha256

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models import ContactRecord, LeadInteraction

NOTE_CHANNEL = '跟进正文'


class FollowupNote(BaseModel):
    content: str = Field(max_length=4000000)
    revision: str


def followup_rows(db, project_id, entity_id, lead=False, lock=False):
    model, key = (LeadInteraction, LeadInteraction.lead_id) if lead else (ContactRecord, ContactRecord.contact_id)
    query = select(model).where(
        model.site_project_id == project_id, key == entity_id,
    ).order_by(model.id)
    return db.scalars(query.with_for_update() if lock else query).all()


def note_data(rows):
    content = ''
    for row in rows:
        if row.channel == NOTE_CHANNEL:
            content = row.content
            continue
        part = '\n'.join(filter(None, (row.subject, row.content, row.content_translation)))
        content = '\n\n'.join(filter(None, (content, part)))
    return document(content)


def document(content):
    return {'content': content, 'revision': sha256(content.encode()).hexdigest()}


def check_revision(rows, revision):
    if note_data(rows)['revision'] != revision:
        raise HTTPException(409, '跟进已更新，请重新打开后再保存。')


def write_note(db, rows, project_id, entity_id, content, user_id, lead=False):
    if rows and rows[-1].channel == NOTE_CHANNEL:
        rows[-1].content = content
    else:
        model, key = (LeadInteraction, 'lead_id') if lead else (ContactRecord, 'contact_id')
        db.add(model(site_project_id=project_id, created_by_user_id=user_id,
                     channel=NOTE_CHANNEL, occurred_at=datetime.now(), direction='outbound', content=content, **{key: entity_id}))
    db.flush()
    return document(content)
