"""Source-backed fixes keep source text, manual edits and number gaps traceable."""
import json
import pytest
from sqlalchemy import select
from app.models import MicProduct
from app.services.mic_catalogue import parse_catalogue, grouped_catalogue
from app.services.mic_catalogue_quality import resolved_title, merge_title_metadata, missing_codes, repair_project_titles
from tests.test_global_access import db


@pytest.mark.parametrize("label,title,expected",[
    ("换热器", "Replacement tainless Steel Tube Coil", "Replacement Stainless Steel Tube Coil"),
    ("换热器", "Stainless Steel Tube Aluminum Fin Fin Coil", "Stainless Steel Tube Aluminum Fin Coil"),
    ("双风机铜管铝翅换热器【冷库】", "Custom Copper Tube Aluminum Fin Heat Exchanger", "Custom Dual-Fan Copper Tube Aluminum Fin Heat Exchanger"),
    ("换热器", "Unclear Product", "Unclear Product"),
])
def test_only_source_supported_repairs(label,title,expected):
    record={"product_code":"vex1","original_title":title,"suggested_title":"","status":"pending","product_group":label}
    result=resolved_title(record)
    assert result["title"]==expected and result["original_title"]==title
    assert result["review_status"]==("corrected" if expected!=title else "pending")


def test_grouped_import_applies_suggestion_without_replacing_source():
    source="## 【vex91-vex100】不锈钢管铜翅换热器【冷凝器】\n【vex95】Stainless Steel Tube Copper Fin Cooling Coil For【待优化】\n建议标题：Stainless Steel Tube Copper Fin Condenser Coil"
    groups=grouped_catalogue(source)
    title=json.loads(groups[0]["titles_json"])[0]
    assert title["title"]=="Stainless Steel Tube Copper Fin Condenser Coil"
    assert title["original_title"].endswith(" For")
    assert groups[0]["product_name"]=="不锈钢管铜翅换热器" and groups[0]["product_group"]=="冷凝器"
    assert parse_catalogue(source)[0]["original_title"].endswith(" For")
    assert missing_codes("vex91-vex100",[title])==[f"vex{i}" for i in range(91,101) if i!=95]


def test_metadata_survives_save_and_manual_edits_are_not_overwritten(db):
    source="## 【vex1-vex10】换热器\n【vex1】Original Name【待优化】\n建议标题：Suggested Name\n【vex2】Original Second【待优化】\n建议标题：Suggested Second"
    db.add(MicProduct(site_project_id=1,product_code="vex1-vex10",product_name="换热器",product_group="换热器",title="Original Name",titles_json=json.dumps([{"code":"vex1","title":"Original Name"},{"code":"vex2","title":"My manual edit"}])))
    db.commit()
    result=repair_project_titles(db,1,parse_catalogue(source));db.commit()
    assert len(result["changed"])==1 and result["conflicts"]==["vex2"]
    item=db.scalar(select(MicProduct));titles=json.loads(item.titles_json)
    assert titles[0]["title"]=="Suggested Name" and titles[1]["title"]=="My manual edit"
    merged=merge_title_metadata(titles,[{"code":"vex1","title":"Next manual edit"},{"code":"vex2","title":"My manual edit"}])
    assert merged[0]["original_title"]=="Original Name" and merged[0]["review_status"]=="edited"
    assert repair_project_titles(db,1,parse_catalogue(source))["changed"]==[]


def test_missing_codes_do_not_create_fictional_titles():
    titles=[{"code":f"vex{i}","title":f"Name {i}"} for i in range(41,46)]
    assert missing_codes("vex41-vex50",titles)==[f"vex{i}" for i in range(46,51)]
    assert len(titles)==5
    assert missing_codes("vex101-vex105",[{"code":f"vex{i}"} for i in range(101,106)])==[]
    assert missing_codes("vex1-vex9999999999",titles)==[]
