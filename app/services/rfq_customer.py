"""Live company facts and stable, server-generated RFQ contact snapshots."""
import json
from fastapi import HTTPException
from app.models import CustomerPerson
from app.services.company_type import company_type_label
from app.services.customer_people import people_by_customer, person_data

SOCIALS = ('linkedin', 'facebook', 'instagram', 'youtube')


def customer_reference(contact, relation, people):
    return {
        'id': contact.id, 'people_initialized':contact.people_initialized, 'name': contact.name, 'company': contact.company or '',
        **{key: getattr(contact, key) or '' for key in (
            'country', 'company_website', 'company_address', 'job_title', 'phone', 'email',
            'whatsapp', 'company_type', *(f'company_{key}' for key in SOCIALS))},
        'company_type_label': company_type_label(contact.company_type),
        'source': relation.source or contact.source or '',
        'people': [{key: value for key, value in person_data(person).items() if key != 'notes'} for person in people],
    }


def contact_details(item, contact):
    try:
        snapshot = json.loads(item.contact_snapshot_json or '{}')
    except (TypeError, json.JSONDecodeError):
        snapshot = {}
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    return {key: (getattr(contact, attr, '') or '') if contact else '' for key, attr in (
        ('contact_name', 'name'), ('email', 'email'), ('phone', 'phone'),
        ('whatsapp', 'whatsapp'), ('job_title', 'job_title'))}


def save_contact_snapshot(db, item, payload, contact):
    """Validate person ownership before changing the RFQ; preserve unchanged snapshots."""
    if not contact:
        if payload.contact_person_id is not None:
            raise HTTPException(422, '请先选择联系人所属的客户。')
        item.contact_person_id = None
        item.contact_snapshot_json = None
        return
    same_customer = item.contact_id == contact.id
    explicit = 'contact_person_id' in payload.model_fields_set
    if same_customer and item.contact_snapshot_json and (
        not explicit or payload.contact_person_id == item.contact_person_id
    ):
        return
    person = None
    if payload.contact_person_id is not None:
        person = db.get(CustomerPerson, payload.contact_person_id)
        if not person or person.customer_id != contact.id:
            raise HTTPException(422, '对接联系人不存在或不属于当前客户，请重新选择。')
    else:
        people = people_by_customer(db, [contact.id])[contact.id]
        person = next((entry for entry in people if entry.primary_slot == 1), None)
    snapshot = person_data(person) if person else {
        'contact_name': contact.name or '', 'email': contact.email or '',
        'phone': contact.phone or '', 'whatsapp': contact.whatsapp or '',
    }
    # Person remarks remain internal to customer records, never part of RFQ exports.
    snapshot = {key: snapshot.get(key, '') for key in ('contact_name', 'email', 'phone', 'whatsapp', *SOCIALS)}
    snapshot['job_title'] = (contact.job_title or '') if not person or person.primary_slot == 1 else ''
    item.contact_person_id = person.id if person else None
    item.contact_snapshot_json = json.dumps(snapshot, ensure_ascii=False)


def customer_fields(item, contact):
    details = contact_details(item, contact)
    return {
        'contact_person_id': item.contact_person_id,
        'contact_snapshot_saved': bool(item.contact_snapshot_json),
        **{f'contact_{key}': details.get(key, '') for key in ('email', 'phone', 'whatsapp', 'job_title', *SOCIALS)},
        'contact_name': details.get('contact_name', ''),
        'company_type': (contact.company_type or '') if contact else '',
        'company_type_label': company_type_label(contact.company_type) if contact else '',
        **{f'company_{key}': (getattr(contact, f'company_{key}') or '') if contact else '' for key in SOCIALS},
    }
