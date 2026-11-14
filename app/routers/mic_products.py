"""One MIC product contains a number range, category, many names and one image."""
from io import BytesIO
from datetime import datetime
from typing import Literal
from types import SimpleNamespace
import json
import re
import warnings
from collections import Counter
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select, update, text
from sqlalchemy.orm import Session, defer
from PIL import Image, ImageOps, UnidentifiedImageError
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_write
from app.models import MicProduct, MicProductImage, User
from app.services.mic_catalogue import find_source
from app.services.mic_product_labels import STATUS_LABELS, UNASSIGNED_MIC_PREFIX, catalogue_dashboard, code_range, display_mic_code, title_entries, title_is_published, publication_status, normalize_published_through, title_matches
from app.services.mic_catalogue_quality import merge_title_metadata, missing_codes
from app.services.mic_title_uniqueness import ensure_unique_titles
from app.services import mic_social, mic_product_social

router = APIRouter(prefix="/api/mic-products", tags=["MIC products"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024
SOCIAL_PLATFORMS = ("linkedin", "facebook", "instagram", "youtube")


class SocialEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=20000)
    published: bool = False


class SocialPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin: SocialEntry = Field(default_factory=SocialEntry)
    facebook: SocialEntry = Field(default_factory=SocialEntry)
    instagram: SocialEntry = Field(default_factory=SocialEntry)
    youtube: SocialEntry = Field(default_factory=SocialEntry)


class ProgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published_through: str = Field(max_length=80)


class CompleteTitleOptimizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(default="", max_length=80)
    expected_title: str = Field(min_length=1, max_length=1000)
    expected_suggestion: str = Field(min_length=1, max_length=4000)


def social_data(product):
    stored = mic_product_social.document(product)["platforms"]
    return {platform: {"content": stored.get(platform, {}).get("content", ""),
                       "published": bool(stored.get(platform, {}).get("published", False))}
            for platform in SOCIAL_PLATFORMS}


class ProductName(BaseModel):
    code: str = Field(default="", max_length=80)
    social_id: str = Field(default="", pattern=r"^$|^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=1000)
    optimization_suggestion: str = Field(default="", max_length=4000)
    core_keywords: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("core_keywords")
    @classmethod
    def valid_core_keywords(cls, values):
        cleaned = [" ".join(value.split()) for value in values]
        if not cleaned:
            return []
        if len(cleaned) != 10:
            raise ValueError("每个标题需填写 10 个核心关键词；尚未配置时可全部留空。")
        seen = set()
        for index, value in enumerate(cleaned, 1):
            if len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9 /'’.-]+", value) or not re.search(r"[A-Za-z]", value):
                raise ValueError(f"第 {index} 个核心关键词请填写有效的英文产品词。")
            words = re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", value)
            if len(words) > 4:
                raise ValueError(f"第 {index} 个核心关键词不能超过 4 个英文单词。")
            key = " ".join(words).casefold()
            if key in seen:
                raise ValueError("同一标题的核心关键词不能重复。")
            seen.add(key)
        return cleaned


    @field_validator("optimization_suggestion")
    @classmethod
    def clean_suggestion(cls, value):
        return value.strip()

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("产品名称不能为空。")
        return value.strip()


class ProductPayload(BaseModel):
    product_code: str = Field(max_length=80)
    product_name: str = Field(min_length=1, max_length=500)
    record_code: str | None = Field(default=None, max_length=80)
    english_title: str | None = Field(default=None, max_length=1000)
    seo_description: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=10000)
    content: str | None = Field(default=None, max_length=32000)
    product_group: str = Field(default="", max_length=500)
    classification: str | None = Field(default=None, max_length=500)
    parameters: str | None = Field(default=None, max_length=16000)
    contact: str | None = Field(default=None, max_length=2000)
    published_through: str = Field(default="", max_length=80)
    titles: list[ProductName] = Field(default_factory=list, max_length=100)

    @field_validator("product_group")
    @classmethod
    def clean_category(cls, value):
        return value.strip()

    @field_validator("product_name")
    @classmethod
    def clean_field(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("产品名称不能为空。")
        return value

    @field_validator("product_code")
    @classmethod
    def normalize_range(cls, value):
        value = re.sub(r"\s*[-~～—–至]\s*", "-", value.strip().lower())
        if value.startswith(UNASSIGNED_MIC_PREFIX):
            raise ValueError("请填写有效的 MIC 编号范围。")
        return value

    @model_validator(mode="after")
    def storage_and_codes(self):
        object.__setattr__(self, "published_through", normalize_published_through(self.product_code, self.published_through))
        data = json.dumps([item.model_dump() for item in self.titles], ensure_ascii=False)
        if len(data.encode("utf-8")) > 60000:
            raise ValueError("名称内容过长，请拆分为多个产品。")
        ids = [item.social_id for item in self.titles if item.social_id]
        if len(ids) != len(set(ids)):
            raise ValueError("产品标题标识重复，请重新打开产品编辑。")
        codes = [item.code.strip().lower() for item in self.titles if item.code.strip()]
        if len(codes) != len(set(codes)):
            raise ValueError("同一个产品内的名称编号不能重复。")
        return self


def product_for(db, project_id, product_id, lock=False):
    query = select(MicProduct).where(MicProduct.site_project_id == project_id, MicProduct.id == product_id,
        MicProduct.is_archived.is_(False), MicProduct.titles_json.is_not(None))
    product = db.scalar(query.with_for_update() if lock else query)
    if not product:
        raise HTTPException(404, "MIC 产品不存在。")
    return product


def image_query():
    return select(MicProductImage).options(defer(MicProductImage.content), defer(MicProductImage.thumbnail))


def image_data(image):
    base = f"/api/mic-products/projects/{image.site_project_id}/{image.product_id}/images/{image.id}"
    return {"id": image.id, "filename": image.filename, "width": image.width, "height": image.height,
            "url": base, "thumbnail_url": base + "/thumbnail"}


def product_data(product, images):
    titles = title_entries(product)
    brief = mic_product_social.document(product)
    parameters = brief["parameters"] if product.parameters is None else product.parameters
    contact = brief["contact"] if product.contact is None else product.contact
    content = product.content
    if content is None:
        saved_brief = mic_social.storage(product).get("product_draft", {})
        explicit_contact = contact if product.contact is not None or "contact" in saved_brief else ""
        parts = [product.description, f"产品参数\n{parameters}" if parameters else "", f"联系方式\n{explicit_contact}" if explicit_contact else ""]
        content = "\n\n".join(part for part in parts if part)
    for title in titles:
        if not title.get('code') and not title.get('social_id'):
            title['social_id'] = mic_social.title_key(title).split(':', 1)[1]
    return {"id": product.id, "product_code": display_mic_code(product.product_code), "product_name": product.product_name, "product_group": product.product_group,
        "record_code": product.record_code or "", "english_title": product.english_title or "",
        "seo_description": product.seo_description or "", "description": product.description or "",
        "classification": product.classification or "",
        "parameters": parameters, "contact": contact, "content": content,
        "social": social_data(product), "social_progress": mic_product_social.summary(product), "published_through": product.published_through or "", "status": publication_status(product), "titles": titles, "missing_codes": missing_codes(product.product_code, titles), "images": [image_data(image) for image in images[:1]]}


def images_for(db, project_id, product_id):
    return list(db.scalars(image_query().where(MicProductImage.site_project_id == project_id,
        MicProductImage.product_id == product_id).order_by(MicProductImage.is_cover.desc(), MicProductImage.id).limit(1)))


def matching_products(project_id, db, q='', group='', status='', social_platform='', social_status='', title_state='', sort_order='asc', classification='', mic_only=False):
    base = [MicProduct.site_project_id == project_id, MicProduct.is_archived.is_(False), MicProduct.titles_json.is_not(None)]
    conditions = list(base)
    if q.strip():
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*[column.ilike(term, escape="\\") for column in
            (MicProduct.record_code, MicProduct.product_code, MicProduct.product_name, MicProduct.english_title, MicProduct.seo_description,
             func.coalesce(MicProduct.content, MicProduct.description), MicProduct.titles_json)]))
    if group:
        conditions.append(MicProduct.product_group == group)
    if classification:
        conditions.append(MicProduct.classification == classification)
    if status:
        if status not in STATUS_LABELS:
            raise HTTPException(400, "无效的产品状态。")
    if social_platform not in ("", *SOCIAL_PLATFORMS) or social_status not in ("", "published", "unpublished"):
        raise HTTPException(400, "无效的社媒平台或发布状态。")
    if bool(social_platform) != bool(social_status):
        raise HTTPException(400, "请选择社媒平台及对应发布状态。")
    if title_state not in ("", "published", "unpublished", "optimizing"):
        raise HTTPException(400, "无效的标题状态。")
    all_products = list(db.scalars(select(MicProduct).where(*conditions)))
    if mic_only or status or title_state:
        all_products = [item for item in all_products if code_range(item.product_code)]
    if status:
        all_products = [item for item in all_products if publication_status(item) == status]
    if social_platform:
        all_products = [item for item in all_products
                        if (mic_product_social.summary(item)[social_platform]["published"] > 0 if social_status == "published" else mic_product_social.summary(item)[social_platform]["published"] < mic_product_social.summary(item)[social_platform]["total"])]
    if title_state:
        all_products = [item for item in all_products if any(
            title_matches(item, entry, title_state) for entry in title_entries(item))]
    def natural(item):
        record_code = item.record_code or ""
        if re.fullmatch(r"\d{8}(?:\d{2})?", record_code):
            return ((0, record_code[:8]), (1, int(record_code[8:] or 0)), (0, item.product_name))
        parts = re.split(r"(\d+)", (record_code or display_mic_code(item.product_code)).lower())
        return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts)
    all_products.sort(key=natural, reverse=sort_order == "desc")
    return base, all_products


@router.get("/projects/{project_id}")
def list_products(project_id: int, q: str = "", group: str = "", status: str = "", page: int = 1,
                  classification: str = "",
                  social_platform: str = "", social_status: str = "", title_state: str = "",
                  mic_only: bool = False,
                  page_size: int = Query(default=10, ge=1, le=100), sort_order: Literal["asc", "desc"] = "asc",
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base, all_products = matching_products(project_id, db, q, group, status, social_platform, social_status, title_state, sort_order, classification, mic_only)
    total = len(all_products)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    items = all_products[(page - 1) * page_size:page * page_size]
    images = list(db.scalars(image_query().where(MicProductImage.site_project_id == project_id,
        MicProductImage.product_id.in_([item.id for item in items])).order_by(MicProductImage.is_cover.desc(), MicProductImage.id))) if items else []
    grouped = {}
    for image in images:
        grouped.setdefault(image.product_id, []).append(image)
    project_products = list(db.scalars(select(MicProduct).where(*base)))
    dashboard = catalogue_dashboard(project_products)
    dashboard["classifications"] = dict(sorted(Counter(item.classification for item in project_products if item.classification).items()))
    social_counts = Counter()
    social_total = len(project_products)
    for item in project_products:
        for platform, entry in mic_product_social.summary(item).items():
            social_counts[platform] += entry["published"]
    dashboard["social"] = [{"platform": platform, "published": social_counts[platform],
                            "unpublished": social_total - social_counts[platform]} for platform in SOCIAL_PLATFORMS]
    groups = [item["name"] for item in dashboard["categories"]]
    title_count = sum(sum(title_matches(item, entry, title_state) for entry in title_entries(item))
                      for item in all_products if code_range(item.product_code))
    source = find_source(db, project_id)
    source_notice = source.content.strip().split("\n\n")[0] if source else ""
    return {"dashboard": dashboard, "source_notice": source_notice, "items": [product_data(item, grouped.get(item.id, [])) for item in items], "total": total, "page": page,
            "pages": pages, "page_size": page_size, "groups": groups, "title_count": title_count}


@router.get("/projects/{project_id}/{product_id}")
def get_product(project_id: int, product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = product_for(db, project_id, product_id)
    return product_data(item, images_for(db, project_id, product_id))


@router.put("/projects/{project_id}/{product_id}/social")
def update_social(project_id: int, product_id: int, payload: SocialPayload,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = product_for(db, project_id, product_id, lock=True)
    if 'product_draft' in mic_social.storage(item):
        current = mic_product_social.document(item)['platforms']
        partial = {platform: {**current[platform], **getattr(payload, platform).model_dump(exclude_unset=True)} for platform in payload.model_fields_set}
        mic_product_social.save(item, mic_product_social.ProductSocialPayload(platforms=partial))
    else:
        entries = social_data(item)
        for platform in payload.model_fields_set:
            entries[platform].update(getattr(payload, platform).model_dump(exclude_unset=True))
        stored = mic_social.storage(item)
        stored.update(entries)
        item.social_json = json.dumps(stored, ensure_ascii=False)
    db.commit()
    return {"id": item.id, "social": social_data(item)}


@router.get("/projects/{project_id}/{product_id}/product-social")
def get_product_social(project_id: int, product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mic_product_social.document(product_for(db, project_id, product_id))


@router.put("/projects/{project_id}/{product_id}/product-social")
def save_product_social(project_id: int, product_id: int, payload: mic_product_social.ProductSocialPayload,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    product = product_for(db, project_id, product_id, lock=True)
    previous = product.social_json
    mic_product_social.save(product, payload)
    encoded = product.social_json
    db.expire(product, ['social_json'])
    unchanged = MicProduct.social_json.is_(None) if previous is None else MicProduct.social_json == previous
    result = db.execute(update(MicProduct).where(MicProduct.id == product.id, unchanged).values(social_json=encoded),
                        execution_options={'synchronize_session': False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '其他窗口刚刚修改了此产品的社媒资料，请保留当前文案并重新打开后保存。')
    db.commit()
    db.refresh(product)
    return mic_product_social.document(product)


@router.get("/projects/{project_id}/{product_id}/social-library")
def get_social_library(project_id: int, product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mic_social.library(product_for(db, project_id, product_id))


@router.put("/projects/{project_id}/{product_id}/title-social")
def save_title_social(project_id: int, product_id: int, payload: mic_social.TitleSocialPayload,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    product = product_for(db, project_id, product_id, lock=True)
    previous = product.social_json
    mic_social.save_title(product, payload)
    encoded = product.social_json
    # Atomic comparison also protects installations using nontransactional MyISAM tables.
    db.expire(product, ["social_json"])
    unchanged = MicProduct.social_json.is_(None) if previous is None else MicProduct.social_json == previous
    result = db.execute(update(MicProduct).where(MicProduct.id == product.id, unchanged).values(social_json=encoded),
                        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '其他窗口刚刚修改了此产品的社媒资料，请保留当前文案并重新打开后保存。')
    db.commit()
    db.refresh(product)
    return mic_social.selected_title(product, payload.key, payload.title)


@router.post("/projects/{project_id}/{product_id}/title-social/generate")
def generate_title_social(project_id: int, product_id: int, payload: mic_social.GeneratePayload,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import AiFeatureBinding, AiModelConfiguration
    from app.routers.ai_config import chat
    product = product_for(db, project_id, product_id)
    mic_social.selected_title(product, payload.key, payload.title)
    binding = db.scalar(select(AiFeatureBinding).where(AiFeatureBinding.site_project_id == project_id,
        AiFeatureBinding.owner_user_id == user.id, AiFeatureBinding.feature_key == 'mic_social'))
    model = db.scalar(select(AiModelConfiguration).where(AiModelConfiguration.id == binding.model_configuration_id,
        AiModelConfiguration.site_project_id == project_id, AiModelConfiguration.owner_user_id == user.id)) if binding else None
    if not model or not model.enabled or model.last_test_status != 'success':
        raise HTTPException(422, '请先在“系统 → AI 配置”中，为“MIC 产品社媒文案”绑定已测试通过并启用的模型。')
    return {"platform": payload.platform, "draft": mic_social.generate(payload, model, chat)}


@router.put("/projects/{project_id}/{product_id}/progress")
def update_progress(project_id: int, product_id: int, payload: ProgressPayload,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = product_for(db, project_id, product_id, lock=True)
    try:
        through = normalize_published_through(item.product_code, payload.published_through)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    item.published_through = through
    item.status = publication_status(item)
    db.commit()
    return {"id": item.id, "published_through": item.published_through or "", "status": item.status}


@router.post("/projects/{project_id}/{product_id}/titles/complete-optimization")
def complete_title_optimization(project_id: int, product_id: int, payload: CompleteTitleOptimizationPayload,
                                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id,user,db,'mic_products')
    item=product_for(db,project_id,product_id,lock=True)
    previous=item.titles_json
    entries=json.loads(previous or '[]')
    matches=[entry for entry in entries if entry.get('code','')==payload.code and entry['title']==payload.expected_title
             and entry.get('optimization_suggestion','')==payload.expected_suggestion]
    if len(matches)!=1:
        raise HTTPException(409,'标题或优化建议已更新，请重新打开名称窗口后再操作。')
    entry=matches[0]
    match=re.search(r'^(?:建议标题|优化标题|新标题)[：:]\s*(.+)$',payload.expected_suggestion,re.M)
    suggested=(match[1].strip() if match else entry.get('suggested_title','').strip()) or entry['title']
    if len(suggested)>1000:
        raise HTTPException(422,'建议标题过长，请先编辑后再标记已优化。')
    old_title=entry['title']
    if not entry.get('original_title'):entry['original_title']=old_title
    entry.update(title=suggested,optimization_suggestion='',suggested_title=suggested,review_status='optimized',
                 optimization_previous_title=old_title,optimization_completed_at=datetime.now().isoformat())
    ensure_unique_titles(db,project_id,[SimpleNamespace(title=value['title']) for value in entries],product_id)
    encoded=json.dumps(entries,ensure_ascii=False)
    if len(encoded.encode('utf-8'))>65000:
        raise HTTPException(422,'名称及原文对照内容过长，请先精简后保存。')
    status=publication_status(SimpleNamespace(product_code=item.product_code,published_through=item.published_through,titles_json=encoded))
    # The production MyISAM tables require a document comparison as well as locks.
    guard=text('BINARY titles_json = BINARY :previous') if db.bind.dialect.name=='mysql' else MicProduct.titles_json==previous
    result=db.execute(update(MicProduct).where(MicProduct.id==item.id,MicProduct.site_project_id==project_id,guard)
        .values(titles_json=encoded,title=entries[0]['title'],status=status).execution_options(synchronize_session=False),
        {'previous':previous} if db.bind.dialect.name=='mysql' else {})
    if result.rowcount!=1:
        db.rollback();raise HTTPException(409,'产品已更新，请重新打开名称窗口后再操作。')
    db.commit();db.refresh(item)
    return product_data(item,images_for(db,project_id,product_id))


def apply_payload(item, payload):
    existing_count = len(title_entries(item))
    if len(payload.titles) > max(10, existing_count):
        raise HTTPException(422, "每个产品最多可新增至 10 个 MIC 标题。")
    through = payload.published_through if "published_through" in payload.model_fields_set else item.published_through
    try:
        through = normalize_published_through(payload.product_code, through)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    incoming = []
    for name in payload.titles:
        entry = name.model_dump()
        if not entry.get("social_id"):
            entry.pop("social_id", None)
        if "core_keywords" not in name.model_fields_set:
            entry.pop("core_keywords")
        if "optimization_suggestion" not in name.model_fields_set:
            entry.pop("optimization_suggestion")
        incoming.append(entry)
    titles = merge_title_metadata(json.loads(item.titles_json or "[]"), incoming)
    encoded = json.dumps(titles, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 65000:
        raise HTTPException(422, "名称及原文对照内容过长，请减少名称数量。")
    # The database requires a unique code even for products awaiting an MIC number.
    if payload.product_code:
        item.product_code = payload.product_code
    elif not (item.product_code or "").startswith(UNASSIGNED_MIC_PREFIX):
        item.product_code = UNASSIGNED_MIC_PREFIX + uuid4().hex
    item.product_name = payload.product_name
    for field in ("record_code", "english_title", "seo_description", "description", "content", "classification", "parameters", "contact"):
        if field in payload.model_fields_set:
            setattr(item, field, (getattr(payload, field) or "").strip())
    if "product_group" in payload.model_fields_set or item.id is None:
        item.product_group = payload.product_group
    item.published_through = through
    item.titles_json = encoded
    item.status = publication_status(item)
    item.title = titles[0]["title"] if titles else ""


def check_duplicate(db, project_id, code, product_id=None):
    if not code:
        return
    if db.scalar(select(MicProduct.id).where(MicProduct.site_project_id == project_id,
        MicProduct.product_code == code, MicProduct.id != product_id)):
        raise HTTPException(409, "该编号范围已存在。")


@router.post("/projects/{project_id}", status_code=201)
def create_product(project_id: int, payload: ProductPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_duplicate(db, project_id, payload.product_code)
    ensure_unique_titles(db, project_id, payload.titles)
    item = MicProduct(site_project_id=project_id)
    apply_payload(item, payload)
    db.add(item); db.commit(); db.refresh(item)
    return product_data(item, [])


@router.put("/projects/{project_id}/{product_id}")
def update_product(project_id: int, product_id: int, payload: ProductPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = product_for(db, project_id, product_id, lock=True)
    check_duplicate(db, project_id, payload.product_code, product_id)
    ensure_unique_titles(db, project_id, payload.titles, product_id)
    apply_payload(item, payload)
    db.commit()
    return product_data(item, images_for(db, project_id, product_id))


@router.delete("/projects/{project_id}/{product_id}")
def remove_product(project_id: int, product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = product_for(db, project_id, product_id, lock=True)
    db.execute(delete(MicProductImage).where(MicProductImage.product_id == item.id))
    db.delete(item); db.commit()
    return {"deleted": True}


def prepare_image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 30000000:
                    raise ValueError("仅支持 JPG、PNG、WebP，图片不能超过 3000 万像素。")
                image.load()
                converted = ImageOps.exif_transpose(image).convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                converted.thumbnail((2000, 2000))
                output = BytesIO(); converted.save(output, format="WEBP", quality=90)
                thumb = converted.copy(); thumb.thumbnail((240, 240))
                small = BytesIO(); thumb.save(small, format="WEBP", quality=85)
                return output.getvalue(), small.getvalue(), converted.width, converted.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(400, "图片无法读取，请上传有效的 JPG、PNG 或 WebP（不超过 3000 万像素）。") from error


@router.post("/projects/{project_id}/{product_id}/images", status_code=201)
async def upload_image(project_id: int, product_id: int, files: list[UploadFile] = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    product_for(db, project_id, product_id, lock=True)
    if len(files) != 1:
        raise HTTPException(400, "每个产品只保留一张图片，请选择一张上传。")
    data = await files[0].read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "单张图片不能超过 8 MB。")
    content, thumbnail, width, height = prepare_image(data)
    db.execute(delete(MicProductImage).where(MicProductImage.site_project_id == project_id, MicProductImage.product_id == product_id))
    db.add(MicProductImage(site_project_id=project_id, product_id=product_id, filename=(files[0].filename or "product.webp")[:260],
        content=content, thumbnail=thumbnail, width=width, height=height, is_cover=True))
    db.commit()
    return {"images": [image_data(image) for image in images_for(db, project_id, product_id)]}


def image_for(db, project_id, product_id, image_id):
    product_for(db, project_id, product_id)
    item = db.scalar(image_query().where(MicProductImage.site_project_id == project_id,
        MicProductImage.product_id == product_id, MicProductImage.id == image_id))
    if not item:
        raise HTTPException(404, "图片不存在。")
    return item


@router.get("/projects/{project_id}/{product_id}/images/{image_id}")
@router.get("/projects/{project_id}/{product_id}/images/{image_id}/thumbnail")
def read_image(request: Request, project_id: int, product_id: int, image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = image_for(db, project_id, product_id, image_id)
    return Response(item.thumbnail if request.url.path.endswith("/thumbnail") else item.content, media_type="image/webp", headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/projects/{project_id}/{product_id}/images/{image_id}")
def remove_image(project_id: int, product_id: int, image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    product_for(db, project_id, product_id, lock=True)
    db.delete(image_for(db, project_id, product_id, image_id)); db.commit()
    return {"images": []}
