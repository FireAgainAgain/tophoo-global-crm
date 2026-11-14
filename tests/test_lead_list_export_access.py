"""Export must preserve search order and enforce project/owner visibility."""
from fastapi.testclient import TestClient

from app.main import app
from datetime import datetime
import json
from app.models import Lead, LeadOutreachDraft, LeadInteraction
from tests.test_global_access import db, headers


def test_export_subset_order_and_permissions(db, monkeypatch):
    client = TestClient(app)
    db.add_all([Lead(id=901, site_project_id=1, owner_user_id=2, company_name='First'),
                Lead(id=902, site_project_id=1, owner_user_id=2, company_name='Second'),
                Lead(id=903, site_project_id=1, owner_user_id=1, company_name='Other owner'),
                Lead(id=904, site_project_id=2, owner_user_id=2, company_name='Other project')])
    db.flush()
    db.get(Lead, 902).notes = 'Company investigation notes'
    db.get(Lead, 902).company_address = 'Detailed address'
    db.get(Lead, 902).company_linkedin = 'https://linkedin.com/company/example'
    db.get(Lead, 902).contacts_json = json.dumps([{'contact_name': 'Buyer', 'email': 'buyer@example.com',
        'notes': 'Person notes', 'linkedin': 'https://linkedin.com/in/buyer', 'is_primary': True},
        {'contact_name': 'Second person', 'email': 'second@example.com', 'is_primary': False}])
    db.add_all([LeadOutreachDraft(lead_id=902, subject='Separate subject', content='Subject: Draft A\nDraft body', content_translation='开发信中文翻译'),
        LeadOutreachDraft(lead_id=903, content='PRIVATE-DRAFT', content_translation=''),
        LeadInteraction(id=901, lead_id=902, site_project_id=1, created_by_user_id=2,
            occurred_at=datetime(2026,10,16,11), direction='outbound', channel='邮件',
            subject='Record subject', content='Record body', content_translation='联系记录中文翻译'),
        LeadInteraction(id=902, lead_id=902, site_project_id=1, created_by_user_id=2,
            occurred_at=datetime(2026,10,17,12), direction='inbound', channel='WhatsApp', content='Newest reply'),
        LeadInteraction(id=903, lead_id=903, site_project_id=1, created_by_user_id=1,
            occurred_at=datetime(2026,10,17,12), direction='inbound', channel='邮件', content='PRIVATE-RECORD'),
        LeadInteraction(id=904, lead_id=902, site_project_id=2, created_by_user_id=2,
            occurred_at=datetime(2026,10,17,12), direction='inbound', channel='邮件', content='WRONG-PROJECT-RECORD')])
    db.commit()
    captured = []
    def capture(items, scope):
        captured.append((items, scope))
        return b'PK-test'
    monkeypatch.setattr('app.services.lead_list_excel.export_lead_list_excel', capture)
    url = '/api/customer-workflow/projects/1/leads/export/xlsx'
    result = client.post(url, headers=headers(2), json={'ids': [902, 901, 902], 'scope': '搜索：测试'})
    assert result.status_code == 200
    assert result.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert "filename*=UTF-8''" in result.headers['content-disposition']
    assert [item['id'] for item in captured[0][0]] == [902, 901]
    assert captured[0][1] == '搜索：测试'
    assert 'owner_name' not in captured[0][0][0]
    details = captured[0][0][0]
    assert details['notes'] == 'Company investigation notes'
    assert details['company_address'] == 'Detailed address'
    assert details['company_linkedin'] == 'https://linkedin.com/company/example'
    assert len(details['contacts']) == 2
    assert details['contacts'][0]['notes'] == 'Person notes'
    assert 'outreach_draft' not in details
    assert 'interactions' not in details
    note_url = '/api/customer-workflow/projects/1/leads/902/followup-note'
    note = client.get(note_url, headers=headers(2))
    assert note.status_code == 200
    assert details['followup'] == note.json()['content']
    assert 'Newest reply' in details['followup']
    assert 'WRONG-PROJECT-RECORD' not in details['followup']
    assert captured[0][0][1]['followup'] == ''
    for ids in [[901, 903], [904], [9999]]:
        assert client.post(url, headers=headers(2), json={'ids': ids}).status_code == 409
    assert len(captured) == 1, 'Never export a partial or unauthorized list'
    assert client.post(url, headers=headers(1), json={'ids': [903, 901]}).status_code == 200
    assert 'owner_name' in captured[-1][0][0]
    assert client.post(url, headers=headers(2), json={'ids': []}).status_code == 422
    assert client.post('/api/customer-workflow/projects/2/leads/export/xlsx', headers=headers(2), json={'ids': [904]}).status_code == 403
    assert client.post(url, json={'ids': [901]}).status_code == 401
    assert db.get(Lead, 901).workflow_status == 'unviewed'
    assert not db.get(Lead, 901).is_contacted
    assert not db.get(Lead, 902).is_contacted
    assert db.get(LeadOutreachDraft,902).content == 'Subject: Draft A\nDraft body'
    assert db.get(LeadInteraction,901).content == 'Record body'
