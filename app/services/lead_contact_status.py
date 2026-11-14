"""Lead-only review status and compatibility with the former contact flag."""
from sqlalchemy import inspect, text

LEAD_STATUSES = {'unviewed': '未查看', 'contacted': '开发中', 'priority_developing': '有回复'}
RETIRED_STATUSES = {
    'ready': 'unviewed', 'checking': 'unviewed', 'checked': 'unviewed',
    'low_match': 'unviewed', 'unfit': 'unviewed', 'fake': 'unviewed',
    'company_contacted': 'contacted', 'replied': 'priority_developing',
}
LEGACY_STAGES = {'todo': 'unviewed', 'developing': 'contacted', 'following': 'contacted', 'replied': 'replied', 'unfit': 'unfit'}


def normalize_status(value, is_contacted=False):
    if value == 'priority':
        return 'contacted' if is_contacted else 'unviewed'
    if value in RETIRED_STATUSES:
        return RETIRED_STATUSES[value]
    if value in (None, 'unviewed') and is_contacted:
        return 'contacted'
    return value if value in LEAD_STATUSES else 'unviewed'


def lead_status(lead):
    return normalize_status(lead.workflow_status, lead.is_contacted)


def set_lead_status(lead, value):
    lead.workflow_status = normalize_status(value)
    lead.is_contacted = lead.workflow_status in ('contacted','priority_developing')
    lead.status_schema_version = 2


def ensure_lead_contact_status_schema(engine):
    with engine.begin() as connection:
        columns = {column['name'] for column in inspect(connection).get_columns('crm_leads')}
        if 'is_contacted' not in columns:
            connection.execute(text('ALTER TABLE crm_leads ADD COLUMN is_contacted BOOLEAN NOT NULL DEFAULT 0'))
        if 'workflow_status' not in columns:
            connection.execute(text("ALTER TABLE crm_leads ADD COLUMN workflow_status VARCHAR(30) NOT NULL DEFAULT 'unviewed'"))
            connection.execute(text("UPDATE crm_leads SET workflow_status = CASE WHEN is_contacted = 1 THEN 'contacted' ELSE 'unviewed' END"))


def unify_lead_status_schema(engine):
    """Migrate each old row once; later edits must never be overwritten on restart."""
    with engine.begin() as connection:
        columns={column['name'] for column in inspect(connection).get_columns('crm_leads')}
        if 'status_schema_version' not in columns:
            connection.execute(text('ALTER TABLE crm_leads ADD COLUMN status_schema_version INTEGER NOT NULL DEFAULT 0'))
        legacy_stage='NULL'
        if 'crm_lead_development' in inspect(connection).get_table_names():
            legacy_stage='(SELECT stage FROM crm_lead_development WHERE lead_id=crm_leads.id)'
        rows=connection.execute(text(f'SELECT id,workflow_status,is_contacted,{legacy_stage} AS legacy_stage FROM crm_leads WHERE status_schema_version < 2')).mappings().all()
        for row in rows:
            value=row['workflow_status']
            if value == 'fake':
                value='unfit'
            elif value == 'priority':
                value='contacted' if row['is_contacted'] else 'ready'
            elif value not in ('ready','low_match','priority_developing','company_contacted','replied','unfit') and row['legacy_stage'] in ('replied','unfit','developing','following'):
                value='ready' if row['legacy_stage']=='developing' and not row['is_contacted'] else LEGACY_STAGES[row['legacy_stage']]
            elif value in ('checked','checking'):value='ready'
            elif value not in LEAD_STATUSES and value not in RETIRED_STATUSES:value='contacted' if row['is_contacted'] else 'unviewed'
            elif value=='unviewed' and row['is_contacted']:value='contacted'
            connection.execute(text('UPDATE crm_leads SET workflow_status=:status,is_contacted=:contacted,status_schema_version=2 WHERE id=:id AND status_schema_version < 2'),{'status':value,'contacted':value in ('contacted','priority_developing','company_contacted','replied'),'id':row['id']})

        connection.execute(text("UPDATE crm_leads SET workflow_status='unfit',is_contacted=0 WHERE workflow_status='fake'"))

        # Merge the retired status even for rows that have already passed schema v2.
        # SQL leaves added/updated dates, research flags and contact history untouched.
        connection.execute(text("UPDATE crm_leads SET workflow_status='ready',is_contacted=0 WHERE workflow_status='checking'"))
        connection.execute(text("UPDATE crm_leads SET workflow_status=CASE WHEN is_contacted=1 THEN 'contacted' ELSE 'ready' END WHERE workflow_status='priority'"))
