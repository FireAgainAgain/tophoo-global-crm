// Status writes are intercepted; no real enquiries are changed.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const partial=fs.readFileSync('app/templates/partials/crm_rfq.html','utf8').replace('data-crm-rfq hidden','data-crm-rfq');
  const items=[1,2].map(id=>({id,number:id===1?'v9':'v10',status:'待处理',inquiry_date:'2026-10-30',company_name:'Test company',local_clock:id===1?{timezone:'Europe/Prague',city:'布拉格'}:{timezone:null,hint:'待确认时区'},notes:'Original notes',generic_fields:[{key:'request',title:'Requirement',content:'Original parameters'}]}));
  let requests=[],fail=false,delayed=false,release;const errors=[];
  await context.route('https://rfq.test/**',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/workbench.css"><link rel="stylesheet" href="/static/css/ui-themes.css"></head><body><script>localStorage.setItem('tophoo-global-selected-project','7');window.tophooProjectAccess={canEdit:()=>false}</script>${partial}</body></html>`});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   if(url.pathname.endsWith('/references'))return route.fulfill({json:{contacts:[],is_top_admin:true,owners:[]}});
   if(req.method()==='PATCH'){
    assert.match(url.pathname,/\/status$/);const data=req.postDataJSON();requests.push(data);
    if(delayed)await new Promise(resolve=>release=resolve);
    if(fail)return route.fulfill({status:500,json:{detail:'模拟保存失败'}});
    const id=Number(url.pathname.split('/').at(-2));items.find(i=>i.id===id).status=data.status;
    return route.fulfill({json:{id,status:data.status}});
   }
   assert.equal(req.method(),'GET','Only explicit status PATCH is allowed');
   return route.fulfill({json:url.pathname.includes('/projects/8')?[{...items[0],number:'OTHER-PROJECT',status:'待处理'}]:items});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto('https://rfq.test/test');
  const status=id=>page.locator(`[data-rfq-inline-status="${id}"]`);
  await status(1).waitFor();assert.deepEqual(await status(1).locator('option').allTextContents(),['待处理','推进中','已报价','已成交','已关闭']);
  assert.equal(await status(1).isDisabled(),true);
  await page.evaluate(()=>{window.tophooProjectAccess={canEdit:()=>true};window.dispatchEvent(new CustomEvent('tophoo-project-availability'));});
  await page.waitForFunction(()=>document.querySelector('[data-rfq-inline-status="1"]')?.disabled===false);
  assert.deepEqual(await page.locator('.rfq-wrap th').allTextContents(),['编号 ↓','询价日期','询盘来源','状态','客户信息','全球时间']);
  assert.match(await page.locator('[data-rfq-clock="1"]').innerText(),/\d{2}:\d{2}/);
  assert.ok((await page.locator('[data-rfq-clock="1"]').innerText()).includes('布拉格'));
  assert.equal(await page.locator('[data-rfq-clock="2"]').innerText(),'待确认时区');
  assert.deepEqual(await page.locator('[data-preview-rfq]').allTextContents(),['v10','v9']);
  assert.ok((await page.locator('.rfq-list-hint').innerText()).includes('编号从大到小'));
  async function checkStatusLayout() {
   const box=await status(1).evaluate(el=>{const r=el.getBoundingClientRect(),cell=el.closest('td').getBoundingClientRect(),date=el.closest('td').nextElementSibling.getBoundingClientRect();return {width:r.width,height:r.height,right:r.right,cellRight:cell.right,dateLeft:date.left};});
   assert.ok(box.width>=80 && box.width<=90,JSON.stringify(box));assert.equal(box.height,30);
   assert.ok(box.cellRight-box.right>=14,JSON.stringify(box));assert.ok(box.dateLeft-box.right>=14,JSON.stringify(box));
  }
  await checkStatusLayout();
  await status(1).focus();fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/rfq-inline-status-desktop.png'});
  await status(1).click();await page.keyboard.press('Escape');
  assert.equal(await page.locator('[data-rfq-preview]').isVisible(),false);
  await status(1).press('ArrowDown');await page.waitForFunction(()=>document.querySelector('[data-rfq-metric="active"]').textContent==='1');
  assert.deepEqual(requests,[{status:'推进中'}]);assert.equal(await status(1).inputValue(),'推进中');assert.match(await status(1).getAttribute('class'),/is-1/);
  assert.equal(await page.locator('.rfq-editor').isVisible(),false);assert.equal(await page.locator('[data-rfq-preview]').isVisible(),false);
  assert.equal(items[0].notes,'Original notes');assert.equal(items[0].generic_fields[0].content,'Original parameters');
  await page.locator('[data-rfq-status]').selectOption('待处理');assert.equal(await page.locator('[data-rfq-row]').count(),1);
  await status(2).selectOption('已报价');await page.waitForFunction(()=>document.querySelectorAll('[data-rfq-row]').length===0);assert.equal(await page.locator('[data-rfq-metric="quoted"]').innerText(),'1');
  await page.locator('[data-rfq-status]').selectOption('');fail=true;await status(1).selectOption('已关闭');await page.waitForFunction(()=>document.querySelector('.rfq-toast').textContent==='模拟保存失败');assert.equal(await status(1).inputValue(),'推进中');assert.equal(await status(1).isEnabled(),true);fail=false;
  await page.evaluate(()=>window.tophooProjectAccess={canEdit:()=>false});await page.locator('[data-rfq-refresh]').click();await page.waitForFunction(()=>document.querySelector('[data-rfq-inline-status="1"]')?.disabled===true);assert.equal(requests.length,3);
  await page.evaluate(()=>delete window.tophooProjectAccess);await page.locator('[data-rfq-refresh]').click();await page.waitForFunction(()=>document.querySelector('[data-rfq-inline-status="1"]')?.disabled===false);
  await page.setViewportSize({width:390,height:844});await checkStatusLayout();fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/rfq-inline-status-mobile.png'});
  delayed=true;await status(1).selectOption('已成交');assert.equal(await status(1).isDisabled(),true);
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','8');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.waitForFunction(()=>document.querySelector('[data-preview-rfq="1"]')?.textContent==='OTHER-PROJECT');
  release();await page.waitForTimeout(150);assert.equal(await status(1).inputValue(),'待处理');assert.deepEqual(errors,[]);
  console.log('PASS: inline status-only save, no editor/preview, colored options, metrics and filters, failure rollback, read-only controls, mobile and stale project response guard. All writes mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
