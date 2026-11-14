const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('node:fs');const {spawnSync}=require('node:child_process');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');const content=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
await context.route('**/__workflow_ui',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="UTF-8">${css}</head><body>${content}<button class="global-nav-item" data-test-nav>测试导航</button><script>localStorage.setItem('tophoo-global-selected-project','7');</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script><script src="/static/js/lead-development.js"></script><script src="/static/js/customer-workflow-form-defaults.js"></script><script src="/static/js/contact-records.js"></script></body></html>`}));
const records=Array.from({length:60},(_,i)=>({id:i+1,company_type:i%3===0?'manufacturer':i%3===1?'distributor':'',country:i%2?'德国':'美国',contact_name:'Alice '+i,email:`person${i}@example.com`,phone:`1380000${String(i).padStart(4,'0')}`,company_website:'https://audit.example.com',customer_source:i%2?'官网':'MIC',owner_name:'测试负责人',owner_user_id:4,grade:i%2?'B':'A',product_match:['A','B','C','D'][i%4],release_reason:'长期没有回复',released_at:'2026-10-01T12:00:00',released_by_name:'测试管理员',created_at:new Date(Date.UTC(2026,9,1,12)-i*86400000).toISOString(),added_at:new Date(Date.UTC(2026,9,1,12)-i*86400000).toISOString(),updated_at:'2026-10-07T12:00:00',company_name:'公司 '+i}));
['C','D','E','D','E',''].forEach((grade,index)=>records[54+index].grade=grade);
let lists={leads:records.map(x=>({...x,id:x.id+100})),contacts:records.map(x=>({...x,id:x.id+300})),pool:records.map(x=>({...x,id:x.id+500}))},writes=[],slow=false,release,seen,failRestore=false,failSave=false,failExport=false;
await context.route('**/api/**',async r=>{const req=r.request(),u=new URL(req.url());if(!u.pathname.startsWith('/api/customer-workflow/')&&!u.pathname.startsWith('/api/contacts/'))return ['GET','HEAD'].includes(req.method())?r.continue():r.fulfill({status:418,json:{detail:'Real business writes blocked'}});const parts=u.pathname.split('/'),kind=parts[2]==='contacts'?'contacts':parts[5],id=+(parts[2]==='contacts'?parts[5]:parts[6]);
if(req.method()==='GET'){
 if(u.pathname.endsWith('/development'))return r.fulfill({json:{development:{stage:'todo',priority:'normal',tags:[],next_followup_date:null},records:[]}});
 if(u.pathname.endsWith('/conversion-history'))return r.fulfill({json:{items:[]}});
 if(u.pathname.endsWith('/records'))return r.fulfill({json:{contact:{name:'Alice',company_name:'公司 0'},records:[{id:1,occurred_at:'2026-09-01',channel:'邮件',content:'旧记录'},{id:2,occurred_at:'2026-10-07',channel:'WhatsApp',content:'最新记录'}]}});
 if(u.pathname.endsWith('/preview'))return r.fulfill({json:lists.contacts.find(x=>x.id===id)});
 if(failExport&&(u.pathname.endsWith('/export/md')||u.pathname.endsWith('/export/pdf')))return r.fulfill({status:500,json:{detail:'模拟导出失败'}});
 if(u.pathname.endsWith('/export/md')||u.pathname.endsWith('/export/pdf'))return r.fulfill({contentType:u.pathname.endsWith('/md')?'text/markdown':'application/pdf',body:lists.contacts.find(x=>x.id===id).company_name});
 if(slow&&kind==='leads'){seen();await new Promise(resolve=>release=resolve);}
 return r.fulfill({json:{items:(u.pathname.includes('/projects/8/')||u.pathname.endsWith('/projects/8'))?[{...records[0],id:999,company_name:'另一个项目'}]:(lists[kind]||[]),is_top_admin:true,owners:[{id:4,name:'测试负责人'},{id:5,name:'另一负责人'}]}});
}
if(req.postData())assert.ok((req.headers()['content-type']||'').includes('application/json'),'Workflow writes must send JSON with the correct content type');const data=req.postData()?req.postDataJSON():{};writes.push({url:u.pathname,method:req.method(),data});
if(u.pathname.endsWith('/product-match')){const item=lists.contacts.find(x=>x.id===id);item.product_match=data.product_match;writes.push({url:u.pathname,method:req.method(),data});return r.fulfill({json:item});}
if(u.pathname.endsWith('/grade')){if(failSave)return r.fulfill({status:403,json:{detail:'没有修改权限'}});const item=lists.contacts.find(x=>x.id===id);Object.assign(item,{grade:data.grade||''});return r.fulfill({json:item});}
if(u.pathname.endsWith('/batch/conversion-preview'))return r.fulfill({json:{can_convert:true,items:data.ids.map(id=>({id,company_name:lists.leads.find(x=>x.id===id)?.company_name||'',mode:'created'}))}});
if(u.pathname.includes('/people')){
 if(failSave)return r.fulfill({status:409,json:{detail:'模拟保存失败'}});
 const item=lists.contacts.find(x=>x.id===id),personId=Number(parts[7]);item.contacts=item.contacts||[{id:id*100+1,contact_name:item.contact_name,email:item.email,phone:item.phone,whatsapp:item.whatsapp,notes:item.other_channels||'',is_primary:true}];
 if(req.method()==='DELETE'){const person=item.contacts.find(x=>x.id===personId);item.contacts=item.contacts.filter(x=>x.id!==personId);if(person.is_primary&&item.contacts.length){const replacement=Number(u.searchParams.get('replacement_id'));item.contacts.forEach(x=>x.is_primary=x.id===replacement);}}
 else if(u.pathname.endsWith('/primary'))item.contacts.forEach(x=>x.is_primary=x.id===personId);
 else if(req.method()==='POST'){const primary=data.is_primary||!item.contacts.length;if(primary)item.contacts.forEach(x=>x.is_primary=false);item.contacts.push({...data,id:Math.max(id*100,...item.contacts.map(x=>x.id))+1,is_primary:primary});}
 else{const person=item.contacts.find(x=>x.id===personId),primary=data.is_primary||person.is_primary;if(primary)item.contacts.forEach(x=>x.is_primary=false);Object.assign(person,data,{is_primary:primary});}
 const primary=item.contacts.find(x=>x.is_primary)||{};Object.assign(item,{contact_name:primary.contact_name||'',email:primary.email||'',phone:primary.phone||'',whatsapp:primary.whatsapp||'',other_channels:primary.notes||'',updated_at:'2026-10-09T13:00:00'});return r.fulfill({status:req.method()==='POST'&&!u.pathname.endsWith('/primary')?201:200,json:item});
}
if(req.method()==='PUT'){if(failSave)return r.fulfill({status:409,json:{detail:'模拟保存失败'}});const item=lists[kind].find(x=>x.id===id);Object.assign(item,data,{updated_at:'2026-10-09T12:34:00'});if(data.contacts){item.contacts=data.contacts.map((person,index)=>({...person,id:person.id||id*100+index+1}));const primary=item.contacts.find(person=>person.is_primary)||{};Object.assign(item,{contact_name:primary.contact_name,email:primary.email,phone:primary.phone,whatsapp:primary.whatsapp,other_channels:primary.notes});}return r.fulfill({json:lists[kind].find(x=>x.id===id)});}
if(u.pathname.endsWith('/release')){const x=lists.contacts.find(x=>x.id===id);lists.contacts=lists.contacts.filter(x=>x.id!==id);lists.pool.unshift({...x,release_reason:data.reason});}
else if(u.pathname.endsWith('/restore')){if(failRestore&&id===502)return r.fulfill({status:409,json:{detail:'模拟恢复冲突'}});const x=lists.pool.find(x=>x.id===id);lists.pool=lists.pool.filter(x=>x.id!==id);lists.contacts.unshift({...x,owner_user_id:data.owner_user_id||x.owner_user_id});}
else if(u.pathname.endsWith('/batch/delete'))lists[kind]=lists[kind].filter(x=>!data.ids.includes(x.id));
else if(u.pathname.endsWith('/to-customers')){const selected=lists.leads.filter(x=>data.ids.includes(x.id));lists.leads=lists.leads.filter(x=>!data.ids.includes(x.id));lists.contacts.push(...selected);}
else return r.fulfill({status:418,json:{detail:'Unsupported fixture write'}});
return r.fulfill({json:{ok:true}});
});

const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8002/__workflow_ui');
await context.route('**/api/contacts/projects/7/*/product-match',async r=>{const id=Number(new URL(r.request().url()).pathname.split('/').at(-2));const item=lists.contacts.find(x=>x.id===id);item.product_match=r.request().postDataJSON().product_match;return r.fulfill({json:item});});
const root=page.locator('[data-customer-workflow]');await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'contacts'}})));await root.locator('[data-customer-grade]').first().waitFor({timeout:5000}).catch(async error=>{console.log({errors,html:(await root.innerHTML()).slice(-4000)});throw error;});
await root.locator('[data-page-size]').selectOption('100');
const grades=()=>root.locator('[data-customer-grade]').evaluateAll(els=>els.map(el=>el.value));
await root.locator('[data-sort-added]').click();
await root.locator('[data-sort-grade]').click();
assert.equal((await grades())[0],'A');assert.equal((await grades()).at(-1),'');
assert.equal(await root.locator('[data-sort-grade]').locator('..').getAttribute('aria-sort'),'ascending');
await root.locator('[data-sort-grade]').click();
assert.equal((await grades())[0],'E');assert.equal((await grades()).at(-1),'');
assert.equal(await root.locator('[data-sort-grade]').locator('..').getAttribute('aria-sort'),'descending');
assert.equal(await root.locator('[data-sort-added]').locator('..').getAttribute('aria-sort'),'none');
assert.deepEqual(writes,[],'Sorting must never update customer records');

const matchField=()=>root.locator('[data-customer-match="301"]');
assert.deepEqual(await matchField().locator('option').allTextContents(),['未评估','A · 对口','B · 小对口','C · 配件','D · 不对口']);
await root.locator('[data-sort-product-match]').click();
assert.equal(await root.locator('[data-customer-match]').first().inputValue(),'A');
await root.locator('[data-sort-product-match]').click();
assert.equal(await root.locator('[data-customer-match]').first().inputValue(),'D');
await matchField().selectOption('C');
await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');
assert.equal(await matchField().inputValue(),'C');assert.equal(lists.contacts[0].grade,'A');
const field=()=>root.locator('[data-customer-grade="301"]');
assert.deepEqual(await field().locator('option').allTextContents(),['未分级 · 待评估','A · 订单客户','B · 样单客户','C · 重潜客户','D · 普潜客户','E · 无潜客户']);
const idle=()=>page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');
await field().selectOption('B');await idle();assert.equal(await field().inputValue(),'B');
assert.deepEqual(writes.at(-1).data,{grade:'B'});assert.equal(writes.at(-1).method,'PATCH');assert.ok(writes.at(-1).url.endsWith('/301/grade'));
assert.equal(lists.contacts.find(x=>x.id===301).email,'person0@example.com');
failSave=true;await field().selectOption('E');await idle();assert.equal(await field().inputValue(),'B');assert.ok((await page.locator('[data-workflow-toast]').innerText()).includes('没有修改权限'));failSave=false;
await field().selectOption('');await idle();assert.equal(lists.contacts.find(x=>x.id===301).grade,'');assert.equal(await field().inputValue(),''); // Ungraded remains selectable after sorting.
if(await root.locator('[data-customer-filters-toggle]').getAttribute('aria-expanded')==='false')await root.locator('[data-customer-filters-toggle]').click();
await root.locator('[data-filter-grade]').selectOption('none');await idle();await field().waitFor();
await field().selectOption('E');await idle();assert.equal(await field().count(),0);assert.equal(lists.contacts.find(x=>x.id===301).grade,'E');
await root.locator('[data-filter-grade]').selectOption('E');await field().waitFor();assert.equal(await field().inputValue(),'E');
assert.equal(await page.locator('[data-workflow-dialog]').isVisible(),false);
await root.locator('[data-filter-grade]').selectOption('');await root.locator('[data-filter-product-match]').selectOption('C');assert.ok((await root.locator('[data-customer-match]').evaluateAll(els=>els.map(el=>el.value))).every(x=>x==='C'));await root.locator('[data-filter-product-match]').selectOption('');await page.screenshot({path:'output/ui/customer-classification-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:844});await page.screenshot({path:'output/ui/customer-classification-mobile.png'});
assert.deepEqual(errors,[]);console.log('PASS: independent product match A-D and customer grade A-E, both header sorts, filters, inline clear, PATCH only grade, failed save rollback, sorting/filter refresh and no edit dialog. All writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
