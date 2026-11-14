"""Keyword Excel exports preserve project scope and category layout."""
from io import BytesIO
from zipfile import ZipFile
from fastapi.testclient import TestClient
from app.main import app
from app.models import Keyword, KeywordCategory, KeywordCategoryMap
from tests.test_global_access import db, headers


def seed(db):
    db.add_all([
        KeywordCategory(id=1, site_project_id=1, name="产品 <分类>"),
        KeywordCategory(id=2, site_project_id=1, parent_id=1, name="烘干设备"),
        Keyword(id=1, site_project_id=1, keyword=" Finned Tube Heat Exchanger ", normalized_keyword="finned tube heat exchanger", chinese_translation="翅片换热器", volume_label="100"),
        Keyword(id=2, site_project_id=1, keyword="Steam Air Heater", normalized_keyword="steam air heater"),
        Keyword(id=3, site_project_id=1, keyword="Unmapped Keyword", normalized_keyword="unmapped keyword"),
        Keyword(id=4, site_project_id=2, keyword="private keyword", normalized_keyword="private keyword"),
    ])
    db.flush()
    db.add_all([KeywordCategoryMap(keyword_id=1, category_id=1), KeywordCategoryMap(keyword_id=1, category_id=2), KeywordCategoryMap(keyword_id=2, category_id=2)])
    db.commit()


def test_excel_export_preserves_categories_and_scope(db, tmp_path):
    seed(db)
    client = TestClient(app)
    xlsx = client.get("/api/keywords/projects/1/export/xlsx", headers=headers(1))
    assert xlsx.status_code == 200
    with ZipFile(BytesIO(xlsx.content)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
    from openpyxl import load_workbook
    table = load_workbook(BytesIO(xlsx.content)).worksheets[0]
    assert table["A1"].value == "一级分类"
    assert table["C1"].value == "关键词"
    assert len({cell.fill.fgColor.rgb for cell in table[1]}) == 4
    assert {str(region) for region in table.merged_cells.ranges} == {"A2:A4", "B3:B4"}
    assert table["B4"].value is None
    assert table["B2"].fill.fgColor.rgb != table["B3"].fill.fgColor.rgb
    assert table["C2"].fill.fgColor.rgb != table["C3"].fill.fgColor.rgb
    assert table.freeze_panes == "C2"
    assert table.auto_filter.ref == f"C1:D{table.max_row}"
    assert sum(bool(table.cell(row, 3).value) for row in range(2, table.max_row + 1)) == 3
    from app.routers.keyword import parse_keyword_workbook
    path = tmp_path / "merged-export.xlsx"
    path.write_bytes(xlsx.content)
    _, records = parse_keyword_workbook(path)
    assert "Unmapped Keyword" in {record["keyword"] for record in records}
    assert "private keyword" not in {record["keyword"] for record in records}
    assert [(record["root"], record["category"]) for record in records[:3]] == [
        ("产品 <分类>", None),
        ("产品 <分类>", "烘干设备"),
        ("产品 <分类>", "烘干设备"),
    ]

def test_exports_require_project_access(db):
    client = TestClient(app)
    base = "/api/keywords/projects/1/export/"
    assert client.get(base + "xlsx").status_code == 401
    assert client.get(base + "xlsx", headers=headers(2)).status_code == 403
    for kind in ("txt", "pdf", "md"):
        assert client.get(base + kind, headers=headers(1)).status_code == 404


def test_download_template_and_import_round_trip(db, tmp_path):
    from openpyxl import load_workbook
    from app.routers.keyword import parse_keyword_workbook
    client = TestClient(app)
    url = "/api/keywords/projects/1/template"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers(2)).status_code == 403
    response = client.get(url, headers=headers(1))
    assert response.status_code == 200
    from urllib.parse import unquote
    from app.models import SiteProject
    filename = unquote(response.headers["content-disposition"].split("''", 1)[1])
    assert filename == f"{db.get(SiteProject, 1).name}_关键词_模版.xlsx"
    workbook = load_workbook(BytesIO(response.content))
    assert workbook["填写示例"]["C2"].value == "finned tube heat exchanger"
    sheet = workbook.active
    assert [cell.value for cell in sheet[1]] == ["一级分类", "二级分类", "关键词", "中文翻译"]
    assert len({cell.fill.fgColor.rgb for cell in sheet[1]}) == 4
    assert sheet["A1"].font.color.rgb.endswith("FFFFFF")
    assert sheet["C1"].comment and sheet.freeze_panes == "C2"
    assert not sheet.merged_cells.ranges and sheet.auto_filter.ref == "A1:D31"
    for column, value in enumerate(["换热器", "翅片换热器", "finned tube coil", "翅片盘管"], 1):
        sheet.cell(2, column, value)
    path = tmp_path / "filled-template.xlsx"
    workbook.save(path)
    format_name, records = parse_keyword_workbook(path)
    assert format_name == "纵向表"
    assert records == [{"root": "换热器", "category": "翅片换热器", "keyword": "finned tube coil", "translation": "翅片盘管", "volume": None}]


def upload(client, path, content, user=1):
    return client.post(path, headers=headers(user), files={"file": ("关键词.xlsx", content)})


def test_export_replace_preserves_tree_memberships_empty_categories_and_unmapped_keywords(db):
    seed(db)
    db.add_all([
        KeywordCategory(id=3, site_project_id=1, parent_id=2, name="工业 / 制冷"),
        KeywordCategory(id=4, site_project_id=1, parent_id=3, name="空分类"),
        KeywordCategory(id=5, site_project_id=1, name="空顶层"),
        KeywordCategory(id=6, site_project_id=2, name="Other"),
    ])
    db.flush()
    db.add(KeywordCategoryMap(keyword_id=2, category_id=3))
    db.commit()
    client = TestClient(app)
    base = "/api/keywords/projects/1"
    excel = client.get(base + "/export/xlsx", headers=headers(1)).content
    preview = upload(client, base + "/imports/preview", excel)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "filename": "关键词.xlsx", "format": "项目导出表", "rows": 5, "unique_keywords": 3,
        "duplicate_rows": 2, "existing_keywords": 3, "category_count": 5,
    }
    replaced = upload(client, base + "/imports?mode=replace", excel)
    assert replaced.status_code == 200, replaced.text
    assert (replaced.json()["removed"], replaced.json()["added"], replaced.json()["mapped"]) == (3, 3, 4)
    categories = client.get(base + "/categories", headers=headers(1)).json()["categories"]
    names = {item["id"]: item["name"] for item in categories}
    assert {item["name"]: names.get(item["parent_id"]) for item in categories} == {
        "产品 <分类>": None, "烘干设备": "产品 <分类>", "工业 / 制冷": "烘干设备",
        "空分类": "工业 / 制冷", "空顶层": None,
    }
    words = client.get(base + "/keywords", headers=headers(1)).json()["keywords"]
    assert {item["keyword"]: {names[id_] for id_ in item["category_ids"]} for item in words} == {
        "Finned Tube Heat Exchanger": {"产品 <分类>", "烘干设备"},
        "Steam Air Heater": {"烘干设备", "工业 / 制冷"},
        "Unmapped Keyword": set(),
    }
    assert db.get(Keyword, 4).keyword == "private keyword"
    assert db.get(KeywordCategory, 6).name == "Other"


def test_import_modes_and_failed_replacement(db, monkeypatch):
    from openpyxl import Workbook
    from app.routers import keyword

    seed(db)
    client = TestClient(app)
    base = "/api/keywords/projects/1"
    book = Workbook()
    book.active.append(keyword.KEYWORD_EXCEL_HEADERS)
    book.active.append(("产品 <分类>", None, "FINNED TUBE HEAT EXCHANGER", "新翻译"))
    book.active.append(("新类", "子类", "finned tube heat exchanger", "新翻译"))
    buf = BytesIO()
    book.save(buf)
    excel = buf.getvalue()
    for mode, expected, updates in [("merge", "翅片换热器", 0), ("update", "新翻译", 1)]:
        result = upload(client, base + f"/imports?mode={mode}", excel)
        assert result.status_code == 200, result.text
        assert result.json()["added"] == 0 and result.json()["updated"] == updates
        assert db.get(Keyword, 1).chinese_translation == expected
    assert upload(client, base + "/imports?mode=replace", b"not an Excel file").status_code == 400

    def fail_category(*args):
        raise RuntimeError("simulated failure during replacement")

    monkeypatch.setattr(keyword, "ensure_category", fail_category)
    assert upload(client, base + "/imports?mode=replace", excel).status_code == 400
    assert db.query(Keyword).filter_by(site_project_id=1).count() == 3
    assert db.query(KeywordCategory).filter_by(site_project_id=1).count() == 4

