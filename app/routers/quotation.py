"""Owner-scoped sales quotations with stable snapshots and server-side totals."""
import json
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_module, require_project_write
from app.models import Quotation, QuotationTemplate, CustomerPerson, Customer, ProjectContact, User
from app.routers.rfq import visible_owner_id
from app.services.customer_people import people_by_customer
from app.services.rfq_customer import customer_reference
from app.services.quotation_links import live_document
from app.services.quotation import QuotePayload, calculate, defaults, shanghai_today
from app.services.quotation_templates import TemplatePayload, built_in, template_data, templates_for, legacy_template

router=APIRouter(prefix='/api/quotations',tags=['Quotations'])


def access(project_id,user,db,write=False):
    return (require_project_write if write else require_project_module)(project_id,user,db,'quotations')


def scoped(db,project_id,quote_id,user,lock=False):
    statement=select(Quotation).where(Quotation.id==quote_id,Quotation.site_project_id==project_id)
    owner=visible_owner_id(project_id,user,db)
    if owner is not None:statement=statement.where(Quotation.owner_user_id==owner)
    if lock and db.get_bind().dialect.name == 'sqlite':
        db.execute(update(Quotation).where(statement.whereclause).values(
            id=Quotation.id, updated_at=Quotation.updated_at,
        ))
    if lock:statement=statement.with_for_update()
    item=db.scalar(statement)
    if not item:raise HTTPException(404,'报价单不存在或无权访问。')
    return item


def data(item,db=None,user=None,document=None):
    if document is None:document=json.loads(item.data_json)
    document=legacy_template(document)
    if db is not None:
        document=live_document(db,item.site_project_id,visible_owner_id(item.site_project_id,user,db),document,item.customer_id)
    return {'id':item.id,'number':item.number,'status':item.status,'revision':item.revision,
            'customer_id':item.customer_id,'rfq_id':item.rfq_id,'owner_user_id':item.owner_user_id,
            'document':document,'totals':calculate(document),'updated_at':item.updated_at.isoformat()}


@router.get('/projects/{project_id}')
def list_quotes(project_id:int,customer_id:int|None=None,mine:bool=False,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    statement=select(Quotation).where(Quotation.site_project_id==project_id).order_by(Quotation.quote_date.desc(),Quotation.id.desc())
    owner=visible_owner_id(project_id,user,db)
    if customer_id is not None:
        from app.routers.customer import get_c
        require_project_module(project_id,user,db,'customer_list')
        get_c(db,project_id,customer_id,owner)
        statement=statement.where(Quotation.customer_id==customer_id)
    if mine:
        statement=statement.where(Quotation.owner_user_id==user.id)
    if owner is not None:statement=statement.where(Quotation.owner_user_id==owner)
    cache={}
    return [data(item,document=live_document(db,project_id,owner,json.loads(item.data_json),item.customer_id,cache)) for item in db.scalars(statement)]


@router.get('/projects/{project_id}/references')
def references(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);owner=visible_owner_id(project_id,user,db)
    query=select(Customer,ProjectContact).join(ProjectContact,Customer.id==ProjectContact.contact_id).where(ProjectContact.site_project_id==project_id,ProjectContact.status.is_distinct_from('pool'))
    if owner is not None:
        query=query.where(ProjectContact.owner_user_id==owner)
    entries=db.execute(query.order_by(Customer.company)).all();people=people_by_customer(db,[c.id for c,_ in entries])
    return {'customers':[customer_reference(c,r,people[c.id]) for c,r in entries],
            'defaults':defaults(),'templates':templates_for(db,project_id)}


@router.get('/projects/{project_id}/templates')
def list_templates(project_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    return templates_for(db,project_id)


def scoped_template(db,project_id,template_id):
    row=db.scalar(select(QuotationTemplate).where(QuotationTemplate.id==template_id,QuotationTemplate.site_project_id==project_id))
    if not row:raise HTTPException(404,'报价模板不存在或不属于当前项目。')
    return row


def write_template(db,project_id,payload,existing=None):
    duplicate=db.scalar(select(QuotationTemplate).where(QuotationTemplate.site_project_id==project_id,QuotationTemplate.name==payload.name))
    if duplicate and (not existing or duplicate.id!=existing.id):raise HTTPException(409,'模板名称已存在，请更换名称。')
    try:
        values=dict(name=payload.name,data_json=json.dumps(payload.settings,ensure_ascii=False))
        if existing:
            revision=payload.revision
            result=db.execute(update(QuotationTemplate).where(QuotationTemplate.id==existing.id,QuotationTemplate.revision==revision)
                              .values(**values,revision=revision+1).execution_options(synchronize_session=False))
            if result.rowcount!=1:
                db.rollback();raise HTTPException(409,'模板已被修改，请重新打开后再保存。')
            db.commit();db.expire_all();return template_data(db.get(QuotationTemplate,existing.id))
        row=QuotationTemplate(site_project_id=project_id,**values);db.add(row);db.commit()
        return template_data(row)
    except IntegrityError:
        db.rollback();raise HTTPException(409,'模板名称发生冲突，请刷新后重试。') from None


@router.post('/projects/{project_id}/templates',status_code=201)
def create_template(project_id:int,payload:TemplatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db,True)
    return write_template(db,project_id,payload)


@router.put('/projects/{project_id}/templates/{template_id}')
def edit_template(project_id:int,template_id:int,payload:TemplatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db,True);row=scoped_template(db,project_id,template_id)
    if payload.revision!=row.revision:raise HTTPException(409,'模板已被修改，请重新打开后再保存。')
    return write_template(db,project_id,payload,row)


@router.post('/projects/{project_id}/templates/preview-pdf')
def preview_template(project_id:int,payload:TemplatePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    document={**payload.settings,'buyer_company':'Sample Buyer','attention':'Purchasing Manager',
              'items':[dict(description='Heat Exchanger - Sample Model',quantity='1',unit_price='100')],
              'quote_date':shanghai_today().isoformat()}
    return Response(pdf_bytes(document),media_type='application/pdf')


@router.get('/projects/{project_id}/templates/{template_id}/xlsx')
def export_template_excel(project_id:int,template_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    template=template_data(scoped_template(db,project_id,template_id)) if template_id!=0 else built_in()
    document={**template['settings'],'buyer_company':'Template buyer',
              'items':[dict(description='Template item',quantity='1',unit_price='0')]}
    return excel_response(document,template['name']+'.xlsx',blank_template=True)


def pdf_bytes(document):
    from app.services.quotation_pdf import build_pdf
    try:return build_pdf(document)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None


@router.post('/projects/{project_id}/preview-pdf')
def preview_pdf(project_id:int,payload:QuotePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db)
    validate_links(db,project_id,payload,user)
    document=live_document(db,project_id,visible_owner_id(project_id,user,db),payload.document.model_dump(mode='json'),payload.customer_id)
    return Response(pdf_bytes(document),media_type='application/pdf')


def validate_links(db,project_id,payload,user,existing=None):
    owner=visible_owner_id(project_id,user,db)
    if payload.customer_id is not None and (not existing or existing.customer_id!=payload.customer_id):
        from app.routers.customer import get_c
        try:
            _, relation = get_c(db,project_id,payload.customer_id,owner,status=None,lock=True)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            raise HTTPException(422,'关联客户不存在或不属于当前可访问范围。') from None
        if relation.status == 'pool':
            raise HTTPException(422,'关联客户不存在或不属于当前可访问范围。')
    if payload.document.contact_person_id:
        person=db.get(CustomerPerson,payload.document.contact_person_id)
        if not person or person.customer_id!=payload.customer_id:
            raise HTTPException(422,'关联联系人不存在或不属于所选客户，请重新选择。')


def persist(db,item,payload,user):
    item.buyer_company=payload.document.buyer_company;item.currency=payload.document.currency
    item.quote_date=payload.document.quote_date
    if 'status' in payload.model_fields_set:
        item.status=payload.status
    item.customer_id=payload.customer_id;item.rfq_id=None
    with db.no_autoflush:
        document=live_document(db,item.site_project_id,visible_owner_id(item.site_project_id,user,db),payload.document.model_dump(mode='json'),payload.customer_id)
    if 'logo_data_url' not in payload.document.model_fields_set and item.data_json:
        document['logo_data_url']=json.loads(item.data_json).get('logo_data_url','')
    if item.data_json:
        previous=legacy_template(json.loads(item.data_json))
        for key in ('template_id','template_name','template_revision','pdf_layout','pdf_logo_width'):
            if key in previous:document[key]=previous[key]
    elif document.get('template_id') is not None:
        if document['template_id']==0:
            template=built_in()
        else:
            with db.no_autoflush:
                template=template_data(scoped_template(db,item.site_project_id,document['template_id']))
        if document['template_revision']!=template['revision']:raise HTTPException(409,'模板已更新，请重新选择模板后新建报价。')
        document.update(template_name=template['name'],template_revision=template['revision'])
        for key in ('pdf_layout','pdf_logo_width'):
            document[key]=template['settings'].get(key,defaults()[key])
    item.buyer_company=document['buyer_company']
    item.data_json=json.dumps(document,ensure_ascii=False)
    db.add(item)
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'报价编号已存在，请更换编号后重试。') from None
    return data(item,db,user)


@router.post('/projects/{project_id}',status_code=201)
def create_quote(project_id:int,payload:QuotePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db,True)
    if payload.document.template_id is None:raise HTTPException(422,'请先选择报价模板。')
    validate_links(db,project_id,payload,user)
    from uuid import uuid4
    number=payload.number.strip() or f'QT-{shanghai_today():%Y%m%d}-{uuid4().hex[:8].upper()}'
    item=Quotation(site_project_id=project_id,owner_user_id=user.id,number=number)
    return persist(db,item,payload,user)


@router.put('/projects/{project_id}/{quote_id}')
def update_quote(project_id:int,quote_id:int,payload:QuotePayload,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db,True);item=scoped(db,project_id,quote_id,user,True)
    if payload.revision!=item.revision:raise HTTPException(409,'报价已被修改，请重新打开后再保存。')
    validate_links(db,project_id,payload,user,item)
    item.number=payload.number.strip() or item.number;item.revision+=1
    return persist(db,item,payload,user)


@router.get('/projects/{project_id}/{quote_id}/pdf')
def export_pdf(project_id:int,quote_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);item=scoped(db,project_id,quote_id,user)
    document=live_document(db,project_id,visible_owner_id(project_id,user,db),json.loads(item.data_json),item.customer_id)
    filename='Quotation-'+item.number.replace('/','-').replace('\\','-')+'.pdf'
    return Response(pdf_bytes(document),media_type='application/pdf',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})


@router.delete('/projects/{project_id}/{quote_id}')
def delete_quote(project_id:int,quote_id:int,revision:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db,True);item=scoped(db,project_id,quote_id,user,True)
    if revision!=item.revision:raise HTTPException(409,'报价已变更，请刷新后再删除。')
    db.delete(item);db.commit();return {'deleted':True}


@router.get('/projects/{project_id}/{quote_id}/xlsx')
def export_excel(project_id:int,quote_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    access(project_id,user,db);item=scoped(db,project_id,quote_id,user)
    document=live_document(db,project_id,visible_owner_id(project_id,user,db),json.loads(item.data_json),item.customer_id)
    return excel_response(document,'Quotation-'+item.number+'.xlsx')


def excel_response(document,filename,*,blank_template=False):
    from app.services.quotation_excel import build_excel
    filename=filename.replace('/','-').replace(chr(92),'-')
    return Response(build_excel(document,blank_template=blank_template),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})
