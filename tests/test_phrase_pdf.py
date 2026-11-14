"""Complete exports respect project access and preserve plain-text content."""
from types import SimpleNamespace as N
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import ProjectMember
from app.services.communication_phrase_pdf import export_phrases_pdf
from tests.test_global_access import db, headers

BASE='/api/phrases/projects/1'


def test_all_export_scope_order_empty_and_readonly(db,monkeypatch):
    client=TestClient(app);owner=headers(1)
    category=client.post(BASE+'/categories',headers=owner,json={'name':'聊天/询价'}).json()['id']
    other=client.post(BASE+'/categories',headers=owner,json={'name':'其他'}).json()['id']
    url=BASE+'/export/pdf'
    assert client.get(url,headers=owner).status_code==400
    scene_ids=[client.post(BASE+'/scenes',headers=owner,json={'category_id':category,'name':name}).json()['id'] for name in ['收到询价','确认工况']]
    ids=[]
    for scene_id,text in [(None,'Unassigned'),(scene_ids[1],'Parameters'),(scene_ids[0],'Drawings')]:
        ids.append(client.post(BASE+'/items',headers=owner,json={'category_id':category,'scene_id':scene_id,'content':text,'translation':'中文对照'}).json()['id'])
    other_phrase=client.post(BASE+'/items',headers=owner,json={'category_id':other,'content':'Other category included'}).json()['id']
    client.put(BASE+'/scenes/order',headers=owner,json={'category_id':category,'ids':scene_ids[::-1]})
    captured={}
    def capture(categories,scenes,phrases):
        captured.update(categories=[c.id for c in categories],scenes=[s.id for s in scenes],phrases=[p.id for p in phrases])
        return b'%PDF-category-test'
    monkeypatch.setattr('app.services.communication_phrase_pdf.export_phrases_pdf',capture)
    assert client.get(url).status_code==401
    assert client.get(url,headers=headers(2)).status_code==403
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.permissions_json='["communication_phrases"]';member.write_permissions_json='[]';db.commit()
    response=client.get(url,headers=headers(2))
    assert response.status_code==200 and response.content==b'%PDF-category-test'
    assert response.headers['content-type']=='application/pdf'
    assert 'no-store' in response.headers['cache-control']
    filename=unquote(response.headers['content-disposition'])
    assert '全部内容_' in filename and filename.endswith('.pdf') and '/' not in filename
    assert captured=={'categories':[category,other],'scenes':scene_ids[::-1],'phrases':[other_phrase]+ids[::-1]}
    assert client.get('/api/phrases/projects/2/export/pdf',headers=owner).status_code==400
    assert client.get(BASE+'/categories/999999/export/pdf',headers=owner).status_code==404


def test_pdf_plain_text_empty_translation_and_multi_page_content(monkeypatch):
    from reportlab.platypus import Paragraph
    observed=[]
    original=Paragraph.__init__
    def record(self,text,*args,**kwargs):
        observed.append(text)
        original(self,text,*args,**kwargs)
    monkeypatch.setattr(Paragraph,'__init__',record)
    content=export_phrases_pdf([N(id=1,name='客户沟通 <分类>')],[N(id=4,category_id=1,name='技术 & 报价')],[
        N(category_id=1,scene_id=None,content='<script>raw & literal</script>\nSecond line',translation='请确认 <尺寸> & 数量。'),
        N(category_id=1,scene_id=4,content='Long text 0123456789. '*550,translation='中文说明。'*400),
        N(category_id=1,scene_id=4,content='No translation',translation=''),
    ])
    from io import BytesIO
    from pypdf import PdfReader
    reader=PdfReader(BytesIO(content))
    assert reader.page_mode=='/UseOutlines'
    assert reader.outline[0].title=='客户沟通 <分类>'
    def destinations(items):
        for item in items:
            if isinstance(item,list):yield from destinations(item)
            else:yield item
    marks=list(destinations(reader.outline))
    assert any(m.title=='技术 & 报价' for m in marks)
    assert any('No translation' in m.title for m in marks)
    assert all(0<=reader.get_destination_page_number(mark)<len(reader.pages) for mark in marks)
    assert len(reader.pages)>1
    assert content.startswith(b'%PDF-') and len(content)>20000
    assert any('&lt;script&gt;raw &amp; literal&lt;/script&gt;<br/>Second line'==text for text in observed)
    assert any('未分场景' in text for text in observed)
    assert any('技术 &amp; 报价' in text for text in observed)
    assert any(text=='No translation' for text in observed)


def test_pdf_preserves_emoji_in_text_and_keeps_outline():
    from io import BytesIO
    from pypdf import PdfReader
    content=export_phrases_pdf([N(id=1,name='沟通')],[],[
        N(category_id=1,scene_id=None,content='Please contact me. 😊',translation='请联系我。')])
    reader=PdfReader(BytesIO(content))
    assert 'Please contact me. 😊' in reader.pages[0].extract_text()
    assert reader.page_mode=='/UseOutlines'
    assert reader.outline[0].title=='沟通'
