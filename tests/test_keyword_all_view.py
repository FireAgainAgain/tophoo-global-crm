"""All-keyword search shares filters but must not duplicate or leak project records."""
from fastapi.testclient import TestClient
from app.main import app
from app.models import Keyword, KeywordCategory, KeywordCategoryMap
from tests.test_global_access import db, headers


def test_all_keywords_include_unmapped_deduplicate_and_share_filters(db):
    db.add_all([
        KeywordCategory(id=1,site_project_id=1,name='Product'),
        KeywordCategory(id=2,site_project_id=1,name='Promotion'),
        KeywordCategory(id=3,site_project_id=2,name='Other project'),
        Keyword(id=1,site_project_id=1,keyword='dry cooler',normalized_keyword='dry cooler',volume_min=100),
        Keyword(id=2,site_project_id=1,keyword='industrial cooling',normalized_keyword='industrial cooling',chinese_translation='跨分类中文词',volume_min=200),
        Keyword(id=3,site_project_id=1,keyword='unmapped keyword',normalized_keyword='unmapped keyword',volume_min=300),
        Keyword(id=4,site_project_id=2,keyword='private keyword',normalized_keyword='private keyword',volume_min=900),
    ])
    db.flush()
    db.add_all([
        KeywordCategoryMap(keyword_id=1,category_id=1),
        KeywordCategoryMap(keyword_id=1,category_id=2),
        KeywordCategoryMap(keyword_id=2,category_id=2),
        KeywordCategoryMap(keyword_id=4,category_id=3),
    ])
    db.commit()
    client=TestClient(app)
    def ids(path):
        response=client.get(path,headers=headers(1)); assert response.status_code==200
        return [item['id'] for item in response.json()['keywords']]
    assert ids('/api/keywords/projects/1/keywords')==[1,2,3]
    assert ids('/api/keywords/projects/1/keywords?sort=volume_asc')==[1,2,3]
    assert ids('/api/keywords/projects/1/keywords?q=跨分类中文词')==[2]
    assert ids('/api/keywords/projects/1/keywords?usage=used')==[1,2,3]
    assert ids('/api/keywords/projects/1/keywords?usage=unused')==[1,2,3]
    assert ids('/api/keywords/projects/1/categories/1/keywords')==[1]
    assert ids('/api/keywords/projects/2/keywords')==[4]
    row=client.get('/api/keywords/projects/1/categories/1/keywords',headers=headers(1)).json()['keywords'][0]
    assert set(row['category_ids'])=={1,2}
    assert not {'tdk_usage','wp_usage','mic_usage'} & row.keys()


def test_batch_move_keeps_other_memberships_and_checks_project(db):
    db.add_all([
        KeywordCategory(id=n, site_project_id=1, name=str(n)) for n in (1, 2, 3)
    ])
    db.add(KeywordCategory(id=4, site_project_id=2, name='Other project'))
    db.add_all([Keyword(id=n, site_project_id=1, keyword=str(n), normalized_keyword=str(n)) for n in (1, 2)])
    db.flush()
    db.add_all([KeywordCategoryMap(keyword_id=k, category_id=c) for k, c in [(1, 1), (1, 2), (2, 1), (2, 3)]])
    db.commit()
    client = TestClient(app)
    base = '/api/keywords/projects/1/keywords'
    payload = {'keyword_ids': [1, 2], 'source_category_id': 1, 'target_category_id': 3}
    assert client.post(base+'/move', headers=headers(1), json={**payload, 'target_category_id': 4}).status_code == 404
    for _ in range(2):
        assert client.post(base+'/move', headers=headers(1), json=payload).json() == {'moved': 2}
    rows = client.get(base, headers=headers(1)).json()['keywords']
    assert {row['id']: set(row['category_ids']) for row in rows} == {1: {2, 3}, 2: {3}}
    assert client.post(base+'/move', headers=headers(1), json={**payload, 'source_category_id': None}).status_code == 200
    rows = client.get(base, headers=headers(1)).json()['keywords']
    assert all(row['category_ids'] == [3] for row in rows)


def test_all_keyword_search_requires_project_and_module_access(db):
    client=TestClient(app)
    assert client.get('/api/keywords/projects/1/keywords',headers=headers(2)).status_code==403
    assert client.get('/api/keywords/projects/2/keywords',headers=headers(2)).status_code==403
    assert client.get('/api/keywords/projects/1/keywords').status_code==401


def test_category_views_only_include_direct_mappings_and_counts_agree(db):
    db.add_all([
        KeywordCategory(id=1, site_project_id=1, name='Parent'),
        KeywordCategory(id=2, site_project_id=1, name='Child', parent_id=1),
        KeywordCategory(id=3, site_project_id=1, name='Grandchild', parent_id=2),
        KeywordCategory(id=4, site_project_id=1, name='Empty parent'),
        KeywordCategory(id=5, site_project_id=1, name='Nested', parent_id=4),
        KeywordCategory(id=6, site_project_id=2, name='Other project'),
        *[Keyword(id=i, site_project_id=1 if i < 7 else 2,
                  keyword=f'cooling {i}', normalized_keyword=f'cooling {i}', volume_min=i * 100)
          for i in range(1, 8)],
    ])
    db.flush()
    db.add_all([
        KeywordCategoryMap(keyword_id=1, category_id=1),
        KeywordCategoryMap(keyword_id=2, category_id=2),
        KeywordCategoryMap(keyword_id=3, category_id=3),
        KeywordCategoryMap(keyword_id=4, category_id=1),
        KeywordCategoryMap(keyword_id=4, category_id=2),
        KeywordCategoryMap(keyword_id=5, category_id=5),
        KeywordCategoryMap(keyword_id=7, category_id=6),
    ])
    db.commit()
    client = TestClient(app)

    def ids(path):
        response = client.get(path, headers=headers(1))
        assert response.status_code == 200
        return [item['id'] for item in response.json()['keywords']]

    counts = {item['id']: item['keyword_count'] for item in
              client.get('/api/keywords/projects/1/categories', headers=headers(1)).json()['categories']}
    for category_id, expected in {1: [1, 4], 2: [2, 4], 3: [3], 4: [], 5: [5]}.items():
        actual = ids(f'/api/keywords/projects/1/categories/{category_id}/keywords')
        assert actual == expected
        assert counts[category_id] == len(actual)
    assert ids('/api/keywords/projects/1/categories/1/keywords?usage=used') == [1, 4]
    assert ids('/api/keywords/projects/1/categories/1/keywords?q=cooling%202') == []
    assert ids('/api/keywords/projects/1/categories/1/keywords?sort=volume_asc') == [1, 4]
    assert ids('/api/keywords/projects/1/keywords') == [1, 2, 3, 4, 5, 6]



def test_bulk_delete_is_atomic_and_project_scoped(db):
    from tests.test_keyword_exports import seed

    seed(db)
    client = TestClient(app)
    base = "/api/keywords/projects/1/keywords"
    endpoint = base + "/bulk-delete"
    assert client.post(endpoint, headers=headers(2), json={"keyword_ids": [1]}).status_code == 403
    assert client.post(endpoint, headers=headers(1), json={"keyword_ids": [1, 4]}).status_code == 404
    assert {row["id"] for row in client.get(base, headers=headers(1)).json()["keywords"]} == {1, 2, 3}
    response = client.post(endpoint, headers=headers(1), json={"keyword_ids": [1, 2, 1]})
    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert [row["id"] for row in client.get(base, headers=headers(1)).json()["keywords"]] == [3]
    assert client.get("/api/keywords/projects/2/keywords", headers=headers(1)).json()["keywords"][0]["id"] == 4
    assert not db.query(KeywordCategoryMap).filter(KeywordCategoryMap.keyword_id.in_([1, 2])).count()


def test_clear_requires_confirmation_and_only_removes_current_library(db):
    from app.models import KeywordImport
    from tests.test_keyword_exports import seed
    from tests.test_module_access_levels import set_access

    seed(db)
    db.add_all([KeywordImport(id=i, site_project_id=i, source_filename="keywords.xlsx") for i in (1, 2)])
    db.add(KeywordCategory(id=3, site_project_id=2, name="Other"))
    db.flush()
    db.get(Keyword, 1).import_id = 1
    db.get(Keyword, 4).import_id = 2
    db.add(KeywordCategoryMap(keyword_id=4, category_id=3))
    db.commit()
    set_access(db, ["keyword_library"], [])
    client = TestClient(app)
    endpoint = "/api/keywords/projects/1/keywords/clear"
    payload = {"confirmation": "清空"}
    assert client.post(endpoint, json=payload).status_code == 401
    assert client.post(endpoint, headers=headers(2), json=payload).status_code == 403
    assert client.post(endpoint, headers=headers(1), json={"confirmation": "取消"}).status_code == 422
    assert db.query(Keyword).count() == 4
    assert client.post(endpoint, headers=headers(1), json=payload).json() == {"keywords": 3, "categories": 2, "imports": 1}
    assert client.post(endpoint, headers=headers(1), json=payload).json() == {"keywords": 0, "categories": 0, "imports": 0}
    assert [item.id for item in db.query(Keyword)] == [4]
    assert [item.id for item in db.query(KeywordCategory)] == [3]
    assert [item.id for item in db.query(KeywordImport)] == [2]
    assert [item.keyword_id for item in db.query(KeywordCategoryMap)] == [4]
