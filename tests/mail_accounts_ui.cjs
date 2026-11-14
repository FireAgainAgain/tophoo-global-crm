// Every SMTP-facing action is intercepted. No real emails or settings are changed.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const template=fs.readFileSync('app/templates/partials/mail_config.html','utf8'),css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('');
 let accounts=[{account_id:0,email:'primary@example.com',sender_name:'Primary',host:'smtp.example.com',port:465,encryption:'ssl',username:'primary@example.com',signature:'Primary signature',configured:true,has_password:true,last_test_status:'passed'},{account_id:1,email:'sales@example.com',sender_name:'Sales',host:'smtp.example.com',port:465,encryption:'ssl',username:'sales@example.com',signature:'Sales signature',configured:true,has_password:true,last_test_status:''}],defaultId=0,posted=[],fail=false;
 const multipart=(raw,key)=>raw.split('name="'+key+'"\r\n\r\n')[1]?.split('\r\n--')[0];
 await context.route('http://mail-accounts.test/**',async r=>{const req=r.request(),u=new URL(req.url());
 if(u.pathname==='/test')return r.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="UTF-8">${css}</head><body>${template}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/mail.js"></script></body></html>`});
 if(u.pathname.startsWith('/static/'))return r.fulfill({path:path.resolve('app'+u.pathname)});
 if(u.pathname==='/api/mail/accounts'&&req.method()==='GET')return r.fulfill({json:{items:accounts.map(a=>({...a,signature:undefined,is_default:a.account_id===defaultId})),default_account_id:defaultId}});
 if(u.pathname==='/api/mail/configuration')return r.fulfill({json:accounts.find(a=>a.account_id===Number(u.searchParams.get('account_id')??defaultId))||{configured:false,port:465,encryption:'ssl'}});
 if(u.pathname==='/api/mail/accounts'&&req.method()==='POST'){if(fail)return r.fulfill({status:422,json:{detail:'模拟保存失败'}});const data=req.postDataJSON();assert.equal(data.password,'app-password');delete data.password;const account={...data,account_id:2,configured:true,has_password:true};accounts.push(account);return r.fulfill({status:201,json:account});}
 if(/\/accounts\/\d+$/.test(u.pathname)){const id=Number(u.pathname.split('/').at(-1));if(req.method()==='DELETE'){accounts=accounts.filter(a=>a.account_id!==id);return r.fulfill({json:{deleted:true}});}if(req.method()==='PUT'){const data=req.postDataJSON();assert.equal(data.password,undefined);const account=accounts.find(a=>a.account_id===id);Object.assign(account,data);return r.fulfill({json:account});}}
 if(u.pathname.endsWith('/default')){defaultId=Number(u.pathname.split('/').at(-2));return r.fulfill({json:{default_account_id:defaultId}});}
 if(u.pathname==='/api/mail/configuration/test'){const account=accounts.find(a=>a.account_id===Number(u.searchParams.get('account_id')));account.last_test_status='passed';account.last_test_message='连接通过';return r.fulfill({json:account});}
 if(u.pathname.endsWith('/send')){const raw=req.postDataBuffer().toString();posted.push({account_id:multipart(raw,'account_id'),content:multipart(raw,'content')});return r.fulfill({json:{id:20,status:'accepted',message:'服务器已接受'}});}
 if(u.pathname.endsWith('/deliveries')||u.pathname.endsWith('/outreach-summary'))return r.fulfill({json:{items:[],outreach_stats:{}}});
 throw Error('Unexpected request '+req.method()+' '+u.pathname);
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://mail-accounts.test/test');
 await page.evaluate(()=>{document.querySelector('[data-mail-config]').hidden=false;document.dispatchEvent(new Event('tophoo-mail-config-view'));});
 await page.locator('[data-mail-saved-email]').filter({hasText:'primary@example.com'}).waitFor();assert.equal(await page.locator('[data-mail-account]').count(),2);
 await page.locator('[data-mail-account="1"]').click();await page.locator('[data-mail-saved-email]').filter({hasText:'sales@example.com'}).waitFor();
 await page.locator('[data-mail-edit]').click();await page.locator('[name=sender_name]').fill('Sales team');await page.locator('[data-mail-form] [type=submit]').click();await page.locator('[data-mail-feedback]').filter({hasText:'配置已保存'}).waitFor();assert.equal(accounts[1].sender_name,'Sales team');assert.equal(accounts[0].sender_name,'Primary');
 await page.locator('[data-mail-account-default]').click();await page.waitForFunction(()=>document.querySelector('[data-mail-account="1"] b'));assert.equal(defaultId,1);
 await page.locator('[data-mail-test]').click();await page.locator('[data-mail-feedback]').filter({hasText:'连接通过'}).waitFor();
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/mail-accounts-desktop.png'});
 await page.locator('[data-mail-account-add]').click();for(const [key,value]of Object.entries({email:'extra@example.com',host:'smtp.example.com',username:'extra@example.com',password:'app-password'}))await page.locator(`[name=${key}]`).fill(value);
 fail=true;await page.locator('[data-mail-form] [type=submit]').click();await page.locator('[data-mail-feedback]').filter({hasText:'模拟保存失败'}).waitFor();assert.equal(await page.locator('[name=email]').inputValue(),'extra@example.com');fail=false;await page.locator('[data-mail-form] [type=submit]').click();await page.locator('[data-mail-saved-email]').filter({hasText:'extra@example.com'}).waitFor();assert.equal(await page.locator('[name=password]').inputValue(),'');
 page.once('dialog',d=>d.accept());await page.locator('[data-mail-account-delete]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-mail-account]').length===2);assert.equal(accounts.length,2);
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'output/ui/mail-accounts-mobile.png',fullPage:true});
 await page.evaluate(()=>{window.mailResult=window.TophooMail.compose({project:7,id:1,recipient:'buyer@example.com',people:[{contact_name:'Buyer',email:'buyer@example.com'}],subject:'Coil information',content:'Product introduction',content_html:''});});
 const dialog=page.locator('.mail-send-dialog');await page.waitForFunction(()=>document.querySelector('[data-mail-send-confirm]')?.disabled===false);
 assert.equal(await dialog.locator('[data-mail-sender-select]').inputValue(),'1');await dialog.locator('[data-mail-add-signature]').click();assert.ok((await dialog.locator('[data-mail-body]').innerText()).includes('Sales signature'));
 await dialog.locator('[data-mail-sender-select]').selectOption('0');await dialog.locator('[data-mail-from]').filter({hasText:'primary@example.com'}).waitFor();assert.ok(!(await dialog.locator('[data-mail-body]').innerText()).includes('Sales signature'));await dialog.locator('[data-mail-add-signature]').click();
 await page.screenshot({path:'output/ui/mail-account-sender-mobile.png'});
 await dialog.locator('[data-mail-send-confirm]').click();await dialog.locator('[data-mail-send-status]').filter({hasText:'服务器已接受 1 / 1'}).waitFor();assert.equal(posted[0].account_id,'0');assert.ok(posted[0].content.includes('Primary signature'));assert.equal(await dialog.locator('[data-mail-sender-select]').isDisabled(),true);
 assert.deepEqual(errors,[]);console.log('PASS: multiple mailbox cards, independent editing/password retention, default selection, connection test, create/retry/delete, mobile, selected sender and signature isolation, send lock. All writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
