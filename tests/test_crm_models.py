"""Small regression checks for the standalone CRM model registry."""

from app.models import Base, Company, Customer


def test_crm_metadata_contains_only_crm_and_shared_identity_tables():
    expected = {
        "crm_acquisition_connections",
        "crm_user_acquisition_connections",
        "crm_user_acquisition_connection_tests",
        "crm_user_ai_model_configurations",
        "crm_user_ai_feature_bindings",
        "crm_acquisition_connection_tests",
        "crm_ai_configurations",
        "crm_ai_feature_bindings",
        "crm_ai_model_configurations",
        "crm_communication_script_categories",
        "crm_communication_scripts",
        "crm_phrase_categories",
        "crm_phrase_scenes",
        "crm_communication_phrases",
        "crm_quotations",
        "crm_quotation_templates",
        "crm_communication_preferences",
        "crm_communication_settings",
        "crm_companies",
        "crm_competitor_keywords",
        "crm_competitor_websites",
        "crm_competitors",
        "crm_contact_records",
        "crm_follow_up_plans",
        "crm_customer_pool_audits",
        "crm_customers",
        "crm_customer_people",
        "crm_leads",
        "crm_lead_contact_scans",
        "crm_lead_interactions",
        "crm_lead_outreach_drafts",
        "crm_lead_conversion_history",
        "crm_project_companies",
        "crm_project_contacts",
        "crm_prospecting_candidates",
        "crm_prospecting_entries",
        "crm_prospecting_jobs",
        "crm_rfq_templates",
        "crm_rfqs",
        "plans",
        "crm_sales_contracts",
        "crm_signed_contract_files",
        "project_links",
        "project_members",
        "project_roles",
        "revoked_access_tokens",
        "site_projects",
        "subscriptions",
        "users",
        "user_links",
        "user_mail_configurations",
        "user_mail_accounts",
        "user_mail_deliveries",
        "user_link_categories",
        "user_link_migrations",
        "workspace_members",
        "workspaces",
    }
    libraries = {name for name in Base.metadata.tables if name.startswith(('keyword', 'mic_product'))}
    assert {'keywords', 'mic_products'} <= libraries
    assert set(Base.metadata.tables) == expected | libraries


def test_crm_models_use_the_standalone_registry():
    assert Company.metadata is Base.metadata
    assert Customer.metadata is Base.metadata
