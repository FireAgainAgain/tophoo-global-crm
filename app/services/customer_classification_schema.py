"""Split legacy mixed labels without inferring orders or commercial potential."""
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import inspect, text


def ensure_customer_classification_schema(engine, backup_root=None):
    if not inspect(engine).has_table('crm_customers'):
        return
    columns={column['name'] for column in inspect(engine).get_columns('crm_customers')}
    with engine.begin() as connection:
        for name, definition in [('product_category','VARCHAR(160) NULL'),('product_match','VARCHAR(20) NULL'),('legacy_grade','VARCHAR(20) NULL'),
                                 ('classification_version','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:
                connection.execute(text(f'ALTER TABLE crm_customers ADD COLUMN {name} {definition}'))
        rows=[dict(row) for row in connection.execute(text('SELECT id,grade,product_match,legacy_grade FROM crm_customers WHERE classification_version < 2')).mappings()]
        if rows:
            folder=Path(backup_root) if backup_root else Path(__file__).resolve().parents[2]/'backups'
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/('customer-classification-before-split-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            connection.execute(text("""UPDATE crm_customers SET legacy_grade=grade,
                product_match=CASE grade WHEN 'C' THEN 'A' WHEN 'E' THEN 'B' WHEN 'D' THEN 'C' WHEN 'F' THEN 'D' ELSE NULL END,
                grade=NULL,classification_version=2 WHERE classification_version < 2"""))
        if engine.dialect.name=='mysql':
            connection.execute(text('ALTER TABLE crm_customers ALTER COLUMN classification_version SET DEFAULT 2'))
        inspector = inspect(connection)
        if inspector.has_table('crm_leads') and not any(column['name'] == 'grade' for column in inspector.get_columns('crm_leads')):
            connection.execute(text('ALTER TABLE crm_leads ADD COLUMN grade VARCHAR(20) NULL'))
        if inspector.has_table('crm_project_contacts'):
            relationship_columns = {column['name'] for column in inspector.get_columns('crm_project_contacts')}
            if 'workflow_status' not in relationship_columns:
                connection.execute(text('ALTER TABLE crm_project_contacts ADD COLUMN workflow_status VARCHAR(20) NULL'))
