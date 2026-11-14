"""Read-only referential-integrity audit; never emits business values."""
import json
from sqlalchemy import MetaData, func, inspect, select, text
from app.core.database import engine
from app.models import Base


def run():
    metadata=MetaData()
    problems=[]
    missing_constraints=[]
    checked=0
    with engine.connect() as connection:
        if connection.dialect.name == 'sqlite':
            connection.exec_driver_sql('BEGIN')
        else:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text('START TRANSACTION WITH CONSISTENT SNAPSHOT'))
        metadata.reflect(bind=connection)
        inspector=inspect(connection)
        for name,model in Base.metadata.tables.items():
            if name not in metadata.tables:
                problems.append({'table':name,'problem':'missing table'})
                continue
            actual=metadata.tables[name]
            physical={(tuple(fk['constrained_columns']),fk['referred_table'],tuple(fk['referred_columns'])) for fk in inspector.get_foreign_keys(name)}
            for foreign in model.foreign_keys:
                child=foreign.parent.name
                parent_name=foreign.column.table.name
                parent_key=foreign.column.name
                if child not in actual.c or parent_name not in metadata.tables:
                    problems.append({'table':name,'column':child,'problem':'missing reference schema'})
                    continue
                parent=metadata.tables[parent_name].alias('audit_parent')
                count=connection.scalar(select(func.count()).select_from(actual.outerjoin(parent,actual.c[child]==parent.c[parent_key])).where(actual.c[child].is_not(None),parent.c[parent_key].is_(None)))
                if count:problems.append({'table':name,'column':child,'orphan_count':count})
                if ((child,),parent_name,(parent_key,)) not in physical:
                    missing_constraints.append({'table':name,'column':child,'references':parent_name})
                checked+=1
        # Specific relationships whose two sides both carry a project ID.
        statements={
            'keyword_category_cross_project': 'SELECT COUNT(*) FROM keyword_category_maps m JOIN keywords k ON k.id=m.keyword_id JOIN keyword_categories c ON c.id=m.category_id WHERE k.site_project_id<>c.site_project_id',
        }
        for label,statement in statements.items():
            count=connection.scalar(text(statement))
            if count:problems.append({'problem':label,'count':count})
        delete_blockers=[]
        for name in ('crm_prospecting_entries','crm_leads','crm_ai_model_configurations','crm_customer_pool_audits','crm_prospecting_jobs'):
            if name in metadata.tables:
                table=metadata.tables[name]
                count=connection.scalar(select(func.count()).select_from(table))
                physical=inspector.get_foreign_keys(name)
                if count:delete_blockers.append({'table':name,'rows':count,'project_fk_enforced':any(fk['referred_table']=='site_projects' for fk in physical)})
        connection.rollback()
    print(json.dumps({'references_checked':checked,'integrity_problems':problems,'missing_foreign_constraint_count':len(missing_constraints),'project_table_counts':delete_blockers},ensure_ascii=False,indent=2))


if __name__=='__main__':run()
