"""Install phrase-library permissions once, inheriting the knowledge-base access level."""
import json
from sqlalchemy import select
from app.models import Plan, ProjectMember, ProjectRole
from app.core.modules import normalize_module_keys


def enable_existing_phrase_access(db):
    for model,field in ((Plan,'module_keys_json'),(ProjectRole,'permissions_json'),(ProjectMember,'permissions_json')):
        for record in db.scalars(select(model)):
            try:raw=json.loads(getattr(record,field) or '[]')
            except (ValueError,TypeError):continue
            if not isinstance(raw,list):continue
            keys=normalize_module_keys(raw,include_base=model is Plan)
            if 'knowledge_base' not in keys or 'communication_phrases' in keys:continue
            keys.append('communication_phrases');setattr(record,field,json.dumps(keys,ensure_ascii=False))
            if model is Plan or record.write_permissions_json is None:continue
            try:writes=json.loads(record.write_permissions_json)
            except (ValueError,TypeError):continue
            if isinstance(writes,list) and 'knowledge_base' in normalize_module_keys(writes):
                record.write_permissions_json=json.dumps([*writes,'communication_phrases'],ensure_ascii=False)
