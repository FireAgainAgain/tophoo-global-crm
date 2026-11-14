"""Portable company contacts for prospects, leads and discovery results."""
import json
from fastapi import HTTPException
from sqlalchemy import inspect, text
from app.services.customer_people import PersonPayload
from app.services.customer_social import SOCIAL_FIELDS

FIELDS = ('contact_name', 'email', 'phone', 'whatsapp', 'notes', *SOCIAL_FIELDS)

def normalize_people(values):
    result = []
    for value in values:
        person = value if isinstance(value, PersonPayload) else PersonPayload(**value)
        data = {key: getattr(person, key) or '' for key in FIELDS}
        if not any(data.values()):
            continue
        data['is_primary'] = person.is_primary
        if data['email'] and any(p['email'].casefold() == data['email'].casefold() for p in result):
            raise HTTPException(422, '同一企业的联系人邮箱不能重复。')
        result.append(data)
    if len(result) > 100:
        raise HTTPException(422, '每个企业最多支持 100 位联系人。')
    if sum(p['is_primary'] for p in result) > 1:
        raise HTTPException(422, '只能设置一位主联系人。')
    if result and not any(p['is_primary'] for p in result):
        result[0]['is_primary'] = True
    return sorted(result, key=lambda p: not p['is_primary'])

def workflow_people(item):
    if item.contacts_json is not None:
        return [{**{key:"" for key in FIELDS},**person} for person in json.loads(item.contacts_json)]
    data = {key: getattr(item, key, None) or '' for key in FIELDS if key != 'notes'}
    data['notes'] = getattr(item, 'other_channels', None) or ''
    return normalize_people([data])

def set_workflow_people(item, values):
    people = normalize_people(values)
    item.contacts_json = json.dumps(people, ensure_ascii=False)
    primary = people[0] if people else {}
    for key in ('contact_name', 'email', 'phone', 'whatsapp'):
        if hasattr(item, key):
            setattr(item, key, primary.get(key) or None)
    if hasattr(item, 'other_channels'):
        item.other_channels = primary.get('notes') or None

def ensure_workflow_people_schema(engine):
    with engine.begin() as connection:
        for table in ('crm_prospecting_entries', 'crm_leads', 'crm_prospecting_candidates'):
            if 'contacts_json' not in {c['name'] for c in inspect(connection).get_columns(table)}:
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN contacts_json TEXT NULL'))
