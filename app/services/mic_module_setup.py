"""One-time permission expansion when the MIC catalogue is first installed."""
import json
from sqlalchemy import select
from app.models import Plan, ProjectMember, ProjectRole


def enable_existing_wp_access(db):
    # MIC starts alongside WP products; later edits to individual permissions remain authoritative.
    for model, field in ((Plan, "module_keys_json"), (ProjectMember, "permissions_json"), (ProjectRole, "permissions_json")):
        for record in db.scalars(select(model)):
            raw = getattr(record, field)
            if not raw:
                continue
            try:
                keys = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(keys, list) and "product_tdk" in keys and "mic_products" not in keys:
                keys.append("mic_products")
                setattr(record, field, json.dumps(keys, ensure_ascii=False))
