"""Retire outcome states; quotations track only preparation and issue."""
from sqlalchemy import update
from app.models import Quotation


def migrate_quotation_statuses(db):
    db.execute(update(Quotation).where(Quotation.status.in_(['已成交', '已关闭'])).values(
        status='已报价', revision=Quotation.revision + 1,
    ))
