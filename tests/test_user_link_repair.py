"""Repair only proven copies, retain custom data, and close legacy HTTP access."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import ProjectLink, UserLink, UserLinkCategory, UserLinkMigration
from scripts.repair_personal_links import repair, repair_plan
from tests.test_global_access import db, headers


def fixture_links(db):
    db.add_all([
        ProjectLink(id=1,site_project_id=1,name='Owner link',url='https://owner.test'),
        ProjectLink(id=2,site_project_id=2,name='Other project',url='https://other.test'),
        UserLinkCategory(id=1,owner_user_id=2,name='原项目 · Demo'),
        UserLinkCategory(id=2,owner_user_id=2,name='My tools'),
    ])
    db.flush()
    db.add_all([
        UserLink(id=1,owner_user_id=1,name='Owner link',url='https://owner.test',notes='original note'),
        UserLink(id=2,owner_user_id=2,category_id=1,name='Owner link',url='https://owner.test',notes='original note'),
        UserLink(id=3,owner_user_id=2,category_id=2,name='My link',url='https://mine.test'),
        UserLinkMigration(owner_user_id=2,legacy_link_id=1),
    ])
    db.commit()


def test_repair_backs_up_and_removes_only_verified_copies_and_is_idempotent(db, tmp_path):
    fixture_links(db)
    result = repair(db, 1, 1, tmp_path)
    db.commit()
    assert result['removed_copies'] == 1 and result['removed_categories'] == 1
    saved = json.loads(Path(result['backup']).read_text(encoding='utf-8'))
    assert len(saved['user_links']) == 3 and len(saved['project_links']) == 2
    assert db.get(UserLink, 1).notes == 'original note'
    assert db.get(UserLink, 3).url == 'https://mine.test'
    assert db.get(UserLink, 2) is None
    assert db.get(ProjectLink, 1) is None and db.get(ProjectLink, 2) is not None
    assert db.scalar(select(UserLinkMigration)) is not None
    again = repair(db, 1, 1, tmp_path)
    assert again['removed_copies'] == 0


@pytest.mark.parametrize('change', ['name', 'url', 'notes', 'category', 'missing_marker'])
def test_repair_preserves_members_modified_or_unproven_links(db, tmp_path, change):
    fixture_links(db)
    link = db.get(UserLink, 2)
    if change == 'category':
        link.category_id = 2
    elif change == 'missing_marker':
        db.delete(db.scalar(select(UserLinkMigration)))
    else:
        setattr(link, change, 'custom value')
    db.commit()
    result = repair(db, 1, 1, tmp_path)
    assert result['removed_copies'] == 0
    assert db.get(UserLink, 2) is not None
    assert db.get(UserLinkCategory, 1) is not None or change == 'category'


def test_repair_refuses_wrong_owner_or_missing_owner_copy(db, tmp_path):
    fixture_links(db)
    with pytest.raises(ValueError):
        repair_plan(db, 1, 2)
    db.delete(db.get(UserLink, 1))
    db.flush()
    with pytest.raises(ValueError):
        repair(db, 1, 1, tmp_path)
    assert not list(tmp_path.iterdir())
    assert db.get(UserLink, 2) is not None


@pytest.mark.parametrize('method,suffix', [
    ('GET',''),('GET','/export/pdf'),('POST',''),('POST','/1/move'),('PATCH','/1'),('DELETE','/1'),
])
def test_legacy_shared_api_is_gone_for_all_users(db, method, suffix):
    fixture_links(db)
    endpoint = '/api/workspaces/1/projects/1/links' + suffix
    client = TestClient(app)
    for uid in (1, 2):
        response = client.request(method, endpoint, headers=headers(uid))
        assert response.status_code == 410
        assert 'https://owner.test' not in response.text
    assert client.request(method, endpoint).status_code == 401
    assert db.get(ProjectLink, 1) is not None
