"""Allow only inert email markup and inline styles; never fetch remote resources."""
import base64
import re
from html import escape
from html.parser import HTMLParser

TAGS = set('p div span br hr strong b em i u s strike a img table thead tbody tfoot tr td th ul ol li blockquote h1 h2 h3 h4 font'.split())
VOID = {'br', 'hr', 'img'}
STYLES = set('color background-color font-family font-size font-weight font-style text-decoration text-align vertical-align width height max-width min-width border border-top border-bottom border-left border-right border-collapse border-spacing border-radius padding padding-left padding-right padding-top padding-bottom margin margin-left margin-right margin-top margin-bottom line-height white-space'.split())
IMAGE = re.compile(r'^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=\s]+)$', re.I)

def safe_image(value):
    match = IMAGE.fullmatch(value)
    if not match:
        return value.startswith('https://') and not any(c in value for c in '\r\n<>')
    try:
        data = base64.b64decode(match[2], validate=True)
        return len(data) <= 1024 * 1024 and (
            (match[1].lower() == 'png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or
            (match[1].lower() == 'jpeg' and data.startswith(b'\xff\xd8\xff')) or
            (match[1].lower() == 'gif' and data.startswith((b'GIF87a', b'GIF89a'))) or
            (match[1].lower() == 'webp' and data.startswith(b'RIFF') and data[8:12] == b'WEBP'))
    except ValueError:
        return False

class MailHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output=[]
        self.blocked=0
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style','iframe','object','svg','math','template'}:
            self.blocked += 1
        if self.blocked or tag not in TAGS:return
        kept=[]
        for key,value in attrs:
            value=value or ''
            if key=='style':
                declarations=[]
                for declaration in value.split(';'):
                    name,sep,item=declaration.partition(':')
                    if sep and name.strip().lower() in STYLES and not re.search(r'url|expression|@|[<>\\]',item,re.I):
                        declarations.append(name.strip().lower()+':'+item.strip())
                value=';'.join(declarations)
            elif tag=='a' and key=='href':
                if not re.match(r'^(https?://|mailto:|tel:)',value,re.I):continue
            elif tag=='img' and key=='src':
                if not safe_image(value):continue
            elif key not in {'alt','title','width','height','colspan','rowspan','cellpadding','cellspacing','border','align','valign','color','face','size'}:continue
            kept.append(f' {key}="{escape(value,quote=True)}"')
        self.output.append('<'+tag+''.join(kept)+'>')
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in {'script','style','iframe','object','svg','math','template'}:
            self.blocked=max(0,self.blocked-1)
            return
        if not self.blocked and tag in TAGS and tag not in VOID:self.output.append('</'+tag+'>')
    def handle_data(self,data):
        if not self.blocked:self.output.append(escape(data))

def clean_mail_html(value):
    parser=MailHTML();parser.feed(value);parser.close()
    return ''.join(parser.output)

def embed_mail_images(value):
    images=[]
    def replace(match):
        data=IMAGE.fullmatch(match[1])
        if not data:return match[0]
        cid=f'tophoo-inline-{len(images)+1}'
        images.append((cid,data[1].lower(),base64.b64decode(data[2])))
        return f'src="cid:{cid}"'
    return re.sub(r'src="(data:image/[^\"]+)"',replace,clean_mail_html(value)),images
