"""Task lifecycle helpers run inside the caller's business transaction."""
from sqlalchemy import select
from app.models.follow_up import FollowUpPlan, utc_now


def cancel_pending(db, project_id, customer_id, reason):
    rows = db.scalars(select(FollowUpPlan).where(FollowUpPlan.site_project_id == project_id, FollowUpPlan.customer_id == customer_id, FollowUpPlan.status == 'pending').with_for_update()).all()
    for row in rows:
        row.status = 'cancelled'
        row.cancellation_reason = reason
        row.updated_at = utc_now()


def transfer_pending(db, project_id, customer_id, owner_id, transfer=True):
    if not transfer or owner_id is None:
        return cancel_pending(db, project_id, customer_id, '客户归属变更，原跟进计划已取消')
    rows = db.scalars(select(FollowUpPlan).where(FollowUpPlan.site_project_id == project_id, FollowUpPlan.customer_id == customer_id, FollowUpPlan.status == 'pending').with_for_update()).all()
    for row in rows:
        row.owner_user_id = owner_id
        row.updated_at = utc_now()
