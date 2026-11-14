# TOPHOO Global 部署指南

按 [README](../../README.md#快速开始)安装依赖、创建 `.env` 并启动。默认 SQLite 路径为 `data/tophoo_global.sqlite3`，相对路径从项目根目录解析。

## 正式部署

- 在 `.env` 中设置随机的 `JWT_SECRET_KEY`，至少 32 字节。用 `python -c "import secrets; print(secrets.token_hex(32))"` 生成。
- 使用 HTTPS 时设 `AUTH_COOKIE_SECURE=true`。同一域名运行多个实例时，为每个实例指定不同的 `AUTH_COOKIE_NAME`。
- 正式环境设置 `DEBUG=false`、`TEST_CHECKOUT_ENABLED=false`，通过反向代理提供 HTTPS。默认 `python run.py` 仅在本机监听且关闭热重载。
- 可选 `MAIL_ENCRYPTION_KEY` 是邮箱密码的独立 Fernet 密钥。省略时从 JWT 密钥派生。JWT 密钥也关联获客服务凭据。变更密钥前应迁移或准备重填受影响的凭据，并安排用户重新登录。
- 验证 `/api/health/database`，然后核对登录、项目角色和关键业务页面。

## 从 MySQL 迁移到 SQLite

1. 在项目根目录准备 `data/` 和 `backups/`，备份当前 `.env`，并停止应用写入。
2. 将 `DATABASE_URL` 指向原 MySQL 库，运行 `python -m scripts.migrate_mysql_to_sqlite data/tophoo_global.sqlite3 backups/mysql-snapshot.sqlite3`。两个目标文件都必须是新文件。主库使用当前应用结构，归档包含旧表和旧字段。脚本会逐行比对并执行完整性检查。
3. 在 `.env` 中设置 `DATABASE_URL=sqlite:///data/tophoo_global.sqlite3`，保留原加密密钥，启动服务并验证数据库健康接口及主要业务页面。

回退时先停止应用，恢复原 `.env`，再启动。切换后 SQLite 中的新写入需要单独保留，回退不会自动同步这些改动。备份 SQLite 时应停止应用后复制文件，或使用 SQLite 的在线备份功能。

## 首次创建管理员

已有账号时直接登录。全新空库启动成功后，在另一终端使用同一虚拟环境和项目目录运行下方 Python 代码。可进入 `python` 交互环境，或保存为本地临时脚本后用 `python` 执行。代码提示输入邮箱、显示名称及密码，并在尚无管理员时创建账号和基础授权工作区。

```python
from getpass import getpass
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, Workspace, WorkspaceMember, Plan
with SessionLocal() as db:
    if db.scalar(select(User.id).where(User.is_admin.is_(True))):
        raise SystemExit("已有管理员，请使用已有账号登录。")
    email = input("管理员邮箱：").strip().lower()
    if not email or "@" not in email:
        raise SystemExit("请输入有效邮箱。")
    if db.scalar(select(User.id).where(User.email == email)):
        raise SystemExit("邮箱已存在，请检查已有账号。")
    name = input("显示名称：").strip() or "管理员"
    password = getpass("管理员密码：")
    if len(password) < 8 or password != getpass("再次输入密码："):
        raise SystemExit("密码至少 8 位且两次输入必须相同。")
    plan = db.scalar(select(Plan).where(Plan.code == "free"))
    if not plan:
        raise SystemExit("请先成功启动应用以初始化表和默认授权。")
    user = User(email=email, display_name=name, password_hash=hash_password(password), is_admin=True, is_active=True)
    db.add(user)
    db.flush()
    workspace = Workspace(name=name + "的工作区", owner_id=user.id, plan_id=plan.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    print("管理员和工作区已创建，请登录系统。")
```

登录后通过“用户管理”创建团队账号，通过“工作区授权”配置模块，再创建项目、添加成员及分配角色。基础授权没有启用所有 SEO 功能，需管理员按需求配置。


### 归档已下线模块

升级旧 SQLite 库时，运行 `python -m scripts.retire_seo_data`。脚本先生成并校验完整备份，再清理已下线的 SEO、市场调研、客户统计和报价核算表。关键词库、产品记录和正式报价继续使用现有表。
