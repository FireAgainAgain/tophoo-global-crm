"""Delete project data without touching shared workspace customer masters."""
from sqlalchemy import MetaData, Table, delete, inspect, select
from sqlalchemy.orm import Session
from app.models import Base


def delete_all_project_data(db: Session, project_id: int) -> None:
    """Delete the complete project dependency graph, preserving workspace masters."""
    from sqlalchemy import or_
    excluded = {'crm_customers', 'crm_companies', 'site_projects'}
    scopes = {}
    for table in Base.metadata.sorted_tables:
        if table.name in excluded:
            continue
        if 'site_project_id' in table.c:
            scopes[table.name] = table.c.site_project_id == project_id
        else:
            conditions = [foreign.parent.in_(select(foreign.column).where(scopes[foreign.column.table.name])) for foreign in table.foreign_keys if foreign.column.table.name in scopes]
            if conditions:
                scopes[table.name] = or_(*conditions)
    inspector = inspect(db.connection())
    existing = set(inspector.get_table_names())
    metadata = MetaData()
    for name in ('crm_suppliers', 'crm_selection_options', 'crm_selection_tasks', 'crm_prospecting_job_events', 'crm_prospecting_schedules', 'competitors'):
        if name not in existing:
            continue
        table = Table(name, metadata, autoload_with=db.connection())
        if 'site_project_id' in table.c:
            condition = table.c.site_project_id == project_id
        elif 'selection_task_id' in table.c and 'crm_selection_tasks' in existing:
            tasks = Table('crm_selection_tasks', metadata, autoload_with=db.connection(), extend_existing=True)
            condition = table.c.selection_task_id.in_(select(tasks.c.id).where(tasks.c.site_project_id == project_id))
        elif 'job_id' in table.c:
            jobs = Base.metadata.tables['crm_prospecting_jobs']
            condition = table.c.job_id.in_(select(jobs.c.id).where(jobs.c.site_project_id == project_id))
        else:
            raise RuntimeError(f'Cannot safely scope historical project table: {name}')
        db.execute(delete(table).where(condition))
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in scopes:
            db.execute(delete(table).where(scopes[table.name]))
    projects = Base.metadata.tables['site_projects']
    db.execute(delete(projects).where(projects.c.id == project_id))
