// Mailbox configuration and explicit send review; all SMTP/API writes are mocked.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
 const settings=fs.readFileSync('app/templates/partials/mail_config.html','utf8'),workflow=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
 let configuration={configured:false,has_password:false,port:465,encryption:'ssl'},logs=[],draft={},sendCount=0,testCount=0,failNext=false,saveCount=0,validationError=false;
 const lead={id:1,company_name:'Mailbox buyer',workflow_status:'ready',contacts:[{contact_name:'Buyer',email:'buyer@example.com',is_primary:true},{contact_name:'Engineer',email:'engineer@example.com'}]};
 await context.route('http://mail.test/**',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN" data-ui-theme="green"><head><meta charset="utf-8">${css}</head><body class="global-shell" data-workspace="crm"><main class="main"><div class="main-inner"><section id="page-crm" class="page active"><div id="global-crm-content">${settings}${workflow}</div></section></div></main><script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/company-types.js"></script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/mail.js"></script><script src="/static/js/lead-outreach.js"></script><script src="/static/js/crm-customer-workflow.js"></script><script src="/static/js/contact-records.js"></script></body></html>`});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  if(url.pathname==='/api/mail/accounts'&&request.method()==='GET')return route.fulfill({json:{items:configuration.configured?[{...configuration,account_id:1,is_default:true}]:[],default_account_id:configuration.configured?1:null}});
  if(url.pathname==='/api/mail/configuration'||url.pathname==='/api/mail/accounts'||url.pathname==='/api/mail/accounts/1'){
   if(['PUT','POST'].includes(request.method())){saveCount++;if(validationError)return route.fulfill({status:422,json:{detail:[{loc:['body','host'],msg:'Value error, 服务器地址无效'}]}});const data=request.postDataJSON();if(data.password!==undefined)assert.equal(data.password,'my-app-password');delete data.password;configuration={...data,configured:true,account_id:1,has_password:true,last_test_status:'',last_tested_at:null};}
   return route.fulfill({json:configuration});
  }
  if(url.pathname==='/api/mail/configuration/test'){testCount++;configuration.last_test_status='passed';configuration.last_tested_at='2026-10-19T17:00:00';configuration.last_test_message='TLS 连接和账号验证通过，未发送邮件。';return route.fulfill({json:configuration});}
  if(url.pathname==='/api/mail/test-message'){logs.push({id:1,request_key:request.postDataJSON().request_key,sender:configuration.email,recipient:configuration.email,subject:'Test',content:'Test message',status:'accepted',message:'邮件服务器已接受',attachments:[],created_at:'2026-10-19T17:01:00'});return route.fulfill({json:logs.at(-1)});}
  if(url.pathname==='/api/mail/deliveries')return route.fulfill({json:{items:logs}});
  if(url.pathname.endsWith('/outreach-draft')){if(request.method()==='PUT')draft={...request.postDataJSON(),updated_at:'2026-10-19T17:02:00'};return route.fulfill({json:{subject:'',content:'',content_translation:'',...draft}});}
  if(url.pathname==='/api/mail/projects/7/leads/1/send'){
   sendCount++;assert.ok(request.headers()['content-type'].startsWith('multipart/form-data'));
   const raw=request.postDataBuffer().toString('utf8');assert.ok(raw.includes('engineer@example.com'));assert.ok(raw.includes('catalog.pdf'));assert.ok(raw.includes('Technical coils'));
   if(failNext)return route.fulfill({json:{id:3,status:'unknown',message:'发送结果待核实，请勿直接重发。'}});
   return route.fulfill({json:{id:2,status:'accepted',interaction_id:null,message:'邮件服务器已接受。'}});
  }
  if(url.pathname.endsWith('/interactions'))return route.fulfill({json:{contact:{id:1,name:'Buyer'},records:[]}});
  if(url.pathname.startsWith('/api/'))return route.fulfill({json:{items:[lead],customers:[lead],owners:[],is_top_admin:true}});
  return route.fulfill({status:404});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://mail.test/test');
 await page.evaluate(()=>{document.querySelector('[data-mail-config]').hidden=false;document.dispatchEvent(new CustomEvent('tophoo-mail-config-view'));});
 await page.waitForFunction(()=>!document.querySelector('[data-mail-form] [name=email]').disabled);
 assert.equal(testCount,0);assert.equal(sendCount,0);
 assert.equal(await page.locator('[data-mail-config] h1').count(),1);
 assert.equal(await page.locator('[data-mail-form]').isVisible(),true);
 for(const [name,value] of Object.entries({sender_name:'Sam',email:'sam@example.com',host:'smtp.example.com',username:'sam@example.com',password:'my-app-password'}))await page.locator(`[data-mail-form] [name=${name}]`).fill(value);
 await page.locator('.mail-signature summary').click();await page.locator('[data-mail-form] .mail-rich-body').fill('Best regards, Sam');
 await page.locator('[data-mail-reveal]').click();assert.equal(await page.locator('[name=password]').getAttribute('type'),'text');
 assert.equal(await page.locator('[data-mail-test]').isDisabled(),true);
 await page.locator('[name=host]').fill('https://mail.163.com/');
 await page.locator('[data-mail-form] [type=submit]').click();
 assert.ok((await page.locator('[name=host]').evaluate(el=>el.validationMessage)).includes('SMTP'));assert.equal(saveCount,0);
 await page.locator('[name=host]').fill('smtp.example.com');await page.locator('[name=encryption]').selectOption('starttls');
 await page.locator('[data-mail-form] [type=submit]').click();assert.ok((await page.locator('[name=encryption]').evaluate(el=>el.validationMessage)).includes('SSL'));assert.equal(saveCount,0);
 await page.locator('[name=encryption]').selectOption('ssl');validationError=true;
 await page.locator('[data-mail-form] [type=submit]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-feedback]').textContent==='SMTP 服务器：服务器地址无效');
 validationError=false;
 await page.locator('[data-mail-form] [type=submit]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-feedback]').textContent==='配置已保存。');
 assert.equal(await page.locator('[name=password]').inputValue(),'');assert.equal(await page.locator('[name=password]').getAttribute('type'),'password');
 assert.equal(await page.locator('[data-mail-form]').isVisible(),false);
 assert.equal(await page.locator('[data-mail-saved]').isVisible(),true);
 assert.equal(await page.locator('[data-mail-saved-email]').textContent(),'sam@example.com');
 assert.equal(await page.locator('[data-mail-saved-secret]').textContent(),'已安全保存');
 assert.equal(await page.locator('[data-mail-signature-view]').getAttribute('open'),null);
 await page.locator('[data-mail-signature-view] summary').click();await page.waitForFunction(()=>document.querySelector('[data-mail-signature-preview]').srcdoc.includes('Best regards'));
 const savedCalls=saveCount;
 await page.locator('[data-mail-edit]').click();await page.locator('[name=host]').fill('smtp.changed.example.com');
 await page.locator('[name=password]').fill('discarded-password');
 assert.equal(await page.locator('[data-mail-test-status]').textContent(),'修改未保存');
 page.once('dialog',dialog=>dialog.dismiss());await page.locator('[data-mail-cancel]').click();
 assert.equal(await page.locator('[data-mail-form]').isVisible(),true);
 page.once('dialog',dialog=>dialog.accept());await page.locator('[data-mail-cancel]').click();
 assert.equal(await page.locator('[data-mail-form]').isVisible(),false);
 assert.equal(await page.locator('[data-mail-saved-server]').textContent(),'smtp.example.com:465');
 assert.equal(await page.locator('[name=password]').inputValue(),'');assert.equal(saveCount,savedCalls);

 await page.locator('[data-mail-test]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-test-status]').textContent.includes('测试通过'));
 assert.equal(testCount,1);assert.equal(logs.length,0);
 page.once('dialog',dialog=>dialog.accept());await page.locator('[data-mail-test-message]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-history]').textContent.includes('Test'));
 assert.equal(logs[0].recipient,'sam@example.com');
 await page.locator('[data-mail-edit]').click();await page.locator('[name=sender_name]').fill('Temporary name');
 page.once('dialog',dialog=>dialog.accept());await page.locator('[data-mail-cancel]').click();
 assert.ok((await page.locator('[data-mail-test-status]').textContent()).includes('测试通过'));
 assert.equal(await page.locator('[data-mail-saved-name]').textContent(),'Sam');
 assert.ok((await page.locator('[data-mail-settings]').boundingBox()).height<560);
 await page.screenshot({path:'output/ui/mail-config-desktop.png',fullPage:true});
 await page.evaluate(()=>{document.querySelector('[data-mail-config]').hidden=true;document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'leads'}}));});
 await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');
 await page.locator('[data-lead-outreach-open="1"]').click();
 assert.equal(await page.locator('[data-outreach-person],[data-outreach-recipient-email]').count(),0);await page.locator('[data-outreach-subject]').fill('Technical coils');await page.locator('[data-outreach-content]').fill('Dear Engineer,\nCustom coils for your application.');
 await page.locator('.lead-outreach-editor [data-rich-command="html"]').click();
 await page.locator('.mail-html-dialog textarea').fill('<table><tr><td style="color:blue"><b>Rich signature</b></td></tr></table>');
 await page.locator('.mail-html-dialog [data-insert]').click();
 await page.locator('[data-outreach-send]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-from]')?.textContent.includes('sam@example.com'));assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true);await page.locator('[data-mail-contact="1"]').check();
 assert.equal(await page.locator('[data-mail-body] table').count(),1);
 assert.equal(sendCount,0,'Opening review must not send');assert.equal(await page.locator('[data-mail-contact="1"]').isChecked(),true);assert.equal(await page.locator('[data-mail-recipient]').inputValue(),'');
 assert.ok((await page.locator('[data-mail-from]').textContent()).includes('sam@example.com'));
 await page.locator('[data-mail-files]').setInputFiles({name:'catalog.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-demo')});
 await page.screenshot({path:'output/ui/mail-send-desktop.png'});
 await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('服务器已接受'));
 assert.equal(sendCount,1);assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true);
 await page.locator('[data-mail-send-close]').last().click();await page.locator('.lead-outreach-editor').waitFor({state:'hidden'});
 await page.setViewportSize({width:390,height:844});await page.locator('[data-lead-outreach-open="1"]').click();await page.locator('[data-outreach-send]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-from]')?.textContent.includes('sam@example.com'));assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true);await page.locator('[data-mail-contact="1"]').check();
 await page.locator('[data-mail-files]').setInputFiles({name:'catalog.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-demo')});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'output/ui/mail-send-mobile.png'});
 failNext=true;await page.locator('[data-mail-send-confirm]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-send-status]').textContent.includes('待核实'));
 assert.equal(await page.locator('[data-mail-send-confirm]').isDisabled(),true);assert.equal(sendCount,2);assert.equal(await page.locator('[data-mail-send-query]').isVisible(),true);
 await page.locator('[data-mail-send-close]').last().click();await page.locator('[data-outreach-close]').click();
 await page.evaluate(()=>{document.querySelector('[data-customer-workflow]').hidden=true;document.querySelector('[data-mail-config]').hidden=false;document.dispatchEvent(new CustomEvent('tophoo-mail-config-view'));});
 await page.locator('[data-mail-saved]').waitFor({state:'visible'});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'output/ui/mail-config-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS mail UI: compact saved view, explicit edit, cancel/discard guards, hidden secret, retained test status, personal settings, password reveal/clear, save/test separation, self-test, recipient selection, attachment review, explicit single send, accepted refresh, unknown-result block, mobile. All writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});

