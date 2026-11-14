"""Standalone CRM project helpers and additive schema upgrades."""

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.modules import normalize_module_keys


def ensure_acquisition_criteria_schema(engine: Engine) -> None:
    table = "crm_prospecting_jobs"
    inspector = inspect(engine)
    if table in inspector.get_table_names() and "criteria_json" not in {column["name"] for column in inspector.get_columns(table)}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE crm_prospecting_jobs ADD COLUMN criteria_json TEXT NULL"))
    candidates = "crm_prospecting_candidates"
    if candidates in inspector.get_table_names() and "evidence_json" not in {column["name"] for column in inspector.get_columns(candidates)}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE crm_prospecting_candidates ADD COLUMN evidence_json TEXT NULL"))


def retire_ai_search_parse_binding(engine: Engine) -> None:
    """Remove only the retired search-parser binding; retain model configurations."""
    if "crm_ai_feature_bindings" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM crm_ai_feature_bindings WHERE feature_key = :feature"),
                               {"feature": "auto_prospecting_parse"})


def ensure_ai_model_notes_schema(engine: Engine) -> None:
    """Add optional notes without changing existing model connection settings."""
    table = "crm_ai_model_configurations"
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    if "notes" not in {column["name"] for column in inspector.get_columns(table)}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE crm_ai_model_configurations ADD COLUMN notes TEXT NULL"))


def ensure_workspace_access_schema(engine: Engine) -> None:
    """Move legacy user subscriptions onto the workspace that owns the data."""
    tables = set(inspect(engine).get_table_names())
    if "workspaces" not in tables or "plans" not in tables:
        return
    existing = {column["name"] for column in inspect(engine).get_columns("workspaces")}
    with engine.begin() as connection:
        if "plan_id" not in existing:
            connection.execute(text("ALTER TABLE workspaces ADD COLUMN plan_id INT NULL"))
        if "subscriptions" in tables:
            connection.execute(text(
                "UPDATE workspaces SET plan_id = "
                "(SELECT plan_id FROM subscriptions WHERE subscriptions.user_id = workspaces.owner_id LIMIT 1) "
                "WHERE plan_id IS NULL AND EXISTS "
                "(SELECT 1 FROM subscriptions WHERE subscriptions.user_id = workspaces.owner_id)"
            ))
        connection.execute(text("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code = 'free' LIMIT 1) WHERE plan_id IS NULL"))


def ensure_site_project_sort_column(engine: Engine) -> None:
    if "site_projects" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("site_projects")}
    if "sort_order" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE site_projects ADD COLUMN sort_order INT NOT NULL DEFAULT 0"))
            connection.execute(text("UPDATE site_projects SET sort_order = id WHERE sort_order = 0"))


def ensure_project_link_sort_column(engine: Engine) -> None:
    """Add stable manual ordering to existing project website links."""
    if "project_links" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("project_links")}
    if "sort_order" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE project_links ADD COLUMN sort_order INT NOT NULL DEFAULT 0"))
            connection.execute(text("UPDATE project_links SET sort_order = id WHERE sort_order = 0"))


def ensure_competitor_sort_column(engine: Engine) -> None:
    """Add stable manual ordering to existing competitor research data."""
    if "crm_competitors" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("crm_competitors")}
    if "sort_order" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE crm_competitors ADD COLUMN sort_order INT NOT NULL DEFAULT 0"))
            connection.execute(text("UPDATE crm_competitors SET sort_order = id WHERE sort_order = 0"))


def ensure_user_profile_schema(engine: Engine) -> None:
    if "users" not in inspect(engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as connection:
        if "wechat_id" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN wechat_id VARCHAR(100) NULL"))
        if "session_version" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN session_version VARCHAR(32) NOT NULL DEFAULT ''"))


def ensure_plan_upgrade_column(engine: Engine) -> None:
    if "plans" not in inspect(engine).get_table_names():
        return
    if "is_upgrade_available" not in {column["name"] for column in inspect(engine).get_columns("plans")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE plans ADD COLUMN is_upgrade_available TINYINT(1) NOT NULL DEFAULT 0"))


def ensure_customer_schema(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if "crm_customers" in tables:
        existing = {column["name"] for column in inspect(engine).get_columns("crm_customers")}
        columns = {"customer_type": "VARCHAR(80) NULL", "source": "VARCHAR(80) NULL", "source_type": "VARCHAR(40) NULL", "whatsapp": "VARCHAR(80) NULL", "other_channels": "TEXT NULL", "inquiry_date": "DATE NULL", "grade": "VARCHAR(20) NULL", "owner": "VARCHAR(160) NULL", "status": "VARCHAR(40) NOT NULL DEFAULT 'new'", "last_contact_date": "DATE NULL", "next_follow_up_date": "DATE NULL", "notes": "TEXT NULL", "company_website": "VARCHAR(500) NULL", "company_address": "VARCHAR(500) NULL"}
        with engine.begin() as connection:
            if "people_initialized" not in existing:
                connection.execute(text("ALTER TABLE crm_customers ADD COLUMN people_initialized BOOLEAN NOT NULL DEFAULT 0"))
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE crm_customers ADD COLUMN {name} {definition}"))
            if "company_id" not in existing:
                connection.execute(text("ALTER TABLE crm_customers ADD COLUMN company_id INT NULL"))
            connection.execute(text("UPDATE crm_customers SET grade = NULL WHERE grade IS NOT NULL AND TRIM(grade) = ''"))
    if "crm_project_contacts" in tables:
        existing = {column["name"] for column in inspect(engine).get_columns("crm_project_contacts")}
        columns = {"release_reason": "TEXT NULL", "released_at": "DATETIME NULL"}
        with engine.begin() as connection:
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE crm_project_contacts ADD COLUMN {name} {definition}"))
            connection.execute(text("UPDATE crm_project_contacts SET status = 'active' WHERE status IS NULL OR TRIM(status) = ''"))
    if "crm_companies" in tables:
        company_columns = {column["name"] for column in inspect(engine).get_columns("crm_companies")}
        if "description" not in company_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE crm_companies ADD COLUMN description TEXT NULL"))


def migrate_companies_into_customers(engine: Engine) -> None:
    """Retire separate company masters after copying the three requested facts to customers."""
    tables = set(inspect(engine).get_table_names())
    if not {"crm_customers", "crm_companies"}.issubset(tables):
        return
    with engine.begin() as connection:
        customer_columns = {column["name"] for column in inspect(engine).get_columns("crm_customers")}
        if not {"company", "company_website", "company_address", "company_id"}.issubset(customer_columns):
            return
        # Existing contacts inherit company name, website and address once. Existing
        # per-customer values are deliberately not overwritten when already present.
        connection.execute(text(
            "UPDATE crm_customers customer JOIN crm_companies company ON company.id = customer.company_id "
            "SET customer.company = CASE WHEN customer.company IS NULL OR TRIM(customer.company) = '' THEN company.name ELSE customer.company END, "
            "customer.company_website = CASE WHEN customer.company_website IS NULL OR TRIM(customer.company_website) = '' THEN company.website ELSE customer.company_website END, "
            "customer.company_address = CASE WHEN customer.company_address IS NULL OR TRIM(customer.company_address) = '' THEN company.address ELSE customer.company_address END"
        ) if engine.dialect.name == "mysql" else text(
            "UPDATE crm_customers SET "
            "company = COALESCE(NULLIF(company, ''), (SELECT name FROM crm_companies WHERE id = crm_customers.company_id)), "
            "company_website = COALESCE(NULLIF(company_website, ''), (SELECT website FROM crm_companies WHERE id = crm_customers.company_id)), "
            "company_address = COALESCE(NULLIF(company_address, ''), (SELECT address FROM crm_companies WHERE id = crm_customers.company_id)) "
            "WHERE company_id IS NOT NULL"
        ))
        # RFQs that already have a customer keep it. A historical company-only RFQ is
        # attached to a neutral customer record so its company context is not lost.
        if "crm_rfqs" in tables:
            company_only = connection.execute(text(
                "SELECT rfq.id, rfq.site_project_id, rfq.company_id, company.workspace_id, company.name, company.website, company.address "
                "FROM crm_rfqs rfq JOIN crm_companies company ON company.id = rfq.company_id "
                "WHERE rfq.contact_id IS NULL AND rfq.company_id IS NOT NULL"
            )).mappings().all()
            for row in company_only:
                result = connection.execute(text(
                    "INSERT INTO crm_customers (workspace_id, name, company, company_website, company_address, created_at, updated_at) "
                    "VALUES (:workspace_id, '待维护联系人', :company, :website, :address, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"workspace_id": row["workspace_id"], "company": row["name"], "website": row["website"], "address": row["address"]})
                contact_id = result.lastrowid
                connection.execute(text(
                    "INSERT INTO crm_project_contacts (site_project_id, contact_id, created_at, updated_at) VALUES (:project_id, :contact_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"project_id": row["site_project_id"], "contact_id": contact_id})
                connection.execute(text("UPDATE crm_rfqs SET contact_id = :contact_id WHERE id = :id"), {"contact_id": contact_id, "id": row["id"]})
            connection.execute(text("UPDATE crm_rfqs SET company_id = NULL WHERE company_id IS NOT NULL"))
        connection.execute(text("UPDATE crm_customers SET company_id = NULL WHERE company_id IS NOT NULL"))
        if "crm_project_companies" in tables:
            connection.execute(text("DELETE FROM crm_project_companies"))
        # The retired table may remain physically present for backward-compatible
        # metadata creation, but its records are intentionally removed.
        connection.execute(text("DELETE FROM crm_companies"))


def ensure_contact_record_schema(engine: Engine) -> None:
    """Add optional translated contact content without changing existing records."""
    if "crm_contact_records" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("crm_contact_records")}
    with engine.begin() as connection:
        if "content_translation" not in existing:
            connection.execute(text("ALTER TABLE crm_contact_records ADD COLUMN content_translation TEXT NULL"))
        if "contact_name" not in existing:
            connection.execute(text("ALTER TABLE crm_contact_records ADD COLUMN contact_name VARCHAR(160) NULL"))
        if "created_by_user_id" not in existing:
            connection.execute(text("ALTER TABLE crm_contact_records ADD COLUMN created_by_user_id INT NULL"))


def ensure_removed_contact_summaries(engine: Engine) -> None:
    """Remove the retired contact-summary feature and its standalone data."""
    if "crm_contact_summaries" not in inspect(engine).get_table_names():
        return
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE crm_contact_summaries"))


def ensure_rfq_schema(engine: Engine) -> None:
    if "crm_rfqs" not in inspect(engine).get_table_names():
        return
    existing = {column["name"]: column for column in inspect(engine).get_columns("crm_rfqs")}
    columns = {
        "template_fields_json": "TEXT NOT NULL",
        "parameter_notes_json": "TEXT NULL",
        "contact_person_id": "INTEGER NULL",
        "contact_snapshot_json": "TEXT NULL",
        "inquiry_source": "VARCHAR(160) NULL",
        "product_number": "VARCHAR(160) NULL",
        "inquiry_date": "DATE NULL",
    }
    added_template_fields = False
    with engine.begin() as connection:
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE crm_rfqs ADD COLUMN {name} {definition}"))
                added_template_fields = added_template_fields or name == "template_fields_json"
        if added_template_fields:
            connection.execute(text("UPDATE crm_rfqs SET template_fields_json = '[]' WHERE template_fields_json IS NULL OR template_fields_json = ''"))
        if "parameter_notes_json" not in existing:
            connection.execute(text("UPDATE crm_rfqs SET parameter_notes_json = '{}' WHERE parameter_notes_json IS NULL OR parameter_notes_json = ''"))
        connection.execute(text("UPDATE crm_rfqs SET status = '询盘' WHERE status IS NULL OR status = '' OR status = 'draft'"))
        if "product_id" in existing:
            connection.execute(text("UPDATE crm_rfqs SET product_id = NULL WHERE product_id IS NOT NULL"))
        if engine.dialect.name == "mysql":
            if not existing.get("company_id", {}).get("nullable", False):
                connection.execute(text("ALTER TABLE crm_rfqs MODIFY COLUMN company_id INT NULL"))
            if not existing.get("contact_id", {}).get("nullable", False):
                connection.execute(text("ALTER TABLE crm_rfqs MODIFY COLUMN contact_id INT NULL"))
        for table, field_column in (("crm_rfq_templates", "fields_json"), ("crm_rfqs", "template_fields_json")):
            if table not in inspect(engine).get_table_names():
                continue
            rows = connection.execute(text(f"SELECT id, {field_column} FROM {table}")).mappings().all()
            for row in rows:
                try:
                    fields = json.loads(row[field_column] or "[]")
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(fields, list):
                    continue
                changed = False
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    legacy_example = field.pop("placeholder", None)
                    if legacy_example is not None and "note" not in field:
                        field["note"] = legacy_example
                    changed = changed or legacy_example is not None
                if changed:
                    connection.execute(text(f"UPDATE {table} SET {field_column} = :fields WHERE id = :id"), {"fields": json.dumps(fields, ensure_ascii=False), "id": row["id"]})
        for table, field_column, template_column in (("crm_rfq_templates", "fields_json", "code"), ("crm_rfqs", "template_fields_json", "template_key")):
            if table not in inspect(engine).get_table_names():
                continue
            rows = connection.execute(text(f"SELECT id, {field_column} FROM {table} WHERE {template_column} = 'heat_exchanger'")).mappings().all()
            for row in rows:
                try:
                    fields = json.loads(row[field_column] or "[]")
                except (TypeError, json.JSONDecodeError):
                    continue
                changed = False
                for field in fields:
                    if isinstance(field, dict) and field.get("note") is not None:
                        field["note"] = None
                        changed = True
                if changed:
                    connection.execute(text(f"UPDATE {table} SET {field_column} = :fields WHERE id = :id"), {"fields": json.dumps(fields, ensure_ascii=False), "id": row["id"]})



def ensure_project_memberships(engine: Engine) -> None:
    """Backfill existing workspace members so the access model changes safely."""
    tables = set(inspect(engine).get_table_names())
    if not {"site_projects", "workspace_members", "project_members"}.issubset(tables):
        return
    with engine.begin() as connection:
        if connection.execute(text("SELECT id FROM project_members LIMIT 1")).scalar():
            return
        rows = connection.execute(text(
            "SELECT p.id AS project_id, wm.user_id, wm.role AS workspace_role "
            "FROM site_projects p JOIN workspace_members wm ON wm.workspace_id = p.workspace_id"
        )).mappings().all()
        for row in rows:
            exists = connection.execute(text(
                "SELECT id FROM project_members WHERE site_project_id = :project_id AND user_id = :user_id"
            ), {"project_id": row["project_id"], "user_id": row["user_id"]}).scalar()
            if not exists:
                role = "top_admin" if row["workspace_role"] in {"owner", "admin"} else "sales"
                connection.execute(text(
                    "INSERT INTO project_members (site_project_id, user_id, role, is_active, created_at) "
                    "VALUES (:project_id, :user_id, :role, 1, NOW())"
                ), {"project_id": row["project_id"], "user_id": row["user_id"], "role": role})


def ensure_project_member_schema(engine: Engine) -> None:
    """Add role fields and migrate historical broad permissions to navigation modules."""
    tables = set(inspect(engine).get_table_names())
    if "project_members" not in tables:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("project_members")}
    with engine.begin() as connection:
        if "write_permissions_json" not in columns:
            connection.execute(text("ALTER TABLE project_members ADD COLUMN write_permissions_json TEXT NULL"))
        if "last_accessed_at" not in columns:
            connection.execute(text("ALTER TABLE project_members ADD COLUMN last_accessed_at DATETIME NULL"))
        if "project_roles" in tables and "write_permissions_json" not in {c["name"] for c in inspect(engine).get_columns("project_roles")}:
            connection.execute(text("ALTER TABLE project_roles ADD COLUMN write_permissions_json TEXT NULL"))
        if "permissions_json" not in columns:
            connection.execute(text("ALTER TABLE project_members ADD COLUMN permissions_json TEXT NULL"))
        if "project_role_id" not in columns:
            connection.execute(text("ALTER TABLE project_members ADD COLUMN project_role_id INT NULL"))
        connection.execute(text("UPDATE project_members SET role = 'top_admin' WHERE role = 'manager'"))
        connection.execute(text(
            "UPDATE project_members SET role = 'custom', "
            "permissions_json = '[\"knowledge_base\",\"competitor_research\",\"companies\",\"contacts\",\"rfq\"]' "
            "WHERE role = 'editor'"
        ))
        members = connection.execute(text("SELECT id, permissions_json FROM project_members WHERE permissions_json IS NOT NULL")).mappings()
        for member in members:
            try:
                permissions = json.loads(member["permissions_json"])
            except (TypeError, json.JSONDecodeError):
                permissions = []
            normalized_permissions = normalize_module_keys(permissions)
            if normalized_permissions != permissions:
                connection.execute(text("UPDATE project_members SET permissions_json = :permissions WHERE id = :id"), {
                    "id": member["id"], "permissions": json.dumps(normalized_permissions, ensure_ascii=False),
                })
        if "project_roles" in tables:
            roles = connection.execute(text("SELECT id, permissions_json FROM project_roles")).mappings()
            for role in roles:
                try:
                    permissions = json.loads(role["permissions_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    permissions = []
                normalized_permissions = normalize_module_keys(permissions)
                if normalized_permissions != permissions:
                    connection.execute(text("UPDATE project_roles SET permissions_json = :permissions WHERE id = :id"), {
                        "id": role["id"], "permissions": json.dumps(normalized_permissions, ensure_ascii=False),
                    })


def ensure_workspace_customer_schema(engine: Engine) -> None:
    """Promote legacy project customers into workspace masters without deleting data."""
    tables = set(inspect(engine).get_table_names())
    if not {"site_projects", "crm_companies", "crm_customers"}.issubset(tables):
        return
    with engine.begin() as connection:
        company_columns = {column["name"]: column for column in inspect(engine).get_columns("crm_companies")}
        contact_columns = {column["name"]: column for column in inspect(engine).get_columns("crm_customers")}
        if "workspace_id" not in company_columns:
            connection.execute(text("ALTER TABLE crm_companies ADD COLUMN workspace_id INT NULL"))
        if "workspace_id" not in contact_columns:
            connection.execute(text("ALTER TABLE crm_customers ADD COLUMN workspace_id INT NULL"))
        project_contact_columns = {column["name"] for column in inspect(engine).get_columns("crm_project_contacts")} if "crm_project_contacts" in tables else set()
        if "crm_project_contacts" in tables and "status" not in project_contact_columns:
            connection.execute(text("ALTER TABLE crm_project_contacts ADD COLUMN status VARCHAR(80) NULL"))
        if "crm_project_contacts" in tables:
            if "release_reason" not in project_contact_columns:
                connection.execute(text("ALTER TABLE crm_project_contacts ADD COLUMN release_reason TEXT NULL"))
            if "released_at" not in project_contact_columns:
                connection.execute(text("ALTER TABLE crm_project_contacts ADD COLUMN released_at DATETIME NULL"))
            if "released_by_user_id" not in project_contact_columns:
                connection.execute(text("ALTER TABLE crm_project_contacts ADD COLUMN released_by_user_id INT NULL"))
            # Existing sales statuses now all belong to the active customer list.
            # Only the dedicated "pool" state is excluded from that list.
            connection.execute(text(
                "UPDATE crm_project_contacts SET status = 'active' "
                "WHERE status IS NULL OR TRIM(status) = '' "
                "OR status IN ('询盘', '已报价', '沟通失败')"
            ))

        if "site_project_id" in company_columns:
            connection.execute(text(
                "UPDATE crm_companies company JOIN site_projects project ON project.id = company.site_project_id "
                "SET company.workspace_id = project.workspace_id WHERE company.workspace_id IS NULL"
            ))
            connection.execute(text(
                "INSERT INTO crm_project_companies (site_project_id, company_id, source, status, notes, created_at, updated_at) "
                "SELECT company.site_project_id, company.id, company.source, company.status, company.notes, NOW(), NOW() "
                "FROM crm_companies company LEFT JOIN crm_project_companies relation "
                "ON relation.site_project_id = company.site_project_id AND relation.company_id = company.id "
                "WHERE company.site_project_id IS NOT NULL AND relation.id IS NULL"
            ))
        if "site_project_id" in contact_columns:
            connection.execute(text(
                "UPDATE crm_customers contact JOIN site_projects project ON project.id = contact.site_project_id "
                "SET contact.workspace_id = project.workspace_id WHERE contact.workspace_id IS NULL"
            ))
            connection.execute(text(
                "INSERT INTO crm_project_contacts (site_project_id, contact_id, source, inquiry_date, created_at, updated_at) "
                "SELECT contact.site_project_id, contact.id, contact.source, contact.inquiry_date, NOW(), NOW() "
                "FROM crm_customers contact LEFT JOIN crm_project_contacts relation "
                "ON relation.site_project_id = contact.site_project_id AND relation.contact_id = contact.id "
                "WHERE contact.site_project_id IS NOT NULL AND relation.id IS NULL"
            ))

        if engine.dialect.name == "mysql":
            if "site_project_id" in company_columns and not company_columns["site_project_id"]["nullable"]:
                connection.execute(text("ALTER TABLE crm_companies MODIFY COLUMN site_project_id INT NULL"))
            if "site_project_id" in contact_columns and not contact_columns["site_project_id"]["nullable"]:
                connection.execute(text("ALTER TABLE crm_customers MODIFY COLUMN site_project_id INT NULL"))


def ensure_project_data_ownership_schema(engine: Engine) -> None:
    """Associate project business records with their responsible user."""
    tables = set(inspect(engine).get_table_names())
    required = {"workspaces", "site_projects", "crm_project_companies", "crm_project_contacts", "crm_rfqs"}
    if not required.issubset(tables):
        return
    with engine.begin() as connection:
        for table in ("crm_project_companies", "crm_project_contacts", "crm_rfqs"):
            columns = {column["name"] for column in inspect(engine).get_columns(table)}
            if "owner_user_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_user_id INT NULL"))
            connection.execute(text(
                f"UPDATE {table} SET owner_user_id = ("
                "SELECT workspace.owner_id FROM site_projects project "
                "JOIN workspaces workspace ON workspace.id = project.workspace_id "
                f"WHERE project.id = {table}.site_project_id"
                ") WHERE owner_user_id IS NULL"
            ))


def delete_project_cascade(db: Session, project_id: int) -> None:
    """Delete project-owned CRM and SEO data in the caller's transaction."""
    from app.services.global_project_data import delete_all_project_data
    delete_all_project_data(db, project_id)
