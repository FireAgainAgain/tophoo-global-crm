"""TOPHOO Global application."""

from sqlalchemy import select, inspect

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.services.user_link_schema import ensure_user_link_project_schema
from app.services.database_optimization import ensure_performance_indexes
from app.services.acquisition_results import ensure_acquisition_results_schema, adopt_legacy_entries, repair_historical_results, merge_repeated_results
from app.services.customer_social import ensure_customer_social_schema
from app.services.company_type import ensure_company_type_schema
from app.services.workflow_people import ensure_workflow_people_schema
from app.services.customer_people import ensure_customer_people_schema
from app.services.lead_development import ensure_lead_development_date_schema, ensure_lead_development_schema, retire_lead_followup_data
from app.services.manual_research import ensure_manual_research_schema
from app.services.lead_contact_status import ensure_lead_contact_status_schema, unify_lead_status_schema
from app.routers import keyword, mic_products
from app.dependencies.auth import get_current_user, project_module_dependency, personal_module_dependency, project_management_dependency

from app.core.database import SessionLocal, engine, get_db
from app.core.config import validate_jwt_secret
from app.dependencies.auth import get_optional_current_user
from app.models import Base, User
from app.routers.auth import router as auth_router
from app.routers.billing import router as billing_router

from app.routers.customer import router as customer_router
from app.routers.lead_development import router as lead_development_router
from app.routers.lead_contact_scan import router as lead_contact_scan_router
from app.routers.contact_records import router as contact_records_router
from app.routers.health import router as health_router
from app.routers.communication_phrases import router as communication_phrases_router
from app.routers.rfq import router as rfq_router
from app.routers.quotation import router as quotation_router
from app.routers.competitor import router as competitor_router
from app.routers.communication_scripts import router as communication_scripts_router
from app.routers.ai_config import router as ai_config_router
from app.routers.mail import router as mail_router


from app.routers.follow_up import router as follow_up_router
from app.routers.sales_contract import router as sales_contract_router
from app.routers.communication import router as communication_router
from app.routers.user_links import router as user_links_router
from app.routers.acquisition import router as acquisition_router, recover_interrupted_tasks
from app.services.billing_service import ensure_default_plans
from app.services.project_service import ensure_ai_model_notes_schema, retire_ai_search_parse_binding, ensure_acquisition_criteria_schema
from app.services.project_service import ensure_competitor_sort_column, ensure_contact_record_schema, ensure_customer_schema, ensure_project_data_ownership_schema, ensure_project_link_sort_column, ensure_project_member_schema, ensure_project_memberships, ensure_removed_contact_summaries, ensure_rfq_schema, ensure_site_project_sort_column, ensure_user_profile_schema, ensure_workspace_access_schema, ensure_workspace_customer_schema, migrate_companies_into_customers


BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create and upgrade only the tables owned by the CRM application."""
    validate_jwt_secret()
    new_quotation_module = not inspect(engine).has_table("crm_quotations")
    new_mic_module = not inspect(engine).has_table("mic_products")
    new_phrase_module = not inspect(engine).has_table("crm_phrase_categories")

    Base.metadata.create_all(bind=engine)
    from app.services.quotation_template_schema import ensure_template_schema
    ensure_template_schema(engine)
    if new_phrase_module:
        from app.services.phrase_module_setup import enable_existing_phrase_access
        with SessionLocal() as db:
            enable_existing_phrase_access(db)
            db.commit()
    from app.services.phrase_content_schema import ensure_phrase_translation_schema
    ensure_phrase_translation_schema(engine)
    from app.services.phrase_scene_schema import ensure_phrase_scene_schema
    ensure_phrase_scene_schema(engine)
    ensure_project_member_schema(engine)
    if new_mic_module:
        from app.services.mic_module_setup import enable_existing_wp_access
        with SessionLocal() as db:
            enable_existing_wp_access(db)
            db.commit()
    from app.services.mic_group_schema import ensure_mic_group_columns, migrate_individual_products
    ensure_mic_group_columns(engine)
    with SessionLocal() as db:
        migrate_individual_products(db)
        from app.services.mic_product_labels import sync_publication_statuses
        sync_publication_statuses(db)
        db.commit()
    ensure_customer_social_schema(engine)
    ensure_ai_model_notes_schema(engine)
    ensure_acquisition_criteria_schema(engine)
    ensure_acquisition_results_schema(engine)
    ensure_company_type_schema(engine)
    ensure_manual_research_schema(engine)
    ensure_lead_contact_status_schema(engine)
    ensure_lead_development_date_schema(engine)
    ensure_lead_development_schema(engine)
    from app.services.knowledge_schema import ensure_knowledge_rich_schema
    ensure_knowledge_rich_schema(engine)
    unify_lead_status_schema(engine)
    retire_lead_followup_data(engine)
    retire_ai_search_parse_binding(engine)
    ensure_site_project_sort_column(engine)
    ensure_project_link_sort_column(engine)
    ensure_competitor_sort_column(engine)
    ensure_user_profile_schema(engine)
    ensure_customer_schema(engine)
    ensure_contact_record_schema(engine)
    ensure_removed_contact_summaries(engine)
    ensure_rfq_schema(engine)
    migrate_companies_into_customers(engine)
    from app.services.customer_classification_schema import ensure_customer_classification_schema
    ensure_customer_classification_schema(engine)
    ensure_workspace_customer_schema(engine)
    ensure_customer_people_schema(engine)
    ensure_workflow_people_schema(engine)
    ensure_project_memberships(engine)
    ensure_project_data_ownership_schema(engine)
    with SessionLocal() as db:
        from app.services.rfq_followup_migration import migrate_rfq_followups
        migrate_rfq_followups(db)
        ensure_default_plans(db)
        from app.services.quotation_status import migrate_quotation_statuses
        migrate_quotation_statuses(db)
        if new_quotation_module:
            from app.services.quotation_access import enable_quotation_access
            enable_quotation_access(db)
        from app.services.quotation_logo import legacy_logo_snapshots
        legacy_logo_snapshots(db)
        from app.services.quotation_templates import seed_templates
        seed_templates(db)
        recover_interrupted_tasks(db)
        adopt_legacy_entries(db)
        repair_historical_results(db)
        merge_repeated_results(db)
        from app.routers.acquisition import recount
        from app.models import ProspectingJob
        for job in db.scalars(select(ProspectingJob)):
            recount(db,job)
        db.commit()
    ensure_workspace_access_schema(engine)
    ensure_user_link_project_schema(engine)
    ensure_performance_indexes(engine)
    yield


app = FastAPI(title="TOPHOO Global", description="外贸项目与客户管理工作台", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def disable_page_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    if "ETag" in response.headers:
        del response.headers["ETag"]
    if "Last-Modified" in response.headers:
        del response.headers["Last-Modified"]
    return response


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates = templates


@app.get("/")
async def home(request: Request, user: User | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


app.include_router(auth_router, dependencies=[Depends(project_management_dependency)])
app.include_router(sales_contract_router)
app.include_router(billing_router)
app.include_router(health_router)
for router, module in [
    (customer_router, "crm_workflow"), (lead_development_router, "crm_workflow"), (lead_contact_scan_router, "crm_workflow"),
    (follow_up_router, "customer_list"),
    (contact_records_router, "customer_list"), (rfq_router, "rfq"), (quotation_router, "quotations"),
    (competitor_router, "competitor_research"), (communication_scripts_router, "knowledge_base"),
    (communication_phrases_router, "communication_phrases"),
    (acquisition_router, "auto_prospecting"), (communication_router, "communication_assistant"),
]:
    app.include_router(router, dependencies=[Depends(project_module_dependency(module))])
app.include_router(ai_config_router, dependencies=[Depends(personal_module_dependency('ai_configuration'))])
app.include_router(mail_router, dependencies=[Depends(personal_module_dependency('mail_configuration'))])


for router, module in [(keyword.router, "keyword_library"), (mic_products.router, "mic_products")]:
    app.include_router(router, dependencies=[Depends(project_module_dependency(module))])


app.include_router(user_links_router, dependencies=[Depends(personal_module_dependency('url_navigation'))])

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8002)
