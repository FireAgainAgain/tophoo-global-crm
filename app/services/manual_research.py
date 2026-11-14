"""Independent manual-research marker; existing records are never inferred as reviewed."""
from sqlalchemy import inspect, text


def ensure_manual_research_schema(engine):
    with engine.begin() as connection:
        for table in ('crm_leads', 'crm_customers'):
            columns = {column['name'] for column in inspect(connection).get_columns(table)}
            if 'is_manually_researched' not in columns:
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN is_manually_researched BOOLEAN NOT NULL DEFAULT 0'))
