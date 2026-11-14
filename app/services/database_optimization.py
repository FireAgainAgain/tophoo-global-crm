"""Idempotent indexes for the project keyword library.

`create_all` creates new tables but never adds indexes to existing production tables.
This small migration keeps releases safe for an already populated MySQL database.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


INDEXES: dict[str, tuple[str, str]] = {
    "keyword_categories": ("ix_keyword_category_tree", "site_project_id, parent_id, sort_order"),
}


def ensure_performance_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, (name, columns) in INDEXES.items():
            if table not in tables:
                continue
            existing = {item["name"] for item in inspector.get_indexes(table)}
            if name not in existing:
                connection.execute(text(f"CREATE INDEX {name} ON {table} ({columns})"))
