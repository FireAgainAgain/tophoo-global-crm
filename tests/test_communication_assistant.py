"""Offline scheduling, DST boundaries, private preferences and CRM ownership."""
import json
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from app.main import app
from app.models import Customer, Lead, ProjectContact, ProjectMember, CustomerPerson
from app.models.communication import CommunicationPreference, CommunicationSetting
from app.schemas.communication import PlaceConfig, Preferences, Schedule
from app.services import communication as service
from tests.test_global_access import db, headers

BASE='/api/communication/projects/1'


def config(country='US',zone='America/New_York',**kw):
    return PlaceConfig(country=country,timezone=zone,**kw)


def client_company(client,owner=2,country='美国'):
    response=client.post('/api/contacts/projects/1',headers=headers(1),json={'company_name':'Factory '+str(owner),'country':country,'contacts':[{'contact_name':'Alice','email':str(owner)+'@example.test','is_primary':True}],**({'owner_user_id':owner} if owner!=1 else {})})
    assert response.status_code==201,response.text
    return response.json()


def test_catalog_has_real_country_timezones_and_chinese_city_labels():
    data=service.catalog()
    assert len(data['countries'])>200 and len(data['places'])>400
    assert service.places_by_key()['US:America/New_York']['city']=='纽约'
    uae=service.places_by_key()['AE:Asia/Dubai']
    assert uae['country_name']=='阿联酋' and uae['city']=='迪拜'
    assert 'UAE' in uae['search_aliases'] and '阿拉伯联合酋长国' in uae['search_aliases']
    assert 'AE:Asia/Dubai' in data['recommended']
    assert service.country_code('德国')=='DE' and service.country_code('United Kingdom')=='GB'
    czech=service.places_by_key()['CZ:Europe/Prague']
    assert '捷克共和国' in czech['search_aliases'] and 'Czech Republic' in czech['search_aliases']
    for name in ['捷克','捷克共和国','Czechia','Czech Republic','CZ']:
        assert service.country_code(name)=='CZ'
        place,source=service.infer_place(name)
        assert place['timezone']=='Europe/Prague' and source=='auto_country'
    assert any(x['code']=='CA' for x in service.subdivisions('US'))
    with pytest.raises(HTTPException):service.validate_place(config('US','Asia/Shanghai'))
    with pytest.raises(HTTPException):service.validate_place(config(subdivision='invalid'))


def test_dst_gap_fold_and_fractional_hour_conversion():
    cfg=config()
    with pytest.raises(HTTPException):service.convert_wall(cfg,'2026-03-08T02:30')
    with pytest.raises(HTTPException):service.convert_wall(cfg,'2026-11-01T01:30')
    first=service.convert_wall(cfg,'2026-11-01T01:30',0)
    second=service.convert_wall(cfg,'2026-11-01T01:30',1)
    assert first['utc'].startswith('2026-11-01T05:30')
    assert second['utc'].startswith('2026-11-01T06:30')
    data=service.overview(config('IN','Asia/Kolkata'),now=datetime(2026,10,19,5,tzinfo=timezone.utc))
    assert data['difference_minutes']==-150 and data['now']['time']=='10:30'


def test_lunch_overnight_public_holiday_and_company_closure():
    # New York 12:30 on an ordinary Monday is between configured work periods.
    result=service.overview(config(),now=datetime(2026,10,19,16,30,tzinfo=timezone.utc))
    assert result['state']['key']=='break'
    assert result['next_working']['start']['time']=='13:00'
    night=config(schedule=Schedule(weekdays=[4],periods=[{'start':'22:00','end':'06:00'}]))
    assert service.overview(night,now=datetime(2026,10,17,6,tzinfo=timezone.utc))['state']['key']=='working'
    observed=service.overview(config(),now=datetime(2026,7,3,14,tzinfo=timezone.utc))
    assert observed['state']['key']=='holiday'
    assert service.overview(config(respect_public_holidays=False),now=datetime(2026,7,3,14,tzinfo=timezone.utc))['state']['key']=='working'
    assert observed['next_working']['start']['date']=='2026-07-06'
    closed=config(closures=[{'start':'2026-10-19','end':'2026-10-20','name':'Factory vacation'}])
    assert service.overview(closed,now=datetime(2026,10,19,14,tzinfo=timezone.utc))['state']['key']=='closure'
    assert service.overview(closed,now=datetime(2026,10,19,14,tzinfo=timezone.utc))['next_working']['start']['date']=='2026-10-21'


def test_schedule_rejects_overlap_including_across_week_boundary():
    with pytest.raises(ValidationError):Schedule(periods=[{'start':'09:00','end':'14:00'},{'start':'13:00','end':'17:00'}])
    with pytest.raises(ValidationError):Schedule(weekdays=[6,0],periods=[{'start':'22:00','end':'06:00'},{'start':'01:00','end':'03:00'}])
    with pytest.raises(ValidationError):Schedule(weekdays=[8])
    assert Schedule(weekdays=[],periods=[]).weekdays==[]


def test_read_only_reference_tools_private_preferences_and_no_statistics_writes(db):
    client=TestClient(app);member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.write_permissions_json='[]';db.commit()
    before={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (Lead,Customer,ProjectContact)}
    assert client.get(BASE+'/catalog',headers=headers(2)).status_code==200
    assert client.get(BASE+'/preferences',headers=headers(2)).status_code==200
    assert db.scalar(select(func.count(CommunicationPreference.id)))==0
    prefs=Preferences(favorites=['US:America/New_York']).model_dump(mode='json')
    response=client.put(BASE+'/preferences',headers=headers(2),json=prefs)
    assert response.status_code==200,response.text
    assert client.get(BASE+'/preferences',headers=headers(1)).json()['favorites']!=prefs['favorites']
    assert client.post(BASE+'/preview',headers=headers(2),json={'config':config().model_dump(mode='json')}).status_code==200
    assert client.post(BASE+'/convert',headers=headers(2),json={'config':config().model_dump(mode='json'),'value':'2026-10-19T09:30'}).json()['beijing'].startswith('2026-10-19T21:30')
    after={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (Lead,Customer,ProjectContact)}
    assert before==after
    assert client.get('/api/communication/projects/2/catalog',headers=headers(2)).status_code==403
    assert client.get(BASE+'/catalog').status_code==401


def test_company_person_inheritance_scope_and_read_only_writes(db):
    client=TestClient(app);company=client_company(client);other=client_company(client,1)
    endpoint=BASE+f"/entities/customers/{company['id']}"
    # A multi-timezone country must not silently become New York.
    initial=client.get(endpoint,headers=headers(2)).json()
    assert initial['overview'] is None and initial['origin']=='unconfigured'
    body=config('GB','Europe/London',confirmed=True).model_dump(mode='json')
    assert client.put(endpoint,headers=headers(2),json=body).status_code==200
    person=client.get(endpoint,headers=headers(2)).json()['people'][0]['key']
    inherited=client.get(endpoint+'?person='+person,headers=headers(2)).json()
    assert inherited['overview']['timezone']=='Europe/London' and inherited['origin']=='company' and not inherited['has_override']
    personal=config().model_dump(mode='json')
    assert client.put(endpoint+'?person='+person,headers=headers(2),json=personal).json()['origin']=='person'
    assert client.get(endpoint,headers=headers(2)).json()['overview']['timezone']=='Europe/London'
    assert client.get(endpoint+'?person=99999',headers=headers(2)).status_code==422
    assert client.get(BASE+f"/entities/customers/{other['id']}",headers=headers(2)).status_code==404
    db.refresh(db.get(Customer,company['id']))
    assert db.get(Customer,company['id']).country=='美国'
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.write_permissions_json='[]';db.commit()
    assert client.put(endpoint,headers=headers(2),json=body).status_code==403
    assert client.delete(endpoint,headers=headers(2)).status_code==403
    assert client.get(endpoint,headers=headers(2)).status_code==200


def test_conversion_keeps_company_and_contact_settings_and_cleanup(db):
    client=TestClient(app)
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={'company_name':'Coil maker','country':'美国','company_website':'https://coil.example.test','contacts':[{'contact_name':'Alice','email':'alice@example.test','is_primary':True}]}).json()
    endpoint=BASE+f"/entities/leads/{lead['id']}"
    info=client.get(endpoint,headers=headers(2)).json();person=info['people'][0]['key']
    assert client.put(endpoint,headers=headers(2),json=config().model_dump(mode='json')).status_code==200
    assert client.put(endpoint+'?person='+person,headers=headers(2),json=config('GB','Europe/London').model_dump(mode='json')).status_code==200
    response=client.post(f"/api/customer-workflow/projects/1/leads/{lead['id']}/to-customers",headers=headers(2))
    assert response.status_code==200,response.text
    customer_id=response.json()['customer_id'];new=BASE+f'/entities/customers/{customer_id}'
    assert client.get(new,headers=headers(2)).json()['overview']['timezone']=='America/New_York'
    rows=db.scalars(select(CommunicationSetting).where(CommunicationSetting.customer_id==customer_id)).all()
    assert len(rows)==2 and not db.scalars(select(CommunicationSetting).where(CommunicationSetting.lead_id==lead['id'])).all()
    from app.models import LeadConversionHistory
    history=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==customer_id))
    assert len(json.loads(history.snapshot_json)['communication_settings'])==2
    person_id=next(row.person_id for row in rows if row.person_id)
    assert client.get(new+'?person='+str(person_id),headers=headers(2)).json()['overview']['timezone']=='Europe/London'
    assert client.delete('/api/contacts/projects/1/'+str(customer_id),headers=headers(2)).status_code==200
    assert not db.scalars(select(CommunicationSetting)).all()


def test_related_customers_and_project_deletion_preserve_other_projects(db):
    client=TestClient(app);company=client_company(client);client_company(client,1)
    endpoint=BASE+f"/entities/customers/{company['id']}"
    assert client.put(endpoint,headers=headers(2),json=config().model_dump(mode='json')).status_code==200
    related=client.get(BASE+'/related-customers',params={'key':'US:America/New_York'},headers=headers(2)).json()
    assert [row['id'] for row in related['items']]==[company['id']]
    assert client.put(BASE+'/preferences',headers=headers(2),json=Preferences().model_dump(mode='json')).status_code==200
    db.add(CommunicationPreference(site_project_id=2,user_id=1,settings_json='{}'));db.commit()
    assert client.request('DELETE','/api/workspaces/1/projects/1',headers=headers(1),json={'confirm_name':'Demo'}).status_code==200
    assert not db.scalars(select(CommunicationSetting)).all()
    assert [row.site_project_id for row in db.scalars(select(CommunicationPreference))]==[2]


def test_global_time_comparison_crosses_dates_and_dst_without_persistence(db):
    client=TestClient(app)
    counts=lambda:{m.__tablename__:db.scalar(select(func.count()).select_from(m)) for m in (CommunicationPreference,CommunicationSetting,Customer,Lead)}
    before=counts()
    def at(value):
        response=client.get(BASE+'/overview',headers=headers(2),params={'keys':'US:America/New_York,IN:Asia/Kolkata','at':value})
        assert response.status_code==200,response.text
        return response.json()['items']
    first=at('2026-11-01T13:30:00+08:00')
    second=at('2026-11-01T14:30:00+08:00')
    assert first[0]['now']['time']==second[0]['now']['time']=='01:30'
    assert first[0]['now']['offset_minutes']==-240
    assert second[0]['now']['offset_minutes']==-300
    assert first[1]['now']['time']=='11:00'
    previous=at('2026-11-01T00:00:00+08:00')
    assert previous[0]['now']['date']=='2026-10-31'
    for invalid in ('2026-11-01T13:30:00','2200-01-01T00:00:00Z'):
        assert client.get(BASE+'/overview',headers=headers(2),params={'at':invalid}).status_code==422
    assert counts()==before


@pytest.mark.parametrize('country,address,key,origin',[
    ('阿联酋','','AE:Asia/Dubai','auto_country'),
    ('United Arab Emirates','','AE:Asia/Dubai','auto_country'),
    ('阿拉伯联合酋长国','','AE:Asia/Dubai','auto_country'),
    ('中国','','CN:Asia/Shanghai','auto_country'),
    ('中国','乌鲁木齐','CN:Asia/Shanghai','auto_country'),
    ('美国','120 New York Avenue, New York, NY','US:America/New_York','auto_address'),
    ('美国','美国洛杉矶市','US:America/Los_Angeles','auto_address'),
    ('美国','New Yorkshire',None,'unconfigured'),
    ('美国','New York / Los Angeles',None,'unconfigured'),
    ('美国','',None,'unconfigured'),
    ('未知国家','New York',None,'unconfigured'),
])
def test_automatic_place_resolution(country,address,key,origin):
    place,source=service.infer_place(country,address)
    assert (place['key'] if place else None)==key
    assert source==origin


def test_auto_customer_and_lead_time_inheritance_without_writes(db):
    client=TestClient(app)
    company=client_company(client,country='阿联酋')
    endpoint=BASE+f"/entities/customers/{company['id']}"
    info=client.get(endpoint,headers=headers(2)).json()
    assert info['overview']['timezone']=='Asia/Dubai' and info['origin']=='auto_country'
    person=info['people'][0]['key']
    inherited=client.get(endpoint+'?person='+person,headers=headers(2)).json()
    assert inherited['overview']['timezone']=='Asia/Dubai' and not inherited['has_override']
    customer=db.get(Customer,company['id']);customer.country='美国';customer.company_address='New York, NY';db.commit()
    info=client.get(endpoint,headers=headers(2)).json()
    assert info['overview']['timezone']=='America/New_York' and info['origin']=='auto_address'
    related=client.get(BASE+'/related-customers',params={'key':'US:America/New_York'},headers=headers(2)).json()
    assert company['id'] in [row['id'] for row in related['items']]
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={
        'company_name':'Automatic city lead','country':'美国','company_address':'Los Angeles, CA',
        'contacts':[{'contact_name':'Alice','email':'auto@example.test','is_primary':True}]}).json()
    lead_endpoint=BASE+f"/entities/leads/{lead['id']}"
    info=client.get(lead_endpoint,headers=headers(2)).json()
    assert info['overview']['timezone']=='America/Los_Angeles' and info['origin']=='auto_address'
    assert db.scalar(select(func.count(CommunicationSetting.id)))==0
    # An explicit setting continues to override inferred company facts.
    body=config('GB','Europe/London').model_dump(mode='json')
    assert client.put(endpoint,headers=headers(2),json=body).json()['origin']=='company'
    assert client.get(endpoint,headers=headers(2)).json()['overview']['timezone']=='Europe/London'
    assert client.delete(endpoint,headers=headers(2)).json()['overview']['timezone']=='America/New_York'
