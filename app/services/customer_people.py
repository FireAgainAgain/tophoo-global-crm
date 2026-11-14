"""Keep customer people and the legacy primary-contact fields consistent."""
from datetime import datetime

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import insert, literal, select, update
from sqlalchemy.orm import Session

from app.models import Customer, CustomerPerson
from app.services.customer_social import SocialPayload, SOCIAL_FIELDS


class PersonPayload(SocialPayload):
    id: int | None = Field(default=None, gt=0)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=260)
    phone: str | None = Field(default=None, max_length=80)
    whatsapp: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=5000)
    is_primary: bool = False

    @field_validator("contact_name", "email", "phone", "whatsapp", "notes")
    @classmethod
    def trim(cls, value):
        return (value.strip() or None) if value else None

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
            raise ValueError("请输入有效的邮箱地址。")
        return value


def people_for(db: Session, customer_id: int) -> list[CustomerPerson]:
    return list(db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id == customer_id)
        .order_by(CustomerPerson.primary_slot.desc(), CustomerPerson.id)))


def person_data(person: CustomerPerson) -> dict:
    return {"id": person.id, "contact_name": person.contact_name or "", "email": person.email or "",
            "phone": person.phone or "", "whatsapp": person.whatsapp or "", "notes": person.notes or "",
            "is_primary": person.primary_slot == 1, **{key: getattr(person,key) or "" for key in SOCIAL_FIELDS}}


def people_by_customer(db: Session, customer_ids: list[int]) -> dict[int, list[CustomerPerson]]:
    grouped = {customer_id: [] for customer_id in customer_ids}
    if customer_ids:
        for person in db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id.in_(customer_ids))
                .order_by(CustomerPerson.primary_slot.desc(), CustomerPerson.id)):
            grouped[person.customer_id].append(person)
    return grouped


def legacy_person(customer: Customer) -> dict:
    return {"contact_name": customer.name or "", "email": customer.email or "", "phone": customer.phone or "",
            "whatsapp": customer.whatsapp or "", "notes": customer.other_channels or "", "is_primary": True}


def sync_primary(customer: Customer, person: CustomerPerson | None) -> None:
    customer.name = (person.contact_name if person else None) or customer.company or "未填写联系人"
    customer.email = person.email if person else None
    customer.phone = person.phone if person else None
    customer.whatsapp = person.whatsapp if person else None
    customer.other_channels = person.notes if person else None
    customer.people_initialized = True
    customer.updated_at = datetime.now()


def save_people(db: Session, customer: Customer, payloads: list[PersonPayload], deleted_ids=()) -> None:
    """Upsert people without removing omitted contacts. Caller locks the customer."""
    existing = {person.id: person for person in people_for(db, customer.id)}
    if len(deleted_ids) != len(set(deleted_ids)) or any(person_id not in existing for person_id in deleted_ids):
        raise HTTPException(422, "待删除的联系人不存在或不属于当前客户，请刷新后重试。")
    if any(person.id in deleted_ids for person in payloads):
        raise HTTPException(422, "不能同时修改和删除同一联系人。")
    remaining = {person_id: person for person_id, person in existing.items() if person_id not in deleted_ids}
    if not payloads:
        if remaining:
            raise HTTPException(422, "请保留主联系人。")
        for person in existing.values():
            db.delete(person)
        sync_primary(customer, None)
        db.flush()
        return
    if sum(person.is_primary for person in payloads) != 1:
        raise HTTPException(422, "请选择且仅选择一位主联系人。")
    ids = [person.id for person in payloads if person.id is not None]
    if len(ids) != len(set(ids)) or any(person_id not in existing for person_id in ids):
        raise HTTPException(422, "联系人不存在或不属于当前客户，请刷新后重试。")
    if len(remaining) + sum(person.id is None for person in payloads) > 100:
        raise HTTPException(422, "每个客户最多支持 100 位联系人。")
    # Clear the old primary first so the unique index remains valid during a switch.
    for person in existing.values():
        person.primary_slot = None
    db.flush()
    for person_id in deleted_ids:
        db.delete(existing[person_id])
    primary = None
    for payload in payloads:
        person = existing[payload.id] if payload.id is not None else CustomerPerson(customer_id=customer.id)
        for key in ("contact_name", "email", "phone", "whatsapp", "notes", *SOCIAL_FIELDS):
            if key not in SOCIAL_FIELDS or key in payload.model_fields_set:setattr(person, key, getattr(payload, key))
        person.primary_slot = 1 if payload.is_primary else None
        db.add(person)
        if payload.is_primary:
            primary = person
    sync_primary(customer, primary)
    db.flush()


def save_legacy_primary(db: Session, customer: Customer) -> None:
    """Older clients and lead conversion edit only the primary contact."""
    people = people_for(db, customer.id)
    primary = next((person for person in people if person.primary_slot == 1), None)
    if primary is None:
        primary = CustomerPerson(customer_id=customer.id, primary_slot=1)
        db.add(primary)
    data = legacy_person(customer)
    for key in ("contact_name", "email", "phone", "whatsapp", "notes", *SOCIAL_FIELDS):
        if key not in SOCIAL_FIELDS:setattr(primary, key, data[key] or None)
    customer.people_initialized = True
    db.flush()


def ensure_customer_people_schema(engine) -> None:
    """Add the new table and copy legacy people once, without changing old fields."""
    CustomerPerson.__table__.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(insert(CustomerPerson).from_select(
            ['customer_id', 'contact_name', 'email', 'phone', 'whatsapp', 'notes', 'primary_slot', 'created_at', 'updated_at'],
            select(Customer.id, Customer.name, Customer.email, Customer.phone, Customer.whatsapp,
                   Customer.other_channels, literal(1), Customer.created_at, Customer.updated_at)
            .where(Customer.people_initialized.is_(False), ~select(CustomerPerson.id).where(CustomerPerson.customer_id == Customer.id).exists())))
        connection.execute(update(Customer).where(Customer.people_initialized.is_(False)).values(people_initialized=True))


def mutate_person(db, customer, operation, person_id=None, payload=None, replacement_id=None):
    """Change one person under the customer lock, preserving all other people."""
    people = people_for(db, customer.id)
    person = next((item for item in people if item.id == person_id), None)
    if operation != 'add' and person is None:
        raise HTTPException(404, "联系人不存在或不属于当前客户。")
    primary = next((item for item in people if item.primary_slot == 1), None)
    if operation == 'add':
        if len(people) >= 100:
            raise HTTPException(422, "每个客户最多支持 100 位联系人。")
        person = CustomerPerson(customer_id=customer.id)
        db.add(person)
    if operation in {'add', 'edit'}:
        for key in ('contact_name', 'email', 'phone', 'whatsapp', 'notes', *SOCIAL_FIELDS):
            if key not in SOCIAL_FIELDS or key in payload.model_fields_set:setattr(person, key, getattr(payload, key))
    if operation == 'delete':
        remaining = [item for item in people if item.id != person_id]
        if person is primary and remaining:
            primary = next((item for item in remaining if item.id == replacement_id), None)
            if primary is None:
                raise HTTPException(422, "删除主联系人前，请选择接替的主联系人。")
        elif person is primary:
            primary = None
        if replacement_id is not None and (person.primary_slot != 1 or not remaining):
            raise HTTPException(422, "当前删除操作不需要指定接替联系人。")
        person.primary_slot = None
        db.flush()
        db.delete(person)
    elif operation == 'primary' or (operation in {'add', 'edit'} and (payload.is_primary or primary is None)):
        if primary and primary is not person:
            primary.primary_slot = None
            db.flush()
        primary = person
    if primary:
        primary.primary_slot = 1
    sync_primary(customer, primary)
    db.flush()
