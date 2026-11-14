// Customer detail design regression; all APIs use local fixtures, no real writes.
const {chromium}=require('playwright'), assert=require('node:assert/strict'), fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
  const html=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
  await context.route('**/__customer_detail_layout',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="utf-8">${css}</head><body>${html}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script><script src="/static/js/contact-records.js"></script><script src="/static/js/follow-up.js"></script><script src="/static/js/lead-development.js"></script></body></html>`}));
  const customer={id:301,company_name:'Northstar Climate Solutions',country:'德国',company_type:'distributor',grade:'A',company_website:'https://climate.example.test',company_address:'Industriestraße 18, Hamburg',company_linkedin:'https://linkedin.com/company/climate-example',customer_source:'行业展会',source_type:'自主开发',owner_name:'张经理',owner_user_id:4,notes:'关注工业空气处理设备，下一步确认换热工况与安装尺寸。',created_at:'2026-10-01T08:00:00',updated_at:'2026-10-15T10:30:00',contacts:[{id:1,contact_name:'Emma Wilson',email:'emma@climate.example.test',phone:'+49 40 123456',whatsapp:'+49 40 123456',linkedin:'https://linkedin.com/in/emma-example',notes:'采购负责人，优先邮件沟通。',is_primary:true},{id:2,contact_name:'Thomas Becker',email:'thomas@climate.example.test',notes:'技术联系人，负责确认图纸。',is_primary:false}]};
  const plan={id:1,title:'确认入口水温和风量参数',customer_id:301,contact_name:'Thomas Becker',owner_name:'张经理',status:'pending',due_at:'2026-10-20T06:00:00Z',notes:'确认工况后安排选型。'};
  let writes=0;
  await context.route('**/api/**',r=>{
   const request=r.request(),url=new URL(request.url()),p=url.pathname;
   if(!['GET','HEAD'].includes(request.method())){writes++;return r.fulfill({status:418,json:{detail:'Read-only fixture'}});}
   if(p.endsWith('/conversion-history'))return r.fulfill({json:{items:[]}});
   if(p.endsWith('/records'))return r.fulfill({json:{records:[{id:1,direction:'inbound',occurred_at:'2026-10-15T09:20:00',contact_name:'Emma Wilson',channel:'邮件',content:'Please share your coil selection sheet and dimensional drawing. We will confirm the operating conditions this week.',content_translation:'请提供盘管选型表和尺寸图，本周确认运行工况。'}]}});
   if(p.endsWith('/context'))return r.fulfill({json:{company_name:customer.company_name,people:customer.contacts.map(x=>({id:x.id,name:x.contact_name})),owners:[{id:4,name:'张经理'}],current_user_id:4,can_write:true}});
   if(p.startsWith('/api/followups/'))return r.fulfill({json:{items:[plan],total:1,can_write:true,is_top_admin:true,counts:{pending:1,today:0,overdue:0,future:1,completed:0,cancelled:0}}});
   if(p.startsWith('/api/contacts/'))return r.fulfill({json:{customers:[customer],is_top_admin:true,owners:[{id:4,name:'张经理'}]}});
   return r.fulfill({json:{items:[]}});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8002/__customer_detail_layout');
  await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'contacts'}})));
  await page.locator('[data-detail="301"]').click();
  const detail=page.locator('[data-workflow-detail]');
  assert.equal(await detail.locator('[data-detail-records], .followup-customer').count(),0);
  assert.deepEqual(await detail.locator('[data-detail-actions] button').allTextContents(),['编辑','放入公池']);
  const management=detail.locator('[data-detail-management]');
  assert.equal(await management.locator('h3').innerText(),'客户管理');
  assert.equal(await management.getByText('行业展会',{exact:true}).count(),0);
  assert.equal(await management.getByText('自主开发',{exact:true}).count(),1);
  assert.equal(await management.getByText('来源详情',{exact:true}).count(),0);

  assert.equal(await page.locator('[data-workflow-row="301"] .action-followups .workflow-activity-count').count(),0);
  assert.equal(await detail.locator('[data-detail-company] .profile-fields').count(),0);
  assert.equal(await detail.locator('[data-detail-company]').getByText('emma@climate.example.test',{exact:true}).count(),0,'Company details do not duplicate contact information');
  assert.equal(await detail.locator('.profile-person').count(),2);
  assert.equal(await detail.locator('.profile-fields small').filter({hasText:'WhatsApp'}).count(),1,'Empty optional contact fields are omitted');
  assert.equal(await detail.locator('[data-detail-company] dd').filter({hasText:'—'}).count(),0);
  await detail.locator('[data-detail-main]').click();
  await page.locator('[data-action-dialog]').waitFor({state:'visible'});
  await page.locator('[data-action-cancel]').last().click();
  assert.equal(await detail.isVisible(),true,'Cancelling release preserves the customer detail');
  assert.equal(await detail.locator('[data-detail-company] a[href="https://linkedin.com/company/climate-example"]').innerText(),'LinkedIn ↗');
  assert.equal(await detail.locator('[data-detail-company]').getByText(customer.notes,{exact:true}).count(),1);assert.equal(await detail.locator('[data-detail-notes]').getByText(customer.notes,{exact:true}).count(),1);
  const titles=await detail.locator('[data-detail-content]>section>header h3,[data-detail-content]>section>.people-panel-heading h2').allTextContents();assert.ok(titles.length>=3);
  fs.mkdirSync('output/ui',{recursive:true});
  for(const theme of ['green','purple']){
   await page.evaluate(theme=>document.documentElement.dataset.uiTheme=theme,theme);
   await page.screenshot({path:`output/ui/customer-detail-${theme}.png`,fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile page does not overflow');
  const footer=await detail.locator('[data-detail-actions]').boundingBox();assert.ok(footer.y+footer.height<=845);
  assert.ok(await detail.locator('[data-detail-edit]').isVisible());
  await page.screenshot({path:'output/ui/customer-detail-mobile.png',fullPage:true});
  assert.equal(writes,0);assert.deepEqual(errors,[]);
  console.log('PASS: customer detail actions, compact follow-up button, contacts, social links, themes and mobile. No writes.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
