"""Read MIC catalogue entries without changing the source knowledge article."""
import re
from sqlalchemy import select
from app.models import CommunicationScript, CommunicationScriptCategory, MicProduct


def find_source(db, project_id):
    categories = list(db.scalars(select(CommunicationScriptCategory).where(CommunicationScriptCategory.site_project_id == project_id)))
    platforms = {c.id for c in categories if c.name.strip() == "平台" and c.parent_id is None}
    mic = {c.id for c in categories if c.name.strip().upper() == "MIC" and c.parent_id in platforms}
    if not mic:
        return None
    return db.scalar(select(CommunicationScript).where(CommunicationScript.site_project_id == project_id,
        CommunicationScript.category_id.in_(mic), CommunicationScript.title == "本地产品目录").order_by(CommunicationScript.id))


def parse_catalogue(content):
    products, codes = [], set()
    group, group_notes, current = "", [], None
    for line in content.splitlines():
        section = re.match(r"^##\s+(.+)", line)
        product = re.match(r"^【(vex\d+)】\s*(.+)", line, re.I)
        if section:
            group, group_notes, current = section[1].strip(), [], None
        elif product:
            code = product[1].lower()
            if code in codes:
                raise ValueError(f"目录出现重复编号：{code}，请先整理来源。")
            codes.add(code)
            original = product[2].replace("【待优化】", "").strip()
            current = dict(product_code=code, product_group=group, title=original, original_title=original,
                suggested_title="", status="pending" if "【待优化】" in product[2] else "draft",
                notes="\n".join(group_notes).strip(), source_text=line)
            products.append(current)
        elif current is not None:
            current["source_text"] += "\n" + line
            suggestion = re.match(r"^建议标题[：:]\s*(.+)", line)
            if suggestion:
                current["suggested_title"] = suggestion[1].strip()
        elif group:
            group_notes.append(line)
    return products


def grouped_catalogue(content):
    import json
    from app.services.mic_group_schema import group_identity, split_product_label
    from app.services.mic_catalogue_quality import resolved_title
    groups = {}
    for item in parse_catalogue(content):
        code, label = group_identity(item["product_group"], item["product_code"])
        name, category = split_product_label(label)
        group = groups.setdefault(code, {"product_code": code, "product_name": name, "product_group": category,
            "title": item["title"], "titles": [], "source_text": []})
        group["titles"].append(resolved_title(item))
        group["source_text"].append(item["source_text"])
    for group in groups.values():
        titles = group.pop("titles")
        group["title"] = titles[0]["title"]
        group["titles_json"] = json.dumps(titles, ensure_ascii=False)
        group["source_text"] = "\n\n".join(group["source_text"])
    return list(groups.values())

