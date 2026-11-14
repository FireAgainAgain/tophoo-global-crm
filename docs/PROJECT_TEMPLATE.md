# 生成 GitHub 发布包

## 本地开发与公开仓库

公开仓库为 [FireAgainAgain/tophoo-global-crm](https://github.com/FireAgainAgain/tophoo-global-crm)，默认分支为 `main`。本项目发布目录的 `origin` 地址是 `https://github.com/FireAgainAgain/tophoo-global-crm.git`。

源码先在本地项目目录修改和测试。公开 Git 仓库可放在独立目录，例如 `output/github-release/`。发布脚本把允许公开的文件汇成 ZIP。ZIP 用于挑选和核对发布内容，GitHub 仓库保存解压后的源码及提交历史。

发布脚本按文件和目录范围挑选内容。更新源码时仍需检查文件内容，特别是代码里的默认参数、测试样例、模板和图片。

## 每次发布

在项目根目录运行：

```bash
python -m pytest -q
python -m scripts.build_frontend --check
python -m scripts.create_project_template
```

1. 将 `output/tophoo-global-github.zip` 解压到新的临时目录，核对发布内容。
2. 在独立的 Git 发布目录检查 `origin` 指向正确仓库、当前分支为 `main`，并用 `git pull --ff-only` 同步已有提交。有冲突时先核对线上变更。
3. 将解压后的受审文件同步到 Git 发布目录。保留 `.git/`，同时根据新包的文件清单处理已删除的源码，避免旧文件残留。
4. 在发布目录检查 `git status --short` 和文件变更。暂存后用 `git diff --cached --stat` 和 `git diff --cached` 核对，再提交并执行 `git push origin main`。推送后核对 GitHub 的最新提交与本地发布提交一致。

发布包包含源码、测试、公开说明、通用报价样式和 MIT 许可证。工作目录的 `.env`、真实库、演示库文件、上传资料、业务备份、历史维护记录及普通导出产物留在本地。

启动方法和演示数据生成命令见 [README](../README.md)。每个部署自行创建 `.env` 和管理员；每次生成演示库都会产生新的演示密码。若需要复用此项目，请从干净发布包创建新仓库。

## 修改样式

- 主界面以 `workbench.css` 与 `ui-themes.css` 为主，`appearance.css` 及邮件审阅、联系人等现有独立样式按模板引用加载。
- 模块源文件及顺序见 `app/static/css/workbench.sources.json`。
- 修改清单中的源文件，然后运行 `python -m scripts.build_frontend`；不要直接修改生成的 `workbench.css` 或 `ui-themes.css`。
- 新模块使用独立类名前缀；合入清单，不追加 `fix`、`v2` 等覆盖文件，也不在模板中堆叠 `<style>`。
- `appearance.css` 负责外观面板，登录、个人设置和管理页面保留各自独立样式。

检查构建是否最新：`python -m scripts.build_frontend --check`。

