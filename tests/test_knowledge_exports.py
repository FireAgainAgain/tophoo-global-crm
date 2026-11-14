"""Individual knowledge exports must enforce project access and dated filenames."""
from datetime import datetime, timezone
from urllib.parse import unquote
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.routers import communication_scripts
from tests.test_global_access import db, headers
from app.services.communication_script_pdf import export_knowledge_script_pdf, export_knowledge_category_pdf


def test_single_entry_export_uses_category_title_shanghai_date_and_project_scope(db, monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 12, 17, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(communication_scripts, "datetime", Clock)
    client = TestClient(app)
    category = client.post('/api/communication-scripts/projects/1/categories', headers=headers(1), json={'name': '搜索技巧'}).json()
    entry = client.post('/api/communication-scripts/projects/1/scripts', headers=headers(1), json={
        'category_id': category['id'], 'title': 'Google搜索技巧',
        'content': '# 搜索\n\n使用精确关键词。\n\n- 按国家筛选\n- 查看官网\n\n> 核实信息',
    }).json()
    path = f"/api/communication-scripts/projects/1/scripts/{entry['id']}/export/pdf"
    response = client.get(path, headers=headers(1))
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')
    assert unquote(response.headers['content-disposition']).split("UTF-8''")[1] == "搜索技巧_Google搜索技巧_2026-10-13.pdf"
    assert client.get(path, headers=headers(2)).status_code == 403
    assert client.get(path.replace('/projects/1/', '/projects/2/'), headers=headers(1)).status_code == 404
    assert client.get(path.replace(f"/{entry['id']}/export", '/999999/export'), headers=headers(1)).status_code == 404
    assert client.get(path).status_code in (401, 403)
    # Keep existing category exports functional after sharing PDF rendering.
    category_pdf = client.get(f"/api/communication-scripts/projects/1/categories/{category['id']}/export/pdf", headers=headers(1))
    assert category_pdf.status_code == 200 and category_pdf.content.startswith(b'%PDF')
    assert unquote(category_pdf.headers['content-disposition']).split("UTF-8''")[1] == "搜索技巧_Google搜索技巧_2026-10-13.pdf"
    client.post('/api/communication-scripts/projects/1/scripts', headers=headers(1), json={
        'category_id': category['id'], 'title': '其他技巧', 'content': '其他内容',
    })
    category_pdf = client.get(f"/api/communication-scripts/projects/1/categories/{category['id']}/export/pdf", headers=headers(1))
    assert unquote(category_pdf.headers['content-disposition']).split("UTF-8''")[1] == "搜索技巧_知识库合集_2026-10-13.pdf"


def test_export_filename_sanitizes_file_and_header_characters(db):
    client = TestClient(app)
    category = client.post('/api/communication-scripts/projects/1/categories', headers=headers(1), json={'name': '资料/分类:\r\n'}).json()
    entry = client.post('/api/communication-scripts/projects/1/scripts', headers=headers(1), json={
        'category_id': category['id'], 'title': '技巧/搜索:示例\r\n', 'content': '内容',
    }).json()
    response = client.get(f"/api/communication-scripts/projects/1/scripts/{entry['id']}/export/pdf", headers=headers(1))
    assert response.status_code == 200
    name = unquote(response.headers['content-disposition'].split("UTF-8''")[1])
    assert name.startswith('资料_分类__技巧_搜索_示例_')
    assert not any(char in name for char in '\\/:*?"<>|\r\n')


def test_markdown_becomes_styled_blocks_in_both_exports(monkeypatch):
    from reportlab.platypus import SimpleDocTemplate, LongTable, Paragraph, XPreformatted, HRFlowable

    captured = []
    original = SimpleDocTemplate.build

    def inspect_build(document, story, **kwargs):
        captured.append((list(story), [[cell.getPlainText() for cell in row] for block in story if isinstance(block, LongTable) for row in block._cellvalues]))
        return original(document, story, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, 'build', inspect_build)
    category = SimpleNamespace(name='搜索技巧')
    script = SimpleNamespace(title='Google搜索', content=r'''##### 小标题

**中文粗体**、~~过期方法~~、[搜索引擎](https://example.com/?a=1&b=2)。

| 方法 | 说明 |
| --- | --- |
| **精确搜索** | 中文单元格自动换行 |
| A\|B | `site:example.com` |

1. 核实官网
   - 核实产品

> 优先查看官网。
> 核实信息。

---

```text
中文代码 <tag>
**这是真正的代码**
```
''')
    for render in (lambda: export_knowledge_script_pdf(category, script), lambda: export_knowledge_category_pdf(category, [script])):
        assert render().startswith(b'%PDF')
        story, table_text = captured[-1]
        table = next(block for block in story if isinstance(block, LongTable))
        assert table.repeatRows == 1
        assert table_text[1][0] == '精确搜索'
        assert table_text[2][0] == 'A|B'
        text = '\n'.join(block.getPlainText() for block in story if isinstance(block, Paragraph))
        assert '#####' not in text and '](' not in text and '| ---' not in text
        heading = next(block for block in story if isinstance(block, Paragraph) and block.getPlainText() == '小标题')
        assert heading.style.fontSize > 10
        rich = next(block for block in story if isinstance(block, Paragraph) and '中文粗体' in block.getPlainText())
        assert any('Bold' in fragment.fontName for fragment in rich.frags)
        assert any(fragment.link for fragment in rich.frags)
        code = next(block for block in story if isinstance(block, XPreformatted))
        assert '**这是真正的代码**' in code.getPlainText()
        assert '<tag>' in code.getPlainText()
        assert code.style.backColor is not None
        assert any(isinstance(block, HRFlowable) for block in story)


def test_large_table_row_and_chinese_code_paginate_without_layout_errors():
    script = SimpleNamespace(title='长内容', content='| 项目 | 内容 |\n| --- | --- |\n| 长单元格 | ' + ('内容自动分页。' * 500) + ' |\n\n```text\n' + ('中文代码行\n' * 100) + '```')
    result = export_knowledge_script_pdf(SimpleNamespace(name='资料'), script)
    assert result.startswith(b'%PDF')
