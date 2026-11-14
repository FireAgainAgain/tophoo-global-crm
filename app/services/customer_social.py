"""Company and person social links shared by the CRM workflow."""
from urllib.parse import urlsplit
import re
from pydantic import BaseModel, Field, field_validator
from app.services.company_type import CompanyTypePayload
from sqlalchemy import inspect, text

SOCIAL_FIELDS = ('linkedin', 'facebook', 'instagram', 'youtube')
COMPANY_SOCIAL_FIELDS = tuple('company_' + key for key in SOCIAL_FIELDS)

def social_url(value):
    value = (value or '').strip()
    if not value:
        return None
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',value) and not value.lower().startswith(('http://','https://')):
        raise ValueError('请输入 HTTP 或 HTTPS 主页链接。')
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    _ = parsed.port
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
        raise ValueError('请输入有效的 HTTP 或 HTTPS 主页链接。')
    if len(value) > 500:
        raise ValueError('主页链接不能超过 500 个字符。')
    return value

class SocialPayload(BaseModel):
    linkedin: str | None = Field(default=None, max_length=500)
    facebook: str | None = Field(default=None, max_length=500)
    instagram: str | None = Field(default=None, max_length=500)
    youtube: str | None = Field(default=None, max_length=500)
    @field_validator(*SOCIAL_FIELDS)
    @classmethod
    def validate_social(cls, value):
        return social_url(value)

class CompanySocialPayload(CompanyTypePayload):
    company_linkedin: str | None = Field(default=None, max_length=500)
    company_facebook: str | None = Field(default=None, max_length=500)
    company_instagram: str | None = Field(default=None, max_length=500)
    company_youtube: str | None = Field(default=None, max_length=500)
    @field_validator(*COMPANY_SOCIAL_FIELDS)
    @classmethod
    def validate_social(cls, value):
        return social_url(value)

def company_social_data(item):
    return {key: getattr(item, key) or '' for key in COMPANY_SOCIAL_FIELDS}

def save_company_social(item, payload):
    # Older clients must not erase links they do not know about.
    for key in COMPANY_SOCIAL_FIELDS:
        if key in payload.model_fields_set:
            setattr(item, key, getattr(payload, key))

def copy_company_social(target, source, fill_only=False):
    for key in COMPANY_SOCIAL_FIELDS:
        if not fill_only or not getattr(target, key):
            setattr(target, key, getattr(source, key))

def ensure_customer_social_schema(engine):
    with engine.begin() as connection:
        for table in ('crm_customers', 'crm_prospecting_entries', 'crm_leads', 'crm_prospecting_candidates', 'crm_customer_people'):
            existing = {column['name'] for column in inspect(connection).get_columns(table)}
            fields = SOCIAL_FIELDS if table == 'crm_customer_people' else COMPANY_SOCIAL_FIELDS
            for key in fields:
                if key not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {key} VARCHAR(500) NULL'))
