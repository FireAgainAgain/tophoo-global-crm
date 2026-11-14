// All follow-up and customer traffic is mocked; no real business data changes.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
const html=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
await context.route('**/__followup_ui',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="UTF-8">${css}</head><body>${html}<script>localStorage.setItem('tophoo-global-selected-project','7');</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script><script src="/static/js/follow-up.js"></script><script src="/static/js/contact-records.js"></script></body></html>`}));
const customer={id:301,company_name:'暖通设备采购企业',contact_name:'Alice',email:'buyer@example.test',country:'德国',grade:'A',owner_user_id:4,owner_name:'测试用户',contacts:[{id:1,contact_name:'Alice',email:'buyer@example.test',is_primary:true}],created_at:'2026-10-01T00:00:00'};
let tasks=[],records=[],nextId=1,failSave=false,writes=[],reads=[];
await context.route('**/api/**',async r=>{
const req=r.request(),u=new URL(req.url()),path=u.pathname,method=req.method();if(method==='GET')reads.push({url:u.pathname+u.search,tasks:tasks.length});
if(path.startsWith('/api/followups/')){
 if(method==='GET'){
  if(path.endsWith('/context'))return r.fulfill({json:{company_name:customer.company_name,people:[{id:1,name:'Alice'},{id:2,name:'Bob'}],owners:[{id:4,name:'测试用户'}],current_user_id:4,can_write:true}});
  const now=Date.now(),start=new Date().setHours(0,0,0,0),end=start+86400000;
  const filters={pending:x=>x.status==='pending',today:x=>x.status==='pending'&&Date.parse(x.due_at)>=start&&Date.parse(x.due_at)<end,overdue:x=>x.status==='pending'&&Date.parse(x.due_at)<now,future:x=>x.status==='pending'&&Date.parse(x.due_at)>=end,completed:x=>x.status==='completed',cancelled:x=>x.status==='cancelled'};
  const counts=Object.fromEntries(Object.entries(filters).map(([key,filter])=>[key,tasks.filter(filter).length]));
  const bucket=u.searchParams.get('bucket')||'pending';return r.fulfill({json:{items:tasks.filter(filters[bucket]),counts,total:counts[bucket],is_top_admin:true,can_write:true}});
 }
 if(method==='DELETE'){
  writes.push({path,method});
  if(failSave)return r.fulfill({status:409,json:{detail:'模拟删除失败'}});
  const id=Number(path.split('/').at(-1));tasks=tasks.filter(x=>x.id!==id);
  return r.fulfill({json:{deleted:id}});
 }
 const data=req.postDataJSON();writes.push({path,method,data});
 if(failSave)return r.fulfill({status:409,json:{detail:'模拟保存失败，草稿保留'}});
 const id=Number(path.split('/').at(-1)),task=tasks.find(x=>x.id===Number(path.split('/').at(-2)));
 const make=data=>({...data,id:nextId++,customer_id:301,company_name:customer.company_name,owner_name:'测试用户',contact_name:data.person_id===2?'Bob':'Alice',status:'pending',is_overdue:Date.parse(data.due_at)<Date.now()});
 if(path.endsWith('/complete')){task.status='completed';task.result=data.result;records.push({id:records.length+1,occurred_at:data.occurred_at,channel:data.channel,content:data.result});if(data.next_plan)tasks.push(make(data.next_plan));return r.fulfill({json:task});}
 if(path.endsWith('/cancel')){task.status='cancelled';task.cancellation_reason=data.reason;return r.fulfill({json:task});}
 if(method==='PUT'){Object.assign(tasks.find(x=>x.id===id),data);return r.fulfill({json:tasks.find(x=>x.id===id)});}
 const created=make(data);tasks.push(created);return r.fulfill({status:201,json:created});
 }
 if(path.startsWith('/api/contacts/')){
  assert.equal(method,'GET');if(path.endsWith('/records'))return r.fulfill({json:{records}});
  customer.next_followup=tasks.filter(x=>x.status==='pending').sort((a,b)=>a.due_at.localeCompare(b.due_at))[0]||null;
  return r.fulfill({json:{customers:[customer],is_top_admin:true,owners:[{id:4,name:'测试用户'}]}});
 }
 return r.fulfill({status:418,json:{detail:'Unexpected request blocked'}});
});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8002/__followup_ui');
await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'contacts'}})));
await page.locator('[data-workflow-row="301"]').waitFor();assert.ok((await page.locator('[data-workflow-head]').innerText()).includes('下次跟进'));
await page.locator('[data-followup-open="301"]').click();assert.equal(await page.locator('[data-workflow-detail]').isVisible(),false);
const editor=page.locator('[data-followup-dialog]'),queue=page.locator('[data-followup-queue]');await queue.waitFor({state:'visible'});await queue.locator('[data-fu-queue-add]').waitFor();assert.equal(await editor.isVisible(),false);assert.equal(await queue.locator('h2').innerText(),'跟进管理');assert.equal(await queue.locator('header p').innerText(),customer.company_name);await queue.locator('[data-fu-queue-add]').click();await editor.waitFor({state:'visible'});
await editor.locator('[name="title"]').fill('确认工况参数');await editor.locator('[name="person_id"]').selectOption('2');failSave=true;
await editor.locator('[type="submit"]').click();await editor.locator('[data-fu-error]').filter({hasText:'模拟保存失败'}).waitFor();assert.equal(await editor.locator('[name="title"]').inputValue(),'确认工况参数');
failSave=false;await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});await page.locator('[data-workflow-row="301"]').filter({hasText:'确认工况参数'}).waitFor();assert.equal(await page.locator('[data-workflow-detail]').isVisible(),false);assert.ok(!reads.some(x=>x.url.endsWith('/records')));await queue.locator('[data-fu-edit="1"]').waitFor();assert.equal(await queue.isVisible(),true);assert.equal(await editor.isVisible(),false);await queue.locator('[data-fu-queue-close]').click();await page.locator('[data-followup-open="301"]').click();await queue.waitFor({state:'visible'});await queue.locator('[data-fu-edit="1"]').waitFor();assert.equal(await page.locator('[data-workflow-detail]').isVisible(),false);await queue.locator('[data-fu-queue-close]').click();await page.locator('[data-detail="301"]').first().click();await page.locator('[data-fu-complete="1"]').waitFor({timeout:5000}).catch(async error=>{console.log(JSON.stringify({errors,tasks,reads,text:await page.locator('[data-workflow-detail]').innerText()}));await page.screenshot({path:'output/ui/followup-debug.png',fullPage:true});throw error;});
assert.ok((await page.locator('[data-followup-customer="301"]').innerText()).includes('Bob'));await page.screenshot({path:'output/ui/follow-up-detail-compact.png',fullPage:true});assert.ok((await page.locator('[data-workflow-row="301"]').innerText()).includes('确认工况参数'));
await page.locator('[data-fu-edit="1"]').click();await editor.waitFor({state:'visible'});await editor.locator('[name="title"]').fill('确认入口水温');await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});await page.locator('[data-followup-customer]').filter({hasText:'确认入口水温'}).waitFor();
await page.locator('[data-fu-complete="1"]').click();await editor.waitFor({state:'visible'});await editor.locator('[name="result"]').fill('客户要求补充工况表');await editor.locator('[name="channel"]').fill('WhatsApp');await editor.locator('[name="has_next"]').check();await editor.locator('[name="next_title"]').fill('跟进工况表');await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});await page.locator('[data-followup-customer]').filter({hasText:'跟进工况表'}).waitFor();assert.equal(records.length,1);assert.ok((await page.locator('[data-detail-records]').innerText()).includes('客户要求补充工况表'));
await page.locator('[data-fu-cancel="2"]').click();await editor.waitFor({state:'visible'});await editor.locator('[name="reason"]').fill('客户暂缓采购');await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});assert.equal(records.length,1);
await page.locator('[data-fu-history]').click();await queue.waitFor({state:'visible'});await queue.locator('[data-fu-bucket="completed"]').click();await queue.locator('[data-fu-queue-rows]').filter({hasText:'客户要求补充工况表'}).waitFor();
fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/follow-up-desktop.png',fullPage:true});
await queue.locator('[data-fu-queue-close]').click();await page.locator('[data-detail-close]').last().click();await page.locator('[data-followup-mine]').click();await queue.locator('[data-fu-bucket="cancelled"]').click();await queue.locator('[data-fu-queue-rows]').filter({hasText:'客户暂缓采购'}).waitFor();
await queue.locator('[data-fu-customer="301"]').click();await page.locator('[data-fu-add="301"]').waitFor();await page.setViewportSize({width:390,height:844});await page.locator('[data-fu-add="301"]').click();await editor.waitFor({state:'visible'});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'output/ui/follow-up-mobile.png',fullPage:true});
await editor.locator('[name="title"]').fill('长说明操作按钮检查');
await editor.locator('[name="notes"]').fill('请先核实身份，再收集数量、用途、技术参数及图纸。'.repeat(12));
await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});
const section=page.locator('[data-followup-customer="301"]');
await section.locator('[data-fu-delete="3"]').waitFor();
await section.locator('.followup-notes summary').click();
for(const width of [1440,390]){
 await page.setViewportSize({width,height:width===390?844:1000});
 for(const name of ['complete','edit','cancel','delete']){
  const button=section.locator(`[data-fu-${name}="3"]`);await button.scrollIntoViewIfNeeded();
  const box=await button.boundingBox();assert.ok(box&&box.x>=0&&box.x+box.width<=width,`${name} fits width ${width}`);
  assert.ok(await button.isVisible());
 }
 assert.equal(await section.locator('.followup-more').count(),0);
 await page.screenshot({path:`output/ui/follow-up-actions-${width}.png`,fullPage:true});
}
// Dismissal makes no request; failure keeps the plan; success hard-deletes it.
const deletions=()=>writes.filter(x=>x.method==='DELETE').length;
const beforeDelete=deletions();page.once('dialog',d=>d.dismiss());
await section.locator('[data-fu-delete="3"]').click();assert.equal(deletions(),beforeDelete);
failSave=true;page.once('dialog',d=>d.accept());await section.locator('[data-fu-delete="3"]').click();
await page.locator('[data-workflow-toast]').filter({hasText:'模拟删除失败'}).waitFor();
assert.ok(tasks.some(x=>x.id===3));failSave=false;
page.once('dialog',d=>d.accept());await section.locator('[data-fu-delete="3"]').click();
await section.locator('.followup-empty-state').waitFor();assert.ok(!tasks.some(x=>x.id===3));
assert.equal(records.length,1);
await page.locator('[data-fu-history]').click();await queue.waitFor({state:'visible'});
await queue.locator('[data-fu-bucket="cancelled"]').click();
await queue.locator('[data-fu-delete="2"]').waitFor();page.once('dialog',d=>d.accept());
await queue.locator('[data-fu-delete="2"]').click();
await queue.locator('[data-fu-queue-rows]').filter({hasText:'暂无已取消计划'}).waitFor();
assert.ok(!tasks.some(x=>x.id===2));assert.equal(records.length,1);
await queue.locator('[data-fu-queue-close]').click();
await page.locator('[data-fu-add="301"]').click();await editor.waitFor({state:'visible'});
await editor.locator('[name="title"]').fill('未保存内容');page.once('dialog',d=>d.dismiss());await page.keyboard.press('Escape');assert.equal(await editor.isVisible(),true);assert.equal(await editor.locator('[name="title"]').inputValue(),'未保存内容');page.once('dialog',d=>d.accept());await page.keyboard.press('Escape');await editor.waitFor({state:'hidden'});
await page.locator('[data-fu-add="301"]').click();await editor.waitFor({state:'visible'});await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','8');window.dispatchEvent(new Event('tophoo-project-changed'));});await editor.waitFor({state:'hidden'});
assert.deepEqual(errors,[]);assert.ok(writes.every(x=>x.path.startsWith('/api/followups/projects/7')));console.log('PASS follow-up: customer entry, nearest task, multiple contacts, failed-save drafts, edit, completion into history with next task, cancellation, queues, mobile, unsaved guard and project switching. All writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
