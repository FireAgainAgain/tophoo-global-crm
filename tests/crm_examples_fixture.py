"""Fictional full-field records for isolated database regression tests only."""
import json
from datetime import date, datetime
from sqlalchemy import select
from app.dependencies.auth import require_project_write
from app.models import Lead, Customer, LeadInteraction, ProjectContact, CustomerPoolAudit, LeadConversionHistory, ContactRecord, FollowUpPlan
from app.models import User
from app.routers.customer import WorkflowPayload, access, save_w, lead_to_customer, target_owner
from app.services.follow_up import cancel_pending

MARKER='TOPHOO_DEMO_FULL_20261013'
NAMES={'leads':'【演示】北辰空调设备有限公司','contacts':'【演示】示例客户设备','pool':'【演示】示例公池设备'}

def create_examples(db,project_id,owner_id):
    user=db.get(User,owner_id)
    assert user and user.display_name.casefold()=='sam','Unexpected example owner'
    project=require_project_write(project_id,user,db)
    assert project.name=='Demo','Unexpected example project'
    access(project_id,user,db);assert target_owner(project_id,owner_id,user,db)==owner_id
    result={'project_id':project_id,'owner_user_id':owner_id,'marker':MARKER,'examples':[]}
    for kind,name in NAMES.items():
        existing_lead=db.scalar(select(Lead).where(Lead.site_project_id==project_id,Lead.company_name==name))
        existing_customer=db.execute(select(Customer,ProjectContact).join(ProjectContact,ProjectContact.contact_id==Customer.id).where(ProjectContact.site_project_id==project_id,Customer.company==name)).first()
        if existing_lead or existing_customer:
            result['examples'].append({'view':kind,'name':name,'id':existing_lead.id if existing_lead else existing_customer[0].id,'created':False});continue
        domain=f'hvac-demo-{kind}.example'
        people=[]
        for index,(person,email) in enumerate([('Alex Chen（演示采购）','buyer'),('Emma Lin（演示技术）','engineer')]):
            people.append({'contact_name':person,'email':f'{email}@{domain}','phone':f'+00 000 000 10{index+1}','whatsapp':f'+00 000 000 20{index+1}','notes':'虚构演示联系人，请勿外联。采购负责供应商评估。' if index==0 else '虚构演示联系人，请勿外联。技术负责工况与盘管图纸确认。','is_primary':index==0,**{social:f'https://{social}.example/demo/{kind}/{email}' for social in ('linkedin','facebook','instagram','youtube')}})
        payload=WorkflowPayload(company_name=name,country='Germany',company_type='manufacturer',company_website=f'https://{domain}',company_address='Demo Industrial Park, 12 Example Avenue, Berlin（虚构地址）',customer_source='演示展会资料｜HVAC DEMO',source_type='自主开发',notes=f'{MARKER}\n这是虚构演示数据，用于查看完整字段、开发记录和转换历史，请勿用于实际开发。\n应用：AHU / FCU、热泵、制冷设备。\n需求示例：铜管铝翅盘管；需核实尺寸、翅片间距、工况、材质与样品周期。',owner_user_id=owner_id,contacts=people,**{f'company_{social}':f'https://{social}.example/company/{kind}' for social in ('linkedin','facebook','instagram','youtube')})
        item=Lead(site_project_id=project_id,is_contacted=True);save_w(item,payload,owner_id);db.add(item);db.flush()
        for direction,occurred,subject,content in [('outbound',date(2026,10,12),'【演示】盘管配套沟通','【虚构演示，未实际发送】\n介绍铜管铝翅盘管配套范围，请对方确认应用设备、工况和供应商评估流程。'),('inbound',date(2026,10,13),'【演示】技术资料需求','【虚构演示回复】\n请提供选型资料、样品周期及测试条件说明。采购和技术将共同评估。')]:
            db.add(LeadInteraction(site_project_id=project_id,lead_id=item.id,created_by_user_id=owner_id,occurred_at=occurred,direction=direction,contact_name=people[0]['contact_name'] if direction=='outbound' else people[1]['contact_name'],channel='email',subject=subject,content=content))
        db.flush()
        if kind=='leads':example_id=item.id
        else:
            customer=lead_to_customer(db,project,item,user.id);db.flush()
            customer.grade='A' if kind=='contacts' else 'B';customer.job_title='Procurement Manager（演示）';customer.customer_type='设备制造商';customer.source='虚构演示';customer.status='active';customer.last_contact_date=date(2026,10,13);customer.next_follow_up_date=date(2026,10,20)
            relation=db.scalar(select(ProjectContact).where(ProjectContact.site_project_id==project_id,ProjectContact.contact_id==customer.id));relation.inquiry_date=date(2026,10,12)
            if kind in ('contacts','pool'):db.add(FollowUpPlan(site_project_id=project_id,customer_id=customer.id,owner_user_id=owner_id,title='【演示】客户技术跟进',due_at=datetime(2026,10,20,1),notes='客户阶段演示计划'))
            if kind=='pool':
                now=datetime.now();reason='【演示】项目暂缓，释放到公池供查看；并非真实客户。'
                cancel_pending(db,project_id,customer.id,reason)
                relation.status='pool';relation.release_reason=reason;relation.released_at=now;relation.released_by_user_id=user.id
                db.add(CustomerPoolAudit(site_project_id=project_id,contact_id=customer.id,original_owner_user_id=owner_id,released_by_user_id=user.id,release_reason=reason,released_at=now))
            example_id=customer.id
        result['examples'].append({'view':kind,'name':name,'id':example_id,'created':True})
    db.commit()
    for item in result['examples']:
        if item['view']!='leads':
            item['history_count']=len(db.scalars(select(LeadConversionHistory).where(LeadConversionHistory.site_project_id==project_id,LeadConversionHistory.customer_id==item['id'])).all())
            item['record_count']=len(db.scalars(select(ContactRecord).where(ContactRecord.site_project_id==project_id,ContactRecord.contact_id==item['id'])).all())
    return result

