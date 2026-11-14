"""Admin profile edits use isolated data and preserve workspace memberships."""
from fastapi.testclient import TestClient
from app.main import app
from app.models import User, Workspace, ProjectMember
from tests.test_global_access import db, headers


def admin(db):
    db.get(User, 1).is_admin = True
    db.get(User, 1).email = 'owner@example.com'
    db.commit()
    return TestClient(app)


def test_admin_can_edit_contact_details_and_email_without_changing_memberships(db):
    client = admin(db)
    response = client.patch('/api/admin/users/2', headers=headers(1), json={
        'display_name': '  New Sales  ', 'email': 'Sales.New@EXAMPLE.com',
        'phone': '13800138000', 'wechat_id': '  new-sales  ',
    })
    assert response.status_code == 200, response.text
    assert response.json()['display_name'] == 'New Sales'
    assert response.json()['email'] == 'sales.new@example.com'
    assert response.json()['wechat_id'] == 'new-sales'
    assert db.get(User, 2).password_hash == 'unused'
    assert db.get(User, 2).is_admin is False
    assert db.get(Workspace, 1).owner_id == 1
    assert db.get(ProjectMember, 1).user_id == 2
    cleared = client.patch('/api/admin/users/2', headers=headers(1), json={'phone': None, 'wechat_id': None})
    assert cleared.status_code == 200
    assert cleared.json()['phone'] is None and cleared.json()['wechat_id'] is None


def test_duplicate_and_invalid_profile_edits_do_not_change_user(db):
    client = admin(db)
    original = db.get(User, 2).display_name
    response = client.patch('/api/admin/users/2', headers=headers(1), json={
        'email': 'OWNER@example.com', 'display_name': 'Should not save',
    })
    assert response.status_code == 409
    assert db.get(User, 2).display_name == original
    for payload in ({'email': None}, {'display_name': None}, {'display_name': '   '},
                    {'email': 'invalid'}, {'phone': '123'}):
        assert client.patch('/api/admin/users/2', headers=headers(1), json=payload).status_code == 422
    response = client.patch('/api/admin/users/2', headers=headers(1), json={
        'plan_code': 'missing', 'display_name': 'Should not save',
    })
    assert response.status_code == 400
    assert db.get(User, 2).display_name == original


def test_non_admin_cannot_edit_users_and_self_disable_stays_blocked(db):
    client = admin(db)
    assert client.patch('/api/admin/users/1', headers=headers(2), json={'display_name': 'Intruder'}).status_code == 403
    assert client.patch('/api/admin/users/2', json={'display_name': 'Intruder'}).status_code == 401
    assert client.patch('/api/admin/users/1', headers=headers(1), json={'is_active': False}).status_code == 400
    assert client.patch('/api/admin/users/9999', headers=headers(1), json={'display_name': 'Missing'}).status_code == 404
    response = client.patch('/api/admin/users/1', headers=headers(1), json={'email': 'new.owner@example.com'})
    assert response.status_code == 200 and response.json()['is_admin'] is True


def test_admin_users_page_uses_single_stylesheet_and_edit_dialog(db):
    client = admin(db)
    page = client.get('/admin/users', headers=headers(1))
    assert page.status_code == 200
    assert 'admin-users-extra.css' not in page.text
    assert 'id="user-editor-dialog"' in page.text
    assert 'id="user-search"' in page.text


def test_admin_password_reset_is_hashed_and_preserves_profile(db):
    from app.core.security import hash_password, verify_password
    client = admin(db)
    user = db.get(User, 2)
    user.email = 'sales@example.com'
    user.password_hash = hash_password('OriginalPassword1')
    db.commit()
    before = (user.email, user.display_name, user.is_active, user.is_admin)
    response = client.patch('/api/admin/users/2/password', headers=headers(1), json={'new_password': 'NewPassword2026'})
    assert response.status_code == 200
    assert 'NewPassword2026' not in response.text
    db.refresh(user)
    assert verify_password('NewPassword2026', user.password_hash)
    assert not verify_password('OriginalPassword1', user.password_hash)
    assert before == (user.email, user.display_name, user.is_active, user.is_admin)
    assert db.get(ProjectMember, 1).user_id == 2
    saved = user.password_hash
    for payload in ({}, {'new_password': 'short'}, {'new_password': 'x' * 129}, {'new_password': ' ' * 8}, {'new_password': None}, {'new_password': 'NewPassword2026', 'is_admin': True}):
        assert client.patch('/api/admin/users/2/password', headers=headers(1), json=payload).status_code == 422
    assert db.get(User, 2).password_hash == saved
    assert client.get('/api/auth/me', headers=headers(2)).status_code == 401
    login = client.post('/api/auth/login', json={'email': user.email, 'password': 'NewPassword2026'})
    assert login.status_code == 200
    refreshed = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.patch('/api/admin/users/2/password', headers=refreshed, json={'new_password': 'Intruder2026'}).status_code == 403
    client.cookies.clear()
    assert client.patch('/api/admin/users/2/password', json={'new_password': 'Intruder2026'}).status_code == 401
    assert client.patch('/api/admin/users/9999/password', headers=headers(1), json={'new_password': 'NewPassword2026'}).status_code == 404
    assert client.patch('/api/admin/users/1/password', headers=headers(1), json={'new_password': 'OwnPassword2026'}).status_code == 200
