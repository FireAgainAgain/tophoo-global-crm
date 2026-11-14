from io import BytesIO
from openpyxl import load_workbook
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead, ProjectMember
from app.services.lead_list_excel import export_lead_list_excel, MIME
from tests.test_global_access import db, headers

COLUMN_NAMES = ['公司名称', '公司官网', '国家', '公司备注', '联系人信息', '跟进']


def values(sheet, row=2):
    return dict(zip([cell.value for cell in sheet[1]], [cell.value for cell in sheet[row]]))


def test_company_contacts_and_followup_columns_and_text_safety():
    notes = '公司备注第一行\n' + '长备注保留全文\n' * 40 + '最后一行'
    book=load_workbook(BytesIO(export_lead_list_excel([{
        'id':2,'company_name':'=HYPERLINK("http://example.test","company")','country':'德国',
        'workflow_status':'ready','is_manually_researched':True,'company_type':'manufacturer',
        'phone':'+99999999','notes':notes,
        'company_website':'https://www.example.test/products?a=1',
        'contacts':[{'contact_name':'Secondary','email':'secondary@example.test','phone':'+88888888'},
            {'contact_name':'Buyer','is_primary':True,'email':'buyer@example.test',
             'phone':'+0012345678','whatsapp':'00112233','notes':'Do not export person notes',
             'linkedin':'https://linkedin.com/in/buyer','facebook':'https://facebook.com/buyer',
             'instagram':'https://instagram.com/buyer','youtube':'https://youtube.com/@buyer'}],
        'followup':'第一行跟进\n第二行跟进',
        'outreach_draft':{'content':'Do not export draft'},
        'interactions':[{'content':'Do not export history'}],
    }, {'id':1,'company_name':'Second','contacts':[],'phone':'+000321',
        'company_website':'javascript://alert(1)'}], '国家：德国；排序：名称')))
    assert book.sheetnames==['线索列表']
    sheet=book.active
    assert sheet.max_column==6 and sheet.max_row==3
    assert [cell.value for cell in sheet[1]]==COLUMN_NAMES
    assert not sheet.merged_cells.ranges
    lead=values(sheet)
    assert lead['国家']=='德国' and values(sheet,3)['公司名称']=='Second'
    assert lead['公司备注']==notes
    assert lead['联系人信息']==(
        'Secondary\n邮箱：secondary@example.test\n电话：+88888888\n\n'
        'Buyer（主联系人）\n邮箱：buyer@example.test\n电话：+0012345678\nWhatsApp：00112233\n'
        'LinkedIn：https://linkedin.com/in/buyer\nFacebook：https://facebook.com/buyer\n'
        'Instagram：https://instagram.com/buyer\nYouTube：https://youtube.com/@buyer')
    assert lead['跟进']=='第一行跟进\n第二行跟进'
    assert values(sheet,3)['联系人信息'] is None and values(sheet,3)['跟进'] is None
    assert sheet['A2'].data_type=='s' and sheet['D2'].number_format=='@'
    assert sheet['B2'].value=='https://www.example.test/products?a=1'
    assert sheet['B2'].hyperlink.target==sheet['B2'].value
    assert sheet['B3'].hyperlink is None
    assert sheet.freeze_panes=='B2' and sheet.auto_filter.ref=='A1:F3'
    assert sheet.sheet_view.showGridLines is False
    assert sheet['A1'].fill.fgColor.rgb.endswith('19724D')
    assert sheet.row_dimensions[2].height==sheet.row_dimensions[3].height==48
    assert all(sheet[f'{column}2'].alignment.wrap_text for column in 'DEF')
    assert book.properties.description=='国家：德国；排序：名称'
    assert all(c.data_type!='f' for row in sheet for c in row)
    assert not any('Do not export' in str(c.value) for row in sheet for c in row)


def test_empty_export_and_blank_company_fields_keep_all_columns():
    empty=load_workbook(BytesIO(export_lead_list_excel([]))).active
    assert empty.max_row==1 and empty.max_column==6
    assert empty.auto_filter.ref=='A1:F1'
    sheet=load_workbook(BytesIO(export_lead_list_excel([{
        'company_name':'Example','email':'somebody-else@example.test','phone':'+wrong',
        'contacts':[{'is_primary':True,'contact_name':'Primary','email':'','phone':''},
                    {'contact_name':'Secondary','email':'second@example.test','phone':'+second'}],
    }]))).active
    assert values(sheet)=={'公司名称':'Example','公司官网':None,'国家':None,'公司备注':None,
                          '联系人信息':'Primary（主联系人）\n\nSecondary\n邮箱：second@example.test\n电话：+second',
                          '跟进':None}
    assert sheet.auto_filter.ref=='A1:F2'


def test_excel_readonly_route_and_pdf_entry_removed(db):
    client=TestClient(app)
    member=db.query(ProjectMember).filter_by(site_project_id=1,user_id=2).one()
    member.permissions_json='["leads"]'
    # Respect an explicitly read-only project member.
    member.role='readonly'
    db.add(Lead(id=1,site_project_id=1,owner_user_id=2,company_name='Readonly export',
                contact_name='Legacy buyer', phone='+0012300'))
    db.commit()
    url='/api/customer-workflow/projects/1/leads/export/xlsx'
    result=client.post(url,headers=headers(2),json={'ids':[1]})
    assert result.status_code==200,result.text
    assert result.headers['content-type']==MIME
    assert '.xlsx' in result.headers['content-disposition']
    sheet = load_workbook(BytesIO(result.content))['线索列表']
    assert [cell.value for cell in sheet[1]] == COLUMN_NAMES
    assert sheet['A2'].value == 'Readonly export'
    assert sheet['E2'].value == 'Legacy buyer（主联系人）\n电话：+0012300'
    assert sheet.row_dimensions[2].height == 48
    assert db.get(Lead,1).workflow_status=='unviewed'
    assert not any(getattr(route,'path','').endswith('/leads/export/pdf') for route in app.routes)
