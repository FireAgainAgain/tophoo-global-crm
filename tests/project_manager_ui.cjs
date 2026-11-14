// Isolated project UI regression: all API requests use fixtures, no business writes.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const css=fs.readFileSync(path.resolve(__dirname,'../app/templates/index.html'),'utf8').match(/<link rel="stylesheet"[^>]+>/g).join('\n');
  await context.route('**/__pm_ui_test',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html><head>${css}</head><body><div class="crm-project-management"><div id="project-manager" class="pm-page"></div></div><script src="/static/js/crm-project-context.js?v=test"></script></body></html>`}));
  let lists=0, details=0, release, slowStarted, slow=false, failRoleSave=false;const writes=[];let roles=[{id:8,name:"业务员",permissions:["knowledge_base"]}];const {spawnSync}=require("node:child_process");const modules=JSON.parse(spawnSync("python",["-c","import json; from app.core.modules import module_catalog_payload; print(json.dumps([x for x in module_catalog_payload() if not x[\"is_base\"]]))"],{encoding:"utf8"}).stdout);
  const projects=[{id:1,name:'测试项目一',site_url:'https://one.example.com',role:'top_admin',permissions:['project_management']},{id:2,name:'测试项目二',site_url:'https://two.example.com',role:'top_admin',permissions:['project_management']}];
  await context.route('**/api/**',async r=>{
   const req=r.request(),url=new URL(req.url());
   if(req.method()==='PUT'&&/\/roles\/8$/.test(url.pathname)){
    writes.push(req.postDataJSON());if(failRoleSave)return r.fulfill({status:422,json:{detail:[{msg:'模拟权限保存失败'}]}});
    roles=[{...roles[0],...req.postDataJSON()}];return r.fulfill({json:roles[0]});
   }
   if(req.method()==='POST'&&url.pathname.endsWith('/roles')){const role={id:9,...req.postDataJSON()};roles.push(role);return r.fulfill({status:201,json:role});}
   if(req.method()==='POST'&&/\/visit$/.test(url.pathname))return r.fulfill({json:{recorded:true}});
   assert.equal(req.method(),'GET','Only fixture role updates and project visits may write');
   let data=[];
   if(url.pathname==='/api/workspaces')data=[{id:1,name:'测试工作区',role:'owner'}];
   else if(url.pathname==='/api/workspaces/1/projects'){lists++;data=projects;}
   else if(url.pathname.endsWith('/members')){details++;if(slow&&url.pathname.includes('/projects/2/')){slowStarted();await new Promise(resolve=>release=resolve);}data={members:[{id:3,display_name:'测试成员',email:'test@example.com',role:'top_admin',access_source:'工作区管理员',last_accessed_at:'2026-10-16T01:30:00+00:00'},{id:4,display_name:'旧业务员',email:'legacy@example.com',role:'sales'}],modules};}
   else if(url.pathname.endsWith('/roles'))data=roles;
   await r.fulfill({json:data});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8002/__pm_ui_test');
  await page.locator('[data-new]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#project-manager').getAttribute('aria-busy')==='false');
  const buttonStyle=await page.locator('[data-new]').evaluate(el=>({bg:getComputedStyle(el).backgroundImage,color:getComputedStyle(el).color}));
  assert.ok(buttonStyle.bg.includes('gradient'),'Project primary button must have a visible background');
  assert.equal(buttonStyle.color,'rgb(255, 255, 255)');
  await page.locator('[data-new]').click();
  const modalButton=page.locator('.pm-modal [type="submit"]');
  assert.ok((await modalButton.evaluate(el=>getComputedStyle(el).backgroundImage)).includes('gradient'),'Modal primary button must inherit its own theme');
  assert.equal(await page.locator('.pm-modal-kicker').evaluate(el=>getComputedStyle(el).webkitTextFillColor),'rgb(15, 122, 76)');
  assert.equal(await page.locator('.pm-modal .pm-form').evaluate(el=>getComputedStyle(el).display),'block');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.pm-modal').count(),0,'Escape closes form dialog');
  assert.match(await page.locator('[data-member="3"] .pm-member-visit').innerText(),/2026.*10.*16.*09:30/);
  assert.equal(await page.locator('[data-member="4"] .pm-member-visit').innerText(),'暂无记录');
  const before=details;
  assert.equal(await page.locator('[data-project-tool="links"],[data-new-link]').count(),0,'Project management must not include bookmark navigation');
  assert.equal(details,before,'Tab switch must not refetch');
  await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-project-management-view',{detail:{tool:'links'}})));
  assert.equal(details,before,'Reopening current page must not refetch');
  await page.locator('[data-project-id="1"]').click();assert.equal(details,before,'Selecting the current project must do nothing');
  slow=true;const started=new Promise(resolve=>slowStarted=resolve);
  await page.locator('[data-project-id="2"]').click();await started;
  assert.equal(await page.locator('.pm-projects-section').isVisible(),true,'Keep content visible during slow loading');
  await page.locator('[data-project-id="1"]').click();
  await page.waitForFunction(()=>document.querySelector('#project-manager').getAttribute('aria-busy')==='false');
  release();await page.waitForTimeout(100);
  assert.equal(await page.locator('.pm-current-id h3').innerText(),'测试项目一','Old response must not replace latest selection');
  assert.equal(lists,1,'Project switching reuses workspace/project list');

  assert.equal(await page.locator('[data-save-member]').first().evaluate(el=>getComputedStyle(el).color),'rgb(83, 113, 97)');
  assert.equal(await page.locator('.pm-card-tools').first().evaluate(el=>getComputedStyle(el).opacity),'1');
  await page.waitForTimeout(250);
  const out=path.resolve(__dirname,'../output/ui');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'project-management-fixed-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile page must not overflow');
  await page.locator('[data-new]').click();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile modal must not overflow');
  await page.screenshot({path:path.join(out,'project-management-fixed-mobile.png'),fullPage:true});
  await page.locator('.pm-modal [data-cancel]').click();
  slow=false;await page.emulateMedia({reducedMotion:'reduce'});
  await page.locator('[data-project-id="2"]').click();
  assert.equal(await page.locator('.pm-ripple').count(),0);await page.waitForFunction(()=>document.querySelector('#project-manager').getAttribute('aria-busy')==='false');
  await page.setViewportSize({width:1440,height:1000});
  assert.equal(await page.locator('[data-member="4"] [data-member-assignment]').inputValue(),'sales','Legacy roles must not display as top administrator');
  assert.ok((await page.locator('[data-member="3"]').innerText()).includes('不受角色限制'));
  await page.locator('[data-toggle-role-permissions]').click();
  await page.locator('[data-permission-directory="crm"]').click();
  assert.ok((await page.locator('[data-role-permission="customer_list"]').locator('..').innerText()).includes('联系人'));
  for(const directory of ['projects','seo','system','crm']){
   await page.locator(`[data-permission-directory="${directory}"]`).click();
   const boxes=page.locator(`[data-permission-panel="${directory}"] [data-role-permission]`);
   for(let index=0;index<await boxes.count();index++)await boxes.nth(index).selectOption('write');
   assert.equal(await page.locator('[data-permission-panel]:visible').count(),1);
  }
  await page.locator('[data-save-role]').click();await page.locator('.pm-permission-notice').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#project-manager').getAttribute('aria-busy')==='false');
  assert.ok(writes.at(-1).permissions.length>8);assert.equal(writes.at(-1).write_permissions.length,modules.length);
  assert.equal(await page.locator('[data-toggle-role-permissions]').getAttribute('aria-expanded'),'true','Keep the edited permissions open after saving');
  assert.equal(await page.locator('[data-save-role]').isDisabled(),true);await page.screenshot({path:path.join(out,'project-permissions-saved-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'project-permissions-saved-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
  failRoleSave=true;await page.locator('[data-role-permission="customer_list"]').selectOption('read');let message='';page.once('dialog',async dialog=>{message=dialog.message();await dialog.accept();});await page.locator('[data-save-role]').click();await page.waitForFunction(()=>!document.querySelector('[data-save-role]').disabled);
  assert.equal(message,'模拟权限保存失败');assert.equal(await page.locator('[data-role-permission="customer_list"]').inputValue(),'read','Failure preserves the draft');
  await page.locator('[data-add-role]').click();
  await page.locator('.pm-role-form-modal input[name="name"]').fill('Test custom role');
  await page.locator('.pm-role-form-modal [type="submit"]').click();
  await page.locator('[data-role-id="9"]').waitFor();
  assert.equal(await page.locator('[data-role-id="9"] [data-role-name]').inputValue(),'Test custom role');
  assert.equal(await page.locator('[data-member="4"] option[value="9"]').count(),1);
  assert.equal(await page.locator('option[value="builtin:engineer"],option[value="builtin:viewer"],option[value="builtin:order"]').count(),0);
  await page.locator('[data-role-id="8"] [data-permission-directory="crm"]').click();
  assert.equal(await page.locator('[data-role-id="8"] [data-permission-directory="crm"]').evaluate(el=>el.classList.contains('is-active')),true);
  const crmPanel=page.locator('[data-role-id="8"] [data-permission-panel="crm"]');
  await crmPanel.locator('[data-permission-batch="read"]').click();
  assert.equal(await page.locator('[data-role-id="8"] [data-role-permission="customer_list"]').inputValue(),'read');
  assert.equal(await page.locator('[data-role-id="8"] [data-role-permission="rfq"]').inputValue(),'read');
  assert.equal(await page.locator('[data-role-id="8"] [data-role-permission="competitor_research"]').inputValue(),'write','CRM batch must not modify project permissions');
  assert.ok((await page.locator('[data-role-id="8"] [data-role-summary]').innerText()).includes('未保存'));
  assert.equal(await crmPanel.locator('[data-role-permission]').count(),8,'CRM tools, customers and sales documents must be independently editable');
  await page.locator('[data-role-id="8"]').screenshot({path:path.join(out,'project-crm-leaf-permissions.png')});
  await page.locator('[data-role-id="8"] [data-permission-directory="seo"]').click();
  assert.equal(await page.locator('[data-role-id="8"] [data-role-permission="customer_list"]').inputValue(),'read','Switching directories preserves unsaved edits');
  const editor=page.locator('[data-role-id="8"] .pm-permission-content');
  assert.ok(await editor.evaluate(el=>el.scrollHeight<=el.clientHeight+1),'No nested scrolling');
  assert.ok((await editor.boundingBox()).height<440,'Desktop editor stays compact');
  await page.locator('[data-role-id="8"]').screenshot({path:path.join(out,'project-role-compact-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.equal(await page.locator('[data-role-id="8"] [data-permission-panel]:visible').count(),1);
  await page.locator('[data-role-id="8"]').screenshot({path:path.join(out,'project-role-compact-mobile.png')});
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:path.join(out,'project-role-directory-desktop.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: button/modal contrast, form layout, visible tools, no duplicate requests, retained content, stale responses, mobile overflow, reduced motion. All API requests mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
