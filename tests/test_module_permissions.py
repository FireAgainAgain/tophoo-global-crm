"""Keep navigation, plans and project roles on one canonical permission catalog."""

from app.core.modules import MODULE_CATALOG, PROJECT_MODULES, module_catalog_payload, normalize_module_keys


def test_current_navigation_permission_catalog():
    assert list(MODULE_CATALOG) == [
        "project_management",
        "url_navigation",
        "competitor_research",
        "knowledge_base",
        "keyword_library",
        "mic_products",
        "communication_assistant",
        "communication_phrases",
        "auto_prospecting",
        "leads",
        "customer_list",
        "customer_pool",
        "rfq",
        "quotations",
        "ai_configuration",
        "mail_configuration",
    ]
    assert PROJECT_MODULES == set(MODULE_CATALOG)
    groups = {}
    for item in module_catalog_payload():
        groups.setdefault(item["group"], []).append(item["key"])
    assert list(groups) == ["项目", "SEO · 建站", "CRM · 工具", "CRM · 客户", "系统"]
    assert groups["SEO · 建站"] == ["keyword_library", "mic_products"]
    assert groups["CRM · 工具"] == ["communication_assistant", "communication_phrases"]


def test_legacy_permissions_expand_without_access_loss():
    assert normalize_module_keys(["product_research", "customer_management", "rfq"]) == [
        "competitor_research",
        "knowledge_base",
        "communication_assistant",
        "auto_prospecting",
        "leads",
        "customer_list",
        "customer_pool",
        "rfq",
    ]
    assert "communication_phrases" not in normalize_module_keys(["customer_management"])


def test_retired_modules_are_removed():
    assert normalize_module_keys(["suppliers", "customer_statistics", "selection", "opportunities", "sample_orders", "capabilities", "product_catalog"]) == []
