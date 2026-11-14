// All writes are intercepted; production catalogue data is never changed.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path'),os=require('node:os');
(async()=>{
 const auth=spawnSync((process.env.PYTHON || 'python'),['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
 assert.equal(auth.status,0);const token=auth.stdout.trim();
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--no-proxy-server']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  await context.addInitScript(token=>{if(window!==window.top)return;localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
  await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:'http://127.0.0.1:8002'});
  const values=['Heat Exchanger','Finned Tube Heat Exchanger','Copper Tube Coil','Aluminum Fin Coil','Condenser Coil','Evaporator Coil','Cooling Coil','HVAC Coil','Replacement Coil','Custom Heat Exchanger'];
  let item={id:99001,product_code:'vex1-vex1',product_name:'测试换热器',product_group:'换热器',published_through:'',status:'pending',titles:[{code:'vex1',title:'Copper Tube Aluminum Fin Heat Exchanger',optimization_suggestion:'',core_keywords:[]}],images:[]},writes=0,lastSort=null;
  await context.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),match=url.pathname.match(/^\/api\/mic-products\/projects\/7(.*)$/);
   if(!match){if(!['GET','HEAD'].includes(request.method()))return route.fulfill({status:418,json:{detail:'Unexpected write blocked'}});return route.continue();}
   if(request.method()==='PUT'&&match[1]==='/99001'){writes++;item={...item,...request.postDataJSON()};return route.fulfill({json:item});}
   if(request.method()!=='GET')return route.fulfill({status:418,json:{detail:'Unexpected write blocked'}});
   if(match[1]==='/99001')return route.fulfill({json:item});lastSort=url.searchParams.get('sort_order');
   return route.fulfill({json:{items:[item],total:1,title_count:1,page:1,pages:1,page_size:12,groups:['换热器'],dashboard:{total:1,categories:[{name:'换热器',count:1,percentage:100}],titles:{total:1,published:0,unpublished:1},labels:[],social:[]}}});
  });
  const page=await context.newPage();let errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8002/');
  await page.locator('.pm-project-row').first().waitFor({state:'attached'});await page.evaluate(()=>window.tophooNavigateGlobal('mic-products'));
  await page.locator('[data-mic-id="99001"]').waitFor();
  assert.equal(await page.locator('#mic-sort-order').getAttribute('data-order'),'desc');assert.equal(lastSort,'desc');
  await page.locator('#mic-sort-order').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(lastSort,'asc');
  assert.equal(await page.evaluate(()=>localStorage.getItem('tophoo-mic-sort-order:4')),'asc');await page.locator('#mic-sort-order').press('Enter');await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(lastSort,'desc');assert.equal(await page.locator('#mic-sort-order').getAttribute('aria-pressed'),'true');await page.locator('#mic-sort-order').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(lastSort,'asc');
  await page.locator('[data-mic-open-record="99001"]').click();await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('#mic-editor[open]').waitFor();
  assert.equal(await page.locator('#mic-form [name="publishing_group"]').count(),0);
  assert.equal(await page.locator('#mic-publishing-group').count(),0);
  await page.screenshot({path:path.join(os.tmpdir(),'mic-editor-aligned.png')});
  const detail=page.locator('.mic-keyword-editor');await detail.locator('summary').click();
  const fields=page.locator('[data-core-keyword]');assert.equal(await fields.count(),10);
  await fields.nth(0).fill(values[0]);await page.locator('#mic-save').click();
  assert.equal(writes,0);assert.match(await page.locator('#mic-editor-error').innerText(),/10/);
  for(let i=0;i<10;i++)await fields.nth(i).fill(values[i]);
  await fields.nth(9).fill('Copper-Tube-Aluminum-Fin-Heat-Exchanger');await page.locator('#mic-save').click();assert.equal(writes,0);
  await fields.nth(9).fill(values[9]);await fields.nth(9).fill(values[0]);await page.locator('#mic-save').click();assert.equal(writes,0);
  await fields.nth(9).fill(values[9]);
  assert.equal(await detail.locator('.is-priority').count(),3);
  assert.equal(await detail.locator('[data-keyword-move="-1"]').first().isDisabled(),true);
  await detail.locator('[data-keyword-move="1"]').first().click();
  assert.equal(await fields.nth(0).inputValue(),values[1]);assert.equal(await fields.nth(1).inputValue(),values[0]);
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.locator('#mic-editor').evaluate(el=>el.scrollWidth<=el.clientWidth+2));
  await fields.nth(0).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(os.tmpdir(),'mic-keywords-mobile.png')});
  await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});assert.equal(writes,1);
  await page.locator('[data-mic-open-record="99001"]').click();await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('#mic-open-publish-tools').click();await page.locator('#mic-titles-dialog[open]').waitFor();
  await page.locator('.mic-keyword-view summary').click();assert.equal(await page.locator('.mic-keyword-view li').count(),10);assert.notEqual(await page.locator('.mic-keyword-view li').first().evaluate(el=>getComputedStyle(el).backgroundColor),await page.locator('.mic-keyword-view li').nth(3).evaluate(el=>getComputedStyle(el).backgroundColor));
  await page.locator('[data-copy-keywords]').click();assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n'),[values[1],values[0],...values.slice(2)].join('\n'));
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:path.join(os.tmpdir(),'mic-keywords-desktop.png')});
  await page.locator('#mic-titles-edit').click();await page.locator('#mic-editor[open]').waitFor();
  assert.equal(await page.locator('[data-core-keyword]').first().inputValue(),values[1]);
  assert.deepEqual(errors,[]);console.log('PASS: validation, persistence, ordering, priority styling, copy, aligned fields, sorting and mobile layout; all writes mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
