# TOPHOO Global

一个可自行部署的中文外贸 CRM。按项目管理线索、客户、联系人、跟进、报价和合同，也可以集中维护产品记录、关键词和知识库。

| 模块 | 功能 |
| --- | --- |
| 项目 | 切换工作区和项目，管理成员、角色与个人网址 |
| CRM | 线索、客户、公池、跟进、开发信草稿、询价、报价和合同 |
| SEO | 关键词分类与 Excel 导入导出、产品记录、SEO 文案与 MIC 发布进度 |
| 工具 | 客户查证、自动获客、全球时间、沟通话术及 Markdown 知识库 |

## 快速开始

需要 Python 3.12。以下命令在仓库根目录运行。

```bash
python -m venv .venv
```

激活环境。Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`，macOS 或 Linux 使用 `source .venv/bin/activate`。

```bash
python -m pip install -r requirements.txt
python -c "import secrets; print(secrets.token_hex(32))"
```

在根目录创建 `.env`，把上一步生成的随机值填入 `JWT_SECRET_KEY`。

```dotenv
DEBUG=false
DATABASE_URL=sqlite:///data/tophoo_global.sqlite3
JWT_SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=10080
AUTH_COOKIE_NAME=tophoo_global_access_token
AUTH_COOKIE_SECURE=false
TEST_CHECKOUT_ENABLED=false
```

运行 `python run.py`，访问 <http://127.0.0.1:8002>。程序会创建 SQLite 文件和表。空库请按[初始化管理员](docs/deployment/DEPLOYMENT.md#首次创建管理员)创建账号。API 文档在 <http://127.0.0.1:8002/docs>。

## 体验演示数据

安装好依赖后运行：

```bash
python -m scripts.create_demo_database
```

命令从空库生成 `data/demo.sqlite3`，并显示演示账号和随机密码。演示包含一个项目、两条线索、一家客户、一张报价、一条关键词和一项产品。公司和联系人均为虚构，使用专用示例域名。若文件已存在，使用 `--output data/demo-2.sqlite3` 生成另一个文件。

用环境变量临时选择演示库并启动。打开 <http://127.0.0.1:8003> 后用上一步的账号密码登录。

**PowerShell**

```powershell
$env:DATABASE_URL = "sqlite:///data/demo.sqlite3"
$env:AUTH_COOKIE_NAME = "tophoo_global_demo_token"
$env:JWT_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python run.py --port 8003
# 停止演示服务后，清除当前终端的临时设置
Remove-Item Env:DATABASE_URL, Env:AUTH_COOKIE_NAME, Env:JWT_SECRET_KEY
```

**macOS / Linux**

```bash
DATABASE_URL=sqlite:///data/demo.sqlite3 AUTH_COOKIE_NAME=tophoo_global_demo_token JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" python run.py --port 8003
```

## 开发与测试

技术栈为 FastAPI、SQLAlchemy、Jinja2、SQLite 和原生 JavaScript。应用代码在 `app/`，维护工具在 `scripts/`，回归测试在 `tests/`。

```bash
python -m pip install pytest httpx
python -m pytest -q
python -m scripts.build_frontend --check
```

样式源文件由 `app/static/css/workbench.sources.json` 管理。修改源样式后执行 `python -m scripts.build_frontend`。

## 部署与发布

- [部署说明](docs/deployment/DEPLOYMENT.md)涵盖 HTTPS、Cookie、管理员初始化和 MySQL 迁移。
- [模块文档](docs/README.md)提供客户工作流、项目权限、报价和其他功能的说明。
- [发布包说明](docs/PROJECT_TEMPLATE.md)介绍如何从工作目录生成适合 GitHub 的源码副本。个人配置、业务库、模拟库和本机资料均应保留在本地。演示库由公开脚本生成。

## 许可证

本项目采用 [MIT License](LICENSE)。
