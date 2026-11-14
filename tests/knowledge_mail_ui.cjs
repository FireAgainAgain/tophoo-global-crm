const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
 const library={categories:[{id:1,name:'邮件资料',parent_id:null}],scripts:[{id:1,category_id:1,title:'我的签名',content:'Seller',sort_order:1}]};
 const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
 const template=fs.readFileSync('app/templates/partials/crm_communication_scripts.html','utf8').replace('data-crm-communication-scripts hidden','data-crm-communication-scripts');
 await context.route('http://knowledge.test/**',route=>{const req=route.request(),url=new URL(req.url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="utf-8">${css}</head><body><main class="main"><div class="main-inner">${template}</div></main><script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/mail-rich-editor.js"></script><script src="/static/js/crm-communication-scripts.js"></script></body></html>`});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  if(url.pathname.startsWith('/api/communication-scripts')){if(req.method()==='GET')return route.fulfill({json:library});Object.assign(library.scripts[0],req.postDataJSON());return route.fulfill({json:library.scripts[0]});}
  return route.fulfill({status:404,body:''});});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://knowledge.test/');
 await page.locator('[data-reader-edit]').click();await page.locator('[name=content_format]').selectOption('email');
 const body=page.locator('[data-knowledge-mail-body]');await body.fill('My signature');
 await page.locator('[data-rich-command=html]').click();await page.locator('.mail-html-dialog textarea').fill('<table><tr><td style="color:blue"><b>Seller</b></td><td><img width="80" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5X8AAAAASUVORK5CYII="></td></tr></table>');
 await page.locator('[data-insert]').click();assert.equal(await body.locator('img').count(),1);
 await page.locator('[data-script-editor] [type=submit]').click();await page.locator('[data-reader-edit]').waitFor();assert.equal(library.scripts[0].content_format,'email');assert.ok(library.scripts[0].content_html.includes('data:image/png'));
 assert.equal(await page.locator('.script-reader .script-markdown-render table').count(),1);
 await page.locator('[data-reader-preview]').click();assert.equal(await page.locator('[data-script-content-preview]').isVisible(),true);assert.equal(await page.locator('[data-script-preview-body] table').count(),1);assert.equal(await page.locator('[data-script-preview-body] img').count(),1);await page.locator('[data-script-preview-close]').click();
 await page.locator('[data-reader-edit]').click();assert.equal(await body.locator('img').count(),1);
 await page.screenshot({path:'output/ui/knowledge-mail-editor-desktop.png'});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'output/ui/knowledge-mail-editor-mobile.png'});
 assert.deepEqual(errors,[]);console.log('PASS: knowledge email format, HTML signature/image save and reopen, styled reader, desktop/mobile. All writes mocked.');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
