"""RFQ ownership changes share the customer's transaction, never its contact snapshot."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models import ProjectContact, ProjectMember, Rfq, User

FINAL_STATUSES = ('已成交', '已关闭', '沟通失败')


def project_owners(db, project_id):
    users = db.scalars(select(User).join(ProjectMember, ProjectMember.user_id == User.id).where(
        ProjectMember.site_project_id == project_id, ProjectMember.is_active.is_(True)
    ).order_by(User.display_name, User.email)).all()
    return [{'id': user.id, 'name': user.display_name or user.email} for user in users]


def assign_owner(db, project_id, user, payload, admin, item=None):
    explicit = 'owner_user_id' in payload.model_fields_set
    if explicit and not admin:
        if payload.owner_user_id != (item.owner_user_id if item else user.id):
            raise HTTPException(403, '只有管理员可以调整 RFQ 归属。')
    if explicit and admin and payload.owner_user_id is not None:
        if payload.owner_user_id not in {entry['id'] for entry in project_owners(db, project_id)}:
            raise HTTPException(422, '归属用户不是当前项目成员。')
        return payload.owner_user_id
    if item and item.contact_id == payload.contact_id:
        return item.owner_user_id
    if payload.contact_id is not None:
        relation = db.scalar(select(ProjectContact).where(
            ProjectContact.site_project_id == project_id, ProjectContact.contact_id == payload.contact_id
        ).with_for_update())
        if relation and relation.owner_user_id is not None:
            return relation.owner_user_id
    return user.id if item is None else item.owner_user_id


def transfer_open_rfqs(db, project_id, customer_id, owner_id):
    rows = db.scalars(select(Rfq).where(
        Rfq.site_project_id == project_id, Rfq.contact_id == customer_id,
        Rfq.status.not_in(FINAL_STATUSES)
    ).with_for_update()).all()
    for item in rows:
        item.owner_user_id = owner_id
