"""Customer-scoped sales contracts with frozen documents and signed PDF archives."""
import json
from decimal import Decimal
from io import BytesIO
from typing import Literal
from urllib.parse import quote as encode_filename

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_access, require_project_module, require_project_write
from app.models import SalesContract, SignedContractFile, User
from app.routers.customer import get_c
from app.routers.quotation import data as quotation_data, scoped as scoped_quote
from app.routers.rfq import visible_owner_id
from app.services.quotation_links import live_document
from app.services.quotation_templates import built_in
from app.services.sales_contract import BANK_FIELDS, ContractDocument, ContractPayload, contract_totals

router = APIRouter(prefix="/api/contracts/projects/{project_id}/customers/{customer_id}", tags=["Sales contracts"])
MAX_SIGNED_PDF = 20 * 1024 * 1024


class ContractStatus(BaseModel):
    status: Literal["已发出", "已作废"]
    revision: int = Field(gt=0)


def customer_access(db, project_id, customer_id, user, *, write=False):
    owner = visible_owner_id(project_id, user, db)
    if write:
        project = require_project_write(project_id, user, db, "customer_list")
        get_c(db, project_id, customer_id, owner, lock=True)
    else:
        project = require_project_access(project_id, user, db)
        _, relation = get_c(db, project_id, customer_id, owner, status=None)
        require_project_module(project_id, user, db, "customer_pool" if relation.status == "pool" else "customer_list")
    return project, owner


def get_contract(db, project_id, customer_id, contract_id):
    contract = db.scalar(select(SalesContract).where(
        SalesContract.id == contract_id,
        SalesContract.site_project_id == project_id,
        SalesContract.customer_id == customer_id,
    ))
    if not contract:
        raise HTTPException(404, "此客户下没有这份合同。")
    return contract


def source_quote(db, project_id, customer_id, quotation_id, user):
    require_project_module(project_id, user, db, "quotations")
    row = scoped_quote(db, project_id, quotation_id, user)
    if row.customer_id != customer_id:
        raise HTTPException(422, "来源报价必须属于当前客户。")
    return row


def row_data(row):
    doc = ContractDocument.model_validate_json(row.document_json)
    return {
        "id": row.id, "number": row.number, "status": row.status, "revision": row.revision,
        "date": row.contract_date.isoformat(), "layout": doc.layout, "currency": doc.currency,
        "total": f"{contract_totals(doc)['total']:.2f}", "source_quote_number": row.source_quote_number,
    }


def detail_data(db, row):
    filename = db.scalar(select(SignedContractFile.filename).where(SignedContractFile.contract_id == row.id))
    return {
        **row_data(row), "document": json.loads(row.document_json),
        "source_quote_id": row.source_quote_id, "signed_filename": filename,
    }


@router.get("")
def list_contracts(project_id: int, customer_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user)
    rows = db.execute(select(SalesContract, SignedContractFile.contract_id).outerjoin(
        SignedContractFile, SignedContractFile.contract_id == SalesContract.id,
    ).where(
        SalesContract.site_project_id == project_id, SalesContract.customer_id == customer_id,
    ).order_by(SalesContract.contract_date.desc(), SalesContract.id.desc()))
    return [{**row_data(row), "has_signed": signed_id is not None} for row, signed_id in rows]


@router.get("/defaults")
def defaults(project_id: int, customer_id: int, quotation_id: int | None = None,
             layout: Literal["domestic", "export"] = "export",
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, owner = customer_access(db, project_id, customer_id, user, write=True)
    base = {}
    if project.name.strip().casefold() == "ever":
        settings = built_in()["settings"]
        base = {key: settings[key] for key in ("seller_company", "seller_address", "seller_email",
                 "seller_phone", "salesperson", "logo_data_url", "commodity", "origin", "packing")}
    if not quotation_id:
        base["layout"] = layout
        if layout == "domestic":
            base["currency"] = "CNY"
            if project.name.strip().casefold() == "ever":
                base.update(commodity="换热器", origin="中国", packing="出口包装")
        base = live_document(db, project_id, owner, base, customer_id)
        base.pop("contact_person_id", None)
        return {"document": base}

    row = source_quote(db, project_id, customer_id, quotation_id, user)
    quote = quotation_data(row, db, user)["document"]
    base.update({key: quote[key] for key in ContractDocument.model_fields if key in quote})
    base["layout"] = layout
    partial_deposit = 0 < Decimal(str(base.get("deposit_percent", 0))) < 100
    base["payment_mode"] = quote.get("payment_mode") or ("deposit" if partial_deposit or quote.get("include_balance") else "full")
    if base["payment_mode"] == "deposit" and not partial_deposit:
        base["deposit_percent"] = "50"
    base["items"] = [{**line, "unit": quote.get("quantity_unit", "")} for line in quote["items"]]
    if quote.get("include_local_charge"):
        base.update(charge_label=quote.get("local_charge_label", ""), charge_amount=quote.get("local_charge_amount", "0"))
    if quote.get("include_bank"):
        base["receipt_mode"] = "bank"
    else:
        for key in BANK_FIELDS:
            base.pop(key, None)
    return {"document": base, "source_quote_id": row.id, "source_quote_number": row.number}


@router.post("", status_code=201)
def create_contract(project_id: int, customer_id: int, payload: ContractPayload,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user, write=True)
    source = source_quote(db, project_id, customer_id, payload.source_quote_id, user) if payload.source_quote_id else None
    row = SalesContract(site_project_id=project_id, customer_id=customer_id, owner_user_id=user.id,
                        source_quote_id=source.id if source else None, source_quote_number=source.number if source else None,
                        number=payload.number, contract_date=payload.document.contract_date,
                        document_json=payload.document.model_dump_json())
    db.add(row)
    commit_document(db)
    return detail_data(db, row)


def commit_document(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "当前项目已使用此合同号，请更换编号。") from None


def change(db, row, revision, allowed_statuses, **values):
    result = db.execute(update(SalesContract).where(
        SalesContract.id == row.id, SalesContract.revision == revision,
        SalesContract.status.in_(allowed_statuses),
    ).values(**values, revision=SalesContract.revision + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "合同状态或版本已变化，请刷新后再操作。")


def file_response(content, extension, number, inline=False):
    media = "application/pdf" if extension == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = "Sales-Contract-" + number.replace("/", "-").replace(chr(92), "-") + "." + extension
    disposition = "inline" if inline else "attachment"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{encode_filename(filename, safe='')}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.post("/preview/pdf")
def preview(project_id: int, customer_id: int, payload: ContractPayload,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.sales_contract_exports import build_pdf
    customer_access(db, project_id, customer_id, user, write=True)
    return file_response(build_pdf(payload.number, payload.document), "pdf", payload.number, inline=True)


@router.get("/{contract_id}")
def get_detail(project_id: int, customer_id: int, contract_id: int,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user)
    return detail_data(db, get_contract(db, project_id, customer_id, contract_id))


@router.put("/{contract_id}")
def edit_contract(project_id: int, customer_id: int, contract_id: int, payload: ContractPayload,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user, write=True)
    row = get_contract(db, project_id, customer_id, contract_id)
    try:
        change(db, row, payload.revision, ["草稿"], number=payload.number,
               contract_date=payload.document.contract_date, document_json=payload.document.model_dump_json())
        commit_document(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "当前项目已使用此合同号，请更换编号。") from None
    db.refresh(row)
    return detail_data(db, row)


@router.patch("/{contract_id}/status")
def change_status(project_id: int, customer_id: int, contract_id: int, payload: ContractStatus,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user, write=True)
    row = get_contract(db, project_id, customer_id, contract_id)
    allowed = ["草稿"] if payload.status == "已发出" else ["草稿", "已发出", "已签署"]
    change(db, row, payload.revision, allowed, status=payload.status)
    db.commit()
    db.refresh(row)
    return detail_data(db, row)


@router.get("/{contract_id}/document/{extension}")
def export_document(project_id: int, customer_id: int, contract_id: int, extension: Literal["pdf", "xlsx"],
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.sales_contract_exports import build_excel, build_pdf
    customer_access(db, project_id, customer_id, user)
    row = get_contract(db, project_id, customer_id, contract_id)
    document = ContractDocument.model_validate_json(row.document_json)
    build = build_pdf if extension == "pdf" else build_excel
    return file_response(build(row.number, document), extension, row.number)


@router.post("/{contract_id}/signed")
def upload_signed(project_id: int, customer_id: int, contract_id: int, revision: int,
                  file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from pypdf import PdfReader
    customer_access(db, project_id, customer_id, user, write=True)
    row = get_contract(db, project_id, customer_id, contract_id)
    content = file.file.read(MAX_SIGNED_PDF + 1)
    if len(content) > MAX_SIGNED_PDF:
        raise HTTPException(413, "签回 PDF 不能超过 20 MB。")
    try:
        if not content.startswith(b"%PDF-"):
            raise ValueError()
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not len(reader.pages):
            raise ValueError()
    except Exception:
        raise HTTPException(422, "请上传可打开、未加密的签回 PDF。") from None
    filename = (file.filename or "签回合同.pdf").replace(chr(92), "/").rsplit("/", 1)[-1][:260]
    change(db, row, revision, ["草稿", "已发出"], status="已签署")
    db.add(SignedContractFile(contract_id=row.id, filename=filename, content=content))
    db.commit()
    db.refresh(row)
    return detail_data(db, row)


@router.get("/{contract_id}/signed")
def download_signed(project_id: int, customer_id: int, contract_id: int,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_access(db, project_id, customer_id, user)
    row = get_contract(db, project_id, customer_id, contract_id)
    file = db.get(SignedContractFile, row.id)
    if not file:
        raise HTTPException(404, "这份合同没有签回件。")
    return file_response(file.content, "pdf", row.number + "-signed")
