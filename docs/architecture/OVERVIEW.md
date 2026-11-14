# 项目架构与目录

TOPHOO Global 是一个面向外贸团队的自托管 CRM。工作区管理账号和授权，项目承载线索、客户、询价、报价、合同、关键词和产品记录。成员能操作哪些功能，由工作区授权、项目角色和记录归属共同决定。邮箱、AI 配置和个人网址另有相应的访问规则。

## 应用怎样运行

1. `run.py` 启动 FastAPI。日常从项目根目录执行 `python run.py`，默认监听本机的 8002 端口。
2. `app/main.py` 注册页面和 API，启动时初始化数据库和执行兼容升级。
3. 页面由 Jinja2 模板生成。浏览器加载 CSS 和原生 JavaScript，交互通过 API 读取和保存业务记录。
4. 路由处理请求和权限，服务层负责业务规则与文件导出。SQLAlchemy 通过模型读写 SQLite。

## 在哪里改

| 路径 | 内容 |
| --- | --- |
| `app/templates/` 和 `app/static/` | 页面、样式和浏览器交互 |
| `app/routers/` | API 路由及各入口的请求处理 |
| `app/services/` | 业务逻辑、导入导出和兼容处理 |
| `app/models/` 和 `app/schemas/` | 数据库结构与接口字段校验 |
| `app/core/` 和 `app/dependencies/` | 应用配置、数据库连接、认证及权限 |
| `app/resources/` | 应用随源码提供的资源，例如通用报价 Excel 版式 |
| `scripts/` 和 `tests/` | 样式构建、数据审计、演示库、发布打包和回归测试 |
| `docs/` | 架构、模块、部署及发布说明 |
| `.env` 和 `data/` | 实例配置、业务库及可选演示库，留在本地 |
| `output/`、`backups/` 和 `tmp/` | 本机发布包、备份和临时资料 |

默认业务库为 `data/tophoo_global.sqlite3`。演示脚本从空库生成独立的 `data/demo.sqlite3`。两个库可以分别启动，操作前确认当前实例使用的 `DATABASE_URL`。

## 文档随功能一起更新

| 变更 | 更新位置 |
| --- | --- |
| 安装、首次启动、演示入口或项目主要功能 | [根目录 README](../../README.md) |
| 模块入口、操作步骤、权限或字段 | [模块文档索引](../README.md)下对应的说明 |
| 配置变量、账号初始化、数据库迁移、HTTPS | [部署说明](../deployment/DEPLOYMENT.md) |
| 文件结构、代码职责和数据归属 | 本页 |
| 发布范围、打包流程和 GitHub 推送 | [发布说明](../PROJECT_TEMPLATE.md) |

文档示例使用虚构资料和相对链接。发布前核对命令、配置项和页面入口是否与当前代码一致。
