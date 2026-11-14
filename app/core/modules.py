"""Canonical CRM navigation modules and backwards-compatible permission keys."""

MODULE_CATALOG = {
    "project_management": "项目管理",
    "url_navigation": "网址导航",
    "competitor_research": "竞争对手",
    "knowledge_base": "知识库",
    "keyword_library": "关键词库",
    "mic_products": "产品记录",
    "communication_assistant": "全球时间",
    "communication_phrases": "沟通话术",

    "auto_prospecting": "自动获客",
    "leads": "线索列表",
    "customer_list": "客户列表",
    "customer_pool": "客户公池",
    "rfq": "询价单",
    "quotations": "报价单",
    "ai_configuration": "AI 配置",
    "mail_configuration": "邮箱配置",
}

MODULE_GROUPS = (
    ("项目", ("project_management", "url_navigation", "competitor_research", "knowledge_base")),
    ("SEO · 建站", ("keyword_library", "mic_products")),
    ("CRM · 工具", ("communication_assistant", "communication_phrases")),
    ("CRM · 客户", ("auto_prospecting", "leads", "customer_list", "customer_pool", "rfq", "quotations")),
    ("系统", ("ai_configuration", "mail_configuration")),
)

PROJECT_MODULES = frozenset(MODULE_CATALOG)

CRM_CUSTOMER_MODULES = ("communication_assistant", "auto_prospecting", "leads", "customer_list", "customer_pool")

# Old releases authorized whole navigation groups. Expanding those keys keeps
# existing plans and project roles working while all new edits use leaf modules.
LEGACY_MODULE_EXPANSIONS = {
    "product_research": ("knowledge_base", "competitor_research"),
    "customer_management": CRM_CUSTOMER_MODULES,
    "contacts": CRM_CUSTOMER_MODULES,
}

RETIRED_MODULES = frozenset({"quote_calculator", "suppliers", "customer_statistics", "article_creation", "backlink_building", "market_research", "opportunities", "sample_orders", "sales_orders", "selection", "capabilities", "product_catalog"})


def normalize_module_keys(values, *, include_base: bool = False) -> list[str]:
    """Return valid leaf permissions in navigation order, expanding old keys."""
    selected: set[str] = set()
    # Persisted grants must be arrays of strings, never object keys or scalars.
    if not isinstance(values, (list, tuple, set, frozenset)):
        values = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        if value in RETIRED_MODULES:
            continue
        if value in LEGACY_MODULE_EXPANSIONS:
            selected.update(LEGACY_MODULE_EXPANSIONS[value])
        elif value in MODULE_CATALOG:
            selected.add(value)
    # include_base is retained for older callers; every module is now optional.
    return [key for key in MODULE_CATALOG if key in selected]


def module_catalog_payload() -> list[dict[str, object]]:
    group_lookup = {key: group for group, keys in MODULE_GROUPS for key in keys}
    return [
        {"key": key, "name": name, "description": "包含联系人、跟进及跟进计划" if key == "customer_list" else "", "group": group_lookup[key], "is_base": False}
        for key, name in MODULE_CATALOG.items()
    ]
