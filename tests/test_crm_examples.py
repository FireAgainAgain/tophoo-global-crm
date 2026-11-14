"""Requested examples are complete, idempotent and use only fictional addresses."""
import json
from sqlalchemy import select
from app.models import User, Lead, Customer, ProjectContact, LeadInteraction, LeadConversionHistory, ContactRecord, FollowUpPlan, CustomerPoolAudit
from tests.crm_examples_fixture import create_examples, NAMES, MARKER
from tests.test_global_access import db


def test_three_full_examples_and_repeat_without_duplicates(db):
    db.get(User,2).display_name='sam';db.commit()
    result=create_examples(db,1,2)
    assert len(result['examples'])==3 and all(row['created'] for row in result['examples'])
    source=db.scalar(select(Lead));assert source.company_name==NAMES['leads'] and source.is_contacted
    for key in ('country','company_type','company_website','company_address','customer_source','source_type','notes','company_linkedin','company_facebook','company_instagram','company_youtube'):assert getattr(source,key)
    people=json.loads(source.contacts_json);assert len(people)==2
    for person in people:
        for key in ('contact_name','email','phone','whatsapp','linkedin','facebook','instagram','youtube','notes'):assert person[key]
        assert person['email'].endswith('.example')
    assert len(db.scalars(select(LeadInteraction)).all())==2
    assert len(db.scalars(select(Customer)).all())==2
    assert {row.status for row in db.scalars(select(ProjectContact))}=={'active','pool'}
    assert len(db.scalars(select(LeadConversionHistory)).all())==2
    assert len(db.scalars(select(ContactRecord)).all())==4
    assert {row.status for row in db.scalars(select(FollowUpPlan))}=={'pending','cancelled'}
    assert db.scalar(select(CustomerPoolAudit)).release_reason.startswith('【演示】')
    repeated=create_examples(db,1,2)
    assert all(not row['created'] for row in repeated['examples'])
    assert len(db.scalars(select(LeadConversionHistory)).all())==2 and len(db.scalars(select(ContactRecord)).all())==4
