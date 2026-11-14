"""Only the new template table needs transactions for atomic default switching."""
from sqlalchemy import inspect, text


def ensure_template_schema(engine):
    if engine.dialect.name!='mysql':return
    inspector=inspect(engine)
    if not inspector.has_table('crm_quotation_templates'):return
    if inspector.get_table_options('crm_quotation_templates').get('mysql_engine','').lower()!='innodb':
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE crm_quotation_templates ENGINE=InnoDB'))
