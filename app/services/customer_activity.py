"""Customer entry counts share the same project, owner and module boundaries."""
from fastapi import HTTPException
from sqlalchemy import select, func
from app.dependencies.auth import require_project_module
from app.models import ContactRecord, Rfq, Quotation, SalesContract
from app.models.follow_up import FollowUpPlan


def activity_counts(db, project_id, customer_ids, user, with_statuses=False):
    counts = {cid: {'records': 0, 'rfqs': None, 'quotations': None, 'contracts': 0, 'followups': 0} for cid in customer_ids}
    statuses = {cid: {'rfqs': None, 'quotations': None} for cid in customer_ids}
    documents = {cid: {'rfqs': [], 'quotations': []} for cid in customer_ids}
    if not counts:
        return (counts, statuses, documents) if with_statuses else counts
    sources = [('records', ContactRecord, ContactRecord.contact_id, []),
               ('contracts', SalesContract, SalesContract.customer_id, []),
               ('followups', FollowUpPlan, FollowUpPlan.customer_id,
                [FollowUpPlan.owner_user_id == user.id, FollowUpPlan.status == 'pending'])]
    for key, model, column, module in [('rfqs', Rfq, Rfq.contact_id, 'rfq'),
                                       ('quotations', Quotation, Quotation.customer_id, 'quotations')]:
        try:
            require_project_module(project_id, user, db, module)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        for value in counts.values():
            value[key] = 0
        for value in statuses.values():
            value[key] = {}
        sources.append((key, model, column, [model.owner_user_id == user.id]))
    for key, model, column, filters in sources:
        if key in {'rfqs', 'quotations'}:
            query = select(column, model.status, model.id, model.number).where(model.site_project_id == project_id,
                        column.in_(customer_ids), *filters).order_by(model.id.desc())
            for cid, status, document_id, number in db.execute(query):
                if key == 'rfqs':
                    status = {'需求确认中':'推进中', '报价准备中':'推进中', '沟通失败':'已关闭', '询盘':'待处理'}.get(status, status)
                    if status not in {'待处理','推进中','已报价','已成交','已关闭'}:
                        status = '待处理'
                else:
                    status = '草稿' if status in {None, '', '草稿'} else '已报价'
                counts[cid][key] += 1
                statuses[cid][key][status] = statuses[cid][key].get(status, 0) + 1
                if with_statuses:
                    documents[cid][key].append({'id': document_id, 'number': number, 'status': status})
            continue
        query = select(column, func.count()).where(model.site_project_id == project_id,
                    column.in_(customer_ids), *filters).group_by(column)
        for cid, count in db.execute(query):
            counts[cid][key] = count
    return (counts, statuses, documents) if with_statuses else counts
