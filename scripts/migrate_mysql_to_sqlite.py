"""Copy the configured MySQL database into a new SQLite file and a full archive."""

import argparse
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table, create_engine, select

from app.core.database import engine
from app.models import Base


def archive_schema(source):
    metadata = MetaData()
    for table in source.sorted_tables:
        columns = []
        for column in table.columns:
            kind = column.type.as_generic()
            if isinstance(kind, String):
                kind.collation = None
            columns.append(Column(column.name, kind, primary_key=column.primary_key))
        Table(table.name, metadata, *columns)
    return metadata


def copy_database(target_path, archive_path):
    if engine.dialect.name != "mysql":
        raise RuntimeError("The configured source must be MySQL.")
    if target_path == archive_path or any(p.exists() for p in (target_path, archive_path)):
        raise FileExistsError("Specify two distinct, new SQLite files.")

    source = MetaData()
    source.reflect(bind=engine)
    missing = set(Base.metadata.tables) - set(source.tables)
    if missing:
        raise RuntimeError(f"Missing source tables: {', '.join(sorted(missing))}")
    archive = archive_schema(source)
    target_engine = create_engine(f"sqlite:///{target_path.as_posix()}", hide_parameters=True)
    archive_engine = create_engine(f"sqlite:///{archive_path.as_posix()}", hide_parameters=True)

    def verify(connection, table, expected):
        order = list(table.primary_key.columns)
        actual = connection.execute(select(table).order_by(*order)).tuples().all()
        if actual != expected:
            raise RuntimeError(f"Values did not round-trip in {table.name}.")

    counts = {}
    try:
        with engine.connect() as mysql, target_engine.begin() as target, archive_engine.begin() as backup:
            Base.metadata.create_all(target)
            archive.create_all(backup)
            quote = mysql.dialect.identifier_preparer.quote_identifier
            locks = ", ".join(f"{quote(name)} READ" for name in sorted(source.tables))
            # MyISAM tables do not participate in transactional snapshots.
            mysql.exec_driver_sql(f"LOCK TABLES {locks}")
            try:
                for name, source_table in sorted(source.tables.items()):
                    order = list(source_table.primary_key.columns)
                    records = mysql.execute(select(source_table).order_by(*order)).mappings().all()
                    counts[name] = len(records)
                    for connection, metadata in ((backup, archive), (target, Base.metadata)):
                        table = metadata.tables.get(name)
                        if table is None:
                            continue
                        keys = list(table.c.keys())
                        rows = [{key: row[key] for key in keys} for row in records]
                        for offset in range(0, len(rows), 250):
                            connection.execute(table.insert(), rows[offset:offset + 250])
                        verify(connection, table, [tuple(row.values()) for row in rows])
            finally:
                mysql.exec_driver_sql("UNLOCK TABLES")
            violations = target.exec_driver_sql("PRAGMA foreign_key_check").all()
            if violations:
                tables = ", ".join(sorted({row[0] for row in violations}))
                raise RuntimeError(f"{len(violations)} foreign-key violations: {tables}")
            for connection in (target, backup):
                if connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
                    raise RuntimeError("SQLite integrity check failed.")
    finally:
        target_engine.dispose()
        archive_engine.dispose()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    counts = copy_database(args.target.resolve(), args.archive.resolve())
    print(f"Verified {sum(counts.values())} rows across {len(counts)} source tables.")
