"""On installation, mirror existing RFQ grants for the new sales quotation module."""
import json
from sqlalchemy import select
from app.models import Plan, ProjectMember, ProjectRole


def enable_quotation_access(db):
    for model,fields in ((Plan,('module_keys_json',)),(ProjectMember,('permissions_json','write_permissions_json')),(ProjectRole,('permissions_json','write_permissions_json'))):
        for row in db.scalars(select(model)):
            for field in fields:
                raw=getattr(row,field)
                if raw is None:continue
                try:keys=json.loads(raw)
                except (ValueError,TypeError):continue
                if isinstance(keys,list) and 'rfq' in keys and 'quotations' not in keys:
                    setattr(row,field,json.dumps([*keys,'quotations'],ensure_ascii=False))
    db.commit()
