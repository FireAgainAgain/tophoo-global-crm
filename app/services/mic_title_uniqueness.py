"""Compare active MIC titles independently of case, punctuation and spacing."""
import json
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select

from app.models import MicProduct


def normalized_title(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", " ", value).strip()


def ensure_unique_titles(db, project_id, titles, product_id=None):
    requested = {normalized_title(entry.title) for entry in titles}
    if len(requested) != len(titles):
        raise HTTPException(409, "同一产品的 MIC名称不能重复，请检查大小写、空格和连字符。")
    if not requested:
        return
    query = select(MicProduct).where(
        MicProduct.site_project_id == project_id,
        MicProduct.is_archived.is_(False), MicProduct.titles_json.is_not(None))
    if product_id is not None:
        query = query.where(MicProduct.id != product_id)
    for product in db.scalars(query):
        for entry in json.loads(product.titles_json):
            if normalized_title(entry["title"]) in requested:
                code = entry.get("code") or product.product_code
                raise HTTPException(409, f"MIC名称与 {product.product_code} 中的 {code} 重复，请调整产品结构或用途描述。")
