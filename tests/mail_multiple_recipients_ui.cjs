// All SMTP-facing requests are intercepted; no real emails are sent.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join(''),settings=fs.readFileSync('app/templates/partials/mail_config.html','utf8');
 const config={configured:true,email:'sam@example.com',sender_name:'Sam',signature:'',has_password:true};
 const people=[{contact_name:'Buyer',email:'buyer@example.com'},{contact_name:'Engineer',email:'engineer@example.com'},{contact_name:'Product Manager',email:'manager@example.com'},{contact_name:'Sales Director',email:'sales@example.com'},{contact_name:'Duplicate Buyer',email:'BUYER@example.com'},{contact_name:'No email',email:''},{contact_name:'Invalid email',email:'not-an-email'}];
 let mode='batch',posts=[],logs=new Map(),queries=0,nextId=1,release=null;
 const formValue=(raw,name)=>raw.match(new RegExp('name="'+name+'"\\r\\n\\r\\n([^\\r\\n]*)'))?.[1]||'';
 await context.route('http://multi-mail.test/**',async r=>{const req=r.request(),url=new URL(req.url());
  if(url.pathname==='/test')return r.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body>${settings}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/mail.js"></script></body></html>`});
  if(url.pathname.startsWith('/static/'))return r.fulfill({path:path.resolve('app'+url.pathname)});
  if(url.pathname==='/api/mail/accounts')return r.fulfill({json:{items:[{account_id:0,email:config.email,is_default:true}],default_account_id:0}});
  if(url.pathname==='/api/mail/configuration')return r.fulfill({json:config});
  if(url.pathname.endsWith('/outreach-summary')){const stats={'buyer@example.com':{sent_count:2}};for(const row of logs.values())if(row.status==='accepted'){stats[row.recipient]??={sent_count:0};stats[row.recipient].sent_count++;}return r.fulfill({json:{outreach_stats:stats}});}
  if(url.pathname.startsWith('/api/mail/deliveries/by-request/')){queries++;const row=logs.get(url.pathname.split('/').at(-1));return r.fulfill(row?{json:row}:{status:404,json:{detail:'暂无记录'}});}
  if(url.pathname==='/api/mail/projects/7/leads/694/send'){
   const raw=req.postDataBuffer().toString('utf8'),recipient=formValue(raw,'recipient'),key=formValue(raw,'request_key'),name=formValue(raw,'contact_name');
   const post={recipient,key,name};posts.push(post);assert.ok(raw.includes('catalog.pdf'));assert.ok(!raw.includes('remove-me.txt'));assert.ok(raw.includes('Dear Team'));assert.ok(!raw.includes('name="cc"'));
   if(mode==='missing'&&posts.length===1)return r.abort('failed');
   if(mode==='switch')await new Promise(resolve=>release=resolve);
   const failed=mode==='batch'&&recipient==='engineer@example.com'&&posts.filter(p=>p.recipient===recipient).length===1;
   const row={id:nextId++,request_key:key,recipient,status:failed?'failed':'accepted',message:failed?'服务器明确拒绝本次发送':'邮件服务器已接受。'};logs.set(key,row);
   if(mode==='batch'&&recipient==='manager@example.com')return r.abort('failed');
   return r.fulfill({json:row});
  }
  if(url.pathname.startsWith('/api/'))return r.fulfill({status:418,json:{detail:'Unexpected business request blocked'}});
  return r.fulfill({status:404});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://multi-mail.test/test');
 const open=async(list=people)=>{await page.evaluate(people=>{window.outcome=null;window.TophooMail.compose({project:7,id:694,recipient:'buyer@example.com',contact_name:'Buyer',people,subject:'Custom coils for your HVAC projects',content:'Dear Team,\nWe manufacture customized heat exchanger coils.',content_html:'<p>Dear Team,</p><p>We manufacture customized heat exchanger coils.</p>'}).then(result=>window.outcome=result);},list);await page.waitForFunction(()=>document.querySelector('[data-mail-from]')?.textContent.includes('sam@example.com'));await page.locator('[data-mail-files]').setInputFiles({name:'catalog.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF mock')});};
 await open();assert.equal(posts.length,0,'Opening never sends');assert.equal(await page.locator('[data-mail-contact]').count(),4,'Missing/invalid excluded, duplicate email grouped');assert.equal(await page.locator('[data-mail-contact="0"]').isChecked(),true);
 await page.locator('[data-mail-outreach="0"]').filter({hasText:'已发开发信 · 2 封'}).waitFor();assert.equal(await page.locator('[data-mail-outreach="1"]').innerText(),'未发开发信');
 assert.equal(await page.locator('.mail-recipient-options').evaluate(el=>getComputedStyle(el).display),'flex','Selection stylesheet must actually load');
 const check=await page.locator('[data-mail-contact="0"]').boundingBox(),label=await page.locator('.mail-recipient-option>span').first().boundingBox();assert.ok(check.x<label.x&&Math.abs(check.y-label.y)<8,'Checkbox and contact text align on one row');
 assert.equal(await page.locator('[data-mail-files]').isVisible(),false,'Native file picker stays hidden');
 const chooserEvent=page.waitForEvent('filechooser');await page.locator('[data-mail-add-files]').click();const chooser=await chooserEvent;await chooser.setFiles({name:'remove-me.txt',mimeType:'text/plain',buffer:Buffer.from('Remove me')});assert.equal(await page.locator('[data-mail-file-list] li').count(),2);await page.locator('[data-mail-remove-file="1"]').click();assert.equal(await page.locator('[data-mail-file-list] li').count(),1);
 await page.locator('[data-mail-recipient-all]').check();await page.locator('.mail-recipient-extra-box>summary').click();await page.locator('[data-mail-recipient]').fill('BUYER@example.com');assert.equal(await page.locator('[data-mail-recipient-count]').innerText(),'已选 4 位');
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/mail-multiple-recipients-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.locator('.mail-send-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth));await page.screenshot({path:'output/ui/mail-multiple-recipients-mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});
 await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('待核实'));
 assert.equal(posts.length,3);assert.deepEqual(posts.map(p=>p.recipient),['buyer@example.com','engineer@example.com','manager@example.com']);assert.equal(await page.locator('[data-mail-contact="0"]').isDisabled(),true,'Freeze recipients after submission');
 await page.locator('[data-mail-send-query]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('服务器已接受 2 / 4'));assert.equal(queries,1);assert.equal(posts.length,3,'Query does not send');
 await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('服务器已接受 4 / 4'));
 assert.equal(posts.length,5);assert.equal(posts.filter(p=>p.recipient==='buyer@example.com').length,1);assert.equal(posts.filter(p=>p.recipient==='manager@example.com').length,1);assert.equal(posts.filter(p=>p.recipient==='sales@example.com').length,1);
 await page.locator('[data-mail-outreach="0"]').filter({hasText:'已发开发信 · 3 封'}).waitFor();assert.equal(await page.locator('[data-mail-outreach="1"]').innerText(),'已发开发信 · 1 封');
 const attempts=posts.filter(p=>p.recipient==='engineer@example.com');assert.equal(attempts.length,2);assert.notEqual(attempts[0].key,attempts[1].key,'Explicit retry of a known failure uses a new key');assert.equal(new Set(posts.map(p=>p.key)).size,5);
 await page.screenshot({path:'output/ui/mail-multiple-recipients-results.png',fullPage:true});await page.locator('[data-mail-send-close]').last().click();await page.waitForFunction(()=>window.outcome?.accepted_count===4);assert.equal(await page.evaluate(()=>window.outcome.status),'accepted');
 mode='missing';posts=[];logs.clear();await open(people.slice(0,1));await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('待核实'));const oldKey=posts[0].key;
 assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true,'Unknown single send cannot be blindly retried');await page.locator('[data-mail-send-query]').click();await page.waitForFunction(()=>!document.querySelector('[data-mail-send-confirm]').disabled);assert.equal(posts.length,1);
 await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('服务器已接受 1 / 1'));assert.equal(posts[1].key,oldKey,'Missing log safely resubmits original idempotency key');await page.locator('[data-mail-send-close]').last().click();
 mode='switch';posts=[];await open();await page.locator('[data-mail-recipient-all]').check();await page.locator('[data-mail-send-confirm]').click();await page.waitForTimeout(100);assert.equal(posts.length,1);await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','8');window.dispatchEvent(new Event('tophoo-project-changed'));});release();await page.waitForFunction(()=>!document.querySelector('[data-mail-send-close]').disabled);assert.equal(posts.length,1,'Project switch stops remaining recipients');assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true);await page.locator('[data-mail-send-close]').last().click();
 assert.deepEqual(errors,[]);console.log('PASS multiple-recipient UI: same-company selection, email dedupe, missing-email exclusion, per-person attachments, partial failures, query-only recovery, no accepted/unknown resends, safe same-key retry, project-switch stop, desktop/mobile. All sends mocked.');
 }finally{await browser.close();}})().catch(error=>{console.error(error.stack);process.exitCode=1;});
