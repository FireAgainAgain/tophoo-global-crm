// Isolated UI fixtures: no business data is read or written.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
(async()=>{
 const fixtureProcess=spawnSync('python',['-c',"import json; from app.services.communication import catalog,overview,place_from_key; print(json.dumps({'catalog':catalog(),'overview':overview(place_from_key('GB:Europe/London'),details=True)}))"],{encoding:'utf8'});
 assert.equal(fixtureProcess.status,0,fixtureProcess.stderr);const fixture=JSON.parse(fixtureProcess.stdout);
 const rfqTemplate=fs.readFileSync('app/templates/partials/crm_rfq.html','utf8').replace('data-crm-rfq hidden','data-crm-rfq');
 const communicationTemplate=fs.readFileSync('app/templates/partials/communication_assistant.html','utf8');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
  const row=(id,contact_id,contact_person_id=null)=>({id,number:'RFQ-TIME-'+id,status:'待处理',company_name:'London customer',contact_id,contact_person_id});
  await page.route('http://rfq-time.test/**',async route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   assert.equal(route.request().method(),'GET');
   if(p==='/')return route.fulfill({contentType:'text/html',body:`<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/css/workbench.css"><link rel="stylesheet" href="/static/css/rfq.css"><link rel="stylesheet" href="/static/css/communication-assistant.css"><script>localStorage.setItem('tophoo-global-selected-project','7')</script>${rfqTemplate}${communicationTemplate}<div data-workflow-detail hidden><div data-detail-company></div></div><script src="/static/js/communication-assistant.js"></script>`});
   if(p.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+p)});
   if(p.endsWith('/references'))return route.fulfill({json:{contacts:[],owners:[],is_top_admin:false}});
   if(p==='/api/rfqs/projects/7')return route.fulfill({json:[row(1,5),row(2,null),row(3,5,9)]});
   if(p.endsWith('/catalog'))return route.fulfill({json:fixture.catalog});
   if(p.endsWith('/preferences'))return route.fulfill({json:{favorites:[],overrides:{},home_timezone:'Asia/Shanghai'}});
   if(p.includes('/entities/')){requests.push(p+url.search);return route.fulfill({json:{people:[{key:'9',name:'Alice'}],person:url.searchParams.get('person')||'',company_name:'London customer',country_code:'GB',origin:'auto_country',can_edit:false,overview:fixture.overview}});}
   throw Error('Unexpected request '+p);
  });
  await page.goto('http://rfq-time.test/');
  await page.locator('[data-preview-rfq="1"]').click();const detail=page.locator('[data-rfq-preview]'),strip=detail.locator('[data-comm-inline]');
  await strip.locator('[data-comm-inline-zone]').waitFor();assert.match(await strip.innerText(),/伦敦/);
  const time=await strip.locator('[data-comm-inline-zone]').innerText();await page.waitForTimeout(1200);assert.notEqual(await strip.locator('[data-comm-inline-zone]').innerText(),time);
  await strip.locator('button').click();await page.locator('[data-comm-panel] .comm-big-clock').waitFor();await page.keyboard.press('Escape');await page.locator('[data-comm-panel]').waitFor({state:'hidden'});assert.ok(await detail.isVisible());
  await page.setViewportSize({width:390,height:844});assert.ok(await strip.evaluate(n=>n.scrollWidth<=n.clientWidth));await page.screenshot({path:'output/ui/rfq-time-mobile.png'});
  await page.locator('[data-rfq-preview] button[data-close-rfq-preview]').click();await page.locator('[data-preview-rfq="2"]').click();assert.match(await strip.innerText(),/请先.*关联客户/);assert.equal(await strip.locator('button').count(),0);
  await page.locator('[data-rfq-preview] button[data-close-rfq-preview]').click();await page.locator('[data-preview-rfq="3"]').click();await strip.locator('[data-comm-inline-zone]').waitFor();assert.ok(requests.every(p=>p.includes('/customers/5?person=')));assert.ok(requests.at(-1).endsWith('person=9'));assert.match(await strip.innerText(),/Alice/);
  await page.locator('[data-rfq-preview] button[data-close-rfq-preview]').click();
  await page.evaluate(()=>{document.querySelector('[data-workflow-detail]').hidden=false;document.dispatchEvent(new CustomEvent('tophoo-workflow-detail-ready',{detail:{view:'leads',id:201,project:7}}));});
  const lead=page.locator('[data-workflow-detail] [data-comm-inline]');await lead.locator('[data-comm-inline-zone]').waitFor();assert.ok(requests.at(-1).includes('/leads/201?'));
  await page.evaluate(()=>document.querySelector('[data-workflow-detail]').hidden=true);
  await page.locator('[data-preview-rfq="1"]').click();await strip.locator('[data-comm-inline-zone]').waitFor();await strip.locator('button').click();await page.locator('[data-comm-panel] .comm-big-clock').waitFor();assert.ok(requests.at(-1).endsWith('/customers/5?person='));
  assert.deepEqual(errors,[]);console.log('PASS RFQ time: shared live clock, schedule dialog, mobile, unlinked hint, RFQ contact schedule, lead/RFQ context isolation. All data mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
