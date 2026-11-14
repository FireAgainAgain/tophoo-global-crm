"""Add grouped MIC fields and retain individual records as migration history."""
import json
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone, timedelta

BACKUP_ROOT = Path(__file__).resolve().parents[2] / "backups"
from sqlalchemy import inspect, select, text
from app.models import MicProduct, MicProductImage


def ensure_mic_group_columns(engine):
    columns = {column["name"] for column in inspect(engine).get_columns("mic_products")}
    with engine.begin() as connection:
        # Retire the former manual label only after preserving every existing value.
        if "publishing_group" in columns:
            rows = [dict(row) for row in connection.execute(text(
                "SELECT id, site_project_id, publishing_group FROM mic_products ORDER BY id"
            )).mappings()]
            stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S-%f")
            folder = BACKUP_ROOT / ("mic-retired-group-" + stamp)
            folder.mkdir(parents=True)
            (folder / "removed-field.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            connection.execute(text("ALTER TABLE mic_products DROP COLUMN publishing_group"))
        if "social_json" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN social_json MEDIUMTEXT NULL"))
        if "published_through" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN published_through VARCHAR(80) NULL"))
        if "titles_json" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN titles_json TEXT NULL"))
        if "is_archived" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
        if "product_name" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN product_name VARCHAR(500) NOT NULL DEFAULT ''"))
            connection.execute(text("UPDATE mic_products SET product_name=product_group WHERE titles_json IS NOT NULL"))
        if "english_title" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN english_title VARCHAR(1000) NULL"))
        if "seo_description" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN seo_description TEXT NULL"))
        if "record_code" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN record_code VARCHAR(80) NULL"))
        if "classification" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN classification VARCHAR(500) NULL"))
        if "description" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN description TEXT NULL"))
        if "content" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN content MEDIUMTEXT NULL"))
        if "parameters" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN parameters TEXT NULL"))
        if "contact" not in columns:
            connection.execute(text("ALTER TABLE mic_products ADD COLUMN contact TEXT NULL"))


def group_identity(group, code):
    match = re.match(r"^【(vex\d+\s*-\s*vex\d+)】\s*(.*)$", group, re.I)
    return (re.sub(r"\s+", "", match[1]).lower(), match[2].strip()) if match else (code, group)


def split_product_label(label):
    categories = [value.strip() for value in re.findall(r"【([^】]*)】", label) if value.strip()]
    name = re.sub(r"【[^】]*】", "", label).strip()
    return name, " / ".join(categories) if categories else "换热器"


def migrate_individual_products(db):
    legacy = list(db.scalars(select(MicProduct).where(MicProduct.titles_json.is_(None), MicProduct.is_archived.is_(False)).order_by(MicProduct.id)))
    groups = defaultdict(list)
    for item in legacy:
        code, category = group_identity(item.product_group, item.product_code)
        # Only explicit source ranges identify shared physical products.
        key = (item.site_project_id, code, category)
        groups[key].append(item)
    for (project_id, code, label), items in groups.items():
        name, category = split_product_label(label)
        def order(item):
            match = re.search(r"\d+$", item.product_code)
            return int(match[0]) if match else item.id
        items.sort(key=order)
        titles = [{"code": item.product_code, "title": item.title} for item in items]
        parent = db.scalar(select(MicProduct).where(MicProduct.site_project_id == project_id, MicProduct.product_code == code))
        if parent is None:
            parent = MicProduct(site_project_id=project_id, product_code=code, product_name=name, product_group=category,
                title=items[0].title, source_script_id=items[0].source_script_id,
                titles_json=json.dumps(titles, ensure_ascii=False))
            db.add(parent); db.flush()
        else:
            old = json.loads(parent.titles_json or "[]")
            known = {item["code"] for item in old}
            old.extend(item for item in titles if item["code"] not in known)
            parent.titles_json = json.dumps(old, ensure_ascii=False)
            parent.product_group = category
            if not parent.product_name:
                parent.product_name = name
        image = db.scalar(select(MicProductImage).where(MicProductImage.product_id == parent.id).order_by(MicProductImage.is_cover.desc(), MicProductImage.id))
        if image is None:
            image = db.scalar(select(MicProductImage).where(MicProductImage.product_id.in_([item.id for item in items])).order_by(MicProductImage.is_cover.desc(), MicProductImage.id))
            if image:
                image.product_id = parent.id
                image.is_cover = True
        for item in items:
            if item.id != parent.id:
                item.is_archived = True
    db.flush()
    return len(groups)
