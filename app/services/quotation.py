"""Validated quotation inputs, decimal calculations and read-only Excel import."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


def shanghai_today():return datetime.now(timezone(timedelta(hours=8))).date()


class QuoteLine(BaseModel):
    description: str=Field(min_length=1,max_length=2000)
    quantity: Decimal=Field(gt=0,le=100000000,max_digits=11,decimal_places=3)
    unit_price: Decimal=Field(ge=0,le=1000000000,max_digits=12,decimal_places=2)

    @field_validator('description')
    @classmethod
    def description_not_blank(cls,value):
        if not value.strip():raise ValueError('请填写型号 / 规格。')
        return value.strip()


class QuoteDocument(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    template_id: int | None=Field(default=None,ge=0)
    template_name: str=Field(default='',max_length=120)
    template_revision: int=Field(default=1,ge=1)
    pdf_layout: Literal['standard','compact']='standard'
    pdf_logo_width: float=Field(default=112,ge=60,le=120)
    logo_data_url: str=Field(default='',max_length=1500000)

    @field_validator('logo_data_url')
    @classmethod
    def safe_logo(cls,value):
        from app.services.quotation_logo import validate_logo
        return validate_logo(value)

    quote_date: date=Field(default_factory=shanghai_today)
    currency: str=Field(default='USD',pattern=r'^[A-Z]{3}$')
    contact_person_id: int | None=Field(default=None,gt=0)
    buyer_company: str=Field(min_length=1,max_length=260)
    attention: str=Field(default='',max_length=160)
    buyer_phone: str=Field(default='',max_length=120)
    buyer_email: str=Field(default='',max_length=260)
    buyer_address: str=Field(default='',max_length=1000)
    seller_company: str=Field(default='Your Company',min_length=1,max_length=260)
    seller_address: str=Field(default='',max_length=1000)
    seller_email: str=Field(default='',max_length=260)
    seller_website: str=Field(default='',max_length=260)
    seller_phone: str=Field(default='',max_length=120)
    seller_fax: str=Field(default='',max_length=120)
    salesperson: str=Field(default='',max_length=160)
    salesperson_phone: str=Field(default='',max_length=120)
    salesperson_email: str=Field(default='',max_length=260)
    contact_line: str=Field(default='',max_length=1000)
    commodity: str=Field(default='Heat Exchanger',max_length=260)
    quantity_unit: str=Field(default='UNIT',min_length=1,max_length=20)
    items: list[QuoteLine]=Field(min_length=1,max_length=100)
    payment_mode: Literal['deposit','full'] | None=None
    deposit_percent: Decimal=Field(default=Decimal('30'),ge=0,le=100,max_digits=5,decimal_places=2)
    deposit_label: str=Field(default='',max_length=120)
    quantity_label: str=Field(default='',max_length=120)
    subtotal_label: str=Field(default='',max_length=120)
    total_label: str=Field(default='',max_length=120)
    balance_label: str=Field(default='',max_length=120)
    include_balance: bool=False
    include_local_charge: bool=False
    local_charge_label: str=Field(default='FOB FOSHAN CHARGE :',min_length=1,max_length=120)
    local_charge_amount: Decimal=Field(default=Decimal('0'),ge=0,le=1000000000,max_digits=12,decimal_places=2)
    estimated_volume: Decimal | None=Field(default=None,ge=0,le=100000000,max_digits=11,decimal_places=3)
    price_term: str=Field(default='EXW Foshan, China',max_length=1000)
    payment_term: str=Field(default='30% deposit, 70% balance before shipment',max_length=1000)
    delivery_time: str=Field(default='30 days after receipt of payment',max_length=1000)
    packing: str=Field(default='Standard Export Packing',max_length=1000)
    origin: str=Field(default='China',max_length=260)
    price_validity: str=Field(default='7 days',max_length=260)
    include_bank: bool=False
    beneficiary_name: str=Field(default='',max_length=260)
    beneficiary_address: str=Field(default='',max_length=1000)
    beneficiary_bank: str=Field(default='',max_length=500)
    bank_address: str=Field(default='',max_length=1000)
    bank_account: str=Field(default='',max_length=120)
    swift_code: str=Field(default='',max_length=80)
    internal_notes: str=Field(default='',max_length=5000)

    @property
    def shows_balance(self):
        return self.payment_mode == 'deposit' or (self.payment_mode is None and self.include_balance)

    @property
    def payment_label(self):
        if self.payment_mode == 'full':
            return 'FULL PAYMENT:'
        return self.deposit_label or ('DEPOSIT PAYMENT:' if self.shows_balance else f'{self.deposit_percent.normalize():f}% DEPOSIT:')


class QuotePayload(BaseModel):
    number: str=Field(default='',max_length=80)
    customer_id: int | None=None
    rfq_id: int | None=None
    status: str=Field(default='草稿',pattern=r'^(草稿|已报价)$')
    revision: int | None=None
    document: QuoteDocument


def calculate(document):
    doc=document if isinstance(document,QuoteDocument) else QuoteDocument(**document)
    amounts=[(line.quantity*line.unit_price).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) for line in doc.items]
    subtotal=sum(amounts,Decimal('0.00'))
    total=subtotal+(doc.local_charge_amount if doc.include_local_charge else Decimal('0.00'))
    deposit=(total*doc.deposit_percent/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    result = {'line_amounts':[str(value) for value in amounts], 'total':str(total),
            'quantity_total':str(sum((line.quantity for line in doc.items),Decimal(0))),
            'deposit':str(deposit),'balance':str(total-deposit)}
    if doc.include_local_charge:
        result.update(items_subtotal=str(subtotal),local_charge=f'{doc.local_charge_amount:.2f}')
    return result


def defaults():
    values=QuoteDocument(buyer_company='New buyer',items=[{'description':'New item','quantity':'1','unit_price':'0'}]).model_dump(mode='json')
    values['buyer_company']='';values['items']=[{'description':'','quantity':'1','unit_price':'0'}]
    return values
