"""Keyword library APIs: category tree, keywords and wide Excel imports."""

import re
import tempfile
from copy import copy
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_project_access, require_project_write
from app.models import Keyword, KeywordCategory, KeywordCategoryMap, KeywordImport, User
from app.services.billing_service import require_module_access

def require_keyword_library_module(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    require_module_access(db, user, "keyword_library")


router = APIRouter(prefix="/api/keywords", tags=["Keyword library"], dependencies=[Depends(require_keyword_library_module)])


class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    parent_id: int | None = None


class MovePayload(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class SelectedKeywordsPayload(BaseModel):
    keyword_ids: list[int] = Field(min_length=1)


class MoveKeywordsPayload(SelectedKeywordsPayload):
    target_category_id: int
    source_category_id: int | None = None


@router.post("/projects/{project_id}/keywords/move")
def move_keywords(project_id: int, payload: MoveKeywordsPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_write(project_id, user, db, "keyword_library")
    target = category_or_404(db, project_id, payload.target_category_id)
    source = payload.source_category_id
    if source is not None:
        category_or_404(db, project_id, source)
    ids = lock_selected_keywords(db, project_id, payload.keyword_ids)
    mappings = KeywordCategoryMap
    existing = set(db.scalars(select(mappings.keyword_id).where(mappings.keyword_id.in_(ids), mappings.category_id == target.id)))
    db.add_all([mappings(keyword_id=keyword_id, category_id=target.id) for keyword_id in sorted(ids - existing)])
    db.flush()
    if source != target.id:
        remove = mappings.category_id == source if source is not None else mappings.category_id != target.id
        db.execute(delete(mappings).where(mappings.keyword_id.in_(ids), remove))
    db.commit()
    return {"moved": len(ids)}


def lock_selected_keywords(db: Session, project_id: int, keyword_ids: list[int]) -> set[int]:
    ids = set(keyword_ids)
    found = set(db.scalars(select(Keyword.id).where(Keyword.site_project_id == project_id,
                                                   Keyword.id.in_(ids)).with_for_update()))
    if found != ids:
        raise HTTPException(404, "部分关键词已不存在，请刷新后重新选择。")
    return ids


def delete_keywords(db: Session, project_id: int, ids: set[int]) -> None:
    db.execute(delete(KeywordCategoryMap).where(KeywordCategoryMap.keyword_id.in_(ids)))
    db.execute(delete(Keyword).where(Keyword.site_project_id == project_id, Keyword.id.in_(ids)))
    db.commit()


@router.post("/projects/{project_id}/keywords/bulk-delete")
def bulk_delete_keywords(project_id: int, payload: SelectedKeywordsPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    require_project_write(project_id, user, db, "keyword_library")
    ids = lock_selected_keywords(db, project_id, payload.keyword_ids)
    delete_keywords(db, project_id, ids)
    return {"deleted": len(ids)}


class KeywordPayload(BaseModel):
    keyword: str = Field(min_length=1, max_length=191)
    chinese_translation: str | None = Field(default=None, max_length=500)
    volume_label: str | None = Field(default=None, max_length=80)
    category_id: int | None = None
    category_ids: list[int] | None = Field(default=None, min_length=1, max_length=200)


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def volume_values(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(万?)", str(value).replace(",", ""))
    numbers = [int(float(number) * (10000 if unit == "万" else 1)) for number, unit in matches]
    return (min(numbers), max(numbers)) if numbers else (None, None)


def text_cell(value: object | None) -> str | None:
    """Normalize optional spreadsheet cells without turning empty values into strings."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def header_column(headers: list[object | None], names: set[str]) -> int | None:
    for index, value in enumerate(headers):
        normalized = norm(str(value)) if value is not None else ""
        if normalized in names:
            return index
    return None


KEYWORD_EXAMPLE_SHEET = "填写示例"
KEYWORD_EXAMPLE_NOTE = "请在「关键词导入」工作表填写，本页示例不会导入。"
KEYWORD_EXPORT_MARKER = "tophoo-keyword-export-v2"
KEYWORD_EXPORT_FORMAT = "项目导出表"


def parse_keyword_workbook(path: Path) -> tuple[str, list[dict[str, str | None]]]:
    """Accept the native three-column blocks and a common vertical exchange format."""
    workbook = load_workbook(path, data_only=True)
    native_export = workbook.properties.keywords == KEYWORD_EXPORT_MARKER
    records: list[dict[str, str | None]] = []
    detected_formats: set[str] = set()
    try:
        for sheet in workbook.worksheets:
            if sheet.title == KEYWORD_EXAMPLE_SHEET and sheet["A5"].value == KEYWORD_EXAMPLE_NOTE:
                continue
            headers = [sheet.cell(1, column).value for column in range(1, sheet.max_column + 1)]
            keyword_column = header_column(headers, {"关键词", "keyword", "keywords", "search term", "query"})
            root_column = header_column(headers, {"一级分类", "一级类目", "主分类", "一级目录", "root category"})
            category_column = header_column(headers, {"二级分类", "二级类目", "分类", "子分类", "category", "sub category"})
            translation_column = header_column(headers, {"中文翻译", "翻译", "translation", "chinese translation"})
            volume_column = header_column(headers, {"月搜索量", "搜索量", "月均搜索量", "search volume", "volume"})
            # A sheet containing a recognizable keyword column is treated as a vertical exchange table.
            if keyword_column is not None:
                detected_formats.add("纵向表")
                category_columns = {column + 1 for column in (root_column, category_column) if column is not None}
                merged_labels = {}
                for region in sheet.merged_cells.ranges:
                    column = region.min_col
                    if region.min_row < 2 or column != region.max_col or column not in category_columns:
                        continue
                    label = sheet.cell(region.min_row, column).value
                    for row in range(region.min_row + 1, region.max_row + 1):
                        merged_labels[row, column] = label

                def category_label(row: int, column: int) -> str | None:
                    cell = sheet.cell(row, column + 1)
                    return text_cell(merged_labels.get((row, column + 1), cell.value))

                for row in range(2, sheet.max_row + 1):
                    keyword = text_cell(sheet.cell(row, keyword_column + 1).value)
                    root = category_label(row, root_column) if root_column is not None else sheet.title.strip()
                    category = category_label(row, category_column) if category_column is not None else None
                    if not keyword and not (native_export and root):
                        continue
                    records.append({
                        "root": root,
                        "category": category,
                        "keyword": keyword,
                        "translation": text_cell(sheet.cell(row, translation_column + 1).value) if translation_column is not None else None,
                        "volume": text_cell(sheet.cell(row, volume_column + 1).value) if volume_column is not None else None,
                    })
                continue
            if native_export:
                continue
            # Legacy wide format: three columns per category: keyword / translation / volume.
            detected_formats.add("横向分类表")
            for column in range(1, sheet.max_column + 1, 3):
                category = text_cell(sheet.cell(1, column).value)
                if not category:
                    continue
                for row in range(2, sheet.max_row + 1):
                    keyword = text_cell(sheet.cell(row, column).value)
                    if not keyword:
                        continue
                    records.append({"root": sheet.title.strip() or "未分类", "category": category, "keyword": keyword,
                                    "translation": text_cell(sheet.cell(row, column + 1).value) if column + 1 <= sheet.max_column else None,
                                    "volume": text_cell(sheet.cell(row, column + 2).value) if column + 2 <= sheet.max_column else None})
    finally:
        workbook.close()
    if not records:
        raise ValueError("未识别到关键词。请使用横向分类表，或包含“关键词”列的纵向表。")
    return KEYWORD_EXPORT_FORMAT if native_export else " / ".join(sorted(detected_formats)), records


def import_category_path(record: dict[str, str | None], detected_format: str) -> tuple[str, ...]:
    root, category = record["root"], record["category"]
    if detected_format == KEYWORD_EXPORT_FORMAT:
        if not root:
            return ()
        return (root, *(re.sub(r"\\([\\/])", r"\1", part) for part in category.split(" / "))) if category else (root,)
    return (root or "未分类", category) if category else (root,) if root else ()


def clear_project_keyword_library(db: Session, project_id: int) -> dict[str, int]:
    project_words = Keyword.site_project_id == project_id
    project_categories = KeywordCategory.site_project_id == project_id
    keyword_ids = select(Keyword.id).where(project_words)
    category_ids = select(KeywordCategory.id).where(project_categories)
    db.execute(delete(KeywordCategoryMap).where(or_(KeywordCategoryMap.keyword_id.in_(keyword_ids),
                                                  KeywordCategoryMap.category_id.in_(category_ids))))
    keywords = db.execute(delete(Keyword).where(project_words)).rowcount
    db.execute(update(KeywordCategory).where(project_categories).values(parent_id=None))
    categories = db.execute(delete(KeywordCategory).where(project_categories)).rowcount
    imports = db.execute(delete(KeywordImport).where(KeywordImport.site_project_id == project_id)).rowcount
    return {"keywords": keywords, "categories": categories, "imports": imports}


class ClearKeywordLibraryPayload(BaseModel):
    confirmation: Literal["清空"]


@router.post("/projects/{project_id}/keywords/clear")
def clear_keyword_library(project_id: int, payload: ClearKeywordLibraryPayload,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    require_project_write(project_id, user, db, "keyword_library")
    removed = clear_project_keyword_library(db, project_id)
    db.commit()
    return removed


def category_payload(item: KeywordCategory) -> dict[str, object]:
    return {"id": item.id, "name": item.name, "parent_id": item.parent_id, "sort_order": item.sort_order}


def keyword_payload(item: Keyword) -> dict[str, object]:
    return {"id": item.id, "keyword": item.keyword, "chinese_translation": item.chinese_translation or "", "volume_label": item.volume_label or "", "volume_min": item.volume_min, "volume_max": item.volume_max}


def export_tree(db: Session, project_id: int) -> tuple[list[KeywordCategory], dict[int | None, list[KeywordCategory]], dict[int, list[Keyword]]]:
    categories = project_categories(db, project_id); children: dict[int | None, list[KeywordCategory]] = {}
    for category in categories: children.setdefault(category.parent_id, []).append(category)
    direct: dict[int, list[Keyword]] = {category.id: [] for category in categories}
    pairs = db.execute(select(KeywordCategoryMap.category_id, Keyword)
                       .join(Keyword, Keyword.id == KeywordCategoryMap.keyword_id)
                       .join(KeywordCategory, KeywordCategory.id == KeywordCategoryMap.category_id)
                       .where(Keyword.site_project_id == project_id, KeywordCategory.site_project_id == project_id)).all()
    for category_id, keyword in pairs: direct[category_id].append(keyword)
    mapped_ids = {item.id for items in direct.values() for item in items}
    unmapped = [item for item in db.scalars(select(Keyword).where(Keyword.site_project_id == project_id)) if item.id not in mapped_ids]
    if unmapped:
        unassigned = KeywordCategory(id=-1, site_project_id=project_id, name="未分类", parent_id=None)
        children.setdefault(None, []).append(unassigned)
        direct[-1] = unmapped
    for items in direct.values(): items.sort(key=lambda item: (item.keyword.casefold(), item.id))
    return children.get(None, []), children, direct


KEYWORD_EXCEL_HEADERS = ("一级分类", "二级分类", "关键词", "中文翻译")


def style_keyword_sheet(sheet, *, template=False):
    """Style category groups and keep the keyword columns individually filterable."""
    import math
    import unicodedata

    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 90
    sheet.sheet_properties.tabColor = "4979AC"
    sheet.freeze_panes = "C2"
    filter_start = "A" if template else "C"
    sheet.auto_filter.ref = f"{filter_start}1:D{sheet.max_row}"
    header_colors = ("AD4E50", "D89A99", "4979AC", "638537")
    group_colors = ("DCEEF2", "F4E0DE", "F5EBD8", "E8E3F2")
    header_edge = Side(style="thin", color="E3E8EE")
    body_edge = Side(style="hair", color="DCE4EB")
    for column, width in enumerate((23, 29, 50, 36), 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    group_index = -1
    previous_group = None
    for row in sheet.iter_rows(max_col=4):
        number = row[0].row
        is_header = number == 1
        group = (row[0].value, row[1].value)
        new_group = not is_header and group != previous_group
        if new_group:
            group_index += 1
            previous_group = group
        lines = 1
        for index, cell in enumerate(row):
            if is_header:
                color = header_colors[index]
            elif template and index < 2:
                color = ("EEF4E4", "EAF4F7")[index]
            elif index < 2:
                color = "DCE9C8" if index == 0 else group_colors[group_index % len(group_colors)]
            else:
                color = "F1F4F7" if number % 2 else "FFFFFF"
            cell.fill = PatternFill("solid", fgColor=color)
            cell.font = Font(name="等线", size=11, bold=is_header or (index < 2 and not template),
                             color=("382C2C" if index == 1 else "FFFFFF") if is_header else "26384A")
            cell.border = Border(right=header_edge if is_header else body_edge,
                                 bottom=header_edge if is_header else body_edge,
                                 top=header_edge if new_group and not template else None)
            cell.alignment = Alignment(horizontal="center" if index < 2 else "left",
                                       vertical="center", indent=0 if index < 2 else 1,
                                       wrap_text=not is_header)
            cell.number_format = "@"
            if not is_header and cell.value is not None:
                cell.data_type = "s"
                capacity = sheet.column_dimensions[cell.column_letter].width - 2
                height = sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(char) in "WF" else 1
                                                for char in line) / capacity))
                             for line in str(cell.value).split("\n"))
                lines = max(lines, height)
        sheet.row_dimensions[number].height = 30 if is_header else max(22, lines * 15 + 6)
    sheet.print_title_rows = "1:1"
    sheet.print_options.horizontalCentered = True
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0


def keyword_excel(project_name: str, tree: tuple[list[KeywordCategory], dict[int | None, list[KeywordCategory]], dict[int, list[Keyword]]], output_path: Path) -> None:
    roots, children, direct = tree
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.title = f"{project_name} · 关键词库"
    workbook.properties.keywords = KEYWORD_EXPORT_MARKER
    used = set()

    def add_category(sheet, root, category, path, merges):
        first_row = sheet.max_row + 1
        root_name = root.name if root.id != -1 else None
        for item in direct.get(category.id, []):
            sheet.append((root_name, path, item.keyword,
                          item.chinese_translation or ""))
        if not direct.get(category.id) and not children.get(category.id):
            sheet.append((root_name, path, None, None))
        if path and sheet.max_row > first_row:
            merges.append((2, first_row, sheet.max_row))
        for child in children.get(category.id, []):
            label = re.sub(r"[\\/]", lambda match: "\\" + match[0], child.name)
            add_category(sheet, root, child, " / ".join(filter(None, (path, label))), merges)

    for root in roots:
        base = re.sub(r"[\\/*?:\[\]]", "_", root.name).strip()[:31] or "关键词"
        name, index = base, 2
        while name.casefold() in used:
            suffix = f"_{index}"
            name = base[:31-len(suffix)] + suffix
            index += 1
        used.add(name.casefold())
        sheet = workbook.create_sheet(name)
        sheet.append(KEYWORD_EXCEL_HEADERS)
        merges = []
        add_category(sheet, root, root, "", merges)
        style_keyword_sheet(sheet)
        if root.id != -1 and sheet.max_row > 2:
            merges.append((1, 2, sheet.max_row))
        for column, first_row, last_row in merges:
            fill = copy(sheet.cell(first_row, column).fill)
            sheet.merge_cells(start_row=first_row, start_column=column, end_row=last_row, end_column=column)
            for row in range(first_row + 1, last_row + 1):
                sheet.cell(row, column).fill = fill
    if not workbook.sheetnames:
        sheet = workbook.create_sheet("关键词库")
        sheet.append(KEYWORD_EXCEL_HEADERS)
        style_keyword_sheet(sheet)
    workbook.save(output_path)


def project_categories(db: Session, project_id: int) -> list[KeywordCategory]:
    return list(db.scalars(select(KeywordCategory).where(KeywordCategory.site_project_id == project_id).order_by(KeywordCategory.parent_id.asc(), KeywordCategory.sort_order.asc(), KeywordCategory.id.asc())))


def category_or_404(db: Session, project_id: int, category_id: int) -> KeywordCategory:
    item = db.scalar(select(KeywordCategory).where(KeywordCategory.id == category_id, KeywordCategory.site_project_id == project_id))
    if not item:
        raise HTTPException(status_code=404, detail="关键词分类不存在。")
    return item


def validate_category_change(db: Session, project_id: int, name: str, parent_id: int | None, category_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名称不能为空。")
    seen = {category_id} if category_id is not None else set()
    ancestor_id = parent_id
    while ancestor_id is not None:
        if ancestor_id in seen:
            raise HTTPException(status_code=400, detail="不能将分类移入自身或其子分类。")
        seen.add(ancestor_id)
        ancestor_id = category_or_404(db, project_id, ancestor_id).parent_id
    duplicate = db.scalar(select(KeywordCategory).where(
        KeywordCategory.site_project_id == project_id, KeywordCategory.parent_id == parent_id,
        KeywordCategory.name == name, KeywordCategory.id != category_id if category_id is not None else True,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="该父分类下已存在同名分类。")
    return name


def validated_keyword_categories(db: Session, project_id: int, payload: KeywordPayload) -> list[int]:
    ids = list(dict.fromkeys(payload.category_ids if payload.category_ids is not None else
                             [payload.category_id] if payload.category_id is not None else []))
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一个关键词分类。")
    for category_id in ids:
        category_or_404(db, project_id, category_id)
    return ids


def ensure_category(db: Session, project_id: int, name: str, parent_id: int | None) -> KeywordCategory:
    item = db.scalar(select(KeywordCategory).where(KeywordCategory.site_project_id == project_id, KeywordCategory.parent_id == parent_id, KeywordCategory.name == name))
    if item:
        return item
    maximum = db.scalar(select(func.max(KeywordCategory.sort_order)).where(KeywordCategory.site_project_id == project_id, KeywordCategory.parent_id == parent_id)) or 0
    item = KeywordCategory(site_project_id=project_id, name=name, parent_id=parent_id, sort_order=maximum + 1)
    db.add(item); db.flush()
    return item


@router.get("/projects/{project_id}/categories")
def list_categories(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    counts = dict(db.execute(select(KeywordCategoryMap.category_id, func.count(KeywordCategoryMap.keyword_id))
        .join(Keyword, Keyword.id == KeywordCategoryMap.keyword_id)
        .where(Keyword.site_project_id == project_id).group_by(KeywordCategoryMap.category_id)).all())
    return {"categories": [{**category_payload(item), "keyword_count": counts.get(item.id, 0)}
                           for item in project_categories(db, project_id)]}


@router.post("/projects/{project_id}/categories", status_code=status.HTTP_201_CREATED)
def create_category(project_id: int, payload: CategoryPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    name = validate_category_change(db, project_id, payload.name, payload.parent_id)
    item = ensure_category(db, project_id, name, payload.parent_id)
    db.commit(); db.refresh(item)
    return category_payload(item)


@router.put("/projects/{project_id}/categories/{category_id}")
def rename_category(project_id: int, category_id: int, payload: CategoryPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    item = category_or_404(db, project_id, category_id)
    name = validate_category_change(db, project_id, payload.name, payload.parent_id, category_id)
    if item.parent_id != payload.parent_id:
        maximum = db.scalar(select(func.max(KeywordCategory.sort_order)).where(
            KeywordCategory.site_project_id == project_id, KeywordCategory.parent_id == payload.parent_id)) or 0
        item.sort_order = maximum + 1
    item.name = name
    item.parent_id = payload.parent_id
    db.commit(); db.refresh(item)
    return category_payload(item)


@router.post("/projects/{project_id}/categories/{category_id}/move")
def move_category(project_id: int, category_id: int, payload: MovePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    item = category_or_404(db, project_id, category_id)
    siblings = [row for row in project_categories(db, project_id) if row.parent_id == item.parent_id]
    index = next(index for index, row in enumerate(siblings) if row.id == item.id)
    target_index = index - 1 if payload.direction == "up" else index + 1
    if 0 <= target_index < len(siblings):
        siblings[index], siblings[target_index] = siblings[target_index], siblings[index]
        for order, sibling in enumerate(siblings, 1):
            sibling.sort_order = order
        db.commit()
    return {"categories": [category_payload(row) for row in project_categories(db, project_id)]}


@router.delete("/projects/{project_id}/categories/{category_id}")
def delete_category(project_id: int, category_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    category_or_404(db, project_id, category_id)
    rows = project_categories(db, project_id); child_map: dict[int | None, list[int]] = {}
    for row in rows: child_map.setdefault(row.parent_id, []).append(row.id)
    ids: list[int] = []
    def collect(current: int) -> None:
        ids.append(current)
        for child in child_map.get(current, []): collect(child)
    collect(category_id)
    keyword_ids = list(db.scalars(select(KeywordCategoryMap.keyword_id).where(KeywordCategoryMap.category_id.in_(ids))))
    db.execute(delete(KeywordCategoryMap).where(KeywordCategoryMap.category_id.in_(ids)))
    db.execute(update(KeywordCategory).where(KeywordCategory.id.in_(ids)).values(parent_id=None))
    db.execute(delete(KeywordCategory).where(KeywordCategory.id.in_(ids)))
    if keyword_ids:
        orphan_ids = [keyword_id for keyword_id in set(keyword_ids) if not db.scalar(select(KeywordCategoryMap.id).where(KeywordCategoryMap.keyword_id == keyword_id))]
        if orphan_ids:
            db.execute(delete(Keyword).where(Keyword.id.in_(orphan_ids)))
    db.commit()
    return {"deleted_category_count": len(ids)}


@router.get("/projects/{project_id}/categories/{category_id}/keywords")
def list_keywords(project_id: int, category_id: int | None, q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    query = select(Keyword).where(Keyword.site_project_id == project_id)
    if category_id is not None:
        category_or_404(db, project_id, category_id)
        query = query.join(KeywordCategoryMap, KeywordCategoryMap.keyword_id == Keyword.id).where(KeywordCategoryMap.category_id == category_id).distinct()
    for token in [part for part in re.split(r"\s+", q.strip()) if part]:
        query = query.where(or_(Keyword.keyword.ilike(f"%{token}%"), Keyword.chinese_translation.ilike(f"%{token}%")))
    query = query.order_by(Keyword.keyword.asc(), Keyword.id.asc())
    items = list(db.scalars(query))
    payloads = []
    mappings: dict[int, list[int]] = {item.id: [] for item in items}
    if mappings:
        for keyword_id, mapped_category_id in db.execute(select(KeywordCategoryMap.keyword_id, KeywordCategoryMap.category_id)
                .join(KeywordCategory, KeywordCategory.id == KeywordCategoryMap.category_id)
                .where(KeywordCategoryMap.keyword_id.in_(mappings), KeywordCategory.site_project_id == project_id)
                .order_by(KeywordCategoryMap.id)):
            mappings[keyword_id].append(mapped_category_id)
    for item in items:
        payload = keyword_payload(item)
        payload["category_ids"] = mappings[item.id]
        payloads.append(payload)
    return {"keywords": payloads}


@router.get("/projects/{project_id}/keywords")
def list_all_keywords(project_id: int, q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    """Search the whole project, including unmapped keywords, without duplicate rows."""
    return list_keywords(project_id, None, q, user, db)


@router.get("/projects/{project_id}/template")
def download_keyword_template(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = require_project_access(project_id, user, db)
    from io import BytesIO
    from openpyxl.comments import Comment
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "关键词导入"
    sheet.append(KEYWORD_EXCEL_HEADERS)
    hints = (
        "填写主分类，例如：换热器。同名分类会自动合并。",
        "填写子分类，例如：翅片换热器。",
        "必填，每行填写一个关键词，例如：finned tube heat exchanger。",
        "选填，例如：翅片换热器。",
    )
    for column, hint in enumerate(hints, 1):
        sheet.cell(1, column).comment = Comment(hint, "Tophoo")
    for row in range(2, 32):
        for column in range(1, len(KEYWORD_EXCEL_HEADERS) + 1):
            sheet.cell(row, column)
    style_keyword_sheet(sheet, template=True)
    example = workbook.create_sheet(KEYWORD_EXAMPLE_SHEET)
    example.append(KEYWORD_EXCEL_HEADERS)
    example.append(("产品", "翅片换热器", "finned tube heat exchanger", "翅片管换热器"))
    example.append(("产品", "翅片换热器", "condenser coil", "冷凝盘管"))
    example.append(("材质", "管", "stainless steel tube", "不锈钢管"))
    style_keyword_sheet(example, template=True)
    example.merge_cells("A5:D5")
    example["A5"] = KEYWORD_EXAMPLE_NOTE
    example.row_dimensions[5].height = 22

    project_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", project.name).strip(" .") or "项目"
    filename = quote(f"{project_name}_关键词_模版.xlsx", safe="")
    output = BytesIO()
    workbook.save(output)
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.get("/projects/{project_id}/export/xlsx")
def export_keywords(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = require_project_access(project_id, user, db)
    filename = f"{project.name}_关键词库_{date.today():%Y_%m_%d}.xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temporary:
        output_path = Path(temporary.name)
    try:
        keyword_excel(project.name, export_tree(db, project_id), output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename, background=BackgroundTask(output_path.unlink, missing_ok=True))


@router.post("/projects/{project_id}/keywords", status_code=status.HTTP_201_CREATED)
def create_keyword(project_id: int, payload: KeywordPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    category_ids = validated_keyword_categories(db, project_id, payload)
    normalized = norm(payload.keyword)
    if not normalized:
        raise HTTPException(status_code=400, detail="关键词不能为空。")
    item = db.scalar(select(Keyword).where(Keyword.site_project_id == project_id, Keyword.normalized_keyword == normalized))
    volume_min, volume_max = volume_values(payload.volume_label)
    if not item:
        item = Keyword(site_project_id=project_id, keyword=payload.keyword.strip(), normalized_keyword=normalized, chinese_translation=payload.chinese_translation.strip() if payload.chinese_translation else None, volume_label=payload.volume_label.strip() if payload.volume_label else None, volume_min=volume_min, volume_max=volume_max)
        db.add(item); db.flush()
    for category_id in category_ids:
        if not db.scalar(select(KeywordCategoryMap).where(KeywordCategoryMap.keyword_id == item.id, KeywordCategoryMap.category_id == category_id)):
            db.add(KeywordCategoryMap(keyword_id=item.id, category_id=category_id))
    db.commit(); db.refresh(item)
    return {**keyword_payload(item), "category_ids": list(db.scalars(select(KeywordCategoryMap.category_id).where(KeywordCategoryMap.keyword_id == item.id)))}


@router.put("/projects/{project_id}/keywords/{keyword_id}")
def update_keyword(project_id: int, keyword_id: int, payload: KeywordPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    item = db.scalar(select(Keyword).where(Keyword.id == keyword_id, Keyword.site_project_id == project_id))
    if not item: raise HTTPException(status_code=404, detail="关键词不存在。")
    normalized = norm(payload.keyword)
    if not normalized:
        raise HTTPException(status_code=400, detail="关键词不能为空。")
    duplicate = db.scalar(select(Keyword.id).where(Keyword.site_project_id == project_id,
        Keyword.normalized_keyword == normalized, Keyword.id != item.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="当前项目已存在该关键词，请编辑已有记录。")
    # Explicit multi-category edits replace membership; legacy text edits keep it.
    if payload.category_ids is not None:
        category_ids = validated_keyword_categories(db, project_id, payload)
        existing = list(db.scalars(select(KeywordCategoryMap).where(KeywordCategoryMap.keyword_id == item.id)))
        for mapping in existing:
            if mapping.category_id not in category_ids:
                db.delete(mapping)
        existing_ids = {mapping.category_id for mapping in existing}
        for category_id in category_ids:
            if category_id not in existing_ids:
                db.add(KeywordCategoryMap(keyword_id=item.id, category_id=category_id))
    elif payload.category_id is not None:
        category_or_404(db, project_id, payload.category_id)
    item.keyword, item.normalized_keyword = payload.keyword.strip(), norm(payload.keyword)
    item.chinese_translation = payload.chinese_translation.strip() if payload.chinese_translation else None
    if "volume_label" in payload.model_fields_set:
        item.volume_label = payload.volume_label.strip() if payload.volume_label else None
        item.volume_min, item.volume_max = volume_values(payload.volume_label)
    db.commit(); db.refresh(item)
    return {**keyword_payload(item), "category_ids": list(db.scalars(select(KeywordCategoryMap.category_id).where(KeywordCategoryMap.keyword_id == item.id)))}


@router.delete("/projects/{project_id}/keywords/{keyword_id}")
def delete_keyword(project_id: int, keyword_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    require_project_write(project_id, user, db, "keyword_library")
    ids = lock_selected_keywords(db, project_id, [keyword_id])
    delete_keywords(db, project_id, ids)
    return {"deleted": True}


async def uploaded_keyword_records(file: UploadFile) -> tuple[Path, str, list[dict[str, str | None]]]:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 关键词库文件。")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temporary:
        temporary.write(content)
        path = Path(temporary.name)
    try:
        fmt, records = parse_keyword_workbook(path)
        for record in records:
            if (len(record["keyword"] or "") > 191 or len(record["translation"] or "") > 500
                    or len(record["volume"] or "") > 80
                    or any(not part or len(part) > 180 for part in import_category_path(record, fmt))):
                raise ValueError("关键词、翻译、搜索量或分类名称超出长度限制，请检查文件。")
        return path, fmt, records
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"关键词库解析失败：{exc}") from exc


@router.post("/projects/{project_id}/imports/preview")
async def preview_keyword_import(project_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    path, detected_format, records = await uploaded_keyword_records(file)
    try:
        word_rows = [norm(record["keyword"]) for record in records if record["keyword"]]
        unique_keywords = set(word_rows)
        existing = set(db.scalars(select(Keyword.normalized_keyword).where(Keyword.site_project_id == project_id)))
        paths = set()
        for record in records:
            parts = import_category_path(record, detected_format)
            paths.update(parts[:depth] for depth in range(1, len(parts) + 1))
        return {"filename": file.filename, "format": detected_format, "rows": len(word_rows),
                "unique_keywords": len(unique_keywords), "duplicate_rows": len(word_rows) - len(unique_keywords),
                "existing_keywords": len(existing & unique_keywords), "category_count": len(paths)}
    finally:
        path.unlink(missing_ok=True)


@router.post("/projects/{project_id}/imports")
async def import_keywords(project_id: int, mode: str = "update", file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_project_access(project_id, user, db)
    if mode not in {"merge", "update", "replace"}:
        raise HTTPException(status_code=400, detail="不支持的导入方式。")
    path, detected_format, records = await uploaded_keyword_records(file)
    try:
        removed = clear_project_keyword_library(db, project_id)["keywords"] if mode == "replace" else 0
        batch = KeywordImport(site_project_id=project_id, source_filename=file.filename, imported_rows=0); db.add(batch); db.flush()
        added_ids, updated_ids = set(), set()
        mapped = word_rows = 0
        category_ids = {}
        for record in records:
            category_id = None
            for name in import_category_path(record, detected_format):
                key = (category_id, name)
                if key not in category_ids:
                    category_ids[key] = ensure_category(db, project_id, name, category_id).id
                category_id = category_ids[key]
            text = record["keyword"]
            if not text:
                continue
            word_rows += 1
            normalized = norm(text)
            translation, volume = record["translation"], record["volume"]
            item = db.scalar(select(Keyword).where(Keyword.site_project_id == project_id, Keyword.normalized_keyword == normalized))
            if not item:
                low, high = volume_values(volume)
                item = Keyword(site_project_id=project_id, keyword=text, normalized_keyword=normalized, chinese_translation=translation, volume_label=volume, volume_min=low, volume_max=high, import_id=batch.id)
                db.add(item); db.flush(); added_ids.add(item.id)
            elif mode == "update":
                changed = False
                if translation is not None and translation != item.chinese_translation: item.chinese_translation = translation; changed = True
                if volume is not None and volume != item.volume_label:
                    item.volume_label = volume; item.volume_min, item.volume_max = volume_values(volume); changed = True
                if changed and item.id not in added_ids:
                    updated_ids.add(item.id)
            if category_id is not None and not db.scalar(select(KeywordCategoryMap).where(
                KeywordCategoryMap.keyword_id == item.id, KeywordCategoryMap.category_id == category_id
            )):
                db.add(KeywordCategoryMap(keyword_id=item.id, category_id=category_id)); mapped += 1
        batch.imported_rows = word_rows; db.flush(); db.commit()
        return {"message": "关键词库导入成功", "mode": mode, "format": detected_format,
                "added": len(added_ids), "updated": len(updated_ids), "mapped": mapped, "removed": removed, "import_id": batch.id}
    except Exception as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=f"关键词库解析失败：{exc}") from exc
    finally:
        path.unlink(missing_ok=True)
