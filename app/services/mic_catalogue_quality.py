"""Source-backed MIC title corrections, provenance and missing-number hints."""
import json
import re
from sqlalchemy import select
from app.models import MicProduct
from app.services.mic_product_labels import code_range


META_FIELDS = ("social_id", "core_keywords", "original_title", "suggested_title", "review_status", "correction_note", "optimization_suggestion", "optimization_previous_title", "optimization_completed_at")


def resolved_title(record):
    original = record["original_title"]
    title = original
    note = ""
    if record["suggested_title"]:
        title = record["suggested_title"]
        note = "采用原知识库已有建议标题"
    elif record["status"] == "pending":
        if re.search(r"\btainless\b", title):
            title = re.sub(r"\btainless\b", "Stainless", title)
            note = "修正 Stainless 缺少首字母 S 的拼写"
        elif re.search(r"\bFin\s+Fin\b", title):
            title = re.sub(r"\bFin\s+Fin\b", "Fin", title)
            note = "去除重复的 Fin"
        elif "双风机" in record["product_group"] and "Dual-Fan" not in title:
            title = title.replace("Copper Tube", "Dual-Fan Copper Tube", 1)
            if title != original:
                note = "补入原目录产品分组明确标注的双风机结构"
    result = {"code": record["product_code"], "title": title}
    if record["status"] == "pending" or record["suggested_title"]:
        result.update(original_title=original, suggested_title=record["suggested_title"],
            review_status="corrected" if title != original else "pending", correction_note=note)
    return result


def merge_title_metadata(previous, incoming):
    by_code = {str(item.get("code", "")).lower(): item for item in previous if item.get("code")}
    result = []
    for item in incoming:
        old = by_code.get(item.get("code", "").lower(), {})
        merged = {**{key: old[key] for key in META_FIELDS if key in old}, **item}
        if old.get("review_status") and item["title"] != old.get("title"):
            merged["review_status"] = "edited"
        merged.setdefault("optimization_suggestion", "")
        result.append(merged)
    return result


def missing_codes(product_code, titles):
    bounds = code_range(product_code)
    if not bounds:
        return []
    prefix, start, end = bounds
    if end - start > 1000:
        return []
    present = {str(item.get("code", "")).lower() for item in titles}
    return [f"{prefix}{number}" for number in range(start, end + 1) if f"{prefix}{number}" not in present]


def repair_project_titles(db, project_id, records):
    fixes = {item["product_code"]: resolved_title(item) for item in records}
    changed, conflicts = [], []
    products = list(db.scalars(select(MicProduct).where(MicProduct.site_project_id == project_id,
        MicProduct.is_archived.is_(False), MicProduct.titles_json.is_not(None)).with_for_update()))
    for product in products:
        titles = json.loads(product.titles_json)
        for index, item in enumerate(titles):
            resolved = fixes.get(item.get("code"))
            if not resolved or "review_status" not in resolved:
                continue
            if item["title"] not in {resolved["original_title"], resolved["title"]}:
                conflicts.append(item["code"])
                titles[index] = {**resolved, **item, "review_status": "edited"}
                continue
            if item["title"] != resolved["title"]:
                changed.append({"code": item["code"], "original": item["title"], "title": resolved["title"], "note": resolved["correction_note"]})
            titles[index] = {**item, **resolved}
        product.titles_json = json.dumps(titles, ensure_ascii=False)
        if titles:
            product.title = titles[0]["title"]
    db.flush()
    return {"changed": changed, "conflicts": conflicts}
