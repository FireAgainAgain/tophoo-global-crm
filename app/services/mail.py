"""TLS-only SMTP transport. No retry after an ambiguous SMTP DATA response."""
import base64
import hashlib
import ipaddress
import os
import re
import smtplib
import socket
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, make_msgid

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.core.config import JWT_SECRET_KEY


def cipher():
    # A dedicated stable key is recommended; existing installations can use the JWT key.
    key = os.getenv('MAIL_ENCRYPTION_KEY') or base64.urlsafe_b64encode(
        hashlib.sha256(('tophoo-mail:' + JWT_SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt_secret(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt_secret(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise HTTPException(422, '邮箱授权码无法解密，请重新填写并保存。') from None


def public_smtp_host(host, port):
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or '..' in host:
        raise HTTPException(422, '请填写 SMTP 服务器域名，不含协议或路径。')
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise HTTPException(422, '无法解析 SMTP 服务器，请检查服务器地址。') from None
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise HTTPException(422, 'SMTP 服务器必须使用可访问的公网地址。')


@contextmanager
def connection(config):
    public_smtp_host(config.host, config.port)
    secret = decrypt_secret(config.secret_encrypted)
    client = None
    try:
        if config.encryption == 'ssl':
            client = smtplib.SMTP_SSL(config.host, config.port, timeout=25, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=25)
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        client.login(config.username, secret)
        yield client
    finally:
        # A QUIT failure must never turn an accepted message into a failed send.
        if client:
            try:
                client.close()
            except Exception:
                pass


def safe_error(error):
    if isinstance(error, HTTPException):
        return str(error.detail)
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return '登录失败，请检查账号、授权码及邮箱的 SMTP 服务是否已开启。'
    if isinstance(error, ssl.SSLError):
        return 'TLS 连接失败，请检查服务器、端口及加密方式。'
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return '收件地址被邮件服务器拒绝，请核对地址。'
    if isinstance(error, smtplib.SMTPSenderRefused):
        return '发件地址被服务器拒绝，请检查邮箱账号与发件地址。'
    if isinstance(error, smtplib.SMTPDataError):
        return '服务器拒绝接收邮件，请检查内容、附件和邮箱发送额度。'
    return '连接失败或超时，请检查邮箱服务器、网络和账号额度。'


def test_connection(config):
    with connection(config):
        pass


def build_message(config, recipient, subject, content, attachments, message_id, content_html=""):
    message = EmailMessage(policy=SMTP)
    message['From'] = formataddr((config.sender_name, config.email))
    message['To'] = recipient
    message['Subject'] = subject
    message['Message-ID'] = message_id
    from email.utils import formatdate
    message['Date'] = formatdate(localtime=False, usegmt=True)
    message.set_content(content)
    if content_html:
        from app.services.mail_html import embed_mail_images
        markup, images = embed_mail_images(content_html)
        message.add_alternative(markup, subtype="html")
        html_part=message.get_payload()[-1]
        for cid, subtype, data in images:
            html_part.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>", disposition="inline")
    for name, media_type, data in attachments:
        major, minor = media_type.split('/', 1)
        message.add_attachment(data, maintype=major, subtype=minor, filename=name)
    return message


class DeliveryError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def transmit(config, message):
    """Track the DATA boundary: a disconnect afterward requires manual verification."""
    data_started = False
    try:
        with connection(config) as client:
            code, _ = client.mail(config.email)
            if code != 250:
                raise smtplib.SMTPSenderRefused(code, b'rejected', config.email)
            code, _ = client.rcpt(str(message['To']))
            if code not in (250, 251):
                raise smtplib.SMTPRecipientsRefused({str(message['To']): (code, b'rejected')})
            data_started = True
            code, _ = client.data(message.as_bytes())
            if code != 250:
                raise smtplib.SMTPDataError(code, b'rejected')
    except Exception as exc:
        uncertain = data_started and not isinstance(exc, smtplib.SMTPDataError)
        raise DeliveryError('unknown' if uncertain else 'failed',
            '发送结果待核实，请先检查收件箱或邮箱服务器记录，勿直接重发。' if uncertain else safe_error(exc)) from None


def message_id(domain='tophoo.local'):
    return make_msgid(domain=domain)
