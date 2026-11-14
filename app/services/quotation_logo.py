"""Quotation logos are validated inline image snapshots, never remote URLs."""
import base64
import json
import re
import warnings
from io import BytesIO
from pathlib import Path
from PIL import Image

MAX_LOGO_BYTES=1024*1024
LEGACY_LOGO = Path(__file__).resolve().parents[2] / 'data' / 'legacy-quotation-logo.png'


def validate_logo(value):
    if not value:return ''
    match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',value)
    if not match:raise ValueError('Logo 仅支持 PNG、JPG、WebP 图片，请重新上传。')
    try:
        data=base64.b64decode(match[2],validate=True)
        if len(data)>MAX_LOGO_BYTES:raise ValueError('Logo 不能超过 1 MB。')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format!={'png':'PNG','jpeg':'JPEG','webp':'WEBP'}[match[1]]:raise ValueError('Logo 格式与图片内容不一致。')
                if max(image.size)>8192 or image.width*image.height>16000000:raise ValueError('Logo 尺寸过大，请缩小后上传。')
                image.verify()
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('Logo 图片无效或尺寸过大，请重新上传。') from exc
    return value


def legacy_logo_snapshots(db):
    """Preserve previously generated branding in old records; new quotes start blank."""
    from sqlalchemy import select
    from app.models import Quotation
    if not LEGACY_LOGO.exists():return
    logo='data:image/png;base64,'+base64.b64encode(LEGACY_LOGO.read_bytes()).decode('ascii')
    for row in db.scalars(select(Quotation)):
        document=json.loads(row.data_json)
        if 'logo_data_url' in document:continue
        document['logo_data_url']=logo
        row.data_json=json.dumps(document,ensure_ascii=False)
        row.revision+=1
    db.commit()
