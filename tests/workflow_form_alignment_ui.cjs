const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('');
  const template=fs.readFileSync('app/templates/partials/crm_customer_list.html','utf8');
  const item={id:1,company_name:'Example HVAC',country:'阿联酋',company_website:'https://hvac.example/',notes:'项目采购；待确认交货地。',source_type:'邮件',grade:'B',created_at:'2026-10-17T12:00:00',contacts:[{id:10,contact_name:'Sam Example',email:'n-sales@hvac.example',notes:'采购专家',is_primary:true}]};
  const writes=[];
  await page.route('**/__form_alignment',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh"><meta charset="utf-8">${css}<body>${template}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/company-types.js"></script><script src="/static/js/crm-customer-workflow.js"></script></body></html>`}));
  await page.route('**/api/**',r=>{
   const req=r.request();
   if(req.method()==='GET')return r.fulfill({json:{items:[item],is_top_admin:true,owners:[{id:4,name:'负责人'}]}});
   writes.push(req.postDataJSON());return r.fulfill({json:{...item,...req.postDataJSON()}});
  });
  await page.goto('http://127.0.0.1:8002/__form_alignment');
  const form=page.locator('[data-workflow-form]');
  const change=async view=>{await page.evaluate(view=>document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view}})),view);await page.waitForFunction(()=>document.querySelector('[data-customer-workflow]').getAttribute('aria-busy')==='false');};
  let shared, sectionColors;
  for(const view of ['leads','contacts']){
   await change(view);await page.locator('[data-workflow-add]').click();
   await form.waitFor({state:'visible'});
   assert.equal(await form.locator('.workflow-social-disclosure[open]').count(),0,'Empty social inputs stay collapsed');
   assert.deepEqual(await form.locator('.workflow-form-section-head h3').allTextContents(),['公司资料','联系人信息','来源与管理','公司备注']);
   for(const theme of ['green','blue']){
    await page.evaluate(theme=>document.documentElement.dataset.uiTheme=theme,theme);
    const colors=await form.locator('.form-group').evaluateAll(els=>els.map(el=>getComputedStyle(el).borderTopColor));
    assert.equal(new Set(colors).size,4,'Each form section must have a distinct color');
    if(sectionColors)assert.deepEqual(colors,sectionColors,'Section meanings must match across views and themes');else sectionColors=colors;
   }
   const names=await form.locator('[name]').evaluateAll(els=>els.map(e=>e.name).filter(n=>!['grade','transfer_followups'].includes(n)));
   if(shared)assert.deepEqual(names,shared);else shared=names;
   assert.equal(await form.locator('[name=notes]').evaluate(e=>e.closest('label').textContent.trim()),'公司备注');
   assert.equal(await form.locator('[data-person-field=notes]').evaluate(e=>e.closest('label').textContent.trim()),'联系人备注');
   await form.locator('[name=company_name]').fill('测试公司');await form.locator('[name=notes]').fill('核心业务摘要');
   await form.locator('[name=contact_name]').fill('采购');await form.locator('[data-person-more]').first().click();await form.locator('[data-person-field=notes]').fill('联系人专属备注');
   await form.locator('.workflow-form-company .workflow-social-disclosure summary').click();
   await form.locator('[name=company_linkedin]').fill('https://linkedin.com/company/example');
   await form.locator('.workflow-form-company .workflow-social-disclosure summary').click();
   await form.locator('[data-person-add]').click();
   await form.locator('[data-person-card]').nth(1).locator('[data-person-field=email]').fill('engineer@example.test');
   await form.locator('[data-person-card]').nth(1).locator('[data-person-primary]').check();
   fs.mkdirSync('output/ui',{recursive:true});
   await form.evaluate(el=>el.scrollTop=0);
   await page.screenshot({path:`output/ui/${view}-form-desktop.png`});
   await page.setViewportSize({width:390,height:844});
   assert.ok(await form.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Form must not overflow on mobile');
   await form.evaluate(el=>el.scrollTop=0);
   await page.screenshot({path:`output/ui/${view}-form-mobile.png`});
   await page.setViewportSize({width:1440,height:1000});
   await form.locator('button[type=submit]').click();await form.waitFor({state:'hidden'});
   const saved=writes.at(-1);assert.equal(saved.notes,'核心业务摘要');assert.equal(saved.contacts[0].notes,'联系人专属备注');assert.equal(saved.contacts.length,2);assert.equal(saved.contacts[1].is_primary,true);
   assert.equal(saved.company_linkedin,'https://linkedin.com/company/example','Collapsed fields must still save their values');
   await page.locator('[data-detail="1"]').first().click();
   const detail=page.locator('[data-workflow-detail]');
   const detailColors=await detail.locator('[data-detail-company],[data-detail-people]').evaluateAll(els=>els.map(el=>getComputedStyle(el).borderTopColor));
   assert.deepEqual(detailColors,sectionColors.slice(0,2),'Company and contact colors must match the editor');
   assert.equal(await detail.locator('[data-detail-notes]').evaluate(el=>getComputedStyle(el).borderTopColor),sectionColors[3]);
   await page.locator('[data-detail-edit="1"]').last().click();
   await form.waitFor({state:'visible'});
   assert.equal(await form.locator('[name=company_name]').inputValue(),'Example HVAC');
   assert.equal(await form.locator('[name=notes]').inputValue(),item.notes);
   assert.equal(await form.locator('[data-person-field=notes]').inputValue(),'采购专家');
   await page.screenshot({path:`output/ui/${view}-form-edit.png`});
   await form.locator('[data-workflow-close]').last().click();
   await page.locator('[data-detail-close]').last().click();
  }
  assert.deepEqual(errors,[]);console.log('Shared form, create/edit population, multi-contact payload and mobile layout passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
