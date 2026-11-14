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
 const make=data=>({due_at:data.due_date?new Date(data.due_date+'T00:00:00+08:00').toISOString():new Date().toISOString(),...data,id:nextId++,customer_id:301,company_name:customer.company_name,owner_name:'测试用户',contact_name:data.person_id===2?'Bob':'Alice',status:'pending',is_overdue:Date.parse(data.due_at)<Date.now()});
 if(path.endsWith('/complete')){task.status='completed';task.result=data.result;records.push({id:records.length+1,occurred_at:data.occurred_at,channel:data.channel,content:data.result});if(data.next_plan)tasks.push(make(data.next_plan));return r.fulfill({json:task});}
 if(path.endsWith('/cancel')){task.status='cancelled';task.cancellation_reason=data.reason;return r.fulfill({json:task});}
 if(method==='PUT'){Object.assign(tasks.find(x=>x.id===id),data);return r.fulfill({json:tasks.find(x=>x.id===id)});}
 const created=make(data);tasks.push(created);return r.fulfill({status:201,json:created});
 }
 if(path.startsWith('/api/contacts/')){
  assert.equal(method,'GET');if(path.endsWith('/records'))return r.fulfill({json:{records}});
  customer.activity_counts={followups:tasks.filter(x=>x.status==='pending').length,rfqs:0,quotations:0};customer.next_followup=tasks.filter(x=>x.status==='pending').sort((a,b)=>a.due_at.localeCompare(b.due_at))[0]||null;
  return r.fulfill({json:{customers:[customer],is_top_admin:true,owners:[{id:4,name:'测试用户'}]}});
 }
 return r.fulfill({status:418,json:{detail:'Unexpected request blocked'}});
});

const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8002/__followup_ui');
await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'contacts'}})));
const row=page.locator('[data-workflow-row="301"]');await row.waitFor();await row.locator('[data-followup-open]').click();
const editor=page.locator('[data-followup-dialog]'),queue=page.locator('[data-followup-queue]');
await queue.locator('[data-fu-queue-add]').waitFor({state:'visible'});
assert.equal(await queue.locator('[data-fu-tabs],[data-fu-scope]').count(),0);
await queue.locator('[data-fu-queue-add]').click();await editor.waitFor({state:'visible'});
assert.equal(await editor.locator('input,select,textarea').count(),2);
await editor.locator('[name="due_date"]').fill('2099-12-20');await editor.locator('[name="title"]').fill('确认工况参数，然后跟进报价反馈');failSave=true;
await editor.locator('[type="submit"]').click();await editor.locator('[data-fu-error]').filter({hasText:'模拟保存失败'}).waitFor();
assert.equal(await editor.locator('[name="title"]').inputValue(),'确认工况参数，然后跟进报价反馈');
failSave=false;await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});
await queue.locator('[data-fu-edit="1"]').waitFor();
assert.deepEqual(writes[1].data,{title:'确认工况参数，然后跟进报价反馈',due_date:'2099-12-20'});
await page.waitForFunction(()=>document.querySelector('[data-followup-open="301"] .workflow-activity-count').textContent==='1');
assert.equal(await row.locator('[data-followup-open]').getAttribute('data-activity-state'),'future');
assert.match(await queue.innerText(),/未到期 · 2099-12-20/);assert.equal(await queue.locator('.is-future').count(),1);
await queue.locator('[data-fu-edit="1"]').click();await editor.waitFor({state:'visible'});assert.equal(await editor.locator('[name=due_date]').inputValue(),'2099-12-20');
await editor.locator('[name="title"]').fill('确认客户回复');await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});
await queue.locator('[data-fu-queue-rows]').filter({hasText:'确认客户回复'}).waitFor();
assert(!/逾期|跟进时间|负责人|已完成|已取消|补充说明/.test(await queue.innerText()));
fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/simple-followup-desktop.png',fullPage:true});
failSave=true;await queue.locator('[data-fu-complete="1"]').click();await page.locator('[data-workflow-toast]').filter({hasText:'模拟删除失败'}).waitFor();
assert.equal(tasks.length,1);assert.equal(await editor.isVisible(),false);
failSave=false;await queue.locator('[data-fu-complete="1"]').click();await queue.locator('[data-fu-queue-rows]').filter({hasText:'暂无待跟进事项'}).waitFor();
await page.waitForFunction(()=>document.querySelector('[data-followup-open="301"] .workflow-activity-count').textContent==='0');
assert.equal(await row.locator('[data-followup-open]').getAttribute('data-activity-state'),'empty');
assert.equal(tasks.length,0);assert.equal(records.length,0);assert(!writes.some(x=>x.path.endsWith('/complete')));
await queue.locator('[data-fu-queue-add]').click();await editor.waitFor({state:'visible'});await editor.locator('[name="title"]').fill('稍后联系客户');
await editor.locator('[type="submit"]').click();await editor.waitFor({state:'hidden'});await queue.locator('[data-fu-delete="2"]').waitFor();
page.once('dialog',d=>d.accept());await queue.locator('[data-fu-delete="2"]').click();await queue.locator('[data-fu-queue-rows]').filter({hasText:'暂无待跟进事项'}).waitFor();
await page.setViewportSize({width:390,height:844});await queue.locator('[data-fu-queue-add]').click();await editor.waitFor({state:'visible'});
assert(await editor.evaluate(el=>el.getBoundingClientRect().width<=window.innerWidth));
await page.screenshot({path:'output/ui/simple-followup-mobile.png',fullPage:true});
await editor.locator('[data-fu-close]').first().click();await queue.locator('[data-fu-queue-close]').click();await page.locator('[data-followup-mine]').click();await queue.waitFor({state:'visible'});
assert.equal(await queue.locator('h2').innerText(),'我的跟进');assert.equal(await queue.locator('[data-fu-queue-add]').isVisible(),false);
assert.deepEqual(errors,[]);console.log('PASS: day-only date and content add/edit; retry retains content; complete deletes without result form; counts and colors refresh; delete; mobile; my followups');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
