"""Offline IANA clocks, public-holiday rules and timezone-safe work windows."""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from importlib.resources import files
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import holidays
import tzdata
from babel import Locale
from babel.dates import get_timezone_location
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models.communication import CommunicationSetting
from app.schemas.communication import PlaceConfig, Schedule

UTC=timezone.utc
BEIJING=ZoneInfo('Asia/Shanghai')
WEEKDAYS=['周一','周二','周三','周四','周五','周六','周日']
DEFAULT_FAVORITES=['CN:Asia/Shanghai','DE:Europe/Berlin','GB:Europe/London','US:America/New_York','US:America/Los_Angeles','AE:Asia/Dubai','IN:Asia/Kolkata','SG:Asia/Singapore']


@lru_cache(maxsize=1)
def catalog():
    zh,en=Locale.parse('zh_CN'),Locale.parse('en')
    supported=holidays.list_supported_countries()
    places=[];countries={}
    text=files('tzdata.zoneinfo').joinpath('zone.tab').read_text(encoding='utf-8')
    for line in text.splitlines():
        if not line or line.startswith('#'):continue
        code,_,zone,*_=line.split('\t')
        try:
            tz=ZoneInfo(zone)
            city=get_timezone_location(tz,return_city=True,locale=zh)
        except (ZoneInfoNotFoundError,ValueError):continue
        country='阿联酋' if code=='AE' else zh.territories.get(code,code)
        places.append({'key':code+':'+zone,'country':code,'country_name':country,'country_en':en.territories.get(code,code),
            'search_aliases':{'AE':['阿拉伯联合酋长国','UAE'],'CZ':['捷克共和国','Czech Republic']}.get(code,[]),
            'timezone':zone,'city':city,'city_en':zone.split('/')[-1].replace('_',' '),'holiday_supported':code in supported})
        countries.setdefault(code,{'code':code,'name':country,'name_en':en.territories.get(code,code),'places':[]})['places'].append(code+':'+zone)
    return {'places':sorted(places,key=lambda p:(p['country_en'],p['timezone'])),'countries':sorted(countries.values(),key=lambda c:c['name_en']),
        'recommended':[key for key in DEFAULT_FAVORITES if key in {p['key'] for p in places}],
        'sources':{'timezone':'IANA / tzdata '+tzdata.__version__,'holidays':'python-holidays '+holidays.__version__,
            'timezone_url':'https://www.iana.org/time-zones','holiday_url':'https://holidays.readthedocs.io/',
            'note':'公共假日按规则生成，临时公告及调休需核对；参考作息不代表企业实际营业安排。'}}


@lru_cache(maxsize=1)
def places_by_key():return {row['key']:row for row in catalog()['places']}


@lru_cache(maxsize=1024)
def country_code(value):
    value=(value or '').strip().casefold()
    aliases={'usa':'US','u.s.a.':'US','uk':'GB','u.k.':'GB','英国':'GB','美国':'US','uae':'AE','阿联酋':'AE','阿拉伯联合酋长国':'AE','捷克共和国':'CZ','czech republic':'CZ','韩国':'KR','俄罗斯':'RU','中国大陆':'CN','中国':'CN','中国香港':'HK','中国台湾':'TW','越南':'VN'}
    if value in aliases:return aliases[value]
    for row in catalog()['countries']:
        if value in {row['code'].casefold(),row['name'].casefold(),row['name_en'].casefold()}:return row['code']
    return None


def infer_place(country, address=''):
    """Resolve only a known country and an unambiguous catalog city; never guess a capital."""
    code=country_code(country)
    if not code:return None,'unconfigured'
    places=[place for place in catalog()['places'] if place['country']==code]
    # Chinese business records use Beijing time unless explicitly configured otherwise.
    if code=='CN':return places_by_key().get('CN:Asia/Shanghai'),'auto_country'
    if len(places)==1:return places[0],'auto_country'
    text=(address or '').casefold()
    matches=[]
    for place in places:
        names={place['city'],place['city_en']}
        if any(re.search(r'(?<![a-z])'+re.escape(name.casefold())+r'(?![a-z])',text) for name in names if len(name)>1):
            matches.append(place)
    if len(matches)==1:return matches[0],'auto_address'
    if len(matches)>1:return None,'unconfigured'
    return None,'unconfigured'


@lru_cache(maxsize=256)
def subdivisions(country):
    if country not in holidays.list_supported_countries():return []
    cal=holidays.country_holidays(country)
    aliases=getattr(cal,'subdivisions_aliases',{})
    return [{'code':code,'name':next((name for name,target in aliases.items() if target==code and len(name)>3),code)} for code in cal.subdivisions]


def validate_place(config):
    key=config.country+':'+config.timezone
    if key not in places_by_key():raise HTTPException(422,'所选时区不属于该国家／地区，请重新选择。')
    if config.subdivision and config.subdivision not in {row['code'] for row in subdivisions(config.country)}:
        raise HTTPException(422,'所选地方假日地区无效。')
    return config


def place_from_key(key,overrides=None):
    place=places_by_key().get(key)
    if not place:raise HTTPException(422,'地区或时区不存在。')
    return PlaceConfig.model_validate((overrides or {}).get(key) or {'country':place['country'],'timezone':place['timezone']})


@lru_cache(maxsize=1024)
def calendar_for(country,subdivision,year):
    if country not in holidays.list_supported_countries():return None
    try:
        cal=holidays.country_holidays(country,subdiv=subdivision,years=year,expand=False,observed=True,language='en_US')
        if not getattr(cal,'start_year',1)<=year<=getattr(cal,'end_year',9999):return None
        return cal
    except (ValueError,NotImplementedError):return None


def closed_on(config,day,for_work=True):
    closure=next((row for row in config.closures if row.start<=day<=row.end),None)
    if closure:return ('closure',closure.name)
    if for_work and not config.respect_public_holidays:return None
    cal=calendar_for(config.country,config.subdivision,day.year)
    if cal is not None and day in cal:return ('holiday',str(cal[day]))
    return None


def wall_candidates(value,zone):
    """Round-trip validation rejects DST gaps; folds expose both distinct instants."""
    candidates=[]
    for fold in (0,1):
        candidate=value.replace(tzinfo=zone,fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None)==value and candidate not in candidates:candidates.append(candidate)
    return sorted(candidates)


def wall_boundary(value,zone,end=False):
    # A work boundary inside a spring gap moves forward to the first real minute.
    for shift in range(181):
        candidates=wall_candidates(value+timedelta(minutes=shift),zone)
        if candidates:return candidates[-1] if end else candidates[0]
    raise HTTPException(422,'该日期的时区规则无法生成工作时段。')


def work_windows(config,anchor,days=31):
    zone=ZoneInfo(config.timezone);start=anchor.astimezone(zone).date()-timedelta(days=1);result=[]
    for offset in range(days+2):
        day=start+timedelta(days=offset)
        if day.weekday() not in config.schedule.weekdays:continue
        for period in config.schedule.periods:
            a=datetime.combine(day,time.fromisoformat(period.start));b=datetime.combine(day,time.fromisoformat(period.end))
            if b<=a:b+=timedelta(days=1)
            # A holiday/closure on the second day also closes an overnight shift.
            cursor=a
            while cursor<b:
                edge=min(b,datetime.combine(cursor.date()+timedelta(days=1),time.min))
                if not closed_on(config,cursor.date()):
                    left=wall_boundary(cursor,zone);right=wall_boundary(edge,zone,True)
                    if left<right:result.append((left,right))
                cursor=edge
    return sorted(result)


def current_state(config,instant,windows=None):
    instant=instant.astimezone(UTC);local=instant.astimezone(ZoneInfo(config.timezone));day=local.date()
    closed=closed_on(config,day)
    if closed:return {'key':closed[0],'label':'客户休假' if closed[0]=='closure' else '公共假日','reason':closed[1]}
    windows=windows if windows is not None else work_windows(config,instant,1)
    working=next(((a,b) for a,b in windows if a<=instant<b),None)
    supported=not config.respect_public_holidays or calendar_for(config.country,config.subdivision,day.year) is not None
    if working:return {'key':'working' if supported else 'unverified','label':'工作时段' if supported else '参考工作时段 · 假日未核对','reason':''}
    if day.weekday() not in config.schedule.weekdays:return {'key':'weekend','label':'每周休息日','reason':''}
    earlier=any(b.astimezone(ZoneInfo(config.timezone)).date()==day and b<=instant for _,b in windows)
    later=any(a.astimezone(ZoneInfo(config.timezone)).date()==day and a>instant for a,_ in windows)
    return {'key':'break' if earlier and later else 'off','label':'工作间歇' if earlier and later else '非工作时段','reason':''}


def time_data(instant,zone):
    local=instant.astimezone(ZoneInfo(zone));offset=int(local.utcoffset().total_seconds()/60)
    return {'iso':local.isoformat(),'date':local.date().isoformat(),'time':local.strftime('%H:%M'),'weekday':WEEKDAYS[local.weekday()],
        'offset_minutes':offset,'offset_label':f'UTC{"+" if offset>=0 else "-"}{abs(offset)//60:02d}:{abs(offset)%60:02d}',
        'is_dst':bool(local.dst()),'beijing':instant.astimezone(BEIJING).isoformat(),'utc':instant.astimezone(UTC).isoformat()}


def holiday_rows(config,today,days):
    result=[]
    for offset in range(days):
        day=today+timedelta(days=offset);closed=closed_on(config,day,for_work=False)
        if closed:result.append({'date':day.isoformat(),'name':closed[1],'type':closed[0],'scope':config.subdivision or '全国公共假日','days_away':offset})
    grouped=[]
    for row in result:
        previous=grouped[-1] if grouped else None
        if previous and all(previous[key]==row[key] for key in ('name','type','scope')) and date.fromisoformat(row['date'])==date.fromisoformat(previous.get('end_date',previous['date']))+timedelta(days=1):
            previous['end_date']=row['date']
        else:grouped.append(row)
    return grouped


def overview(config,now=None,days=30,details=False,home_timezone='Asia/Shanghai',home_schedule=None):
    validate_place(config);now=now or datetime.now(UTC);zone=ZoneInfo(config.timezone);local=now.astimezone(zone)
    windows=work_windows(config,now);state=current_state(config,now,windows)
    next_window=next(((max(a,now),b) for a,b in windows if b>now),None)
    place=places_by_key()[config.country+':'+config.timezone]
    data={**place,'city':config.city or place['city'],'now':time_data(now,config.timezone),'state':state,
        'difference_minutes':int(local.utcoffset().total_seconds()/60)-480,'config':config.model_dump(mode='json'),
        'next_working':{'start':time_data(next_window[0],config.timezone),'end':time_data(next_window[1],config.timezone)} if next_window else None,
        'holiday_supported':calendar_for(config.country,config.subdivision,local.year) is not None,
        'holidays':holiday_rows(config,local.date(),days),'generated_at':now.isoformat()}
    if details:
        home_place=next((row for row in catalog()['places'] if row['timezone']==home_timezone),None)
        overlaps=[]
        if home_place:
            home=PlaceConfig(country=home_place['country'],timezone=home_timezone,schedule=home_schedule or Schedule())
            for a,b in work_windows(home,now,14):
                for c,d in windows:
                    left=max(a,c,now);right=min(b,d)
                    if left<right:overlaps.append({'start':time_data(left,config.timezone),'end':time_data(right,config.timezone),'home_start':left.astimezone(ZoneInfo(home_timezone)).isoformat(),'home_end':right.astimezone(ZoneInfo(home_timezone)).isoformat()})
        data.update(common_windows=overlaps[:3],home_timezone=home_timezone,subdivisions=subdivisions(config.country),sources=catalog()['sources'])
    return data


def convert_wall(config,value,fold=None):
    try:value=datetime.fromisoformat(value)
    except ValueError:raise HTTPException(422,'请输入正确的当地日期和时间。')
    if value.tzinfo is not None:raise HTTPException(422,'请输入不带时区偏移的当地时间。')
    if not 1900<=value.year<=2100:raise HTTPException(422,'时间换算支持 1900–2100 年。')
    candidates=wall_candidates(value,ZoneInfo(config.timezone))
    if not candidates:raise HTTPException(422,'该当地时间因夏令时跳时而不存在，请换一个时间。')
    if len(candidates)>1 and fold is None:raise HTTPException(422,'该当地时间因夏令时回拨出现两次，请选择第一次或第二次。')
    instant=candidates[fold or 0] if len(candidates)>1 else candidates[0]
    return {**time_data(instant,config.timezone),'state':current_state(config,instant),'ambiguous':len(candidates)>1}


def person_key(person):
    clean=lambda key:str(person.get(key) or '').strip().casefold()
    value='email:'+clean('email') if clean('email') else next((field+':'+clean(field)+':'+clean('contact_name') for field in ('phone','whatsapp','contact_name') if clean(field)),None)
    return hashlib.sha256(value.encode()).hexdigest()[:32] if value else ''


def target_key(kind,entity_id,person=''):return f'{kind}:{entity_id}'+(':'+person if person else '')


def transfer_settings(db,project_id,lead,customer):
    """Carry lead schedules through conversion; existing client settings take priority."""
    from app.models import CustomerPerson
    from app.services.workflow_people import workflow_people
    people={person_key(row):row for row in workflow_people(lead)}
    clients=db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id==customer.id)).all()
    for setting in db.scalars(select(CommunicationSetting).where(CommunicationSetting.site_project_id==project_id,CommunicationSetting.lead_id==lead.id)).all():
        suffix=setting.target_key.split(':')[2:];person_id=None
        if suffix:
            incoming=people.get(suffix[0]);matches=[]
            if incoming:
                if incoming.get('email'):matches=[p for p in clients if p.email and p.email.casefold()==incoming['email'].casefold()]
                if not matches:matches=[p for p in clients if (incoming.get('phone') and p.phone==incoming['phone'] and p.contact_name==incoming.get('contact_name')) or person_key({'contact_name':p.contact_name,'email':p.email,'phone':p.phone,'whatsapp':p.whatsapp})==suffix[0]]
            if len(matches)!=1:continue
            person_id=matches[0].id
        key=target_key('customers',customer.id,str(person_id) if person_id else '')
        if not db.scalar(select(CommunicationSetting.id).where(CommunicationSetting.site_project_id==project_id,CommunicationSetting.target_key==key)):
            db.add(CommunicationSetting(site_project_id=project_id,target_key=key,customer_id=customer.id,person_id=person_id,settings_json=setting.settings_json))
    db.execute(delete(CommunicationSetting).where(CommunicationSetting.lead_id==lead.id))
