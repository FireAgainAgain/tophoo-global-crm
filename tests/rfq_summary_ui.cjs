// RFQ summary buttons use only isolated API fixtures; no business data is changed.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
const items=Array.from({length:12},(_,i)=>({id:i+1,number:'RFQ-'+(i+1),status:i<5?'待处理':i<9?'已报价':i===9?'需求确认中':'沟通失败',inquiry_source:i%2?'MIC':'邮件',owner_user_id:i%2?4:5,company_name:'客户 '+i}));
await context.route('http://rfq.test/**',r=>{const url=new URL(r.request().url());if(url.pathname==='/')return r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/static/css/workbench.css"></head><body>'+fs.readFileSync('app/templates/partials/crm_rfq.html','utf8').replace('data-crm-rfq hidden','data-crm-rfq')+'<script>localStorage.setItem("tophoo-global-selected-project","7")</script></body></html>'});if(url.pathname.startsWith('/static/'))return r.fulfill({path:path.resolve('app'+url.pathname)});assert.equal(r.request().method(),'GET');if(url.pathname.endsWith('/references'))return r.fulfill({json:{contacts:[],is_top_admin:true,owners:[{id:4,name:'Sam'},{id:5,name:'Other'}]}});return r.fulfill({json:items});});
await page.goto('http://rfq.test/');const root=page.locator('[data-crm-rfq]');await root.locator('[data-rfq-stat=""]:enabled').waitFor();
assert.equal(await root.locator('[data-rfq-total]').innerText(),'12');
await root.locator('[data-rfq-size]').selectOption('custom');await root.locator('[data-rfq-custom-count]').fill('2');await root.locator('[data-rfq-custom-count]').press('Tab');await root.locator('[data-rfq-next]').click();
await root.locator('[data-rfq-stat="已报价"]').click();assert.equal(await root.locator('[data-rfq-status]').inputValue(),'已报价');assert.equal(await root.locator('[data-rfq-page]').innerText(),'1 / 2');assert.equal(await root.locator('[data-rfq-stat="已报价"]').getAttribute('aria-pressed'),'true');
await root.locator('[data-rfq-search]').fill('not found');await root.locator('[data-rfq-source]').selectOption('邮件');await root.locator('[data-rfq-owner]').selectOption('4');await root.locator('[data-rfq-stat="待处理"]').click();for(const key of ['search','source','owner'])assert.equal(await root.locator(`[data-rfq-${key}]`).inputValue(),'');assert.match(await root.locator('[data-rfq-summary]').innerText(),/共 5 条/);
await root.locator('[data-rfq-status]').selectOption('推进中');assert.equal(await root.locator('[data-rfq-stat="推进中"]').getAttribute('aria-pressed'),'true');assert.match(await root.locator('[data-rfq-summary]').innerText(),/共 1 条/);
await root.locator('[data-rfq-stat="已成交"]').focus();await page.keyboard.press('Enter');assert.match(await root.locator('[data-rfq-summary]').innerText(),/共 0 条/);assert.equal(await root.locator('[data-rfq-total]').innerText(),'12');
await root.locator('[data-rfq-stat="已关闭"]').click();assert.match(await root.locator('[data-rfq-summary]').innerText(),/共 2 条/);await root.locator('[data-rfq-refresh]').click();await root.locator('[data-rfq-stat="已关闭"]:enabled').waitFor();assert.equal(await root.locator('[data-rfq-stat="已关闭"]').getAttribute('aria-pressed'),'true');
await root.locator('[data-rfq-stat=""]').click();assert.match(await root.locator('[data-rfq-summary]').innerText(),/共 12 条/);await root.locator('[data-rfq-reset]').click();assert.equal(await root.locator('[data-rfq-stat=""]').getAttribute('aria-pressed'),'true');
await root.locator('[data-rfq-search]').fill('客户');assert.equal(await root.locator('[data-rfq-clear-filter="query"]').count(),1);await root.locator('[data-rfq-clear-filter="query"]').click();assert.equal(await root.locator('[data-rfq-search]').inputValue(),'');
await root.locator('[data-preview-rfq]').first().click();await root.locator('[data-rfq-preview]').waitFor({state:'visible'});assert.equal(await root.locator('.rfq-notes-details').count(),0);await root.locator('[data-rfq-preview] button[data-close-rfq-preview]').click();assert.equal(await root.locator('[data-rfq-preview]').isHidden(),true);
await root.locator('[data-rfq-add]').click();assert.equal(await root.locator('[name="notes"]').count(),0);await root.locator('.rfq-editor-head [data-cancel]').click();
// Keep the controls compact, including when a desktop sidebar narrows the content.
for (const width of [1440,900,700,390,320]) {
  await page.setViewportSize({width,height:900});
  const head=await root.locator('.rfq-page-head').boundingBox();
  assert.ok(head.height <= (width>700?120:240), `Compact header at ${width}px`);
  for(const button of await root.locator('[data-rfq-stat]').all()) {
    assert.ok(await button.evaluate(el=>el.scrollWidth<=el.clientWidth), 'Status label and count fit together');
  }
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
}
await page.setViewportSize({width:900,height:900});
await root.evaluate(el=>el.style.width='340px');
assert.ok((await root.locator('.rfq-page-head').boundingBox()).height<=240);
assert.equal(await root.locator('[data-rfq-stat="待处理"]').evaluate(el=>getComputedStyle(el.parentElement).gridTemplateColumns.split(' ').length),3,'Narrow desktop panels use two status rows');
await root.evaluate(el=>el.style.removeProperty('width'));
await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);console.log('PASS: statistics clicks, matching counts, legacy statuses, clear conflicting filters, first page, dropdown sync, keyboard, refresh and mobile.');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
