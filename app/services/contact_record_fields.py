"""Shared fields, validation and serialization for lead and customer records."""
from datetime import date, datetime, time, timezone, timedelta
import re
import json
from fastapi import HTTPException
from pydantic import BaseModel, Field


class ContactRecordPayload(BaseModel):
    direction: str = Field(default='outbound', pattern=r'^(outbound|inbound)$')
    contact_name: str | None = Field(default=None, max_length=160)
    occurred_at: date | datetime = Field(default_factory=lambda:datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None))
    channel: str = Field(default='email', max_length=40)
    subject: str | None = Field(default=None, max_length=260)
    content: str = Field(min_length=1, max_length=50000)
    content_html: str = Field(default='', max_length=3000000)
    content_translation: str | None = Field(default=None, max_length=50000)


def clean(value):
    return value.strip() or None if value else None


def clean_record_content(value):
    if value is None:return None
    value=value.replace('\r\n','\n').replace('\r','\n')
    lines=[re.sub(r'[ \t]+$','',re.sub(r'\t{2,}','\t',line)) for line in value.split('\n')]
    return re.sub(r'\n{4,}','\n\n\n','\n'.join(lines)).strip() or None


def save_record(item,payload):
    content=clean_record_content(payload.content)
    if not content:raise HTTPException(422,'联系内容不能为空。')
    # The five-field summary editor does not expose legacy message direction.
    # Keep it when updating old records instead of silently resetting inbound.
    if 'direction' in payload.model_fields_set or not item.id:item.direction=payload.direction
    item.contact_name=clean(payload.contact_name)
    occurred=payload.occurred_at
    if not isinstance(occurred,datetime):occurred=datetime.combine(occurred,time.min)
    elif occurred.tzinfo:occurred=occurred.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    item.occurred_at=occurred;item.channel=payload.channel.strip() or 'other'
    if 'subject' in payload.model_fields_set:item.subject=clean(payload.subject)
    previous_content=item.content
    item.content=content
    if 'content_html' in payload.model_fields_set:
        from app.services.mail_html import clean_mail_html
        item.content_html=clean_mail_html(payload.content_html)
    elif previous_content!=content:item.content_html=''
    if 'content_translation' in payload.model_fields_set:
        item.content_translation=clean_record_content(payload.content_translation)


def record_html(item):
    from app.services.mail_html import clean_mail_html
    if item.content_html is not None:return clean_mail_html(item.content_html)
    if item.source_outreach_json:
        source=json.loads(item.source_outreach_json)
        if clean_record_content(source.get('content'))==clean_record_content(item.content):
            return clean_mail_html(source.get('content_html') or '')
    return ''


def record_data(item,db):
    from app.models import User
    creator=db.get(User,item.created_by_user_id) if item.created_by_user_id else None
    return {'id':item.id,'direction':item.direction,'contact_name':item.contact_name or '',
            'occurred_at':item.occurred_at.isoformat(),'channel':item.channel,
            'subject':item.subject or '', 'content':item.content,'content_html':record_html(item),'content_translation':item.content_translation,
            'created_by_name':(creator.display_name or creator.email) if creator else '',
            'created_at':item.created_at.isoformat(),'updated_at':item.updated_at.isoformat(),
            **({'outreach_source':{key:value for key,value in json.loads(item.source_outreach_json).items() if key!='conversion_key'}} if item.source_outreach_json else {})}
