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
  const complete={company_name:'完整设备公司',country:'德国',company_website:'https://equipment.test',company_address:'Berlin',email:'info@equipment.test',phone:'+49 123',contact_name:'Buyer',created_at:'2026-10-01T12:00:00',workflow_status:'unviewed'};
  const rows=[{...complete,id:1,local_clock:{timezone:'Europe/Berlin',city:'柏林'}},{...complete,id:2,company_name:'待补邮箱公司',email:'',created_at:'2026-10-02T12:00:00',local_clock:{timezone:null,hint:'待确认时区'}},
   {...complete,id:3,company_name:'多联系人公司',email:'',phone:'',contact_name:'',contacts:[{contact_name:'',email:'',phone:''},{contact_name:'Engineer',email:'engineer@equipment.test',phone:'+49 456'}]},
   {id:4,company_name:'仅有公司名称',country:'  ',email:' ',phone:'',contact_name:'  ',created_at:'2026-10-03T12:00:00'}];
  let writes=0;
  await context.route('http://crm.test/**',route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN" data-ui-theme="green"><head><meta charset="UTF-8">${css}</head><body data-workspace="crm"><main class="main"><header class="crm-topbar">全局导航</header><div class="main-inner"><section id="page-crm" class="page active"><div id="global-crm-content">${template}</div></section></div></main><script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script></body></html>`});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   if(url.pathname.startsWith('/api/')){
    if(route.request().method()!=='GET'){writes++;throw Error('Completeness must never write to the API');}
    return route.fulfill({json:{items:rows,customers:rows,is_top_admin:true,owners:[]}});
   }
   return route.fulfill({status:404,body:''});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.clock.install({time:new Date('2026-10-29T23:59:00Z')});
  await page.goto('http://crm.test/test');
  const activate=async view=>{await page.evaluate(view=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view}})),view);await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');};
  const root=page.locator('[data-customer-workflow]');
  const ids=()=>root.locator('[data-detail]').evaluateAll(nodes=>nodes.map(x=>+x.dataset.detail));
  const score=id=>root.locator(`[data-completeness-detail="${id}"] strong`).textContent();
  await activate('leads');await root.locator('[data-customer-filters-toggle]').click();
  assert.deepEqual((await root.locator('thead th').allTextContents()).slice(2,4),['当前状态','资料完整度']);
  assert.equal(await score(1),'100%');assert.equal(await score(2),'75%');assert.equal(await score(3),'100%');assert.equal(await score(4),'10%');
  assert.equal(await root.locator('[data-completeness-detail="2"]').getAttribute('title'),'缺少：邮箱');
  await root.locator('[data-completeness-detail="2"]').click();
  assert.equal(await page.locator('[data-action-title]').textContent(),'资料完整度 · 75%');
  assert.match(await page.locator('.workflow-completeness-breakdown').textContent(),/邮箱0 \/ 25 分 · 待补充/);
  await page.locator('[data-action-submit]').click();
  await root.locator('[data-filter-completeness]').selectOption('email');assert.deepEqual(await ids(),[4,2]);
  await root.locator('[data-filter-country]').fill('德国');assert.deepEqual(await ids(),[2]);
  await root.locator('[data-reset-filters]').click();
  await root.locator('[data-filter-completeness]').selectOption('phone');assert.deepEqual(await ids(),[4]);
  await root.locator('[data-filter-completeness]').selectOption('contact_name');assert.deepEqual(await ids(),[4]);
  await root.locator('[data-filter-completeness]').selectOption('complete');assert.deepEqual((await ids()).sort(),[1,3]);
  await root.locator('[data-filter-completeness]').selectOption('incomplete');assert.deepEqual(await ids(),[4,2]);
  await root.locator('[data-reset-filters]').click();
  await root.locator('[data-workflow-sort]').selectOption('completeness');assert.deepEqual(await ids(),[3,1,2,4]);
  assert.match(await root.locator('[data-sort-direction]').textContent(),/高到低/);
  await root.locator('[data-sort-direction]').click();assert.deepEqual(await ids(),[4,2,3,1]);
  await root.locator('[data-filter-completeness]').selectOption('email');
  for(const view of ['contacts','customer-pool','prospecting']){
   await activate(view);
   assert.equal(await root.locator('[data-completeness-filter]').isVisible(),false);
   assert.equal(await root.locator('[data-completeness-detail]').count(),0);
   assert.equal(await root.locator('[data-workflow-sort] option[value="completeness"]').count(),0);
   assert.equal((await ids()).length,4);
  }
  await activate('leads');assert.equal(await root.locator('[data-filter-completeness]').inputValue(),'email');
  assert.equal(await root.locator('[data-workflow-sort]').inputValue(),'completeness');assert.deepEqual(await ids(),[4,2]);
  await root.locator('[data-reset-filters]').click();
  rows[1].email='buyer@equipment.test';await activate('leads');assert.equal(await score(2),'100%');
  assert.deepEqual(await root.locator('thead th').allTextContents(),['','公司 / 联系人','当前状态','资料完整度','人工背调','开发信','国家 / 地区','当前时间']);
  assert.equal(await root.locator('.workflow-contact-cell').count(),0);
  assert.equal(await root.locator('[data-lead-clock="2"]').textContent(),'待确认时区');
  await page.clock.setSystemTime(new Date('2026-10-29T23:59:00Z'));
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  assert.equal(await root.locator('[data-lead-clock="1"] strong').textContent(),'00:59');
  await page.clock.fastForward(60_000);
  assert.equal(await root.locator('[data-lead-clock="1"] strong').textContent(),'01:00');
  assert.match(await root.locator('[data-lead-clock="1"] small').textContent(),/10\/30.*柏林/);
  for(const theme of ['green','purple']){
   await page.evaluate(theme=>document.documentElement.dataset.uiTheme=theme,theme);
   await page.screenshot({path:`output/ui/lead-completeness-${theme}.png`,fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.ok((await root.locator('.workflow-table-wrap').boundingBox()).height>100);
  await page.screenshot({path:'output/ui/lead-completeness-mobile.png',fullPage:true});
  assert.equal(writes,0);assert.deepEqual(errors,[]);
  console.log('PASS: weighted scores, secondary contacts, whitespace, missing fields, breakdown, combined filters, sort directions/ties, view isolation, memory/reset, automatic refresh, both themes and mobile; zero API writes.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
