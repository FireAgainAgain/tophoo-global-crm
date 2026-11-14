# 知识库

知识库位于“项目 → 知识库”，访问需要“知识库”权限。

- 左侧顶部将“分类目录”、分类数量和新增入口放在一行，下面保留紧凑搜索框；目录使用图标、缩进和细线表达层级，选中行使用浅绿提示。
- 分类支持嵌套、编辑、上下排序和删除。点击行尾“⋯”打开操作菜单；包含子分类或条目的分类也可删除，确认后连同下方所有内容一起删除。
- 选择分类只显示直接属于该分类的知识；“全部知识”统一浏览当前项目内容。
- 搜索匹配标题、正文及分类路径，范围为当前分类或全部知识。搜索框右侧可一键清除；搜索词、分类展开状态和当前条目按项目在会话内保存，刷新可恢复。
- 中间列表显示标题、分类路径与正文摘要，右侧直接阅读 Markdown。切换条目只更新正文和选中状态，保留目录、列表节点与滚动位置；新条目从正文顶部开始阅读。
- 条目列表获得焦点时可使用 ↑/↓ 切换，Home/End 选择首尾条目。正文支持复制、编辑、放大阅读及上下排序，当前分类支持 PDF 导出。
- 编辑支持 Markdown 工具栏及实时预览、未保存修改提醒和 Ctrl/⌘+S 保存。手机端使用上下布局，条目列表横向滚动，避免挤压正文。

浏览器回归：`node tests/knowledge_library_ui.cjs`。测试覆盖目录占位、条目切换、复制布局、搜索恢复、分类菜单、编辑保护、手机布局和过期项目响应；写入均使用隔离模拟数据。

## 产品与制造资料

原 CRM「资料」下的产品列表、制造能力已移除，资料统一在知识库维护。当前项目路径：**产品 → 翅片式换热器 → 产品目录 / 中谷制造能力**。

## 样式维护与复用

当前界面为「分类目录 → 条目列表 → 正文阅读 / Markdown 编辑」，旧卡片列表与旧预览弹窗的样式已经移除。

| 内容 | 唯一源文件 |
| --- | --- |
| 页面结构 | `app/templates/partials/crm_communication_scripts.html` |
| 阅读、编辑、查找和分类交互 | `app/static/js/crm-communication-scripts.js` |
| 知识库样式 | `app/static/css/knowledge-library-ui.css` |

- 样式限定在 `.crm-communication-scripts` 内；分类菜单位于页面外层，单独限定到 `#knowledge-category-menu`。`:where()` 用于隔离基础样式，同时保持现有选中、编辑和响应式规则的优先级。
- 页面仍按顺序加载 `workbench.css`、`ui-themes.css`、`appearance.css`，并由 `ui-theme.js` 设置 `html[data-ui-theme]`。其他项目只截取部分 CSS 或缺少主题标记，外观会不同。
- 修改源文件后执行 `python -m scripts.build_frontend`。复用前重新运行 `python -m scripts.create_project_template`，不要继续使用较早导出的压缩包。
- 数据保存在 `crm_communication_script_categories`、`crm_communication_scripts` 两张表。虽然沿用原内部名称，它们就是当前知识库的有效数据表，不是废弃副本。

样式隔离检查：`node tests/knowledge_style_scope_ui.cjs`；阅读与编辑检查见 `knowledge_library_ui.cjs`、`knowledge_editor_ui.cjs`、`knowledge_reader_find_ui.cjs`。所有测试写入均使用模拟数据。


### 删除含内容的分类

允许删除含知识条目和子分类的分类。点击删除后，确认提示显示分类名称、子分类总数和知识条目总数，并说明无法恢复。取消不发送删除请求；确认后删除该分类的整棵目录及全部条目，其他目录和其他项目保持不变。非空分类接口必须携带 `confirmed=true`，且要求当前项目知识库编辑权限；未确认返回 409。删除时先清理条目，再按从子级到父级的顺序删除分类。
