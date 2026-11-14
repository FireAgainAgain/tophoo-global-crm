"""Conservative Chinese country labels; unknown/free-text regions remain intact."""
from functools import lru_cache
import unicodedata
from babel import Locale
from babel.core import get_global

OVERRIDES={'AE':'阿联酋','HK':'中国香港','MO':'中国澳门','TW':'中国台湾','CZ':'捷克'}
ALIASES={
    'US':['USA','U.S.A.','U.S.','United States of America','美利坚合众国'],
    'GB':['UK','U.K.','Great Britain','United Kingdom of Great Britain and Northern Ireland','大不列颠及北爱尔兰联合王国'],
    'CZ':['Czech Republic','捷克共和国'], 'TR':['Turkey','Türkiye','土耳其共和国'],
    'IR':['Iran, Islamic Republic of','Islamic Republic of Iran'],
    'KR':['South Korea','Republic of Korea','Korea, Republic of','南韩'],
    'KP':["Korea, Democratic People’s Republic of",'North Korea'],
    'RU':['Russian Federation','俄罗斯联邦'], 'VN':['Viet Nam'],
    'CN':['China (Mainland)','Mainland China','P.R. China','PRC','中国大陆','中华人民共和国'],
    'AE':['UAE','U.A.E.','阿拉伯联合酋长国'],
    'TW':['Taiwan, China','Taiwan, Province of China','台湾','臺灣'],
    'HK':['Hong Kong','Hong Kong, China','香港'], 'MO':['Macao','Macau','澳门','澳門'],
}


def key(value):
    return ' '.join(unicodedata.normalize('NFKC',value or '').strip().casefold().split())


@lru_cache(maxsize=1)
def country_options():
    zh,en=Locale.parse('zh_CN'),Locale.parse('en')
    chinese_variants=[Locale.parse('zh_TW'),Locale.parse('zh_HK')]
    codes=[code for code in en.territories if len(code)==2 and code.isalpha() and code not in {'ZZ','EU','EZ','UN','QO'}]
    legacy=get_global('territory_aliases')
    rows=[]
    for code in codes:
        name=OVERRIDES.get(code,zh.territories.get(code,code))
        aliases={code,en.territories[code],zh.territories.get(code,name),*ALIASES.get(code,[])}
        aliases.add(en.territories[code].replace(' & ', ' and '))
        aliases.update(locale.territories[code] for locale in chinese_variants if code in locale.territories)
        aliases.update(alias for alias,targets in legacy.items() if len(alias)==3 and targets==[code])
        rows.append({'code':code,'name':name,'aliases':sorted(aliases)})
    return sorted(rows,key=lambda row:row['code'])


@lru_cache(maxsize=1)
def country_aliases():
    return {key(alias):row['name'] for row in country_options() for alias in [row['name'],*row['aliases']]}


def chinese_country(value):
    if value is None:return None
    value=value.strip()
    return country_aliases().get(key(value),value) or None


@lru_cache(maxsize=1)
def country_hues():
    # 137 and 360 are coprime, so every catalog entry gets a distinct hue.
    return {row['name']: (index * 137 + 42) % 360
            for index, row in enumerate(country_options())}


def country_hue(value):
    return country_hues().get(chinese_country(value))
