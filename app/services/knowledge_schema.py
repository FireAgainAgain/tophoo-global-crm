"""Add email markup without rewriting existing Markdown knowledge."""
from sqlalchemy import inspect, text

def ensure_knowledge_rich_schema(engine):
    with engine.begin() as connection:
        columns={c['name']:c['type'] for c in inspect(connection).get_columns('crm_communication_scripts')}
        if 'content_format' not in columns:
            connection.execute(text("ALTER TABLE crm_communication_scripts ADD COLUMN content_format VARCHAR(20) NOT NULL DEFAULT 'markdown'"))
        if 'content_html' not in columns:
            if engine.dialect.name=="mysql":
                connection.execute(text("ALTER TABLE crm_communication_scripts ADD COLUMN content_html LONGTEXT NULL"))
                connection.execute(text("UPDATE crm_communication_scripts SET content_html='' WHERE content_html IS NULL"))
                connection.execute(text("ALTER TABLE crm_communication_scripts MODIFY COLUMN content_html LONGTEXT NOT NULL"))
            else:connection.execute(text("ALTER TABLE crm_communication_scripts ADD COLUMN content_html TEXT NOT NULL DEFAULT ''"))
        if engine.dialect.name=='mysql':
            columns={c['name']:c['type'] for c in inspect(connection).get_columns('crm_communication_scripts')}
            if not str(columns['content_html']).upper().startswith('LONGTEXT'):
                connection.execute(text('ALTER TABLE crm_communication_scripts MODIFY COLUMN content_html LONGTEXT NOT NULL'))
