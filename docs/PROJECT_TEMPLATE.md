# 生成 GitHub 发布包

在项目根目录运行：

```bash
python -m scripts.build_frontend --check
python -m scripts.create_project_template
```

发布包保存为 `output/tophoo-global-github.zip`。解压到独立目录，在新目录初始化 Git 并检查待提交文件。发布包包含源码、测试、使用说明、通用报价样式和 MIT 许可证。工作目录的 `.env`、`data/`、上传资料、业务备份、历史维护记录、临时文件和普通导出产物都应保留在本地。

启动方法和演示数据生成命令见 [README](../README.md)。每个部署自行创建 `.env` 和管理员；每次生成演示库都会产生新的演示密码。若需要复用此项目，请从干净发布包创建新仓库。

## 修改样式

- 主界面以 `workbench.css` 与 `ui-themes.css` 为主，`appearance.css` 及邮件审阅、联系人等现有独立样式按模板引用加载。
- 模块源文件及顺序见 `app/static/css/workbench.sources.json`。
- 修改清单中的源文件，然后运行 `python -m scripts.build_frontend`；不要直接修改生成的 `workbench.css` 或 `ui-themes.css`。
- 新模块使用独立类名前缀；合入清单，不追加 `fix`、`v2` 等覆盖文件，也不在模板中堆叠 `<style>`。
- `appearance.css` 负责外观面板，登录、个人设置和管理页面保留各自独立样式。

检查构建是否最新：`python -m scripts.build_frontend --check`。

