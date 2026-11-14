const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const template=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
 const people=[{contact_name:'Buyer',email:' BUYER@example.test ',is_primary:true},{contact_name:'Engineer',email:'engineer@example.test'},{contact_name:'New contact',email:'new@example.test'},{contact_name:'Phone only',phone:'123456'}];
 const lead={id:1,company_name:'Demo contact outreach test',contacts:people,created_at:'2026-11-03T09:00:00'};
 let count=3,fail=false,writes=0,reads=0;
 await context.route('http://crm.test/**',async route=>{const req=route.request(),url=new URL(req.url());
  if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/workbench.css"><link rel="stylesheet" href="/static/css/ui-themes.css"></head><body><main>${template}</main><script>localStorage.setItem('tophoo-global-selected-project','7')</script>${['company-types','crm-customer-workflow','lead-detail-outreach'].map(n=>`<script src="/static/js/${n}.js"></script>`).join('')}</body></html>`});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  if(req.method()!=='GET'){writes++;return route.fulfill({status:418,json:{detail:'No business writes'}});}
  if(url.pathname.endsWith('/contacts')){reads++;if(fail)return route.fulfill({status:500,json:{detail:'Failed'}});return route.fulfill({json:{contacts:people,outreach_stats:{'buyer@example.test':{sent_count:count},'engineer@example.test':{sent_count:1}}}});}
  return route.fulfill({json:{items:[lead],customers:[],owners:[],is_top_admin:true}});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://crm.test/test');
 await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:'leads'}})));
 await page.locator('[data-detail="1"]').click();
 assert.deepEqual(await page.locator('[data-detail-actions] button').allTextContents(),['编辑','转为客户','删除']);
 const badges=page.locator('[data-detail-outreach-email]');await badges.first().getByText('已发开发信 · 3 封',{exact:true}).waitFor();
 assert.equal(await badges.nth(1).innerText(),'已发开发信 · 1 封');assert.equal(await badges.nth(2).innerText(),'已发开发信 · 0 封');assert.match(await badges.nth(3).innerText(),/无邮箱/);
 assert.equal(await badges.first().locator('button').getAttribute('data-outreach-recipient'),'BUYER@example.test');
 count=4;await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-updated',{detail:{project:7,id:1}})));await badges.first().getByText('已发开发信 · 4 封',{exact:true}).waitFor();
 fail=true;await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-updated',{detail:{project:7,id:1}})));await badges.first().getByText('数量读取失败，点击重试',{exact:true}).waitFor();
 fail=false;await badges.first().locator('button').click();await badges.first().getByText('已发开发信 · 4 封',{exact:true}).waitFor();
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/lead-detail-outreach-desktop.png'});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'output/ui/lead-detail-outreach-mobile.png'});
 assert.equal(writes,0);assert.equal(reads,4);assert.deepEqual(errors,[]);console.log('PASS lead detail recipient totals, email normalization, zero/no-email states, live refresh and failure retry; no business writes.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
