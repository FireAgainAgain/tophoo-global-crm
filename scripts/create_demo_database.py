"""Create a new, standalone SQLite database with fictional CRM records."""

import argparse
import asyncio
import json
import os
from contextlib import closing
from pathlib import Path
from secrets import token_urlsafe
import sqlite3

from sqlalchemy.engine import URL


DEMO_EMAIL = "demo@example.com"
ROOT = Path(__file__).resolve().parents[1]


async def populate():
    from app.core.database import SessionLocal
    from app.core.modules import MODULE_CATALOG
    from app.core.security import hash_password
    from app.main import app, lifespan
    from app.models import (
        Keyword, KeywordCategory, KeywordCategoryMap, Lead, MicProduct, Plan,
        ProjectMember, Quotation, SiteProject, User, Workspace, WorkspaceMember,
    )
    from app.routers.customer import WorkflowPayload, lead_to_customer, save_w
    from app.services.quotation import QuoteDocument

    password = token_urlsafe(18)
    async with lifespan(app):
        with SessionLocal() as db:
            user = User(email=DEMO_EMAIL, display_name="演示管理员",
                        is_admin=True, password_hash=hash_password(password))
            plan = Plan(code="demo", name="演示授权", description="虚构工作区的完整功能授权",
                        project_limit=3, module_keys_json=json.dumps(list(MODULE_CATALOG)))
            db.add_all([user, plan])
            db.flush()
            workspace = Workspace(name="演示工作区", owner_id=user.id, plan_id=plan.id)
            db.add(workspace)
            db.flush()
            project = SiteProject(name="示例设备项目", workspace_id=workspace.id,
                                  site_url="https://equipment.example")
            db.add_all([project, WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")])
            db.flush()
            db.add(ProjectMember(site_project_id=project.id, user_id=user.id, role="top_admin"))

            def add_lead(company, domain, notes):
                lead = Lead(site_project_id=project.id)
                payload = WorkflowPayload(
                    company_name=company, country="德国", company_type="manufacturer",
                    company_website=f"https://{domain}", notes=notes,
                    customer_source="演示数据", owner_user_id=user.id,
                    contacts=[{"contact_name": "演示采购", "email": f"buyer@{domain}", "is_primary": True}],
                )
                save_w(lead, payload, user.id)
                db.add(lead)
                db.flush()
                return lead

            add_lead("演示公司 · 北岸通风", "north-air.example", "虚构线索。主要应用为空气处理机组。")
            add_lead("演示公司 · 青屿制冷", "island-cooling.example", "虚构线索。可了解定制冷凝器需求。")
            converted = add_lead("演示公司 · 云桥设备", "cloud-bridge.example", "虚构客户。样品报价待评审。")
            customer = lead_to_customer(db, project, converted, user.id)
            db.flush()
            quote = QuoteDocument(
                buyer_company=customer.company, seller_company="Example Equipment Co.",
                seller_email="sales@equipment.example", payment_mode="full",
                items=[{"description": "Demo finned tube coil", "quantity": 2, "unit_price": 125}],
            )
            db.add(Quotation(site_project_id=project.id, owner_user_id=user.id, customer_id=customer.id,
                             number="DEMO-QT-001", quote_date=quote.quote_date, status="草稿",
                             buyer_company=quote.buyer_company, currency=quote.currency,
                             data_json=quote.model_dump_json()))

            category = KeywordCategory(site_project_id=project.id, name="换热器 · 演示")
            keyword = Keyword(site_project_id=project.id, keyword="finned tube coil",
                              normalized_keyword="finned tube coil", chinese_translation="翅片管盘管")
            db.add_all([category, keyword])
            db.flush()
            db.add(KeywordCategoryMap(keyword_id=keyword.id, category_id=category.id))
            db.add(MicProduct(site_project_id=project.id, record_code="2099010101",
                              product_code="9001-9002", title="Demo Finned Tube Coil",
                              product_name="演示翅片管盘管", english_title="Demo Finned Tube Coil",
                              seo_description="A sample record for a finned tube coil.",
                              content="虚构产品，用于体验产品目录和发布进度。"))
            db.commit()
    return password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "demo.sqlite3")
    target = parser.parse_args().output.resolve()
    if target.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        parser.error("输出必须是 SQLite 文件（.sqlite、.sqlite3 或 .db）。")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.touch(exist_ok=False)
    except FileExistsError:
        parser.error("目标已存在。请指定一个新的数据库路径。")

    os.environ["DATABASE_URL"] = URL.create("sqlite", database=str(target)).render_as_string()
    os.environ["JWT_SECRET_KEY"] = token_urlsafe(48)
    os.environ["TEST_CHECKOUT_ENABLED"] = "false"
    from app.core.database import engine
    try:
        try:
            password = asyncio.run(populate())
        finally:
            engine.dispose()
        with closing(sqlite3.connect(target)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("演示库完整性检查失败。")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("演示库存在无效关联。")
    except BaseException:
        for path in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
            path.unlink(missing_ok=True)
        raise
    print(f"演示数据库：{target}")
    print(f"演示邮箱：{DEMO_EMAIL}")
    print(f"随机演示密码：{password}")


if __name__ == "__main__":
    main()
