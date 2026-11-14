"""Customer plans, scoped work queues and atomic completion into contact history."""
from datetime import date, datetime, time, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write
from app.models import Customer, CustomerPerson, ProjectContact, User, ContactRecord, WorkspaceMember
from app.models.follow_up import FollowUpPlan, utc_now
from app.routers.customer import top_admin, get_c

router = APIRouter(prefix='/api/followups/projects/{project_id}', tags=['Customer follow-up plans'])
CHINA = timezone(timedelta(hours=8))


class PlanPayload(BaseModel):
    title: str = Field(min_length=1, max_length=260)
    due_date: date | None = None
    due_at: datetime = Field(default_factory=utc_now)
    person_id: int | None = Field(default=None, gt=0)
    owner_user_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode='after')
    def date_only_schedule(self):
        if self.due_date is not None:
            self.due_at=datetime.combine(self.due_date,time.min,tzinfo=CHINA).astimezone(timezone.utc).replace(tzinfo=None)
        return self

    @field_validator('title')
    @classmethod
    def title_clean(cls, value):
        if not value.strip(): raise ValueError('请填写跟进事项。')
        return value.strip()

    @field_validator('due_at')
    @classmethod
    def utc_date(cls, value):
        return value.replace(tzinfo=value.tzinfo or CHINA).astimezone(timezone.utc).replace(tzinfo=None)


class CompletePayload(BaseModel):
    result: str = Field(min_length=1, max_length=20000)
    occurred_at: datetime
    channel: str = Field(default='邮件', min_length=1, max_length=40)
    next_plan: PlanPayload | None = None

    @field_validator('result', 'channel')
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError('请填写沟通渠道和跟进结果。')
        return value.strip()

    @field_validator('occurred_at')
    @classmethod
    def occurred(cls, value):
        value = PlanPayload.utc_date(value)
        if value > utc_now() + timedelta(minutes=5): raise ValueError('实际联系时间不能晚于当前时间。')
        return value


class CancelPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


def access(project_id, user, db, write=False):
    project = require_project_module(project_id, user, db, 'customer_list')
    if write: require_project_write(project_id, user, db, "customer_list")
    return project


def can_write(project_id, user, db):
    try:
        require_project_write(project_id, user, db, "customer_list")
        return True
    except HTTPException:
        return False


def customer_for(db, project_id, customer_id, user, lock=False):
    customer, rel = get_c(db, project_id, customer_id, None if top_admin(project_id, user, db) else user.id, status=None, lock=lock)
    if rel.status == 'pool': raise HTTPException(409, '客户已在公池，请恢复后重新安排跟进。')
    return customer, rel


def eligible_owners(db, project_id, customer, rel, user):
    project = access(project_id, user, db)
    ids = set(db.scalars(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == project.workspace_id)).all())
    result = []
    for candidate in db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)).order_by(User.display_name)):
        try:
            access(project_id, candidate, db, write=True)
            if candidate.id == rel.owner_user_id or top_admin(project_id, candidate, db):
                result.append({'id': candidate.id, 'name': candidate.display_name or candidate.email})
        except HTTPException:
            continue
    return result


def serialize(item, db, now=None):
    now = now or utc_now()
    customer = db.get(Customer, item.customer_id)
    owner = db.get(User, item.owner_user_id) if item.owner_user_id else None
    rel = db.scalar(select(ProjectContact).where(ProjectContact.site_project_id == item.site_project_id, ProjectContact.contact_id == item.customer_id))
    return {'id': item.id, 'customer_id': item.customer_id, 'company_name': customer.company or customer.name if customer else '已移除客户', 'title': item.title, 'due_at': item.due_at.isoformat()+'Z', 'due_date': (item.due_at.replace(tzinfo=timezone.utc).astimezone(CHINA).date()).isoformat(), 'person_id': item.person_id, 'contact_name': item.contact_name or '', 'owner_user_id': item.owner_user_id, 'owner_name': owner.display_name or owner.email if owner else '未分配', 'notes': item.notes or '', 'status': item.status, 'is_overdue': item.status == 'pending' and item.due_at.replace(tzinfo=timezone.utc).astimezone(CHINA).date() < now.replace(tzinfo=timezone.utc).astimezone(CHINA).date(), 'result': item.result or '', 'cancellation_reason': item.cancellation_reason or '', 'record_id': item.record_id, 'completed_at': item.completed_at.isoformat()+'Z' if item.completed_at else None, 'customer_in_pool': bool(rel and rel.status == 'pool')}


def assign(db, project_id, customer, rel, user, payload, item):
    wanted = payload.owner_user_id or user.id
    if not top_admin(project_id, user, db) and wanted != user.id:
        raise HTTPException(403, '只能为本人安排跟进。')
    if wanted not in {owner['id'] for owner in eligible_owners(db, project_id, customer, rel, user)}:
        raise HTTPException(422, '负责人需具备当前客户的访问和编辑权限。')
    person = db.get(CustomerPerson, payload.person_id) if payload.person_id else None
    if payload.person_id and (not person or person.customer_id != customer.id):
        raise HTTPException(422, '联系人不属于该客户，请重新选择。')
    item.title, item.due_at = payload.title, payload.due_at
    item.person_id = payload.person_id
    item.contact_name = person.contact_name if person else None
    item.owner_user_id = wanted
    item.notes = (payload.notes or '').strip() or None


def plan_for(db, project_id, plan_id, user, pending_only=True):
    item = db.scalar(select(FollowUpPlan).where(FollowUpPlan.id == plan_id, FollowUpPlan.site_project_id == project_id))
    if not item: raise HTTPException(404, '跟进计划不存在。')
    customer, rel = customer_for(db, project_id, item.customer_id, user, lock=True)
    item = db.scalar(select(FollowUpPlan).where(FollowUpPlan.id == plan_id).with_for_update().execution_options(populate_existing=True))
    if not item: raise HTTPException(404, '跟进计划不存在。')
    if not top_admin(project_id, user, db) and item.owner_user_id != user.id:
        raise HTTPException(403, '只能操作本人的跟进计划。')
    if pending_only and item.status != 'pending': raise HTTPException(409, '此计划已完成或取消，请刷新查看。')
    return item, customer, rel


@router.get('')
def listing(project_id: int, customer_id: int | None = None, scope: str = Query('mine', pattern='^(mine|all)$'), bucket: str = Query('pending', pattern='^(pending|today|overdue|future|completed|cancelled)$'), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db)
    admin = top_admin(project_id, user, db)
    q = select(FollowUpPlan).join(ProjectContact, (ProjectContact.site_project_id == FollowUpPlan.site_project_id) & (ProjectContact.contact_id == FollowUpPlan.customer_id)).where(FollowUpPlan.site_project_id == project_id)
    if customer_id:
        get_c(db, project_id, customer_id, None if admin else user.id)
        q = q.where(FollowUpPlan.customer_id == customer_id)
    if not admin: q = q.where(ProjectContact.owner_user_id == user.id, FollowUpPlan.owner_user_id == user.id)
    elif scope == 'mine': q = q.where(FollowUpPlan.owner_user_id == user.id)
    now = utc_now()
    midnight = datetime.combine(datetime.now(CHINA).date(), time.min, tzinfo=CHINA).astimezone(timezone.utc).replace(tzinfo=None)
    pending = (FollowUpPlan.status == 'pending') & ProjectContact.status.is_distinct_from('pool')
    conditions = {'pending': pending, 'today': pending & (FollowUpPlan.due_at >= midnight) & (FollowUpPlan.due_at < midnight+timedelta(days=1)), 'overdue': pending & (FollowUpPlan.due_at < midnight), 'future': pending & (FollowUpPlan.due_at >= midnight+timedelta(days=1)), 'completed': FollowUpPlan.status == 'completed', 'cancelled': FollowUpPlan.status == 'cancelled'}
    counts = {key: db.scalar(q.with_only_columns(func.count(), maintain_column_froms=True).where(condition)) for key, condition in conditions.items()}
    filtered = q.where(conditions[bucket])
    rows = db.scalars(filtered.order_by(FollowUpPlan.due_at.asc() if bucket in {'pending','today','overdue','future'} else FollowUpPlan.due_at.desc(), FollowUpPlan.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [serialize(row, db, now) for row in rows], 'counts': counts, 'total': counts[bucket], 'page': page, 'is_top_admin': admin, 'can_write': can_write(project_id, user, db)}


@router.get('/customers/{customer_id}/context')
def customer_context(project_id: int, customer_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db)
    customer, rel = customer_for(db, project_id, customer_id, user)
    people = db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id == customer_id)).all()
    return {'customer_id': customer_id, 'company_name': customer.company or customer.name, 'people': [{'id': row.id, 'name': row.contact_name or row.email or '未填写姓名'} for row in people], 'owners': eligible_owners(db, project_id, customer, rel, user), 'current_user_id': user.id, 'can_write': can_write(project_id, user, db)}


@router.post('/customers/{customer_id}', status_code=201)
def create(project_id: int, customer_id: int, payload: PlanPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db, write=True)
    customer, rel = customer_for(db, project_id, customer_id, user, lock=True)
    item = FollowUpPlan(site_project_id=project_id, customer_id=customer_id)
    assign(db, project_id, customer, rel, user, payload, item)
    db.add(item); db.commit(); db.refresh(item)
    return serialize(item, db)


@router.put('/{plan_id:int}')
def edit(project_id: int, plan_id: int, payload: PlanPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db, write=True)
    item, customer, rel = plan_for(db, project_id, plan_id, user)
    # Editing a simple todo must preserve metadata from existing scheduled plans.
    payload = PlanPayload.model_validate({
        'due_at': item.due_at.replace(tzinfo=timezone.utc),
        'owner_user_id': item.owner_user_id, 'person_id': item.person_id, 'notes': item.notes,
        **payload.model_dump(exclude_unset=True),
    })
    assign(db, project_id, customer, rel, user, payload, item)
    db.commit(); db.refresh(item)
    return serialize(item, db)


@router.post('/{plan_id:int}/complete')
def complete(project_id: int, plan_id: int, payload: CompletePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db, write=True)
    item, customer, rel = plan_for(db, project_id, plan_id, user)
    if payload.next_plan:
        next_item = FollowUpPlan(site_project_id=project_id, customer_id=customer.id)
        assign(db, project_id, customer, rel, user, payload.next_plan, next_item)
        db.add(next_item)
    local_time = payload.occurred_at.replace(tzinfo=timezone.utc).astimezone(CHINA).replace(tzinfo=None)
    record = ContactRecord(site_project_id=project_id, contact_id=customer.id, created_by_user_id=user.id, contact_name=item.contact_name, occurred_at=local_time, direction='outbound', channel=payload.channel, subject=item.title, content=payload.result)
    db.add(record); db.flush()
    item.status, item.result, item.completed_at, item.record_id = 'completed', payload.result, payload.occurred_at, record.id
    if customer.last_contact_date is None or customer.last_contact_date < local_time.date(): customer.last_contact_date = local_time.date()
    customer.updated_at = datetime.now()
    db.commit(); db.refresh(item)
    return serialize(item, db)


@router.post('/{plan_id:int}/cancel')
def cancel(project_id: int, plan_id: int, payload: CancelPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db, write=True)
    item, _, _ = plan_for(db, project_id, plan_id, user)
    item.status, item.cancellation_reason = 'cancelled', (payload.reason or '').strip() or None
    db.commit(); db.refresh(item)
    return serialize(item, db)


@router.delete('/{plan_id:int}')
def delete(project_id: int, plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access(project_id, user, db, write=True)
    item, _, _ = plan_for(db, project_id, plan_id, user, pending_only=False)
    # Remove the plan itself; completed contact records remain independent facts.
    db.delete(item)
    db.commit()
    return {'deleted': plan_id}
