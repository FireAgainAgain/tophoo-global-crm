const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:950}});
  const template=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
  const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
  const company={id:1,company_name:'分区检查设备公司',country:'德国',company_type:'manufacturer',company_website:'https://equipment.test',company_address:'Berlin',company_linkedin:'https://linkedin.com/company/equipment',notes:'公司需求说明',other_channels:'旧版主联系人备注',contact_name:'旧版主联系人',email:'legacy@equipment.test',phone:'111',created_at:'2026-10-01T12:00:00',updated_at:'2026-10-15T12:00:00',grade:'A',workflow_status:'ready',release_reason:'公池释放原因',released_at:'2026-10-10T12:00:00',released_by_name:'Release User',owner_name:'sam',contacts:[{id:101,contact_name:'主采购',email:'buyer@equipment.test',phone:'123',whatsapp:'456',notes:'采购联络说明',is_primary:true,linkedin:'https://linkedin.com/in/buyer'},{id:102,contact_name:'技术联系人',email:'engineer@equipment.test',notes:'技术联络说明',is_primary:false}]};
  const rows=[company,{id:2,company_name:'空白线索',contacts:[],created_at:'2026-10-02T12:00:00'},{id:3,company_name:'旧版联系人线索',email:'legacy-only@equipment.test',other_channels:'旧联系人渠道备注',created_at:'2026-10-03T12:00:00'},{id:4,company_name:'旧版空白线索',created_at:'2026-10-04T12:00:00'}];
  let admin=true,writes=0;
  await context.route('http://crm.test/**',route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN" data-ui-theme="green"><head><meta charset="UTF-8">${css}</head><body data-workspace="crm"><main class="main"><header class="crm-topbar">全局导航</header><div class="main-inner"><section id="page-crm" class="page active"><div id="global-crm-content">${template}</div></section></div></main><script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/company-types.js"></script><script src="/static/js/lead-development.js"></script><script src="/static/js/crm-customer-workflow.js"></script></body></html>`});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   if(url.pathname.startsWith('/api/')){
    if(route.request().method()!=='GET'){writes++;throw Error('This display test must not modify records');}
    if(/\/(records|interactions)$/.test(url.pathname))return route.fulfill({json:{records:[]}});
    if(url.pathname.endsWith('/conversion-history'))return route.fulfill({json:{items:[]}});
    return route.fulfill({json:{items:rows,customers:rows,is_top_admin:admin,owners:[]}});
   }
   return route.fulfill({status:404,body:''});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://crm.test/test');
  const activate=async view=>{await page.evaluate(view=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view}})),view);await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');};
  const open=async id=>{await page.locator(`[data-detail="${id}"]`).click();await page.locator('[data-detail-company]').waitFor();};
  const close=()=>page.locator('[data-detail-close]').last().click();
  const fields=()=>page.locator('[data-detail-company] dt,[data-detail-management] dt').allTextContents();
  await activate('leads');await open(1);
  assert.equal(await page.locator('[data-detail-company] h3').textContent(),'公司资料');
  assert.match(await page.locator('[data-detail-people] h2').textContent(),/联系人信息 · 2 位/);
  const labels=await fields();
  assert.deepEqual(await page.locator('[data-detail-content]>section').evaluateAll(els=>els.slice(0,4).map(el=>el.getAttribute('aria-label')|| (el.hasAttribute('data-detail-people')?'联系人信息':''))),['公司资料','联系人信息','来源与管理','公司备注']);
  for(const label of ['联系人','邮箱','电话','WhatsApp','客户分级','释放原因','释放日期','释放人','其它渠道'])assert.ok(!labels.includes(label),label+' must not be in lead company details');
  assert.ok(labels.includes('联系状态'));assert.equal(await page.locator('[data-detail-title]').textContent(),company.company_name);assert.equal(await page.locator('[data-detail-company] a[href="https://linkedin.com/company/equipment"]').count(),1);assert.match(await page.locator('[data-detail-management]').textContent(),/资料完整度/);
  const companyText=await page.locator('[data-detail-company]').textContent();assert.ok(!companyText.includes('公司需求说明'));assert.match(await page.locator('[data-detail-notes]').textContent(),/公司需求说明/);
  for(const value of ['采购联络说明','技术联络说明','旧版主联系人备注','buyer@equipment.test','legacy@equipment.test'])assert.ok(!companyText.includes(value));
  const people=page.locator('[data-detail-people]');assert.equal(await people.locator('.profile-person').count(),2);
  assert.equal(await people.locator('.person-primary-badge').count(),1);assert.match(await people.textContent(),/采购联络说明/);assert.match(await people.textContent(),/技术联络说明/);
  assert.equal(await people.locator('a[href="https://linkedin.com/in/buyer"]').count(),1);
  assert.equal(await page.locator('[data-detail-company] a[href="https://linkedin.com/in/buyer"]').count(),0);
  assert.ok((await page.locator('[data-detail-company]').boundingBox()).y<(await people.boundingBox()).y);
  assert.equal(await page.locator('[data-followup-customer]').count(),0);assert.equal(await page.locator('[data-customer-export]').count(),0);
  assert.equal(await people.locator('[data-person-new],[data-person-edit]').count(),0);
  assert.equal(await page.locator('[data-detail-delete]').isVisible(),false);await page.locator('[data-detail-more] summary').click();assert.equal(await page.locator('[data-detail-delete]').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await page.locator('[data-workflow-detail]').isVisible(),true);
  for(const theme of ['green','purple']){await page.evaluate(theme=>document.documentElement.dataset.uiTheme=theme,theme);await page.screenshot({path:`output/ui/lead-detail-sections-${theme}.png`,fullPage:true});}
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'output/ui/lead-detail-sections-mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:950});
  await page.locator('[data-detail-actions] [data-detail-edit="1"]').click();
  assert.equal(await page.locator('[data-workflow-form] [name="grade"]').count(),0);
  assert.equal(await page.locator('[data-workflow-form] [data-person-card]').count(),2);
  await page.locator('[data-workflow-close]').last().click();await close();
  await open(2);assert.match(await people.textContent(),/联系人信息 · 0 位/);assert.equal(await people.locator('.profile-person').count(),0);await close();
  await open(3);assert.equal(await people.locator('.profile-person').count(),1);assert.match(await people.textContent(),/旧联系人渠道备注/);assert.ok(!(await page.locator('[data-detail-company]').textContent()).includes('旧联系人渠道备注'));await close();
  await open(4);assert.equal(await people.locator('.profile-person').count(),0);await close();
  for(const view of ['contacts','customer-pool','prospecting']){
   await activate(view);await open(1);const labels=await fields();if(view==='contacts')assert.deepEqual(await page.locator('[data-detail-content]>section').evaluateAll(els=>els.slice(0,4).map(el=>el.getAttribute('aria-label')||(el.hasAttribute('data-detail-people')?'联系人信息':''))),['公司资料','联系人信息','来源与管理','公司备注']);
   assert.equal(labels.includes('客户分级'),view==='contacts'||view==='customer-pool');
   assert.equal(labels.includes('释放原因'),view==='customer-pool');assert.equal(labels.includes('当前状态'),false);
   assert.equal(await page.locator('[data-followup-customer]').count(),view==='contacts'?1:0);
   assert.equal(await page.locator('[data-customer-export]').count(),view==='contacts'?2:0);
   assert.equal(await people.locator('[data-person-new]').count(),view==='contacts'?1:0);
   assert.ok(!(await page.locator('[data-detail-company]').textContent()).includes('采购联络说明'));await close();
  }
  admin=false;await activate('leads');await open(1);assert.ok(!(await fields()).includes('归属'));
  assert.equal(writes,0);assert.deepEqual(errors,[]);
  console.log('PASS: company/person separation, no duplicated contacts or notes, view-specific fields/actions, both themes/mobile, multiple/empty/legacy contacts, editor and permission scope; zero writes.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
