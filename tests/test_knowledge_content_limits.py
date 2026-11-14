"""Long catalog entries must fit both editing limits and the database TEXT column."""
import pytest
from pydantic import ValidationError
from app.routers.communication_scripts import ScriptPayload


def test_long_english_catalog_can_be_saved():
    content = 'Copper Tube Aluminum Fin Heat Exchanger\n' * 600
    assert len(content) > 20000
    assert ScriptPayload(category_id=22, title='本地产品目录', content=content).content == content


def test_multibyte_content_cannot_exceed_text_storage():
    with pytest.raises(ValidationError, match='内容过长'):
        ScriptPayload(category_id=22, title='长篇资料', content='热' * 22000)


def test_character_limit_still_applies():
    with pytest.raises(ValidationError):
        ScriptPayload(category_id=22, title='长篇资料', content='x' * 50001)
