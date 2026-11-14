"""Derive per-email outreach totals from durable delivery rows, never counters."""
from sqlalchemy import func, select
from app.models.mail import MailDelivery


def outreach_stats(db, project_id, lead_id):
    email = func.lower(MailDelivery.recipient)
    rows = db.execute(select(email.label('email'), func.count(MailDelivery.id).label('sent_count'),
        func.max(MailDelivery.accepted_at).label('last_sent_at')).where(
        MailDelivery.site_project_id == project_id, MailDelivery.lead_id == lead_id,
        MailDelivery.status == 'accepted').group_by(email)).all()
    return {row.email:{'sent_count':row.sent_count, 'last_sent_at':row.last_sent_at.isoformat() if row.last_sent_at else None} for row in rows}
