"""Project templates supply defaults; saved quotations retain their own snapshots."""
import json
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models import Quotation, QuotationTemplate, SiteProject
from app.services.quotation import QuoteDocument, defaults

SETTING_KEYS=(
    'logo_data_url','seller_company','seller_address','seller_email','seller_website',
    'seller_phone','seller_fax','salesperson','salesperson_phone','salesperson_email',
    'contact_line','commodity','currency','quantity_unit','payment_mode','deposit_percent','deposit_label',
    'quantity_label','subtotal_label','total_label','balance_label','include_balance','include_local_charge','local_charge_label','local_charge_amount','price_term','payment_term','delivery_time','packing','origin',
    'price_validity','include_bank','beneficiary_name','beneficiary_address',
    'beneficiary_bank','bank_address','bank_account','swift_code','pdf_layout','pdf_logo_width',
)


def normalize_settings(settings):
    if set(settings)-set(SETTING_KEYS):
        raise ValueError('模板只能保存卖方资料、版式和默认条款，不能包含客户或产品价格。')
    base=defaults();base.update(settings)
    base.update(buyer_company='Template preview',items=[dict(description='Heat exchanger',quantity='1',unit_price='0')])
    values=QuoteDocument(**base).model_dump(mode='json')
    return {key:values[key] for key in SETTING_KEYS}


class TemplatePayload(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid',validate_default=True)
    name: str=Field(min_length=1,max_length=120)
    revision: int | None=Field(default=None,ge=1)
    settings: dict[str,Any]=Field(default_factory=dict)

    @field_validator('settings')
    @classmethod
    def valid_settings(cls,value):
        return normalize_settings(value)


def built_in():
    return dict(id=0,name='标准报价模板',revision=1,settings=normalize_settings({}))


def template_data(row):
    values={**defaults(),**json.loads(row.data_json)}
    return dict(id=row.id,name=row.name,revision=row.revision,settings={key:values[key] for key in SETTING_KEYS})


def templates_for(db,project_id):
    rows=list(db.scalars(select(QuotationTemplate).where(QuotationTemplate.site_project_id==project_id)
                         .order_by(QuotationTemplate.id)))
    return [template_data(row) for row in rows] if rows else [built_in()]


def legacy_template(document):
    """Give older quotes a template label without changing their saved settings."""
    if not document.get('template_name'):
        return {**document,'template_id':0,'template_name':built_in()['name'],'template_revision':1}
    return document


def seed_templates(db):
    """Idempotent startup migration; change only template metadata on old quotations."""
    for project_id in db.scalars(select(SiteProject.id)).all():
        quotes=db.scalars(select(Quotation).where(Quotation.site_project_id==project_id)).all()
        default=built_in()
        name=default['name']
        row=db.scalar(select(QuotationTemplate).where(QuotationTemplate.site_project_id==project_id,QuotationTemplate.name==name))
        if row is None:
            existing=db.scalar(select(QuotationTemplate.id).where(QuotationTemplate.site_project_id==project_id))
            unclassified=any(not json.loads(quote.data_json).get('template_name') for quote in quotes)
            if existing and not unclassified:continue
            row=QuotationTemplate(site_project_id=project_id,name=default['name'],
                                  data_json=json.dumps(default['settings'],ensure_ascii=False))
            db.add(row)
            try:db.commit()
            except IntegrityError:
                db.rollback()
                row=db.scalar(select(QuotationTemplate).where(QuotationTemplate.site_project_id==project_id,QuotationTemplate.name==name))
        if row is None:continue
        for quote in quotes:
            old=quote.data_json;document=json.loads(old)
            if document.get('template_name'):continue
            document.update(template_id=row.id,template_name=name,template_revision=1)
            db.execute(update(Quotation).where(Quotation.id==quote.id,Quotation.data_json==old)
                       .values(data_json=json.dumps(document,ensure_ascii=False),updated_at=quote.updated_at)
                       .execution_options(synchronize_session=False))
        db.commit()
