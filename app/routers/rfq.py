"""RFQ APIs linking customer relationships and technical requirements."""
from datetime import date
from typing import Literal
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from app.services.local_clocks import add_local_clocks
from app.services.rfq_followup_migration import move_rfq_followup
from app.services.rfq_ownership import assign_owner, project_owners
from app.services.rfq_customer import customer_reference, customer_fields, contact_details, save_contact_snapshot
from app.services.customer_people import people_by_customer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write as require_module_write
from app.models import Customer, ProjectContact, ProjectMember, Rfq, RfqTemplate, SiteProject, User, WorkspaceMember

router = APIRouter(prefix="/api/rfqs", tags=["询价单"])


def rfq_number_key(item):
    parts = re.findall(r'\d+|\D+', (item.number or '').strip())
    return tuple((1, int(part)) if part.isdecimal() else (0, part.casefold()) for part in parts), item.id


def display_status(value: str | None) -> str:
    if value in {"需求确认中", "报价准备中"}:
        return "推进中"
    if value == "沟通失败":
        return "已关闭"
    return "待处理" if not value or value == "询盘" else value

def require_project_access(project_id, user, db): return require_project_module(project_id, user, db, "rfq")
def require_project_write(project_id, user, db): return require_module_write(project_id, user, db, "rfq")

INQUIRY_ITEMS_KEY = "_customer_inquiry_items"
LEGACY_INQUIRY_CONTENT_KEY = "customer_inquiry_content"


class InquiryItem(BaseModel):
    content: str = Field(max_length=20000)
    translation: str = Field(default="", max_length=20000)
    price: str = Field(default="", max_length=20000)
    notes: str = Field(default="", max_length=20000)

    @field_validator("content")
    @classmethod
    def require_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写每条明细的需求。")
        return value


def visible_owner_id(project_id: int, user: User, db: Session) -> int | None:
    if user.is_admin:
        return None
    project = db.get(SiteProject, project_id)
    workspace_member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == project.workspace_id, WorkspaceMember.user_id == user.id)) if project else None
    if workspace_member and workspace_member.role in {"owner", "admin"}:
        return None
    membership = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    return None if membership and membership.role == "top_admin" else user.id

class RfqPayload(BaseModel):
    number: str | None = Field(default=None, max_length=40)
    inquiry_source: str | None = Field(default=None, max_length=160)
    product_number: str | None = Field(default=None, max_length=160)
    inquiry_date: date | None = None
    contact_id: int | None = None
    owner_user_id: int | None = Field(default=None, gt=0)
    contact_person_id: int | None = Field(default=None, gt=0)
    # 保留该字段以兼容历史 RFQ；新建及编辑界面统一采用通用字段。
    template_key: str = Field(default="general", min_length=1, max_length=60)
    status: str = Field(default="待处理", pattern=r"^(待处理|推进中|需求确认中|报价准备中|已报价|已成交|已关闭|询盘|沟通失败)$")
    priority: str = Field(default="normal", max_length=20)
    owner: str | None = Field(default=None, max_length=160)
    application: str | None = Field(default=None, max_length=260)
    quantity: str | None = Field(default=None, max_length=80)
    next_action_date: date | None = None
    notes: str | None = Field(default=None, max_length=10000)
    parameters: dict[str, str] = Field(default_factory=dict)
    parameter_notes: dict[str, str] = Field(default_factory=dict)
    generic_fields: list["GenericField"] = Field(default_factory=list, max_length=100)
    inquiry_items: list[InquiryItem] | None = Field(default=None, min_length=1, max_length=25)

    @field_validator("status")
    @classmethod
    def normalize_legacy_status(cls, value: str) -> str:
        return display_status(value)

class GenericField(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(default="", max_length=20000)


class CustomerInquiryPayload(BaseModel):
    number: str = Field(min_length=1, max_length=40)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    inquiry_items: list[InquiryItem] | None = Field(default=None, min_length=1, max_length=25)


@router.patch("/projects/{project_id}/customers/{customer_id}/{rfq_id}")
def update_customer_inquiry(project_id: int, customer_id: int, rfq_id: int, payload: CustomerInquiryPayload,
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.routers.customer import get_c

    require_project_write(project_id, user, db)
    require_project_module(project_id, user, db, "customer_list")
    owner_id = visible_owner_id(project_id, user, db)
    get_c(db, project_id, customer_id, owner_id)
    statement = select(Rfq).where(Rfq.id == rfq_id, Rfq.site_project_id == project_id, Rfq.contact_id == customer_id)
    if owner_id is not None:
        statement = statement.where(Rfq.owner_user_id == owner_id)
    item = db.scalar(statement.with_for_update())
    if item is None:
        raise HTTPException(404, "询价单不存在。")
    number, content = payload.number.strip(), (payload.content or "").strip()
    if not number or (payload.inquiry_items is None and not content):
        raise HTTPException(422, "请填写编号和内容。")
    validate_number(db, project_id, number, item.id)
    previous = data(item)
    item.number = number
    if payload.inquiry_items is not None or previous["inquiry_items"] is not None:
        if payload.inquiry_items is not None:
            items = [entry.model_dump() for entry in payload.inquiry_items]
        else:
            items = previous["inquiry_items"]
            items[0] = {**items[0], "content": content}
        parameters = previous["parameters"]
        parameters.pop(LEGACY_INQUIRY_CONTENT_KEY, None)
        item.parameters_json = json.dumps({**parameters, INQUIRY_ITEMS_KEY: items}, ensure_ascii=False)
        item.template_fields_json = json.dumps([
            field for field in previous["template_fields"] if field.get("key") != LEGACY_INQUIRY_CONTENT_KEY
        ], ensure_ascii=False)
        db.commit()
        return {"id": item.id, "number": item.number, "inquiry_items": items}
    key = LEGACY_INQUIRY_CONTENT_KEY
    fields = [field for field in previous["template_fields"] if field.get("key") != key]
    fields.append({"key": key, "group": "询价内容", "label_en": "Content", "label_zh": "内容", "input_type": "textarea"})
    item.template_fields_json = json.dumps(fields, ensure_ascii=False)
    item.parameters_json = json.dumps({**previous["parameters"], key: content}, ensure_ascii=False)
    db.commit()
    return {"id": item.id, "number": item.number, "content": content}

class TemplateField(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    group: str = Field(default="基本参数", min_length=1, max_length=100)
    label_en: str = Field(min_length=1, max_length=160)
    label_zh: str | None = Field(default=None, max_length=160)
    input_type: str = Field(default="text", pattern=r"^(text|number|select|textarea)$")
    unit: str | None = Field(default=None, max_length=40)
    required: bool = False
    note: str | None = Field(default=None, max_length=1000)
    default_value: str | None = Field(default=None, max_length=10000)
    options: list[str] = Field(default_factory=list, max_length=50)

class TemplatePayload(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    name_en: str = Field(min_length=1, max_length=160)
    name_zh: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    fields: list[TemplateField] = Field(default_factory=list, max_length=100)

def simple_field(key: str, label_en: str, label_zh: str, note: str = "", content: str = "", group: str = "需求参数") -> dict:
    return {"key":key,"group":group,"label_en":label_en,"label_zh":label_zh,"input_type":"text","unit":None,"required":False,"note":note or None,"default_value":content or None,"options":[]}

DRY_COOLER_FIELDS = [
    simple_field("product_name","Product Name","产品名称","Dry Cooler","Dry Cooler","基本信息"),
    simple_field("usage_location","Usage Location (Province / City)","使用地点（省 / 市）","Heilongjiang, Mudanjiang",group="基本信息"),
    simple_field("usage_site","Usage Site","使用场地","Semiconductor Factory",group="基本信息"),
    simple_field("capacity","Heat Exchange Capacity (kW)","换热量（kW）","88 kW",group="基本工况"),
    simple_field("water_flow","Water Flow Rate (m³/h)","水流量（m³/h）","50 m³/h",group="基本工况"),
    simple_field("ambient_temp","Ambient Temperature (°C)","环境温度（°C）","Winter -15°C / Summer 40°C",group="基本工况"),
    simple_field("inlet_temp","Inlet Liquid Temperature (°C)","进液温度（°C）","15°C",group="基本工况"),
    simple_field("outlet_temp","Outlet Liquid Temperature (°C)","出液温度（°C）","10°C",group="基本工况"),
    simple_field("medium","Tube Side Medium","管侧介质","30% Ethylene Glycol",group="基本工况"),
    simple_field("wet_bulb_or_rh","Inlet / Outlet Air Wet-bulb Temperature or Relative Humidity","进出风湿球温度或相对湿度","50% RH",group="空气侧参数"),
    simple_field("air_flow_or_velocity","Air Volume or Face Velocity","风量或迎面风速","Per design",group="空气侧参数"),
    simple_field("design_pressure","Tube-side Design Pressure","管侧设计压力","1.0 MPa",group="压力与性能"),
    simple_field("air_pressure_drop","Fin-side Air Pressure Drop Requirement","翅片侧空气压降要求","Per design (Pa)",group="压力与性能"),
    simple_field("tube_pressure_drop","Tube-side Pressure Drop or Outlet Pressure Requirement","管侧压降或出口压力要求","100 kPa",group="压力与性能"),
    simple_field("test_pressure","Tube-side Test Pressure","管侧试验压力","3.0 MPa",group="压力与性能"),
    simple_field("dimensions","Dimension Requirements","尺寸要求","L × W × H",group="结构与材质"),
    simple_field("heat_exchanger_material","Heat Exchanger Material","换热器材质","Copper Tube + Aluminum Fin / Stainless Steel Tube + Aluminum Fin",group="结构与材质"),
    simple_field("sheet_metal_material","Sheet Metal Material","钣金材质","Powder-coated Galvanized Steel / Stainless Steel",group="结构与材质"),
    simple_field("header_material","Header Material","汇管材质","Seamless Steel Pipe / Stainless Steel Pipe",group="结构与材质"),
    simple_field("fan_type","Fan Type","风机类型","AC Fan / EC Fan",group="风机与辅助系统"),
    simple_field("fan_brand","Fan Brand Requirement","风机品牌要求","Domestic Brand / International Brand",group="风机与辅助系统"),
    simple_field("spray_system","Wet Film Spray System","湿膜喷淋系统","Included / Not Included",group="风机与辅助系统"),
    simple_field("detailed_requirements","Detailed Requirements","详细需求说明","Please describe the operating conditions and special requirements",group="其他要求"),
]

HEAT_EXCHANGER_FIELDS = [
    simple_field("quantity", "Quantity (Units)", "数量（台）", "100"),
    simple_field("product_name", "Product Name", "产品名称", "Heat Exchanger"),
    simple_field("tube_material", "Tube Material", "管材材质", "Copper / Stainless Steel / Titanium"),
    simple_field("tube_od", "Tube O.D.", "管径", "9.52 mm"),
    simple_field("tube_pitch", "Tube Pitch", "管距", "26 × 21.65 mm"),
    simple_field("tube_wall_thickness", "Tube Wall Thickness", "管壁厚", "0.5 mm"),
    simple_field("number_of_holes", "Number of Holes", "孔数", "2"),
    simple_field("tube_rows", "Tube Rows", "排数", "6"),
    simple_field("circuits", "Circuits", "回路数", "8"),
    simple_field("fin_type", "Fin Type", "翅片类型", "Hydrophilic Aluminum Foil"),
    simple_field("fin_thickness", "Fin Thickness", "翅片厚度", "0.115 mm"),
    simple_field("fin_spacing", "Fin Spacing", "翅片间距", "3 mm"),
    simple_field("fpi", "FPI", "翅片密度（FPI）", "9"),
    simple_field("effective_fin_length", "Effective Fin Length", "翅片有效长度", "1100 mm"),
    simple_field("length_mm", "Length (mm)", "长（mm）", "1100"),
    simple_field("width_mm", "Width (mm)", "宽（mm）", "1120"),
    simple_field("height_mm", "Height (mm)", "高（mm）", "120"),
    simple_field("header_material_and_size", "Header Material & Size", "总管材料及尺寸", "Seamless Carbon Steel Pipe, 3-1/8 in, External Thread"),
    simple_field("sheet_metal", "Sheet Metal", "钣金", "Galvanized Steel"),
    simple_field("evaporator_tube_od", "Evaporator Tube O.D. (Optional)", "蒸发器管径（如有）", "None"),
    simple_field("unit_price", "Unit Price (Tax & Packing Included)", "含税含打包成本单价", "¥150.00"),
    simple_field("total_price", "Total Price", "总价格", "¥15,000.00"),
    simple_field("air_volume_cfm", "Air Volume (CFM)", "风量（立方英尺/分钟）", ""),
    simple_field("total_cooling_capacity_tr", "Total Cooling Capacity (TR)", "总制冷量（冷吨）", ""),
    simple_field("outlet_dry_bulb_temp_f", "Outlet Dry-bulb Temperature (°F)", "出风干球温度（℉）", ""),
    simple_field("outlet_wet_bulb_temp_f", "Outlet Wet-bulb Temperature (°F)", "出风湿球温度（℉）", ""),
    simple_field("air_velocity_fpm", "Air Velocity (FPM)", "风速（英尺/分钟）", ""),
]
for _field in HEAT_EXCHANGER_FIELDS:
    _field["note"] = None

def template_data(item: RfqTemplate):
    try: fields=json.loads(item.fields_json or "[]")
    except json.JSONDecodeError: fields=[]
    return {**customer_fields(item, contact), "id":item.id,"code":item.code,"name_en":item.name_en,"name_zh":item.name_zh or "","description":item.description or "","is_active":item.is_active,"fields":fields}

def ensure_default_templates(db: Session, project_id: int):
    defaults=[("dry_cooler","Dry Cooler","干冷器","干冷器工况、性能、材质与工程要求",DRY_COOLER_FIELDS),("heat_exchanger","Finned Heat Exchanger / Coil","翅片换热器 / 盘管","盘管工况、管翅结构、安装与防腐要求",HEAT_EXCHANGER_FIELDS),("general","General RFQ","通用需求","适用于尚未建立专用模板的产品",[])]
    existing=set(db.scalars(select(RfqTemplate.code).where(RfqTemplate.site_project_id==project_id)).all())
    if existing:
        return
    for code,name_en,name_zh,description,fields in defaults:
        if code not in existing: db.add(RfqTemplate(site_project_id=project_id,code=code,name_en=name_en,name_zh=name_zh,description=description,fields_json=json.dumps(fields,ensure_ascii=False)))
    db.commit()

def clean(value: str | None): return value.strip() or None if value else None
def related(db, project_id, payload, owner_id: int | None = None, existing=None):
    contact = None
    if payload.contact_id is not None:
        if not existing or existing.contact_id != payload.contact_id:
            from app.routers.customer import get_c
            try:
                contact, relation = get_c(db, project_id, payload.contact_id, owner_id, status=None, lock=True)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                raise HTTPException(400, "联系人不存在。") from None
            if relation.status == 'pool':
                raise HTTPException(400, "联系人不存在。")
            return contact
        contact_statement = select(Customer).join(ProjectContact, ProjectContact.contact_id == Customer.id).where(Customer.id == payload.contact_id, ProjectContact.site_project_id == project_id)
        contact = db.scalar(contact_statement)
        if not contact:
            raise HTTPException(400, "联系人不存在。")
    return contact
def owner_label(db: Session, owner_user_id: int | None) -> str:
    owner = db.get(User, owner_user_id) if owner_user_id else None
    return f"{owner.display_name} · {owner.email}" if owner else "未分配"


def data(item, contact=None, owner_name: str = ""):
    try: parameters=json.loads(item.parameters_json or "{}")
    except json.JSONDecodeError: parameters={}
    inquiry_items = parameters.pop(INQUIRY_ITEMS_KEY, None)
    try: parameter_notes=json.loads(item.parameter_notes_json or "{}")
    except json.JSONDecodeError: parameter_notes={}
    try: template_fields=json.loads(item.template_fields_json or "[]")
    except json.JSONDecodeError: template_fields=[]
    known = set()
    generic_fields = []
    for field in template_fields:
        key = field.get("key")
        if not key:
            continue
        known.add(key)
        generic_fields.append({"key": key, "title": field.get("label_zh") or field.get("label_en") or key, "content": parameters.get(key, "")})
    generic_fields.extend({"key": key, "title": key, "content": value} for key, value in parameters.items() if key not in known)
    return {**customer_fields(item, contact), "inquiry_items":inquiry_items, "id":item.id,"number":item.number,"inquiry_source":item.inquiry_source or "","product_number":item.product_number or "","inquiry_date":item.inquiry_date.isoformat() if item.inquiry_date else "","company_id":None,"company_name":contact.company if contact else "","company_website":contact.company_website if contact and contact.company_website else "","company_address":contact.company_address if contact and contact.company_address else "","contact_id":item.contact_id,"contact_country":contact.country if contact and contact.country else "","template_key":item.template_key,"template_fields":template_fields,"generic_fields":generic_fields,"status":display_status(item.status),"priority":item.priority,"owner":item.owner or "","owner_name":owner_name,"owner_user_id":item.owner_user_id,"application":item.application or "","quantity":item.quantity or "","next_action_date":item.next_action_date.isoformat() if item.next_action_date else "","notes":item.notes or "","parameters":parameters,"parameter_notes":parameter_notes}

def save(item,payload):
    # Omitted legacy fields must survive edits to unlinked historical inquiries.
    for name in ("notes", "next_action_date"):
        if name in payload.model_fields_set:
            setattr(item, name, getattr(payload, name))
    for name in ("contact_id","status","priority","inquiry_date"): setattr(item,name,getattr(payload,name))
    item.company_id = None
    for name in ("inquiry_source","product_number","owner","application","quantity"): setattr(item,name,clean(getattr(payload,name)))
    item.template_key = "general"
    # Editing a historical RFQ must retain field annotations used by exports.
    try:
        previous_fields = {field["key"]: field for field in json.loads(item.template_fields_json or "[]") if field.get("key")}
    except (json.JSONDecodeError, TypeError):
        previous_fields = {}
    previous_items = data(item)["inquiry_items"] if item.id else None
    fields = [{"key": field.key, "group": "询价内容", "label_en": field.title, "label_zh": field.title, "input_type": "textarea", "unit": previous_fields.get(field.key, {}).get("unit"), "required": False, "note": previous_fields.get(field.key, {}).get("note"), "default_value": None, "options": []} for field in payload.generic_fields]
    item.template_fields_json = json.dumps(fields, ensure_ascii=False)
    parameters = {field.key: field.content for field in payload.generic_fields
                  if field.key != INQUIRY_ITEMS_KEY and field.content.strip()}
    if payload.inquiry_items is not None:
        parameters[INQUIRY_ITEMS_KEY] = [entry.model_dump() for entry in payload.inquiry_items]
    elif previous_items is not None:
        parameters[INQUIRY_ITEMS_KEY] = previous_items
    item.parameters_json = json.dumps(parameters, ensure_ascii=False)
    allowed_keys = {field.key for field in payload.generic_fields}
    item.parameter_notes_json = json.dumps({key: value for key, value in payload.parameter_notes.items() if key in allowed_keys}, ensure_ascii=False)

def automatic_number(db: Session, project_id: int) -> str:
    prefix=f"RFQ-{date.today():%Y%m%d}-"
    sequence=1
    while db.scalar(select(Rfq.id).where(Rfq.site_project_id==project_id,Rfq.number==f"{prefix}{sequence:04d}")):
        sequence += 1
    return f"{prefix}{sequence:04d}"

def validate_number(db: Session, project_id: int, number: str, rfq_id: int | None = None) -> None:
    statement=select(Rfq.id).where(Rfq.site_project_id==project_id,Rfq.number==number)
    if rfq_id is not None:
        statement=statement.where(Rfq.id!=rfq_id)
    if db.scalar(statement):
        raise HTTPException(400,"询价单编号已存在，请更换一个编号。")

@router.get("/projects/{project_id}/templates")
def list_templates(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_access(project_id,user,db);ensure_default_templates(db,project_id)
    return [template_data(item) for item in db.scalars(select(RfqTemplate).where(RfqTemplate.site_project_id==project_id,RfqTemplate.is_active.is_(True)).order_by(RfqTemplate.id)).all()]

@router.post("/projects/{project_id}/templates")
def create_template(project_id:int,payload:TemplatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db)
    if db.scalar(select(RfqTemplate.id).where(RfqTemplate.site_project_id==project_id,RfqTemplate.code==payload.code)): raise HTTPException(400,"模板编码已存在。")
    item=RfqTemplate(site_project_id=project_id,code=payload.code,name_en=payload.name_en.strip(),name_zh=clean(payload.name_zh),description=clean(payload.description),is_active=payload.is_active,fields_json=json.dumps([field.model_dump() for field in payload.fields],ensure_ascii=False));db.add(item);db.commit();db.refresh(item);return template_data(item)

@router.put("/projects/{project_id}/templates/{template_id}")
def update_template(project_id:int,template_id:int,payload:TemplatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db);item=db.scalar(select(RfqTemplate).where(RfqTemplate.id==template_id,RfqTemplate.site_project_id==project_id))
    if not item: raise HTTPException(404,"需求模板不存在。")
    duplicate=db.scalar(select(RfqTemplate.id).where(RfqTemplate.site_project_id==project_id,RfqTemplate.code==payload.code,RfqTemplate.id!=template_id))
    if duplicate: raise HTTPException(400,"模板编码已存在。")
    if item.code != payload.code and db.scalar(select(Rfq.id).where(Rfq.site_project_id==project_id,Rfq.template_key==item.code)): raise HTTPException(400,"该模板已经被询价单使用，不能修改模板编码。")
    fields_json = json.dumps([field.model_dump() for field in payload.fields], ensure_ascii=False)
    item.code=payload.code;item.name_en=payload.name_en.strip();item.name_zh=clean(payload.name_zh);item.description=clean(payload.description);item.is_active=payload.is_active;item.fields_json=fields_json
    allowed_keys = {field.key for field in payload.fields}
    for rfq in db.scalars(select(Rfq).where(Rfq.site_project_id == project_id, Rfq.template_key == item.code)).all():
        try:
            parameters = json.loads(rfq.parameters_json or "{}")
        except json.JSONDecodeError:
            parameters = {}
        try:
            parameter_notes = json.loads(rfq.parameter_notes_json or "{}")
        except json.JSONDecodeError:
            parameter_notes = {}
        rfq.template_fields_json = fields_json
        rfq.parameters_json = json.dumps({key: value for key, value in parameters.items() if key in allowed_keys}, ensure_ascii=False)
        rfq.parameter_notes_json = json.dumps({key: value for key, value in parameter_notes.items() if key in allowed_keys}, ensure_ascii=False)
    db.commit();db.refresh(item);return template_data(item)

@router.delete("/projects/{project_id}/templates/{template_id}")
def delete_template(project_id:int,template_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db);item=db.scalar(select(RfqTemplate).where(RfqTemplate.id==template_id,RfqTemplate.site_project_id==project_id))
    if not item: raise HTTPException(404,"需求模板不存在。")
    item.is_active=False;db.commit();return {"deleted":True}

@router.get("/projects/{project_id}")
def list_rfqs(project_id:int,customer_id:int|None=None,mine:bool=False,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_access(project_id,user,db);ensure_default_templates(db,project_id); rows=[]; owner_id = visible_owner_id(project_id, user, db)
    statement = select(Rfq).where(Rfq.site_project_id==project_id).order_by(Rfq.id.desc())
    if customer_id is not None:
        from app.routers.customer import get_c
        require_project_module(project_id,user,db,'customer_list')
        get_c(db,project_id,customer_id,owner_id)
        statement=statement.where(Rfq.contact_id==customer_id)
    if mine:
        statement=statement.where(Rfq.owner_user_id==user.id)
    if owner_id is not None:
        statement = statement.where(Rfq.owner_user_id == owner_id)
    clock_contacts = []
    for item in sorted(db.scalars(statement).all(), key=rfq_number_key, reverse=True):
        contact=db.get(Customer,item.contact_id) if item.contact_id else None
        rows.append(data(item,contact,owner_name=owner_label(db, item.owner_user_id)))
        clock_contacts.append(contact)
    add_local_clocks(clock_contacts, rows, project_id, db, "customers")
    return rows

@router.get("/projects/{project_id}/references")
def list_rfq_references(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    """Return the lightweight selector data RFQ needs without requiring other module permissions."""
    require_project_access(project_id,user,db)
    owner_id = visible_owner_id(project_id, user, db)
    contact_statement = (
        select(Customer, ProjectContact)
        .join(ProjectContact, ProjectContact.contact_id == Customer.id)
        .where(ProjectContact.site_project_id == project_id, ProjectContact.status.is_distinct_from("pool"))
        .order_by(Customer.name)
    )
    if owner_id is not None:
        contact_statement = contact_statement.where(ProjectContact.owner_user_id == owner_id)
    entries = db.execute(contact_statement).all()
    people = people_by_customer(db, [contact.id for contact, _ in entries])
    return {
        "contacts": [{**customer_reference(contact, relation, people[contact.id]), "owner_user_id": relation.owner_user_id} for contact, relation in entries],
        "is_top_admin": owner_id is None,
        "current_user_id": user.id,
        "owners": project_owners(db, project_id) if owner_id is None else [],
    }

@router.post("/projects/{project_id}")
def create_rfq(project_id:int,payload:RfqPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db);ensure_default_templates(db,project_id); contact=related(db,project_id,payload,visible_owner_id(project_id, user, db))
    number=clean(payload.number) or automatic_number(db,project_id)
    validate_number(db,project_id,number)
    item=Rfq(site_project_id=project_id,number=number,owner_user_id=assign_owner(db,project_id,user,payload,visible_owner_id(project_id,user,db) is None));save_contact_snapshot(db,item,payload,contact);save(item,payload);db.add(item);move_rfq_followup(db,item);db.commit();db.refresh(item)
    return data(item,contact,owner_name=owner_label(db, item.owner_user_id))


@router.post("/projects/{project_id}/customers/{customer_id}")
def create_customer_inquiry(project_id: int, customer_id: int, payload: CustomerInquiryPayload,
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_module(project_id, user, db, "customer_list")
    number = payload.number.strip()
    if not number or not payload.inquiry_items:
        raise HTTPException(422, "请填写编号和询价明细。")
    return create_rfq(project_id, RfqPayload(number=number, contact_id=customer_id,
                                           inquiry_items=payload.inquiry_items), user, db)


class RfqStatusPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['待处理', '推进中', '已报价', '已成交', '已关闭']


@router.patch("/projects/{project_id}/{rfq_id}/status")
def update_rfq_status(project_id: int, rfq_id: int, payload: RfqStatusPayload,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db)
    owner_id = visible_owner_id(project_id, user, db)
    statement = select(Rfq).where(Rfq.id == rfq_id, Rfq.site_project_id == project_id)
    if owner_id is not None:
        statement = statement.where(Rfq.owner_user_id == owner_id)
    item = db.scalar(statement)
    if not item:
        raise HTTPException(404, '询价单不存在。')
    if item.status != payload.status:
        item.status = payload.status
        db.commit()
    return {'id': item.id, 'status': display_status(item.status)}


@router.put("/projects/{project_id}/{rfq_id}")
def update_rfq(project_id:int,rfq_id:int,payload:RfqPayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db); owner_id = visible_owner_id(project_id, user, db); statement = select(Rfq).where(Rfq.id==rfq_id,Rfq.site_project_id==project_id)
    if owner_id is not None:
        statement = statement.where(Rfq.owner_user_id == owner_id)
    item=db.scalar(statement)
    if not item: raise HTTPException(404,"询价单不存在。")
    contact=related(db,project_id,payload,owner_id,existing=item)
    new_owner=assign_owner(db,project_id,user,payload,owner_id is None,item)
    number=clean(payload.number) or item.number
    validate_number(db,project_id,number,item.id)
    save_contact_snapshot(db,item,payload,contact)
    item.number=number
    item.owner_user_id=new_owner
    save(item,payload);move_rfq_followup(db,item);db.commit();db.refresh(item)
    return data(item,contact,owner_name=owner_label(db, item.owner_user_id))

@router.delete("/projects/{project_id}/{rfq_id}")
def delete_rfq(project_id:int,rfq_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_project_write(project_id,user,db)
    statement = select(Rfq).where(Rfq.id==rfq_id,Rfq.site_project_id==project_id)
    owner_id = visible_owner_id(project_id, user, db)
    if owner_id is not None:
        statement = statement.where(Rfq.owner_user_id == owner_id)
    item=db.scalar(statement)
    if not item: raise HTTPException(404,"询价单不存在。")
    db.delete(item);db.commit()
    return {"deleted":True}
