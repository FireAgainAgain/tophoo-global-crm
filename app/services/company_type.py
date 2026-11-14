"""Optional company business roles shared across the CRM pipeline."""
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import inspect, text

COMPANY_TYPES = {'distributor':'经销商','importer':'进口商','wholesaler':'批发商','retailer':'零售商','manufacturer':'制造商','contractor':'工程承包商','supplier':'供应商','end_user':'终端用户','service_provider':'服务商'}

def normalize_company_type(value):
    value = (value or '').strip()
    if not value or value.casefold() in {'unknown','未知','未分类'}:
        return None
    if value.isdigit():
        raise ValueError('请填写企业类型，例如经销商或制造商，不能填写数字。')
    aliases = {label:key for key,label in COMPANY_TYPES.items()}
    aliases.update({key:key for key in COMPANY_TYPES})
    aliases.update({'end user':'end_user','service provider':'service_provider'})
    return aliases.get(value.casefold(), value)

def company_type_label(value):
    return COMPANY_TYPES.get(value, value or '未知')

class CompanyTypePayload(BaseModel):
    company_type: str | None = Field(default=None, max_length=80)
    @field_validator('company_type')
    @classmethod
    def validate_company_type(cls, value):
        return normalize_company_type(value)

def save_company_type(item, payload):
    if 'company_type' in payload.model_fields_set:
        item.company_type = payload.company_type

def ensure_company_type_schema(engine):
    with engine.begin() as connection:
        migrate_leads = False
        for table in ('crm_customers','crm_leads','crm_prospecting_entries'):
            columns = {column['name'] for column in inspect(connection).get_columns(table)}
            if 'company_type' not in columns:
                migrate_leads = migrate_leads or table == 'crm_leads'
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN company_type VARCHAR(80) NULL'))
        # Recover only an explicit result-to-lead link, never guess from company names.
        # One-time backfill: later deliberate clearing must survive application restarts.
        if migrate_leads:
            rows = connection.execute(text("SELECT l.id, c.company_type FROM crm_leads l JOIN crm_prospecting_candidates c ON c.lead_id = l.id WHERE l.company_type IS NULL AND c.company_type IS NOT NULL ORDER BY c.id"))
            for lead_id, value in rows.fetchall():
                try:
                    value = normalize_company_type(value)
                except ValueError:
                    continue
                if value:
                    connection.execute(text("UPDATE crm_leads SET company_type = :value WHERE id = :id AND company_type IS NULL"), {'id':lead_id,'value':value})
