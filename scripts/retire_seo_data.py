"""Back up and remove retired module tables from the local CRM SQLite database."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "tophoo_global.sqlite3"
TABLES = {
    "crm_quote_calculations", "crm_customer_statistics_events", "crm_customer_statistics_tracking",
    "market_research", "mr_region", "mr_persona", "mr_competitor",
    "article_tdk_imports", "article_tdk_records", "product_tdk_imports", "product_tdk_records",
    "gsc_import_action_tasks", "gsc_import_coverage", "gsc_import_coverage_daily",
    "gsc_import_coverage_issue_batches", "gsc_import_coverage_issue_daily",
    "gsc_import_coverage_issue_pages", "gsc_import_daily_metrics", "gsc_import_dimension_metrics",
    "gsc_import_link_pages", "gsc_import_links", "gsc_import_performance", "keyword_tdk_usages",
}
GRANTS = {"quote_calculator", "customer_statistics", "market_research", "article_tdk", "product_tdk", "gsc_analysis", "gsc_tasks"}


def retire():
    if not DATABASE.is_file():
        raise SystemExit(f"Database missing: {DATABASE}")
    with closing(sqlite3.connect(DATABASE, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        existing = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        pending = TABLES & existing
        if not pending:
            print("No retired module tables found.")
            return
        references = {
            name: {row[2] for row in db.execute("SELECT * FROM pragma_foreign_key_list(?)", (name,))}
            for name in existing
        }
        if any(references[name] & pending for name in existing - pending):
            raise RuntimeError("A retained table still references a retired table.")
        backup = ROOT / "backups" / f"before-module-retirement-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
        backup.parent.mkdir(exist_ok=True)
        db.execute("BEGIN IMMEDIATE")
        with closing(sqlite3.connect(DATABASE, timeout=10)) as source, closing(sqlite3.connect(backup)) as copy:
            source.backup(copy)
            if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed.")
        counts = {name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in pending}
        with db:
            while pending:
                parents = set().union(*(references[name] - {name} for name in pending))
                leaves = sorted(pending - parents)
                if not leaves:
                    raise RuntimeError("Retired tables contain a dependency cycle.")
                for name in leaves:
                    db.execute(f'DROP TABLE "{name}"')
                    pending.remove(name)
            for table, columns in (
                ("plans", ("module_keys_json",)),
                ("project_members", ("permissions_json", "write_permissions_json")),
                ("project_roles", ("permissions_json", "write_permissions_json")),
            ):
                if table not in existing:
                    continue
                available = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                for column in columns:
                    if column not in available:
                        continue
                    for record_id, value in db.execute(f'SELECT id, "{column}" FROM "{table}"').fetchall():
                        try:
                            keys = json.loads(value)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(keys, list):
                            continue
                        retained = [key for key in keys if not isinstance(key, str) or key not in GRANTS]
                        if retained != keys:
                            db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE id=?',
                                       (json.dumps(retained, ensure_ascii=False), record_id))
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"Removed {len(counts)} tables with {sum(counts.values())} rows. Backup: {backup.relative_to(ROOT)}")


if __name__ == "__main__":
    retire()
