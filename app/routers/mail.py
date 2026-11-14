"""User-private SMTP configuration, explicit tests and single-recipient delivery."""
import hashlib
import json
from datetime import datetime
from uuid import UUID
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import User
from app.models.mail import MailConfiguration, MailDelivery, MailAccount
from app.routers.lead_development import scoped_lead
from app.services import mail as transport

router = APIRouter(prefix='/api/mail', tags=['Personal email'])
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class ConfigurationPayload(BaseModel):
    sender_name: str = Field(default='', max_length=160)
    email: EmailStr
    host: str = Field(min_length=1, max_length=260)
    port: int = Field(ge=1, le=65535)
    encryption: str = Field(pattern=r'^(ssl|starttls)$')
    username: str = Field(min_length=1, max_length=260)
    password: str | None = Field(default=None, max_length=2000)
    signature: str = Field(default='', max_length=3000000)

    @field_validator('host')
    @classmethod
    def smtp_hostname(cls, value):
        import re
        value=value.strip()
        if not re.fullmatch(r'[A-Za-z0-9.-]+',value) or '..' in value:
            raise ValueError('请填写 SMTP 服务器域名，例如 smtp.163.com；不要填写 https://mail.163.com/ 这样的网页地址。')
        return value

    @model_validator(mode='after')
    def encryption_matches_port(self):
        if self.port == 465 and self.encryption != 'ssl':
            raise ValueError('465 端口请搭配 SSL / TLS，加密方式不要选择 STARTTLS。')
        return self

    @field_validator('signature')
    @classmethod
    def safe_signature(cls, value):
        import re
        from app.services.mail_html import clean_mail_html
        return clean_mail_html(value) if re.search(r'<[a-z][\s\S]*>', value, re.I) else value

    @field_validator('sender_name', 'username', 'email')
    @classmethod
    def no_header_breaks(cls, value):
        if '\r' in value or '\n' in value:
            raise ValueError('字段中不能包含换行')
        return value.strip()

    @field_validator('email')
    @classmethod
    def ascii_email(cls, value):
        if not value.isascii():
            raise ValueError('请使用英文邮箱地址')
        return value


class SendPayload(BaseModel):
    account_id: int | None = Field(default=None, ge=0)
    request_key: UUID
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=260)
    content: str = Field(min_length=1, max_length=50000)
    content_html: str = Field(default='', max_length=3000000)
    content_translation: str = Field(default='', max_length=50000)
    contact_name: str = Field(default='', max_length=160)

    @field_validator('subject')
    @classmethod
    def subject_valid(cls, value):
        if not value.strip() or '\r' in value or '\n' in value:
            raise ValueError('请填写单行邮件标题')
        return value.strip()

    @field_validator('content')
    @classmethod
    def body_valid(cls, value):
        if not value.strip():
            raise ValueError('邮件正文不能为空')
        return value

    @field_validator('recipient')
    @classmethod
    def recipient_valid(cls, value):
        if not value.isascii():
            raise ValueError('请使用英文邮箱地址')
        return value


class TestMailPayload(BaseModel):
    account_id: int | None = Field(default=None, ge=0)
    request_key: UUID


def config_data(config):
    if not config:
        return {'configured': False, 'sender_name': '', 'email': '', 'host': '', 'port': 465,
                'encryption': 'ssl', 'username': '', 'signature': '', 'has_password': False,
                'last_test_status': '', 'last_test_message': '', 'last_tested_at': None}
    return {'account_id': config.id if isinstance(config, MailAccount) else 0, **{key: getattr(config, key) for key in ('sender_name', 'email', 'host', 'port', 'encryption', 'username', 'signature')},
            'configured': True, 'has_password': bool(config.secret_encrypted),
            'last_test_status': config.last_test_status or '', 'last_test_message': config.last_test_message or '',
            'last_tested_at': config.last_tested_at.isoformat() if config.last_tested_at else None}


def selected_configuration(db, user, account_id=None):
    if account_id == 0:
        return db.get(MailConfiguration, user.id)
    if account_id is not None:
        config = db.scalar(select(MailAccount).where(MailAccount.id==account_id, MailAccount.owner_user_id==user.id))
        if not config: raise HTTPException(404, '发件邮箱不存在。')
        return config
    return (db.scalar(select(MailAccount).where(MailAccount.owner_user_id==user.id, MailAccount.is_default.is_(True)).order_by(MailAccount.id))
        or db.get(MailConfiguration, user.id)
        or db.scalar(select(MailAccount).where(MailAccount.owner_user_id==user.id).order_by(MailAccount.id)))


def configuration(db, user, account_id=None):
    config = selected_configuration(db, user, account_id)
    if not config or not config.secret_encrypted:
        raise HTTPException(422, '请先在系统 → 邮箱配置中保存您的发件邮箱。')
    return config


@router.get('/configuration')
def get_configuration(account_id:int|None=Query(default=None,ge=0), user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    return config_data(selected_configuration(db,user,account_id))


@router.get('/accounts')
def list_accounts(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    primary=selected_configuration(db,user)
    legacy=db.get(MailConfiguration,user.id)
    accounts=([legacy] if legacy else [])+list(db.scalars(select(MailAccount).where(MailAccount.owner_user_id==user.id).order_by(MailAccount.id)))
    default_id=primary.id if isinstance(primary,MailAccount) else 0 if primary else None
    fields=('account_id','sender_name','email','host','port','encryption','username','configured','has_password','last_test_status','last_test_message','last_tested_at')
    items=[]
    for row in accounts:
        summary=config_data(row)
        items.append({**{key:summary.get(key) for key in fields},'is_default':summary['account_id']==default_id})
    return {'items':items,'default_account_id':default_id}


def apply_account(config,payload):
    changed=not config.secret_encrypted or bool(payload.password) or any(getattr(config,key)!=getattr(payload,key) for key in ('email','host','port','encryption','username'))
    if not config.secret_encrypted and not payload.password: raise HTTPException(422,'首次配置请填写邮箱授权码或客户端专用密码。')
    for key in ('sender_name','email','host','port','encryption','username','signature'):setattr(config,key,getattr(payload,key))
    if payload.password:config.secret_encrypted=transport.encrypt_secret(payload.password)
    if changed:config.last_test_status=None;config.last_test_message=None;config.last_tested_at=None


@router.post('/accounts',status_code=201)
def create_account(payload:ConfigurationPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if db.scalar(select(func.count()).select_from(MailAccount).where(MailAccount.owner_user_id==user.id))>=20:
        raise HTTPException(422,'每个用户最多添加 20 个额外邮箱。')
    accounts=list_accounts(user,db)['items']
    if any(row['email'].casefold()==str(payload.email).casefold() for row in accounts):raise HTTPException(409,'此邮箱已配置，请编辑已有邮箱。')
    config=MailAccount(owner_user_id=user.id,is_default=not accounts)
    apply_account(config,payload);db.add(config);db.commit();db.refresh(config)
    return config_data(config)


@router.put('/accounts/{account_id}')
def edit_account(account_id:int,payload:ConfigurationPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    config=selected_configuration(db,user,account_id)
    if not config:raise HTTPException(404,'发件邮箱不存在。')
    if any(row['account_id']!=account_id and row['email'].casefold()==str(payload.email).casefold() for row in list_accounts(user,db)['items']):raise HTTPException(409,'此邮箱已配置，请编辑已有邮箱。')
    apply_account(config,payload);db.commit();return config_data(config)


@router.post('/accounts/{account_id}/default')
def default_account(account_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    config=selected_configuration(db,user,account_id)
    if not config:raise HTTPException(404,'发件邮箱不存在。')
    db.execute(update(MailAccount).where(MailAccount.owner_user_id==user.id).values(is_default=False))
    if isinstance(config,MailAccount):config.is_default=True
    db.commit();return {'default_account_id':account_id}


@router.delete('/accounts/{account_id}')
def delete_account(account_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    config=selected_configuration(db,user,account_id)
    if not config:raise HTTPException(404,'发件邮箱不存在。')
    db.delete(config);db.commit();return {'deleted':True}


@router.put('/configuration')
def save_configuration(payload: ConfigurationPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = selected_configuration(db, user)
    if config is None:
        if not payload.password:
            raise HTTPException(422, '首次配置请填写邮箱授权码或客户端专用密码。')
        config = MailConfiguration(owner_user_id=user.id)
        db.add(config)
    changed = bool(payload.password) or any(getattr(config, key) != getattr(payload, key)
        for key in ('email', 'host', 'port', 'encryption', 'username'))
    for key in ('sender_name', 'email', 'host', 'port', 'encryption', 'username', 'signature'):
        setattr(config, key, getattr(payload, key))
    if payload.password:
        config.secret_encrypted = transport.encrypt_secret(payload.password)
    if changed:
        config.last_test_status = None
        config.last_test_message = None
        config.last_tested_at = None
    db.commit()
    return config_data(config)


@router.post('/configuration/test')
def test_configuration(account_id:int|None=Query(default=None,ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = selected_configuration(db,user,account_id)
    if not config:raise HTTPException(422, '请先保存您的发件邮箱。')
    try:
        transport.test_connection(config)
        config.last_test_status, config.last_test_message = 'passed', 'TLS 连接和账号验证通过，未发送邮件。'
    except Exception as exc:
        config.last_test_status, config.last_test_message = 'failed', transport.safe_error(exc)
    config.last_tested_at = datetime.now()
    db.commit()
    return config_data(config)


def delivery_data(row):
    return {'id': row.id, 'request_key': row.request_key, 'sender': row.sender, 'recipient': row.recipient,
            'subject': row.subject, 'content': row.content, 'content_html': row.content_html, 'status': row.status, 'message': row.message,
            'message_id': row.message_id, 'attachments': json.loads(row.attachments_json),
            'interaction_id': row.interaction_id, 'lead_id': row.lead_id, 'project_id': row.site_project_id,
            'created_at': row.created_at.isoformat(), 'accepted_at': row.accepted_at.isoformat() if row.accepted_at else None}


def deliver(db, user, payload, attachments, project_id=None, lead_id=None):
    saved_config = configuration(db, user, payload.account_id)
    config = SimpleNamespace(**{key: getattr(saved_config, key) for key in ('sender_name','email','host','port','encryption','username','secret_encrypted')})
    files = [{'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
             for name, _, data in attachments]
    fingerprint = hashlib.sha256(json.dumps([config.email, project_id, lead_id,
        payload.model_dump(mode='json', exclude={'request_key'}, exclude_none=True), files], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = db.scalar(select(MailDelivery).where(MailDelivery.owner_user_id == user.id,
                                                   MailDelivery.request_key == str(payload.request_key)))
    if existing:
        if existing.payload_hash != fingerprint:
            raise HTTPException(409, '同一次发送的内容已改变，请重新确认后发起新邮件。')
        return delivery_data(existing)
    row = MailDelivery(owner_user_id=user.id, site_project_id=project_id, lead_id=lead_id,
        request_key=str(payload.request_key), payload_hash=fingerprint, message_id=transport.message_id(config.email.rsplit('@', 1)[-1]),
        sender=config.email, recipient=str(payload.recipient), subject=payload.subject, content=payload.content, content_html=payload.content_html,
        attachments_json=json.dumps(files, ensure_ascii=False), status='pending',
        message='正在处理发送；若长时间未更新，请先核实邮箱记录，勿重复发送。')
    db.add(row)
    try:
        db.commit()  # Persist the unique request BEFORE any SMTP operation.
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '该邮件正在处理，请查看发送记录，勿重复发送。') from None
    try:
        from app.services.mail_html import clean_mail_html
        row.content_html=clean_mail_html(payload.content_html)
        message = transport.build_message(config, str(payload.recipient), payload.subject, payload.content, attachments, row.message_id, content_html=row.content_html)
        transport.transmit(config, message)
    except transport.DeliveryError as exc:
        row.status, row.message = exc.status, exc.message
        db.commit()
        return delivery_data(row)
    except Exception:
        # Fail before transport (for example an invalid MIME attachment).
        row.status, row.message = 'failed', '邮件准备失败，请检查标题、正文和附件。'
        db.commit()
        return delivery_data(row)
    row.status, row.accepted_at = 'accepted', datetime.now()
    row.message = '邮件服务器已接受，不代表收件人已收到或阅读。'
    # Delivery rows are the source of contact outreach statistics. Contact history
    # is maintained explicitly; sending never creates a chat/contact record.
    db.commit()
    return delivery_data(row)


def outreach_lead(project_id, lead_id, user, db):
    from app.dependencies.auth import require_project_module
    require_project_module(project_id, user, db, 'leads')
    return scoped_lead(project_id, lead_id, user, db)


@router.get('/projects/{project_id}/leads/{lead_id}/outreach-summary')
def lead_outreach_summary(project_id:int, lead_id:int, user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    outreach_lead(project_id, lead_id, user, db)
    from app.services.lead_outreach_stats import outreach_stats
    return {'outreach_stats':outreach_stats(db, project_id, lead_id), 'basis':'仅统计该线索、当前邮箱的服务器已接受邮件，不代表对方已收到或阅读。'}


@router.get('/projects/{project_id}/leads/{lead_id}/outreach-history')
def lead_outreach_history(project_id:int, lead_id:int, recipient:EmailStr, before_id:int|None=Query(default=None,gt=0),
    limit:int=Query(default=20,ge=1,le=50), user:User=Depends(get_current_user), db:Session=Depends(get_db)):
    outreach_lead(project_id, lead_id, user, db)
    conditions=[MailDelivery.site_project_id==project_id,MailDelivery.lead_id==lead_id,
        func.lower(MailDelivery.recipient)==str(recipient).lower(),MailDelivery.status=='accepted']
    count=db.scalar(select(func.count(MailDelivery.id)).where(*conditions))
    if before_id is not None:conditions.append(MailDelivery.id<before_id)
    rows=db.scalars(select(MailDelivery).where(*conditions).order_by(MailDelivery.id.desc()).limit(limit+1)).all()
    more=len(rows)>limit;rows=rows[:limit]
    return {'items':[delivery_data(row) for row in rows],'total':count,'next_before_id':rows[-1].id if more else None}


@router.post('/test-message')
def send_test_message(payload: TestMailPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = configuration(db, user, payload.account_id)
    return deliver(db, user, SendPayload(request_key=payload.request_key, account_id=payload.account_id, recipient=config.email,
        subject='TOPHOO 邮箱配置测试', content='这是一封您主动发送的测试邮件，用于验证当前邮箱的发送功能。'), [])


@router.get('/deliveries')
def deliveries(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(MailDelivery).where(MailDelivery.owner_user_id == user.id)
                      .order_by(MailDelivery.id.desc()).limit(50)).all()
    return {'items': [delivery_data(row) for row in rows]}


@router.get('/deliveries/by-request/{request_key}')
def delivery_by_request(request_key: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(MailDelivery).where(MailDelivery.owner_user_id == user.id,
                                              MailDelivery.request_key == str(request_key)))
    if not row:
        raise HTTPException(404, '暂未找到这次发送记录。')
    return delivery_data(row)


@router.post('/projects/{project_id}/leads/{lead_id}/send')
def send_lead_mail(project_id: int, lead_id: int, request_key: str = Form(...), recipient: str = Form(...),
    subject: str = Form(...), content: str = Form(...), content_html: str = Form(''), content_translation: str = Form(''),
    contact_name: str = Form(''), account_id: int|None = Form(default=None,ge=0), attachments: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scoped_lead(project_id, lead_id, user, db, True)
    try:
        payload = SendPayload(request_key=request_key, account_id=account_id, recipient=recipient, subject=subject, content=content,
                              content_translation=content_translation, contact_name=contact_name, content_html=content_html)
    except ValueError:
        raise HTTPException(422, '请核对收件邮箱、单行标题和正文；标题限 260 字，正文限 50000 字。') from None
    if len(attachments) > 5:
        raise HTTPException(422, '每封邮件最多添加 5 个附件，总大小不超过 10 MB。')
    files, total = [], 0
    for file in attachments:
        data = file.file.read(MAX_ATTACHMENT_BYTES - total + 1)
        total += len(data)
        if total > MAX_ATTACHMENT_BYTES:
            raise HTTPException(422, '附件总大小不能超过 10 MB。')
        name = (file.filename or 'attachment').replace('\\', '/').split('/')[-1]
        name = ''.join(c for c in name if c.isprintable())[:200] or 'attachment'
        media = file.content_type or 'application/octet-stream'
        import re
        if not re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+', media):
            media = 'application/octet-stream'
        files.append((name, media, data))
    return deliver(db, user, payload, files, project_id, lead_id)
