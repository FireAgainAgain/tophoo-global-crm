"""One bilingual social set per physical MIC product, preserving earlier title drafts."""
import json
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.services.mic_social import CONTACT, PLATFORMS, PlatformDraft, storage
from app.services.mic_product_labels import display_mic_code


class ProductSocialPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', max_length=1000)
    parameters: str = Field(default='', max_length=16000)
    contact: str = Field(default=CONTACT, max_length=2000)
    platforms: dict[Literal['facebook', 'instagram', 'linkedin', 'youtube'], PlatformDraft] = Field(default_factory=dict)


def document(product):
    stored = storage(product)
    saved = stored.get('product_draft', {})
    titles = json.loads(product.titles_json or '[]')
    return {'title': saved.get('title', product.english_title or (titles[0]['title'] if titles else product.product_name)),
            'parameters': saved.get('parameters', ''), 'contact': saved.get('contact', CONTACT),
            'platforms': {p: {**PlatformDraft().model_dump(), **saved.get('platforms', {}).get(p, stored.get(p, {}))} for p in PLATFORMS},
            'updated_at': saved.get('updated_at', ''), 'product_code': display_mic_code(product.product_code),
            'product_name': product.product_name,
            'name_changed': bool(saved.get('product_name') and saved['product_name'] != product.product_name)}


def summary(product):
    return {p: {'total': 1, 'published': int(bool(entry['published'])),
                'ready': int(bool(entry['content'].strip()))} for p, entry in document(product)['platforms'].items()}


def save(product, payload):
    before = document(product)
    saved = {key: before[key] for key in ('title', 'parameters', 'contact', 'platforms')}
    for key in ('title', 'parameters', 'contact'):
        if key in payload.model_fields_set:
            saved[key] = getattr(payload, key)
    for platform, entry in payload.platforms.items():
        merged = {**saved['platforms'][platform], **entry.model_dump(exclude_unset=True)}
        saved['platforms'][platform] = PlatformDraft.model_validate(merged).model_dump()
    saved['product_name'] = product.product_name
    saved['updated_at'] = datetime.now().isoformat(timespec='seconds')
    stored = storage(product)
    stored['product_draft'] = saved
    encoded = json.dumps(stored, ensure_ascii=False)
    if len(encoded.encode('utf-8')) > 15000000:
        raise HTTPException(422, '此产品的社媒资料过大，请减少文案长度。')
    product.social_json = encoded
