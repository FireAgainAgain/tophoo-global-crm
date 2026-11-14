"""Project model administration preserves secrets and removes retired bindings."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import AiModelConfiguration, AiFeatureBinding
from app.routers import ai_config
from tests.test_global_access import db, headers


def test_draft_save_and_edit_provider_preserve_key_and_permissions(db):
    client = TestClient(app)
    payload = {'name': '百炼连接', 'provider': 'qwen', 'model': 'test-chat',
               'base_url': 'https://example.test/v1', 'api_key': 'fixture-secret-1234', 'enabled': False}
    created = client.post('/api/ai-config/projects/1/models', headers=headers(1), json=payload)
    assert created.status_code == 201
    row = created.json()
    assert row['provider'] == 'qwen' and not row['enabled']
    assert 'fixture-secret-1234' not in created.text
    path = f"/api/ai-config/projects/1/models/{row['id']}"
    edited = client.put(path, headers=headers(1), json={**payload, 'api_key': None, 'notes': '保存说明'})
    assert edited.status_code == 200 and edited.json()['api_key_masked'].endswith('1234')
    assert db.get(AiModelConfiguration, row['id']).api_key == payload['api_key']
    assert client.put(path, headers=headers(2), json=payload).status_code == 404
    assert client.put(path.replace('/projects/1/', '/projects/2/'), headers=headers(1), json=payload).status_code == 404


def test_delete_cleans_retired_bindings_but_keeps_current_bindings(db, monkeypatch):
    db.add(AiModelConfiguration(id=901, owner_user_id=1, site_project_id=1, name='旧连接', model='test-chat', base_url='https://example.test/v1'))
    db.flush()
    db.add(AiFeatureBinding(owner_user_id=1, site_project_id=1, feature_key='retired_feature', model_configuration_id=901))
    db.commit()
    client = TestClient(app)
    path = '/api/ai-config/projects/1/models/901'
    monkeypatch.setattr(ai_config, 'FEATURES', {'retired_feature': {'name': '有效功能'}})
    assert client.delete(path, headers=headers(1)).status_code == 422
    assert db.get(AiModelConfiguration, 901) is not None
    monkeypatch.setattr(ai_config, 'FEATURES', {})
    assert client.delete(path, headers=headers(1)).status_code == 200
    assert db.get(AiModelConfiguration, 901) is None
    assert db.scalar(select(AiFeatureBinding).where(AiFeatureBinding.model_configuration_id == 901)) is None


def test_personal_ai_connections_are_isolated_even_from_project_admin(db,monkeypatch):
    from app.models.ai_config import LegacyAiModelConfiguration
    db.add(LegacyAiModelConfiguration(site_project_id=1,name='Shared old model',model='old',base_url='https://example.test',api_key='legacy-secret'))
    db.commit()
    client=TestClient(app)
    assert client.get('/api/ai-config/projects/1',headers=headers(1)).json()['models']==[]
    payload={'name':'Personal','model':'test-chat','base_url':'https://example.test/v1','api_key':'user-two-secret'}
    created=client.post('/api/ai-config/projects/1/models',headers=headers(2),json=payload)
    assert created.status_code==201
    id=created.json()['id'];root='/api/ai-config/projects/1'
    assert client.get(root,headers=headers(1)).json()['models']==[]
    assert len(client.get(root,headers=headers(2)).json()['models'])==1
    for suffix,method in [('', 'put'),('', 'delete'),('/test','post')]:
        response=getattr(client,method)(root+f'/models/{id}'+suffix,headers=headers(1),**({'json':payload} if method!='delete' else {}))
        assert response.status_code==404
    monkeypatch.setattr(ai_config,'chat',lambda *args,**kwargs:'OK')
    draft=client.post(root+'/test-draft',headers=headers(2),json=payload)
    assert draft.status_code==200
    saved=client.post(root+'/models',headers=headers(1),json={**payload,'verification_token':draft.json()['verification_token']})
    assert saved.status_code==201 and not saved.json()['last_test_status']
    assert db.get(AiModelConfiguration,id).owner_user_id==2
