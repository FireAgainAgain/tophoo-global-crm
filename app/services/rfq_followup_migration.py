"""Move legacy RFQ follow-up notes to the owning customer's history."""
from datetime import datetime, time
import re

from sqlalchemy import or_, select

from app.models import ContactRecord, ProjectContact, Rfq


def move_rfq_followup(db, item):
    content = item.notes or ''
    if not content.strip() and not item.next_action_date:
        return False
    relation = db.scalar(select(ProjectContact).where(
        ProjectContact.site_project_id == item.site_project_id,
        ProjectContact.contact_id == item.contact_id,
    ))
    if relation is None:
        return False

    occurred = item.updated_at or item.created_at or datetime.now()
    match = re.match(r'^【([0-9]{8})】', content)
    if match:
        try:
            occurred = datetime.strptime(match[1], '%Y%m%d')
        except ValueError:
            pass
    elif item.inquiry_date:
        occurred = datetime.combine(item.inquiry_date, time.min)
    if item.next_action_date:
        content = '\n\n'.join(filter(None, [content, f'原询价跟进日期：{item.next_action_date:%Y-%m-%d}']))
    db.add(ContactRecord(
        site_project_id=item.site_project_id,
        contact_id=relation.contact_id,
        occurred_at=occurred,
        direction='outbound',
        channel='询价',
        subject=f'询价 {item.number} · 历史跟进',
        content=content,
    ))
    item.notes = None
    item.next_action_date = None
    return True


def migrate_rfq_followups(db):
    rows = db.scalars(select(Rfq).where(
        or_(Rfq.notes.is_not(None), Rfq.next_action_date.is_not(None)),
    ).order_by(Rfq.id).with_for_update()).all()
    moved = sum(move_rfq_followup(db, item) for item in rows)
    db.commit()
    return moved
