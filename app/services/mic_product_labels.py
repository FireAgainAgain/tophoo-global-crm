"""MIC publishing state follows the last published number in the product range."""
import json
import re
from collections import Counter
from sqlalchemy import select
from app.models import MicProduct

STATUS_LABELS = {"pending": "待发布", "publishing": "正在发布", "optimizing": "待优化", "published": "已发布"}
UNASSIGNED_MIC_PREFIX = "unassigned:"


def display_mic_code(value):
    return "" if value.startswith(UNASSIGNED_MIC_PREFIX) else value


def title_entries(product):
    return [{**entry, "optimization_suggestion": str(entry.get("optimization_suggestion") or "").strip()}
        for entry in json.loads(product.titles_json or "[]")]


def code_range(value):
    match = re.fullmatch(r"([a-z]*)(\d+)(?:-([a-z]*)(\d+))?", (value or "").strip().lower())
    if not match:
        return None
    prefix, start, end_prefix, end = match.groups()
    if end_prefix and end_prefix != prefix:
        return None
    start, end = int(start), int(end or start)
    return (prefix, start, end) if start <= end else None


def normalize_published_through(product_code, value):
    value = (value or "").strip().lower()
    if not value:
        return ""
    bounds = code_range(product_code)
    match = re.fullmatch(r"([a-z]*)(\d+)", value)
    if not bounds or not match:
        raise ValueError("请填写 MIC 编号范围内的发布编号，例如 316。")
    prefix, start, end = bounds
    if (match[1] and match[1] != prefix) or not start <= int(match[2]) <= end:
        raise ValueError("当前发布到的编号必须在产品编号范围内。")
    return f"{prefix}{int(match[2])}"


def publication_status(product):
    value = (product.published_through or "").strip()
    if not value:
        return "pending"
    try:
        value = normalize_published_through(product.product_code, value)
    except ValueError:
        return "publishing"
    prefix, _, end = code_range(product.product_code)
    if value != f"{prefix}{end}":
        return "publishing"
    return "optimizing" if any(entry["optimization_suggestion"] for entry in title_entries(product)) else "published"


def sync_publication_statuses(db):
    for product in db.scalars(select(MicProduct).where(MicProduct.is_archived.is_(False), MicProduct.titles_json.is_not(None))):
        titles = title_entries(product)
        encoded = json.dumps(titles, ensure_ascii=False)
        if encoded != product.titles_json:
            product.titles_json = encoded
        product.status = publication_status(product)
    db.flush()


def title_is_published(product, entry):
    code = re.fullmatch(r"([a-z]*)(\d+)", str(entry.get("code") or "").strip().lower())
    through = re.fullmatch(r"([a-z]*)(\d+)", (product.published_through or "").strip().lower())
    return bool(code and through and code[1] == through[1] and int(code[2]) <= int(through[2]))


def title_needs_optimization(entry):
    return bool(str(entry.get("optimization_suggestion") or "").strip())


def title_matches(product, entry, state):
    if state == "optimizing":
        return title_needs_optimization(entry)
    return not state or title_is_published(product, entry) == (state == "published")


def catalogue_dashboard(products):
    total = len(products)
    categories = Counter(product.product_group or "未分类" for product in products)
    mic_products = [product for product in products if code_range(product.product_code)]
    statuses = Counter(publication_status(product) for product in mic_products)
    title_total = title_published = title_optimizing = 0
    for product in mic_products:
        entries = title_entries(product)
        title_total += len(entries)
        title_optimizing += sum(title_needs_optimization(entry) for entry in entries)
        title_published += sum(title_is_published(product, entry) for entry in entries)
    return {"total": total, "mic_total": len(mic_products), "titles": {"total": title_total, "published": title_published, "unpublished": title_total - title_published, "optimizing":title_optimizing},
        "categories": [{"name": name, "count": count, "percentage": round(count / total * 100, 1) if total else 0}
            for name, count in sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))],
        "labels": [{"status": status, "name": name, "count": statuses.get(status, 0)} for status, name in STATUS_LABELS.items()]}
