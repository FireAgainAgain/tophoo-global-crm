"""Direct lead conversion, merged legacy data and search quality accounting."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Lead, ProspectingCandidate, ProspectingEntry, ProspectingJob
from app.services.acquisition_results import adopt_legacy_entries, repair_historical_results, non_company_reason, result_counts
from app.services.workflow_people import set_workflow_people, workflow_people
from tests.test_global_access import db, headers

BASE='/api/acquisition/projects/1'
PERSON={'contact_name':'Buyer','email':'buyer@coil.test','linkedin':'https://linkedin.com/in/buyer','is_primary':True}

def test_manual_record_direct_conversion_and_history_deletion_keep_lead(db):
    client=TestClient(app)
    response=client.post(BASE+'/records',headers=headers(2),json={'company_name':'Coil','website':'https://coil.test',
        'company_youtube':'https://youtube.com/@coil','company_address':'Industrial Road','contacts':[PERSON,{'email':'engineer@coil.test'}]})
    assert response.status_code==201,response.text
    record=response.json()
    assert not db.scalars(select(ProspectingEntry)).all()
    listing=client.get(BASE+'/results',headers=headers(2)).json()
    assert listing['items'][0]['id']==record['id'] and listing['counts']['ready']==1
    response=client.post(BASE+'/candidates/actions',headers=headers(2),json={'ids':[record['id']],'action':'to-leads'})
    assert response.status_code==200,response.text
    lead=db.scalar(select(Lead));assert len(workflow_people(lead))==2 and lead.company_youtube=='https://youtube.com/@coil'
    assert workflow_people(lead)[0]['linkedin']==PERSON['linkedin']
    assert lead.company_address=='Industrial Road'
    assert db.get(ProspectingCandidate,record['id']).lead_id==lead.id
    assert client.get(BASE+'/results',headers=headers(2)).json()['counts']['converted']==1
    assert client.post(BASE+'/candidates/actions',headers=headers(2),json={'ids':[record['id']],'action':'to-leads'}).json()['skipped']==1
    assert len(db.scalars(select(Lead)).all())==1
    assert client.delete(BASE+f"/jobs/{record['job_id']}",headers=headers(2)).status_code==200
    assert db.get(Lead,lead.id) is not None and len(workflow_people(lead))==2

def test_imports_directly_retained_and_secondary_contacts_survive(db):
    client=TestClient(app)
    response=client.post(BASE+'/imports',headers=headers(2),json={'candidates':[{'company_name':'Coil','website':'https://coil.test','contacts':[PERSON]}]})
    assert response.status_code==201,response.text
    assert not db.scalars(select(ProspectingEntry)).all()
    rows=client.get(BASE+'/results',headers=headers(2)).json()['items']
    assert rows[0]['status']=='ready' and rows[0]['contacts'][0]['linkedin']==PERSON['linkedin']

def test_legacy_adoption_is_idempotent_and_preserves_owner_and_edited_people(db):
    item=ProspectingEntry(site_project_id=1,owner_user_id=2,company_name='Edited company',company_website='https://legacy.test',company_facebook='https://facebook.com/legacy')
    set_workflow_people(item,[PERSON]);db.add(item);db.commit()
    adopt_legacy_entries(db);db.commit()
    result=db.scalar(select(ProspectingCandidate));job=db.get(ProspectingJob,result.job_id)
    assert result.company_name=='Edited company' and result.status=='ready' and job.owner_user_id==2
    assert result.company_facebook=='https://facebook.com/legacy'
    assert workflow_people(result)[0]['email']==PERSON['email']
    adopt_legacy_entries(db);db.commit()
    assert len(db.scalars(select(ProspectingCandidate)).all())==1
    assert not db.scalars(select(ProspectingEntry)).all()

def test_all_results_cross_batch_delete_ownership_and_atomicity(db):
    client=TestClient(app)
    a=client.post(BASE+'/records',headers=headers(2),json={'company_name':'A','website':'https://a.test'}).json()
    b=client.post(BASE+'/records',headers=headers(2),json={'company_name':'B','website':'https://b.test'}).json()
    other=client.post(BASE+'/records',headers=headers(1),json={'company_name':'Other','website':'https://other.test'}).json()
    assert len(client.get(BASE+'/results',headers=headers(2)).json()['items'])==2
    assert client.post(BASE+'/results/delete',headers=headers(2),json={'ids':[a['id'],other['id']]}).status_code==404
    assert db.get(ProspectingCandidate,a['id']) is not None
    assert client.post(BASE+'/results/delete',headers=headers(2),json={'ids':[a['id'],b['id']]}).status_code==200
    assert db.get(ProspectingCandidate,other['id']) is not None
    for record in (a,b):
        counts=result_counts(db,db.get(ProspectingJob,record['job_id']))
        assert counts['deleted']==1 and counts['collapsed_duplicates']==0

def test_non_company_pages_and_invalid_historical_type_keep_original_evidence(db):
    assert non_company_reason('https://en.wikipedia.org/wiki/Drying')
    assert non_company_reason('https://www.ese.iitb.ac.in/lab.pdf')
    assert not non_company_reason('https://coil.test/products')
    job=ProspectingJob(site_project_id=1,owner_user_id=2,found_count=10,status='running',criteria_json=json.dumps({'processed':2}))
    db.add(job);db.flush()
    item=ProspectingCandidate(job_id=job.id,site_project_id=1,company_name='Wikipedia',website='https://en.wikipedia.org/wiki/Drying',fingerprint='wiki',status='ready',company_type='1')
    db.add(item);db.flush();repair_historical_results(db);db.flush()
    assert item.status=='filtered' and item.company_type is None
    assert json.loads(item.evidence_json)['invalid_company_type']=='1'
    counts=result_counts(db,job)
    assert counts['processed']==2 and counts['collapsed_duplicates']==1 # unprocessed pages are not duplicates


def test_repeated_batches_merge_contacts_but_keep_audit_rows(db):
    from app.services.acquisition_results import merge_repeated_results
    for index,status in enumerate(['ready','pending_review']):
        job=ProspectingJob(site_project_id=1,owner_user_id=2,status='done',found_count=1)
        db.add(job);db.flush()
        item=ProspectingCandidate(job_id=job.id,site_project_id=1,company_name='Coil',website='https://coil.test',fingerprint='same',status=status)
        set_workflow_people(item,[{'email':f'person{index}@coil.test','is_primary':True}])
        db.add(item)
    db.flush();merge_repeated_results(db);db.flush()
    rows=db.scalars(select(ProspectingCandidate).order_by(ProspectingCandidate.id)).all()
    assert [item.status for item in rows]==['ready','duplicate']
    assert len(workflow_people(rows[0]))==2
    assert json.loads(rows[1].evidence_json)['duplicate_of']==rows[0].id
    merge_repeated_results(db);db.flush()
    assert len(workflow_people(rows[0]))==2


def test_plural_and_hyphen_keyword_matching_preserves_word_boundaries():
    from app.services.acquisition_filter import keyword_matches
    assert keyword_matches('finned tube heat exchangers','finned tube heat exchanger')
    assert keyword_matches('fin-and-tube heat exchangers','finned tube heat exchanger')
    assert not keyword_matches('ribbed tubing','rib')
    assert not keyword_matches('food preservation and cooking','food drying')
