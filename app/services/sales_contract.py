"""Validated contract snapshots and values shared by PDF and Excel."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.quotation import QuoteLine, shanghai_today
from app.services.quotation_logo import validate_logo


class ContractLine(QuoteLine):
    name: str = Field(default="", max_length=160)
    brand: str = Field(default="", max_length=100)
    unit: str = Field(default="", max_length=20)
    remark: str = Field(default="", max_length=300)


class ContractDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    layout: Literal["domestic", "export"] = "export"
    contract_date: date = Field(default_factory=shanghai_today)
    signing_place: str = Field(default="", max_length=260)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    buyer_company: str = Field(min_length=1, max_length=260)
    buyer_address: str = Field(default="", max_length=1000)
    attention: str = Field(default="", max_length=160)
    buyer_phone: str = Field(default="", max_length=120)
    buyer_email: str = Field(default="", max_length=260)
    buyer_tax_id: str = Field(default="", max_length=120)
    seller_company: str = Field(min_length=1, max_length=260)
    seller_address: str = Field(default="", max_length=1000)
    salesperson: str = Field(default="", max_length=160)
    seller_phone: str = Field(default="", max_length=120)
    seller_email: str = Field(default="", max_length=260)
    seller_tax_id: str = Field(default="", max_length=120)
    logo_data_url: str = Field(default="", max_length=1500000)
    commodity: str = Field(default="", max_length=260)
    hs_code: str = Field(default="", max_length=40)
    items: list[ContractLine] = Field(min_length=1, max_length=100)
    charge_label: str = Field(default="", max_length=120)
    charge_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    payment_mode: Literal["full", "deposit"] = "full"
    deposit_percent: Decimal = Field(default=Decimal("50"), ge=0, le=100, max_digits=5, decimal_places=2)
    price_term: str = Field(default="", max_length=1000)
    delivery_time: str = Field(default="", max_length=1000)
    packing: str = Field(default="", max_length=1000)
    origin: str = Field(default="", max_length=260)
    price_validity: str = Field(default="", max_length=260)
    transport: str = Field(default="", max_length=1000)
    invoice: str = Field(default="", max_length=1000)
    acceptance: str = Field(default="", max_length=1000)
    quality: str = Field(default="", max_length=1000)
    breach: str = Field(default="", max_length=2000)
    additional_terms: str = Field(default="", max_length=4000)
    receipt_mode: Literal["none", "bank", "alipay"] = "none"
    beneficiary_name: str = Field(default="", max_length=260)
    beneficiary_address: str = Field(default="", max_length=1000)
    beneficiary_bank: str = Field(default="", max_length=500)
    bank_address: str = Field(default="", max_length=1000)
    bank_account: str = Field(default="", max_length=120)
    swift_code: str = Field(default="", max_length=80)
    alipay_name: str = Field(default="", max_length=260)
    alipay_account: str = Field(default="", max_length=160)
    alipay_qr: str = Field(default="", max_length=1500000)

    @field_validator("logo_data_url", "alipay_qr")
    @classmethod
    def valid_image(cls, value):
        return validate_logo(value)

    @model_validator(mode="after")
    def validate_document(self):
        if self.layout == "domestic" and self.currency not in {"CNY", "RMB"}:
            raise ValueError("内销合同请使用人民币。")
        if self.payment_mode == "deposit" and not 0 < self.deposit_percent < 100:
            raise ValueError("定金比例必须大于 0% 且小于 100%。")
        if self.receipt_mode == "bank" and not all((self.beneficiary_name, self.beneficiary_bank, self.bank_account)):
            raise ValueError("公司银行账户须填写户名、开户行和账号。")
        if self.receipt_mode == "alipay" and not (self.alipay_name and (self.alipay_account or self.alipay_qr)):
            raise ValueError("支付宝收款须填写收款人，并填写账号或上传二维码。")
        if self.receipt_mode != "bank":
            for key in BANK_FIELDS:
                setattr(self, key, "")
        if self.receipt_mode != "alipay":
            self.alipay_name = self.alipay_account = self.alipay_qr = ""
        return self


BANK_FIELDS = ("beneficiary_name", "beneficiary_address", "beneficiary_bank", "bank_address", "bank_account", "swift_code")


class ContractPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    number: str = Field(min_length=1, max_length=80)
    source_quote_id: int | None = Field(default=None, gt=0)
    revision: int | None = Field(default=None, gt=0)
    document: ContractDocument


def contract_totals(document):
    def cents(amount):
        return amount.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

    lines = [cents(item.quantity * item.unit_price) for item in document.items]
    total = sum(lines) + document.charge_amount
    deposit = cents(total * document.deposit_percent / 100) if document.payment_mode == "deposit" else total
    return {"lines": lines, "subtotal": sum(lines), "total": total, "deposit": deposit, "balance": total - deposit}


def rmb_upper(amount):
    digits = "零壹贰叁肆伍陆柒捌玖"

    def group(value):
        result = ""
        for scale, unit in ((1000, "仟"), (100, "佰"), (10, "拾"), (1, "")):
            digit, value = divmod(value, scale)
            if digit:
                result += digits[digit] + unit
            elif result and value and not result.endswith("零"):
                result += "零"
        return result

    integer, fraction = divmod(int(amount * 100), 100)
    groups = []
    for unit in ("", "万", "亿", "兆"):
        integer, value = divmod(integer, 10000)
        groups.append((unit, value))
    result = ""
    zero = False
    for unit, value in reversed(groups):
        if not value:
            zero |= bool(result)
            continue
        if result and (zero or value < 1000):
            result += "零"
        result += group(value) + unit
        zero = False
    jiao, fen = divmod(fraction, 10)
    ending = (digits[jiao] + "角" if jiao else ("零" if fen else ""))
    ending += digits[fen] + "分" if fen else ("" if jiao else "整")
    return "人民币" + (result or "零") + "元" + ending


def payment_text(doc):
    if doc.payment_mode == "full":
        return "发货前付清全款" if doc.layout == "domestic" else "100% payment before shipment"
    deposit = f"{doc.deposit_percent.normalize():f}%"
    balance = f"{(100 - doc.deposit_percent).normalize():f}%"
    if doc.layout == "domestic":
        return f"{deposit} 定金，发货前付清 {balance} 尾款"
    return f"{deposit} deposit, {balance} balance before shipment"


def document_terms(doc):
    domestic = doc.layout == "domestic"
    entries = [
        ("价格 / 交货条件", "Price Term", doc.price_term),
        ("付款方式", "Payment Term", payment_text(doc)),
        ("交货时间", "Delivery Time", doc.delivery_time),
        ("包装方式", "Packing", doc.packing),
        ("运输及费用", "Transport and Charges", doc.transport),
        ("原产地", "Origin", doc.origin),
        ("价格有效期", "Price Validity", doc.price_validity),
        ("税费及发票", "Tax and Invoice", doc.invoice),
        ("验收标准", "Acceptance", doc.acceptance),
        ("质量要求", "Quality Requirements", doc.quality),
        ("违约责任", "Breach of Contract", doc.breach),
        ("其他条款", "Additional Terms", doc.additional_terms),
    ]
    domestic_only = {"税费及发票", "验收标准", "质量要求", "违约责任"}
    return [(cn if domestic else en, value) for cn, en, value in entries
            if value and (domestic or cn not in domestic_only)]


def receipt_fields(doc):
    if doc.receipt_mode == "alipay":
        return [("收款人", doc.alipay_name), ("支付宝账号", doc.alipay_account)]
    if doc.receipt_mode == "bank":
        domestic = doc.layout == "domestic"
        labels = ("户名", "收款人地址", "开户行", "银行地址", "账号", "SWIFT") if domestic else (
            "Beneficiary Name", "Beneficiary Address", "Beneficiary Bank", "Bank Address", "Account No.", "SWIFT"
        )
        return [(label, getattr(doc, key)) for label, key in zip(labels, BANK_FIELDS) if getattr(doc, key)]
    return []
