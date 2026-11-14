// Read-only browser audit: no business writes or external API requests.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {spawnSync}=require('node:child_process');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const token=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{encoding:'utf8'}).stdout.trim();
  assert.ok(token);
  await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true}]);
  await context.addInitScript(token=>{localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
  let mutations=0;await context.route('**/api/**',route=>{if(['GET','HEAD'].includes(route.request().method()))return route.continue();mutations++;return route.fulfill({status:418,json:{detail:'Read-only audit'}});});
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:8002/?section=url-navigation');
  await page.locator('[data-user-links]').waitFor({state:'visible'});
  const trigger=page.locator('[data-appearance-trigger]'),panel=page.locator('[data-appearance-panel]');
  assert.equal(await panel.isVisible(),false);
  const second=await context.newPage();await second.goto('http://127.0.0.1:8002/?section=url-navigation');
  await second.locator('[data-appearance-trigger]').waitFor();
  fs.mkdirSync('output/ui',{recursive:true});
  await page.locator('[data-ul-search]').fill('Google');
  const colors=[];
  for(const theme of ['green','blue','purple']){
   if(!await panel.isVisible())await trigger.click();
   await panel.locator(`[data-ui-theme="${theme}"]`).click();
   assert.equal(await panel.locator('[aria-pressed="true"]').count(),1);
   await second.waitForFunction(theme=>document.documentElement.dataset.uiTheme===theme,theme);
   assert.equal(await page.locator('[data-ul-search]').inputValue(),'Google');
   colors.push(await page.locator('[data-ul-add]').first().evaluate(el=>getComputedStyle(el).backgroundColor));
   const tokens=await page.evaluate(()=>{const s=getComputedStyle(document.body);return {success:s.getPropertyValue('--success').trim(),background:s.backgroundColor,text:s.color};});
   assert.equal(tokens.success,'#16754f');assert.equal(tokens.background,'rgb(246, 247, 249)');assert.equal(tokens.text,'rgb(37, 48, 68)');
   await page.screenshot({path:`output/ui/appearance-${theme}.png`});
  }
  assert.equal(new Set(colors).size,3,'Primary action must change in all three themes');
  await panel.locator('[data-ui-theme="green"]').focus();await page.keyboard.press('ArrowRight');
  assert.equal(await panel.locator('[data-ui-theme="blue"]').evaluate(el=>el===document.activeElement),true);
  await page.keyboard.press('Escape');assert.equal(await panel.isVisible(),false);
  assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
  await trigger.click();await page.locator('[data-user-links] h1').click();assert.equal(await panel.isVisible(),false);
  await page.reload();assert.equal(await page.evaluate(()=>document.documentElement.dataset.uiTheme),'purple');
  for(const section of ['communication-scripts','auto-prospecting','contacts','keyword-system']){
   await page.goto('http://127.0.0.1:8002/?section='+section);
   await page.locator('#crm-breadcrumb-current').filter({hasText:section==='communication-scripts'?'知识库':section==='auto-prospecting'?'自动获客':section==='contacts'?'客户列表':'关键词库'}).waitFor();
   await trigger.click();assert.equal(await panel.isVisible(),true);await panel.locator('[data-appearance-close]').click();
  }
  await page.setViewportSize({width:390,height:844});await trigger.click();
  const box=await panel.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390&&box.y+box.height<=844);
  await page.screenshot({path:'output/ui/appearance-mobile.png'});
  await page.keyboard.press('Escape');
  await page.evaluate(()=>window.dispatchEvent(new StorageEvent('storage',{key:'tophoo-global-ui-theme',newValue:'unknown'})));
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.uiTheme),'green');
  assert.equal(mutations,0);assert.deepEqual(errors,[]);
  console.log('PASS appearance: three accents, neutral surfaces, semantic colors, persistence, cross-tab sync, preserved search, keyboard, outside dismissal, four modules and mobile. No business writes.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
