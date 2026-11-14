// All requests mocked. This test never sends email or changes business data.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1280,height:900}}),css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('');
 let count=2,historyReads=0;const contacts=[{contact_name:'Buyer',email:'BUYER@example.com',is_primary:true},{contact_name:'Engineer',email:'engineer@example.com'},{contact_name:'No email'}];
 await context.route('http://outreach.test/**',async r=>{const u=new URL(r.request().url());assert.equal(r.request().method(),'GET','Read-only UI must never mutate');
  if(u.pathname==='/test')return r.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="UTF-8">${css}</head><body><script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/contact-outreach-history.js"></script><script src="/static/js/lead-contacts.js"></script></body></html>`});
  if(u.pathname.startsWith('/static/'))return r.fulfill({path:path.resolve('app'+u.pathname)});
  if(u.pathname.endsWith('/contacts'))return r.fulfill({json:{contacts,version:'v1',outreach_stats:{'buyer@example.com':{sent_count:count,last_sent_at:'2026-10-30T17:00:00'}}}});
  if(u.pathname.endsWith('/outreach-history')){historyReads++;assert.equal(u.searchParams.get('recipient'),'BUYER@example.com');return r.fulfill({json:{total:2,next_before_id:u.searchParams.has('before_id')?null:2,items:[{id:historyReads,subject:'Custom coils '+historyReads,content_html:'<p>Our coils</p><script>window.injected=true</script>',sender:'sam@example.com',accepted_at:'2026-10-30T17:00:00',attachments:[{name:'catalog.pdf'}]}]}});}
  throw Error('Unexpected request '+u.pathname);
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://outreach.test/test');
 await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-lead-contacts-open',{detail:{project:7,id:694,item:{company_name:'Example HVAC'}}})));
 const badges=page.locator('[data-contact-outreach]');await badges.first().filter({hasText:'已发开发信 · 2 封'}).waitFor();assert.equal(await badges.nth(1).innerText(),'未发开发信');assert.equal(await badges.nth(2).isDisabled(),true);
 assert.notEqual(await badges.first().evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)','Badge stylesheet loaded');
 await badges.first().click();const history=page.locator('.contact-outreach-history');await history.locator('[data-history-status]').filter({hasText:'共发送 2 封'}).waitFor();await history.locator('summary').click();assert.ok((await history.innerText()).includes('catalog.pdf'));assert.equal(await page.evaluate(()=>window.injected),undefined);
 await history.locator('[data-history-more]').click();await page.waitForFunction(()=>document.querySelectorAll('.outreach-history-card').length===2);assert.equal(await history.locator('[data-history-more]').isVisible(),false);
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/contact-outreach-history-desktop.png'});await page.keyboard.press('Escape');await history.waitFor({state:'detached'});assert.equal(await page.locator('.lead-contacts-dialog').isVisible(),true);
 count=3;await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-updated',{detail:{project:7,id:694}})));await badges.first().filter({hasText:'已发开发信 · 3 封'}).waitFor();
 await page.setViewportSize({width:390,height:844});assert.ok(await page.locator('.lead-contacts-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth));await page.screenshot({path:'output/ui/contact-outreach-badges-mobile.png'});await badges.first().click();await history.waitFor({state:'visible'});assert.ok(await history.evaluate(e=>e.scrollWidth<=e.clientWidth));
 await page.evaluate(()=>window.dispatchEvent(new Event('tophoo-project-changed')));await history.waitFor({state:'detached'});assert.equal(await page.locator('.lead-contacts-dialog').isVisible(),false);assert.deepEqual(errors,[]);console.log('PASS contact counts, safe paginated history, refresh, Escape, project cleanup, desktop/mobile; no writes.');
 }finally{await browser.close();}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
