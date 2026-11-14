"""Bounded discovery and evidence extraction; external text is never instructions."""
import json
import re
import socket
import ipaddress
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen
from app.services.acquisition_filter import COUNTRY_ALIASES, TYPE_ALIASES, canonical, contains, terms

# Public offer descriptions checked against official pages on 2026-10-09.
PROVIDERS = {
    'tavily': {
        'name': 'Tavily', 'kind': 'search', 'env': 'ACQUISITION_TAVILY_API_KEY',
        'description': '通用网页搜索，适合先免费验证企业搜索效果',
        'free_offer': '每月 1,000 credits', 'requires_card': False,
        'website_url': 'https://tavily.com', 'key_url': 'https://app.tavily.com',
        'pricing_url': 'https://docs.tavily.com/documentation/api-credits',
        'key_steps': ['注册或登录 Tavily Platform', '在 Dashboard 复制 API Key', '粘贴到下方，保存后选择 Tavily 搜索'],
        'cost_hint': '本项目固定使用 Basic Search，每次查询 1 credit；不调用 Advanced Search。超额规则以账号设置为准。',
    },
    'exa': {
        'name': 'Exa', 'kind': 'search', 'env': 'ACQUISITION_EXA_API_KEY',
        'description': '支持 company 分类搜索，适合发现相关企业网站',
        'free_offer': '每月 $10 额度 + $10 新用户额度', 'requires_card': False,
        'website_url': 'https://exa.ai', 'key_url': 'https://dashboard.exa.ai',
        'pricing_url': 'https://exa.ai/pricing',
        'key_steps': ['注册或登录 Exa Dashboard', '在 API Keys 创建并复制密钥', '粘贴到下方并保存'],
        'cost_hint': '按搜索模式、结果数量及内容选项计费；本项目使用 Fast 企业搜索，不请求额外正文内容。',
    },
    'firecrawl': {
        'name': 'Firecrawl', 'kind': 'search', 'env': 'ACQUISITION_FIRECRAWL_API_KEY',
        'description': '网页搜索接口；搜索后继续使用项目内置的官网资料读取',
        'free_offer': '每月 1,000 credits', 'requires_card': False,
        'website_url': 'https://www.firecrawl.dev', 'key_url': 'https://www.firecrawl.dev/app',
        'pricing_url': 'https://www.firecrawl.dev/pricing',
        'key_steps': ['注册或登录 Firecrawl', '在控制台找到 API Keys 并复制密钥', '粘贴到下方并保存'],
        'cost_hint': '搜索按官方 credits 规则扣费；本项目不调用额外付费抓取、Agent 或企业数据工具。',
    },
    'serper': {
        'name': 'Serper (Google)', 'kind': 'search', 'env': 'ACQUISITION_SERPER_API_KEY',
        'description': '通过第三方 Serper 获取 Google 搜索结果',
        'free_offer': '新用户 2,500 次查询试用', 'requires_card': False,
        'website_url': 'https://serper.dev', 'key_url': 'https://serper.dev', 'pricing_url': 'https://serper.dev',
        'key_steps': ['打开官网并点击免费试用', '注册登录后在控制台复制 API Key', '粘贴到下方并保存'],
        'cost_hint': '试用额度不是每月补充；之后按充值包付费，查询可能按结果数量消耗不同额度。',
    },
    'brave': {
        'name': 'Brave Search', 'kind': 'search', 'env': 'ACQUISITION_BRAVE_API_KEY',
        'description': '使用 Brave 独立网页索引，作为搜索备选',
        'free_offer': '每月 $5 额度', 'requires_card': True,
        'website_url': 'https://brave.com/search/api/', 'key_url': 'https://api-dashboard.search.brave.com',
        'pricing_url': 'https://brave.com/search/api/',
        'key_steps': ['注册 Brave Search API 账号', '在 Plans 激活 Search 套餐，官方要求信用卡', '在 API Keys 点击 Add API Key，复制后保存'],
        'cost_hint': '当前 Search 为 $5 / 1,000 请求；超出免费额度按账号套餐计费。',
    },
    'hunter': {
        'name': 'Hunter', 'kind': 'enrichment', 'env': 'ACQUISITION_HUNTER_API_KEY',
        'description': '按企业域名查找邮箱，作为官网公开联系方式的补充',
        'free_offer': '免费套餐每月 50 credits', 'requires_card': False,
        'website_url': 'https://hunter.io', 'key_url': 'https://hunter.io/api',
        'pricing_url': 'https://hunter.io/pricing',
        'key_steps': ['注册或登录 Hunter', '进入 Account → API，创建或复制 API Key', '保存后在搜索页勾选 Hunter 邮箱补全'],
        'cost_hint': '不同套餐按邮箱或域名扣额度；找到多个邮箱可能消耗多份额度，不保证每家公司都有邮箱。',
    },
}

BLOCKED_HOSTS = {'google.com','bing.com','youtube.com','facebook.com','linkedin.com','alibaba.com','made-in-china.com','globalsources.com','wikipedia.org','amazon.com'}

def public_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None,80,443}:
        raise ValueError('网址不支持公开网页读取')
    addresses=socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('仅允许公开企业网站')
    return url

class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch_html(url):
    public_url(url)
    request=Request(url,headers={'User-Agent':'TophooCompanyResearch/1.0','Accept':'text/html'})
    with build_opener(PublicRedirect()).open(request,timeout=8) as response:
        final=response.geturl();public_url(final)
        if 'html' not in response.headers.get('Content-Type','').lower():raise ValueError('目标不是 HTML 企业网页')
        content=response.read(600001)
        if len(content)>600000:raise ValueError('网页过大，保留搜索结果待核实')
        return final,content.decode(response.headers.get_content_charset() or 'utf-8','replace')

def provider_json(url, key, provider, payload=None):
    headers={'Accept':'application/json'}
    if payload is not None:headers['Content-Type']='application/json'
    if provider in {'tavily','firecrawl'}:headers['Authorization']='Bearer '+key
    if provider=='exa':headers['x-api-key']=key
    if provider=='serper':headers.update({'X-API-KEY':key,'Content-Type':'application/json'})
    if provider=='brave':headers['X-Subscription-Token']=key
    request=Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
    try:
        with urlopen(request,timeout=20) as response:return json.loads(response.read(2000000))
    except Exception as error:
        # Never surface request URLs (Hunter embeds the API key in a query string).
        code=getattr(error,'code',None)
        reasons={401:'密钥无效或已过期',403:'账号没有接口权限或套餐未激活',402:'余额或额度不足',429:'触发频率或额度限制，请检查平台后台'}
        reason=reasons.get(code, f'平台返回 HTTP {code}，请稍后重试' if code else '网络超时或连接失败，请稍后重试')
        raise ValueError(PROVIDERS[provider]['name']+'：'+reason) from None

def search(provider,key,keyword,countries,types,industries,limit=20):
    countries=[next((name for name in COUNTRY_ALIASES.get(canonical(value,COUNTRY_ALIASES),()) if name.isascii() and len(name)>3),value) for value in countries]
    types=[canonical(value,TYPE_ALIASES) for value in types]
    groups=lambda values:'('+' OR '.join('"'+value.replace('"','')+'"' for value in values)+')' if values else ''
    query=' '.join(filter(None,[groups(terms(keyword)),groups(countries),groups(types) or '(company OR distributor OR importer OR contractor OR supplier)',groups(industries),'-site:wikipedia.org -site:wikihow.com -filetype:pdf']))
    if len(query)>590:raise ValueError('搜索条件过长，请精简关键词或国家数量')
    if provider not in PROVIDERS or PROVIDERS[provider]['kind'] != 'search':
        raise ValueError('该平台不是搜索渠道')
    if provider == 'tavily':
        data = provider_json('https://api.tavily.com/search', key, provider, {
            'query': query, 'search_depth': 'basic', 'max_results': limit,
            'include_answer': False, 'include_raw_content': False, 'auto_parameters': False,
        })
        results = data.get('results')
        snippet = 'content'
    elif provider == 'exa':
        data = provider_json('https://api.exa.ai/search', key, provider, {
            'query': query, 'type': 'fast', 'category': 'company', 'numResults': limit,
        })
        results = data.get('results')
        snippet = 'text'
    elif provider == 'firecrawl':
        data = provider_json('https://api.firecrawl.dev/v2/search', key, provider, {
            'query': query, 'limit': limit, 'sources': ['web'], 'timeout': 15000, 'domainTools': False,
        })
        if data.get('success') is False:
            raise ValueError('Firecrawl 搜索失败，请检查连接、额度或稍后重试')
        results = data.get('data', {}).get('web')
        snippet = 'description'
    elif provider == 'serper':
        data = provider_json('https://google.serper.dev/search', key, provider, {'q': query, 'num': limit})
        results = data.get('organic')
        snippet = 'snippet'
    else:
        data = provider_json('https://api.search.brave.com/res/v1/web/search?' + urlencode({
            'q': query, 'count': limit, 'extra_snippets': 'true',
        }), key, provider)
        results = data.get('web', {}).get('results')
        snippet = 'description'
    if data.get('error'):
        raise ValueError(PROVIDERS[provider]['name']+' 搜索失败，请检查连接、额度或稍后重试')
    if not isinstance(results,list):
        raise ValueError(PROVIDERS[provider]['name']+' 响应格式不符合搜索接口，请检查套餐或接口权限')
    # Result count caps are not a promise of verified companies or buying intent.
    return [{
        'company_name': str(row.get('title') or '待核实企业')[:260],
        'website': row.get('url') or row.get('link'),
        'description': str(row.get(snippet) or '')[:5000],
        'source_url': row.get('url') or row.get('link'),
    } for row in results if row.get('url') or row.get('link')][:limit]

class CompanyHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.text=[];self.links=[];self.json=[];self.script=None;self.buffer=[];self.skip=0;self.site_name='';self.emails=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {'script','style','noscript'}:
            self.skip+=1
            if tag=='script' and attrs.get('type','').lower()=='application/ld+json':self.script=True;self.buffer=[]
        if tag=='meta' and attrs.get('property','').lower()=='og:site_name':self.site_name=attrs.get('content','')
        if tag=='a':
            href=attrs.get('href','');self.links.append(href)
            if href.lower().startswith('mailto:'):self.emails.append(href[7:].split('?')[0])
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'}:
            if self.script and tag=='script':
                try:self.json.append(json.loads(''.join(self.buffer)))
                except (ValueError,TypeError):pass
                self.script=None
            self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if self.script:self.buffer.append(data)
        if not self.skip:self.text.append(data)

def organizations(value):
    if isinstance(value,list):
        for entry in value:yield from organizations(entry)
    elif isinstance(value,dict):
        types=value.get('@type',[]);types=[types] if isinstance(types,str) else types
        if any(item in {'Organization','Corporation','LocalBusiness','Store','ProfessionalService','HVACBusiness','ManufacturingBusiness'} for item in types):yield value
        if '@graph' in value:yield from organizations(value['@graph'])

def inspect_company(row, reader=fetch_html):
    result=dict(row);evidence={'source_url':row.get('source_url') or row.get('website'),'pages':[],'identity_verified':False,'facts':[],'warnings':[]}
    from app.services.acquisition_results import non_company_reason
    evidence['search_title']=row.get('company_name') or ''
    result['evidence']=evidence
    reason=non_company_reason(evidence['source_url'])
    if reason:
        evidence['warnings'].append(reason);return result
    try:
        website=row.get('website') or '';parsed=urlsplit(website);host=(parsed.hostname or '').lower().removeprefix('www.')
        if not host or any(host==blocked or host.endswith('.'+blocked) for blocked in BLOCKED_HOSTS):
            evidence['warnings'].append('平台或目录页面，尚未识别企业官网');return result
        homepage=f'{parsed.scheme}://{parsed.netloc}/'
        final,html=reader(homepage);parser=CompanyHTML();parser.feed(html);evidence['pages'].append(final)
        alltext=[' '.join(parser.text)];emails=list(parser.emails)
        orgs=list(organizations(parser.json));organization=next((org for org in orgs if org.get('name') and str(org['name']).strip().lower() not in {'admin','administrator','wordpress','home','website','unknown'}),None)
        if organization:
            result['company_name']=str(organization['name'])[:260];evidence['identity_verified']=True;evidence['facts'].append('企业名称来自官网结构化 Organization 信息')
            address=organization.get('address') or {};address=address[0] if isinstance(address,list) and address else address
            if isinstance(address,dict):
                country=address.get('addressCountry');country=country.get('name') if isinstance(country,dict) else country
                if country:result['country']=str(country)[:120];evidence['facts'].append('国家来自官网企业地址')
                location=', '.join(str(address[key]) for key in ('streetAddress','addressLocality','addressRegion','postalCode') if address.get(key) and isinstance(address[key],(str,int)))
                if location:result['company_address']=location[:500]
            phone=organization.get('telephone')
            if phone:result['phone']=str(phone)[:80]
            email=organization.get('email')
            if email:emails.insert(0,str(email).removeprefix('mailto:'))
        elif parser.site_name:
            result['company_name']=parser.site_name[:260];evidence['facts'].append('企业名称来自官网站点名称，仍需核实企业身份')
        contact=next((urljoin(final,link) for link in parser.links if re.search(r'contact|kontakt|about',link,re.I) and urlsplit(urljoin(final,link)).hostname==urlsplit(final).hostname),None)
        if contact and contact!=final:
            try:
                contact_url,contact_html=reader(contact);other=CompanyHTML();other.feed(contact_html);evidence['pages'].append(contact_url);emails.extend(other.emails);alltext.append(' '.join(other.text))
            except Exception:evidence['warnings'].append('联系页面读取失败')
        text=' '.join(alltext);result['qualification_text']=text[:5000];result['description']=str(row.get('description') or '')[:1200]
        valid=list(dict.fromkeys(email.lower() for email in emails if re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',email) and not email.lower().endswith(('.png','.jpg','.webp'))))[:100]
        if valid:
            result['email']=valid[0][:260]
            result['contacts']=[{'email':email[:260],'phone':result.get('phone') if index==0 else None,'is_primary':index==0} for index,email in enumerate(valid)]
            evidence['facts'].append('邮箱来自官网公开信息（未验证投递）')
        hits=[kind for kind,aliases in TYPE_ALIASES.items() if any(contains(text.lower(),word) for word in (kind,*aliases))]
        if len(hits)==1:result['company_type']=hits[0];evidence['facts'].append('客户类型根据官网描述识别，需业务复核')
        result['website']=f'{urlsplit(final).scheme}://{urlsplit(final).netloc}/'
    except Exception:evidence['warnings'].append('官网读取失败，保留搜索结果待核实')
    return result

def enrich_email(row,key):
    result=dict(row);domain=urlsplit(row.get('website') or '').hostname
    if not domain:return result
    data=provider_json('https://api.hunter.io/v2/domain-search?'+urlencode({'domain':domain,'api_key':key,'limit':5}),key,'hunter')
    addresses=[item for item in data.get('data',{}).get('emails',[]) if re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',str(item.get('value') or '')) and (item.get('verification') or {}).get('status') not in {'invalid','disposable'}]
    ranked=sorted(addresses,key=lambda item:((item.get('verification') or {}).get('status')=='valid',item.get('confidence') or 0),reverse=True)
    if ranked:
        email=ranked[0];result['email']=email['value'][:260];result['contact_name']=' '.join(filter(None,[email.get('first_name'),email.get('last_name')]))[:160] or None
        result['contacts']=[{'email':item['value'][:260],'contact_name':' '.join(filter(None,[item.get('first_name'),item.get('last_name')]))[:160] or None,'is_primary':index==0} for index,item in enumerate(ranked)]
        result['evidence']['facts'].append('邮箱由 Hunter 补全')
        result['evidence']['email_status']=(email.get('verification') or {}).get('status') or '未验证'
    return result
