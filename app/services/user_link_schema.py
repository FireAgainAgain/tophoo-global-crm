"""Add project scoping without copying bookmarks to other users or projects."""
from sqlalchemy import inspect, text


def ensure_user_link_project_schema(engine):
    with engine.begin() as conn:
        for table in ('user_links', 'user_link_categories'):
            columns={c['name'] for c in inspect(conn).get_columns(table)}
            if 'site_project_id' not in columns:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN site_project_id INTEGER NULL'))
                conn.execute(text(f'CREATE INDEX ix_{table}_site_project_id ON {table} (site_project_id)'))
        if engine.dialect.name == 'mysql':
            names={c['name'] for c in inspect(conn).get_unique_constraints('user_link_categories')}
            if 'uq_user_link_category' in names:
                conn.execute(text('ALTER TABLE user_link_categories DROP INDEX uq_user_link_category'))
            if 'uq_user_link_category_project' not in names:
                conn.execute(text('ALTER TABLE user_link_categories ADD CONSTRAINT uq_user_link_category_project UNIQUE (owner_user_id,site_project_id,name)'))
        elif engine.dialect.name == 'sqlite':
            constraints=inspect(conn).get_unique_constraints('user_link_categories')
            if any(c['column_names']==['owner_user_id','name'] for c in constraints):
                conn.execute(text('CREATE TABLE user_link_categories_scoped (id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL REFERENCES users(id), site_project_id INTEGER NULL REFERENCES site_projects(id), name VARCHAR(80) NOT NULL, sort_order INTEGER NOT NULL, CONSTRAINT uq_user_link_category_project UNIQUE(owner_user_id,site_project_id,name))'))
                conn.execute(text('INSERT INTO user_link_categories_scoped SELECT id,owner_user_id,site_project_id,name,sort_order FROM user_link_categories'))
                conn.execute(text('DROP TABLE user_link_categories'))
                conn.execute(text('ALTER TABLE user_link_categories_scoped RENAME TO user_link_categories'))
                for column in ('owner_user_id','site_project_id'):
                    conn.execute(text(f'CREATE INDEX ix_user_link_categories_{column} ON user_link_categories ({column})'))
