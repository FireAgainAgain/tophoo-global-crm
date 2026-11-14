// Lead and customer record edits use identical controls; all writes are mocked.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join(''),template=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
 await context.route('**/__lead_records_ui',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="UTF-8">${css}</head><body>${template}<script>localStorage.setItem('tophoo-global-selected-project','7');</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script><script src="/static/js/lead-development.js"></script><script src="/static/js/contact-records.js"></script></body></html>`}));
 let leads=[{id:1,company_name:'AHU Equipment',contact_name:'Buyer',country:'Germany',contacts:[{contact_name:'Buyer',email:'buyer@example.test',is_primary:true}],created_at:'2026-08-01',workflow_status:'unviewed'}],customers=[],records=[],customerRecords=[],histories=[],fail=false,writes=0;
 await context.route('**/api/**',r=>{const req=r.request(),path=new URL(req.url()).pathname,method=req.method(),data=req.postData()?req.postDataJSON():{};
  if(path.endsWith('/conversion-history'))return r.fulfill({json:{items:histories}});
  if(/\/(interactions|records)(\/\d+)?$/.test(path)){
   const target=path.includes('/leads/')?records:customerRecords;
   if(method==='GET')return r.fulfill({json:{contact:{company_name:'AHU Equipment',name:'Buyer'},records:target}});
   if(fail)return r.fulfill({status:403,json:{detail:'无修改权限'}});
   writes++;
   if(method==='POST'){target.push({direction:'outbound',id:target.length+1,created_at:'2026-10-14T09:00:00',updated_at:'2026-10-14T09:00:00',...data});if(leads[0])leads[0].workflow_status=data.direction==='inbound'?'replied':'contacted';return r.fulfill({status:201,json:target.at(-1)});}
   const id=Number(path.split('/').at(-1)),item=target.find(x=>x.id===id);
   if(method==='PUT'){Object.assign(item,data);return r.fulfill({json:item});}
   target.splice(target.indexOf(item),1);return r.fulfill({json:{deleted:true}});
  }
  if(path.endsWith('/batch/conversion-preview'))return r.fulfill({json:{can_convert:true,items:[{company_name:'AHU Equipment',mode:'created'}]}});
  if(path.endsWith('/to-customers')){writes++;customerRecords=records.map(x=>({...x}));histories=[{source_lead_id:1,mode:'created',converted_at:'2026-10-14T12:00:00',snapshot:{company_name:'AHU Equipment',notes:'Original company note',created_at:'2026-08-01',contacts:leads[0].contacts,interactions:records.map(x=>({...x}))}}];customers=[{...leads[0],id:100,grade:'A'}];leads=[];return r.fulfill({json:{customer_id:100,moved:1}});}
  if(method==='GET')return r.fulfill({json:{items:path.includes('/leads')?leads:customers,customers,is_top_admin:true,owners:[]}});
  return r.fulfill({status:418,json:{detail:'Real business writes blocked'}});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8002/__lead_records_ui');
 const root=page.locator('[data-customer-workflow]'),recordPage=page.locator('[data-contact-records-page]');
 const activate=async view=>{await page.evaluate(view=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view}})),view);await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');};
 await activate('leads');assert.equal(await root.locator('[data-filter-lead-priority],[data-filter-lead-tag],[data-open-development]').count(),0);assert.ok(!(await root.innerText()).includes('跟进安排'));
 await root.locator('[data-detail="1"]').click();await page.locator('[data-detail-actions]').getByRole('button',{name:'联系记录',exact:true}).click();await recordPage.waitFor({state:'visible'});
 await recordPage.locator('[data-record-add]').click();const editor=recordPage.locator('.record-editor');const fields=await editor.locator('[data-field]').evaluateAll(nodes=>nodes.map(x=>x.dataset.field));
 assert.deepEqual(fields,['contact_name','occurred_at','channel','subject','content']);
 await editor.locator('[data-field="contact_name"]').fill('Engineer');await editor.locator('[data-field="channel"]').fill('WhatsApp');await editor.locator('[data-field="content"]').fill('Confirm coil parameters and send selection sheet.');
 await editor.locator('[data-save]').click();await page.locator('[data-workflow-toast]').filter({hasText:'标题'}).waitFor();assert.equal(writes,0,'A summary needs a clear title');
 await editor.locator('[data-field="subject"]').fill('Coil selection requirements');
 fail=true;await editor.locator('[data-save]').click();await page.locator('[data-workflow-toast]').filter({hasText:'无修改权限'}).waitFor();assert.equal(await editor.locator('[data-field="content"]').inputValue(),'Confirm coil parameters and send selection sheet.');fail=false;await editor.locator('[data-save]').click();await recordPage.locator('.record-card h3').filter({hasText:'Coil selection requirements'}).waitFor();
 // Imported legacy records retain their translation and direction in the new editor.
 records[0].content_translation='确认盘管参数并发送选型表。';records[0].direction='inbound';leads[0].workflow_status='replied';
 await recordPage.locator('[data-record-back]').click();await page.locator('[data-workflow-detail]').waitFor({state:'visible'});await page.locator('[data-detail-records] .record-translation summary').click();await page.locator('[data-detail-records] .record-translation p').waitFor();assert.equal(await root.locator('[data-contact-status="1"]').inputValue(),'replied');
 await page.locator('[data-detail-main="1"]').click();await page.locator('[data-action-submit]').click();await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false'&&document.querySelectorAll('[data-workflow-row]').length===0);
 customerRecords[0].occurred_at='2026-10-14T16:35:47';await activate('contacts');await root.locator('[data-detail="100"]').click();await page.locator('.lead-history').waitFor();await page.locator('.lead-history>summary').click();assert.ok((await page.locator('.lead-history').innerText()).includes('Original company note'));await page.locator('.lead-history .record-translation summary').click();assert.equal(await page.locator('.lead-history .record-translation p').innerText(),'确认盘管参数并发送选型表。');
 await page.locator('[data-detail-actions]').getByRole('button',{name:'联系记录',exact:true}).click();await recordPage.locator('[data-edit="1"]').click();assert.deepEqual(await recordPage.locator('.record-editor [data-field]').evaluateAll(nodes=>nodes.map(x=>x.dataset.field)),fields);assert.equal(await recordPage.locator('[data-field="subject"]').inputValue(),'Coil selection requirements');await recordPage.locator('[data-field="content"]').fill('Selection sheet sent; waiting for dimensions.');await recordPage.locator('[data-save]').click();await recordPage.locator('.record-card>p').filter({hasText:'Selection sheet sent'}).waitFor();assert.equal(customerRecords[0].occurred_at,'2026-10-14T16:35:47');assert.equal(customerRecords[0].direction,'inbound');assert.equal(customerRecords[0].content_translation,'确认盘管参数并发送选型表。');
 await page.setViewportSize({width:390,height:844});await recordPage.locator('[data-edit="1"]').click();assert.ok(await recordPage.evaluate(el=>el.scrollWidth<=el.clientWidth),'Five-field editor fits mobile');await page.screenshot({path:'output/ui/communication-summary-editor-mobile.png',fullPage:true});await recordPage.locator('[data-cancel]').click();await page.setViewportSize({width:1440,height:1000});
 assert.equal(writes,3);assert.deepEqual(errors,[]);fs.mkdirSync('output/ui',{recursive:true});await recordPage.locator('.record-card').evaluate(el=>Promise.all(el.getAnimations({subtree:true}).map(animation=>animation.finished.catch(()=>{}))));await page.screenshot({path:'output/ui/lead-customer-shared-records.png',fullPage:true});console.log('PASS shared lead/customer fields and editor, removed arrangements, translations, failed-save recovery, refreshed status on return, conversion and readable history. All writes mocked.');
 }finally{await browser.close();}})().catch(error=>{console.error(error.stack);process.exitCode=1;});
