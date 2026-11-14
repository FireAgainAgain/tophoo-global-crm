"""Bounded public-site research. Website content is data, never instructions."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

AGENT = 'TophooContactResearch'
EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])')
PHONE = re.compile(r'(?<!\w)(?:\+|00)\d[\d ()\-.]{6,24}\d(?!\w)')
RELEVANT = re.compile(r'contact|kontakt|team|people|staff|management|leadership|about|career|jobs|vacanc|recruit|purchas|procure|news|联系我们|团队|招聘|采购', re.I)
SHARED = re.compile(r'^(info|hello|contact|sales|support|office|admin|service|hr|career|jobs|purchasing|procurement)[._-]?$', re.I)
ROLE = re.compile(r'manager|director|engineer|president|officer|procure|purchas|sourcing|sales|ceo|cto|cfo|chef|经理|总监|工程师|采购', re.I)


def website_url(value):
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    parts = urlsplit(value)
    try:
        valid = parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password and parts.port in (None, 80, 443)
        host = parts.hostname.encode('idna').decode('ascii')
    except (ValueError, AttributeError, UnicodeError):
        raise ValueError('请输入有效的公司官网地址。') from None
    if not valid or any(c.isspace() for c in value) or len(value) > 500:
        raise ValueError('请输入公开的 HTTP 或 HTTPS 公司官网地址。')
    return urlunsplit((parts.scheme, host + (':' + str(parts.port) if parts.port else ''), parts.path or '/', parts.query, ''))


def same_site(url, root):
    try:
        return urlsplit(url).scheme in ('http', 'https') and urlsplit(url).hostname.lower().removeprefix('www.') == urlsplit(root).hostname.lower().removeprefix('www.')
    except (ValueError, AttributeError):
        return False


def public_addresses(host, port):
    values = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not values or any(not ipaddress.ip_address(value[4][0]).is_global for value in values):
        raise ValueError('只能扫描公开公司网站，不能访问本机或内网地址。')
    return values


def fetch_public(url, root, limit=2_000_000):
    """Pin the validated IP to the socket, preserving TLS hostname verification."""
    for _ in range(4):
        url = website_url(url)
        if not same_site(url, root):
            raise ValueError('跳转到了其他网站，已跳过。')
        p = urlsplit(url)
        port = p.port or (443 if p.scheme == 'https' else 80)
        addresses = public_addresses(p.hostname, port)
        family, socktype, protocol, _, address = addresses[0]
        connection = http.client.HTTPConnection(p.hostname, port, timeout=5)
        sock = socket.socket(family, socktype, protocol)
        try:
            sock.settimeout(5)
            sock.connect(address)
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname) if p.scheme == 'https' else sock
            connection.request('GET', urlunsplit(('', '', p.path or '/', p.query, '')), headers={'User-Agent': AGENT + '/1.0', 'Accept': 'text/html,application/pdf,text/plain,application/xml', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('网站跳转缺少目标地址。')
                url = urljoin(url, location)
                continue
            if response.status >= 400:
                raise ValueError(f'网站返回 HTTP {response.status}')
            content = response.read(limit + 1)
            if len(content) > limit:
                raise ValueError('页面或文件过大，已跳过。')
            return url, response.getheader('Content-Type', ''), content
        finally:
            connection.close()
            sock.close()
    raise ValueError('网站跳转次数过多。')


def phone_value(value):
    value = unquote(str(value)).split('?')[0].strip().removeprefix('tel:')
    digits = re.sub(r'\D', '', value)
    if not 7 <= len(digits) <= 15:
        return ''
    return ('+' if value.startswith(('+', '00')) else '') + (digits[2:] if value.startswith('00') else digits)


def email_values(value):
    return [email.lower() for email in EMAIL.findall(unquote(str(value))) if not email.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.css', '.js'))]


def key_name(value):
    return re.sub(r'[^\w]', '', value.casefold())


def person_name(value):
    value = ' '.join(value.split())
    return value if 3 <= len(value) <= 80 and 2 <= len(value.split()) <= 5 and not RELEVANT.search(value) and not ROLE.search(value) and '@' not in value and not re.search(r'\d|[/:|]', value) else ''


def extract_html(html, source, known_names=()):
    soup = BeautifulSoup(html, 'html.parser')
    results = []

    def add(email='', phone='', name='', title='', evidence='', kind='', whatsapp=''):
        email = next(iter(email_values(email)), '')
        phone = phone_value(phone) if phone else ''
        whatsapp = phone_value(whatsapp) if whatsapp else ''
        if not (email or phone or whatsapp):
            return
        if email and SHARED.fullmatch(email.split('@')[0]):
            name, title = '', ''
        results.append({'contact_name': name[:160], 'title': title[:160], 'email': email, 'phone': phone, 'whatsapp': whatsapp, 'phone_kind': kind or ('公开电话，类型待核实' if phone else ''), 'source_url': source, 'evidence': ' '.join(evidence.split())[:350], 'verification': '公开披露，未验证有效性'})

    def walk(data):
        if isinstance(data, list):
            for item in data:
                walk(item)
        elif isinstance(data, dict):
            types = data.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if 'Person' in types and isinstance(data.get('name'), str):
                # Person JSON-LD provides an explicit association; no page-wide pairing.
                email, telephone = data.get('email'), data.get('telephone')
                add(email if isinstance(email, str) else '', telephone if isinstance(telephone, str) else '', data['name'], str(data.get('jobTitle') or ''), json.dumps({k: data[k] for k in ('name', 'jobTitle', 'email', 'telephone') if k in data}, ensure_ascii=False))
            for item in data.values():
                if isinstance(item, (list, dict)):
                    walk(item)

    for script in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            walk(json.loads(script.get_text()))
        except (ValueError, TypeError, RecursionError):
            pass
    for tag in soup(['script', 'style', 'noscript', 'svg']):
        tag.decompose()

    for link in soup.select('a[href]'):
        href = link.get('href', '')
        whatsapp = ''
        if urlsplit(urljoin(source, href)).hostname in ('wa.me', 'api.whatsapp.com'):
            from urllib.parse import parse_qs
            whatsapp = urlsplit(href).path.strip('/') if 'wa.me' in href else parse_qs(urlsplit(href).query).get('phone', [''])[0]
            if whatsapp and whatsapp[0].isdigit():
                whatsapp = '+' + whatsapp
        is_email = href.lower().startswith('mailto:')
        is_phone = href.lower().startswith('tel:')
        if not (is_email or is_phone or whatsapp):
            continue
        email = next(iter(email_values(href[7:].split('?')[0])), '') if is_email else ''
        phone = href[4:] if is_phone else ''
        name = title = ''
        evidence = link.get_text(' ', strip=True) + ' ' + href
        # Only a small enclosing contact card with one unique email can identify a person.
        for parent in list(link.parents)[:4]:
            text = parent.get_text(' ', strip=True)
            emails = set(email_values(text)) | {v for a in parent.select('a[href^="mailto:"]') for v in email_values(a['href'])}
            phones = {phone_value(a['href'][4:]) for a in parent.select('a[href^="tel:"]')}
            if len(text) > 600 or len(emails) > 1 or len(phones) > 1 or parent.name in ('body', 'html', 'footer', 'nav'):
                break
            matches = [n for n in known_names if n and re.search(r'(?<!\w)' + re.escape(n) + r'(?!\w)', text, re.I)]
            headings = [h.get_text(' ', strip=True) for h in parent.select('h2,h3,h4,strong,[itemprop="name"]')]
            candidates = list(dict.fromkeys(matches or [person_name(h) for h in headings if person_name(h)]))
            if len(candidates) == 1 and (emails or phone):
                name = candidates[0]
                title = next((h for h in headings if h != name and ROLE.search(h)), '')
                if not email and len(emails) == 1:
                    email = next(iter(emails))
                if not phone and len(phones) == 1:
                    phone = next(iter(phones))
                evidence = text
                break
        add(email, phone, name, title, evidence, whatsapp=whatsapp)

    # Plain-text emails and international numbers remain unassigned company contacts.
    text = soup.get_text(' ', strip=True)
    assigned_emails = {r['email'] for r in results if r['email']}
    assigned_phones = {r['phone'] for r in results if r['phone']}
    for match in EMAIL.finditer(text):
        if match.group().lower() not in assigned_emails:
            add(match.group(), evidence=text[max(0, match.start()-80):match.end()+80])
    for match in PHONE.finditer(text):
        value = phone_value(match.group())
        if value and value not in assigned_phones:
            add(phone=value, evidence=text[max(0, match.start()-60):match.end()+60], kind='公司公开电话，归属及类型待核实')
    links = [urljoin(source, a.get('href', '')) for a in soup.select('a[href]')]
    return results, links


def pdf_contacts(content, source):
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(content))
    results = []
    for index, page in enumerate(reader.pages[:12]):
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 4_000_000:
            continue
        text = (page.extract_text() or '')[:100_000]
        for email in set(email_values(text)):
            offset = text.lower().find(email)
            results.append({'contact_name': '', 'title': '', 'email': email, 'phone': '', 'whatsapp': '', 'phone_kind': '', 'source_url': source + f'#page={index+1}', 'evidence': ' '.join(text[max(0,offset-100):offset+len(email)+100].split()), 'verification': 'PDF公开披露，姓名归属待核实；未验证有效性'})
        for match in PHONE.finditer(text):
            phone = phone_value(match.group())
            if phone:
                results.append({'contact_name':'', 'title':'', 'email':'', 'phone':phone, 'whatsapp':'', 'phone_kind':'PDF公开电话，归属及类型待核实', 'source_url':source + f'#page={index+1}', 'evidence':' '.join(text[max(0,match.start()-80):match.end()+80].split()), 'verification':'PDF公开披露，未验证有效性'})
    return results[:100]


def read_pdf_contacts(content, source):
    """Isolate public PDF parsing so one malformed document cannot stall a worker."""
    process = subprocess.run([sys.executable, '-m', 'app.services.lead_contact_pdf', source], input=content, capture_output=True, timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode or len(process.stdout) > 500_000:
        raise ValueError('无法读取该PDF。')
    return json.loads(process.stdout.decode('utf-8'))


def consolidate(rows):
    result = {}
    for row in rows:
        key = ('email', row['email']) if row['email'] else ('phone', re.sub(r'\D','',row['phone'] or row['whatsapp']))
        old = result.get(key)
        if old:
            if old['contact_name'] and row['contact_name'] and key_name(old['contact_name']) != key_name(row['contact_name']):
                old.update(contact_name='', title='', verification='多人共用或归属冲突，需人工核实')
                old['_conflict'] = True
            elif not old.get('_conflict') and row['contact_name'] and not old['contact_name']:
                result[key] = {**row, 'sources': old['sources']}
                old = result[key]
            for field in ('phone', 'whatsapp'):
                if row[field] and old[field] and row[field] != old[field]:
                    old['verification'] += '；存在不同号码，请查看来源'
                elif row[field] and not old[field] and not old.get('_conflict'):
                    old[field] = row[field]
                    if field == 'phone':
                        old['phone_kind'] = row['phone_kind']
            if row['source_url'] not in old['sources']:
                old['sources'].append(row['source_url'])
        else:
            result[key] = {**row, 'sources': [row['source_url']]}
    items = list(result.values())[:100]
    for index, row in enumerate(items):
        row.pop('_conflict', None)
        row['id'] = str(index+1)
    return items


def scan_site(website, names=(), progress=lambda value: None, reader=fetch_public):
    website = website_url(website)
    origin = urlunsplit((*urlsplit(website)[:2], '/', '', ''))
    robot = RobotFileParser()
    warnings, pages, rows, visited = [], [], [], set()
    started = time.monotonic()
    try:
        _, _, content = reader(urljoin(origin, 'robots.txt'), website, 100_000)
        robot.parse(content.decode('utf-8', 'replace').splitlines())
    except ValueError as error:
        if 'HTTP 404' not in str(error):
            raise ValueError('无法确认网站的公开访问规则，请稍后重试。') from None
        robot.parse([])
    queue = [website]
    try:
        sitemap = urljoin(origin, 'sitemap.xml')
        if robot.can_fetch(AGENT, sitemap):
            _, _, content = reader(sitemap, website, 500_000)
            xml = ET.fromstring(content)
            queue.extend(node.text.strip() for parent in xml if parent.tag.rsplit('}',1)[-1]=='url' for node in parent if node.tag.rsplit('}',1)[-1]=='loc' and node.text and RELEVANT.search(node.text) and same_site(node.text.strip(), website))
    except Exception:
        pass
    while queue and len(visited) < 24 and time.monotonic() - started < 80:
        url = queue.pop(0).split('#')[0]
        if url in visited or not same_site(url, website) or (urlsplit(url).query and url != website) or not robot.can_fetch(AGENT, url):
            continue
        visited.add(url)
        progress({'scanned': len(pages), 'attempted': len(visited), 'found': len(consolidate(rows)), 'current_url': url})
        try:
            final, kind, content = reader(url, website)
            if not robot.can_fetch(AGENT, final):
                continue
            if 'pdf' in kind or urlsplit(final).path.lower().endswith('.pdf'):
                if sum(p['kind'] == 'pdf' for p in pages) >= 3:
                    continue
                rows.extend(read_pdf_contacts(content, final))
                pages.append({'url': final, 'kind': 'pdf'})
            elif 'html' in kind:
                html = content.decode('utf-8', 'replace')
                encoding = re.search(br'charset=["\s]*([A-Za-z0-9_-]+)', content[:3000])
                if encoding:
                    try:
                        html = content.decode(encoding[1].decode(), 'replace')
                    except LookupError:
                        pass
                contacts, links = extract_html(html, final, names)
                rows.extend(contacts)
                pages.append({'url': final, 'kind': 'html'})
                candidates = [link for link in links if same_site(link, website) and RELEVANT.search(link) and link not in visited]
                queue.extend(sorted(set(candidates), key=lambda link: (0 if re.search(r'contact|team|people|staff|kontakt', link, re.I) else 1, len(link)))[:60])
                queue = list(dict.fromkeys(queue))[:150]
            else:
                warnings.append('跳过不支持的文件：' + final)
        except Exception:
            warnings.append('未能读取：' + url)
        time.sleep(.15)
    if not pages:
        raise ValueError('没有可读取的公开页面；网站可能限制访问、需要登录或暂时不可用。')
    items = consolidate(rows)
    if queue:
        warnings.append('已达到本次扫描的页面或时间上限，可补充具体页面网址再次扫描。')
    if not items:
        warnings.append('本次读取的页面未找到公开联系方式；这不代表该公司没有联系人。')
    return {'items': items, 'pages': pages, 'warnings': warnings[:30], 'scanned_at': datetime.now().isoformat(), 'scope': '仅官网公开资料，不含付费数据库；邮箱和电话未验证可用性。'}


def candidate_matches(row, people):
    """Exact channels establish an existing contact; a shared name is only a hint."""
    matches = []
    for index, person in enumerate(people):
        reasons = []
        if row.get('email') and row['email'].strip().casefold() == person.get('email','').strip().casefold():
            reasons.append('邮箱相同')
        for field, label in (('phone','电话相同'),('whatsapp','WhatsApp 相同')):
            number = phone_value(row.get(field,''))
            if number and number == phone_value(person.get(field,'')):
                reasons.append(label)
        if reasons:
            matches.append({'index':index,'kind':'existing','reasons':reasons})
        elif row.get('contact_name') and key_name(row['contact_name']) == key_name(person.get('contact_name','')):
            matches.append({'index':index,'kind':'possible','reasons':['姓名相同，待核对']})
    return matches


def merge_candidates(people, items, choices, scanned_at):
    """Apply explicit choices atomically; never overwrite a conflicting value."""
    from copy import deepcopy
    result, conflicts, applied = deepcopy(people), [], []
    for choice in choices:
        row = next((r for r in items if r['id'] == choice['candidate_id']), None)
        if not row:
            raise ValueError('所选结果不存在，请重新读取扫描结果。')
        target = choice.get('target_index')
        if target is not None and not 0 <= target < len(people):
            raise ValueError('目标联系人已变更，请重新选择。')
        email_match = [i for i,p in enumerate(result) if row['email'] and p.get('email','').casefold() == row['email'].casefold()]
        name_match = [i for i,p in enumerate(result) if row['contact_name'] and key_name(p.get('contact_name','')) == key_name(row['contact_name'])]
        if email_match:
            if target is not None and target != email_match[0]:
                conflicts.append({'candidate_id': row['id'], 'message': '该邮箱已属于另一位联系人。'})
                continue
            target = email_match[0]
        elif target is None and len(name_match) == 1:
            target = name_match[0]
        if target is None:
            phone_match = [i for i,p in enumerate(result) if (row['phone'] and phone_value(p.get('phone','')) == row['phone']) or (row['whatsapp'] and phone_value(p.get('whatsapp','')) == row['whatsapp'])]
            if phone_match:
                if len(phone_match) != 1 or (row['contact_name'] and result[phone_match[0]].get('contact_name') and key_name(row['contact_name']) != key_name(result[phone_match[0]]['contact_name'])):
                    conflicts.append({'candidate_id': row['id'], 'message': '号码已被其他联系人使用，请人工核对归属。'})
                    continue
                target = phone_match[0]
        person = result[target] if target is not None else {'contact_name':'', 'email':'', 'phone':'', 'whatsapp':'', 'notes':'', 'is_primary':not result}
        differences = [field for field in ('email','phone','whatsapp') if row[field] and person.get(field) and (person[field].casefold() != row[field].casefold() if field=='email' else phone_value(person[field]) != phone_value(row[field]))]
        if row['contact_name'] and person.get('contact_name') and key_name(row['contact_name']) != key_name(person['contact_name']):
            differences.append('姓名')
        # Unassigned company numbers/shared mailboxes must not silently become personal contacts.
        if not row['contact_name'] and person.get('contact_name') and target is not None and not email_match:
            differences.append('联系方式未明确对应此人')
        if differences:
            conflicts.append({'candidate_id': row['id'], 'message': '、'.join(differences) + '与已有资料冲突或归属不明；请在联系人编辑中核对。'})
            continue
        for field in ('contact_name','email','phone','whatsapp'):
            if not person.get(field) and row[field]:
                person[field] = row[field]
        # Research evidence stays in the scan result, never in contact notes.
        if target is None:
            result.append(person)
        applied.append(row['id'])
    if conflicts:
        return people, conflicts, []
    if len(result) > 100:
        raise ValueError('每家公司最多100位联系人，请减少本次选择。')
    return result, [], applied
