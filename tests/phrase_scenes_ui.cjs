// Scenario interactions use isolated fixtures; no requests reach the CRM.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:950}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let scenes=[],items=[{id:10,category_id:1,scene_id:null,content:'Existing original',translation:'已有话术'}],next=20,canEdit=true;
 const categories=[{id:1,name:'询价沟通'},{id:2,name:'报价跟进'}];
 await context.route('http://scenes.test/**',async route=>{
  const req=route.request(),url=new URL(req.url()),payload=req.postDataJSON(),method=req.method();
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/workbench.css"></head><body style="margin:24px"><script>localStorage.setItem("tophoo-global-selected-project","1")</script>'+fs.readFileSync('app/templates/partials/communication_phrases.html','utf8').replace('data-phrase-library hidden','data-phrase-library')+'</body></html>'});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  let result={};
  if(method==='GET')result={categories,scenes,items,can_edit:canEdit};
  else if(url.pathname.endsWith('/scenes/order'))scenes=payload.ids.map(id=>scenes.find(x=>x.id===id));
  else if(url.pathname.endsWith('/scenes')){result={id:next++,...payload};scenes.push(result);}
  else if(url.pathname.includes('/scenes/')){
   const id=Number(url.pathname.split('/').at(-1));
   if(method==='DELETE'){scenes=scenes.filter(x=>x.id!==id);items=items.map(x=>x.scene_id===id?{...x,scene_id:Number(url.searchParams.get('target_id'))||null}:x);}
   else scenes=scenes.map(x=>x.id===id?{...x,...payload}:x);
  }else if(url.pathname.endsWith('/items')){result={id:next++,...payload};items.unshift(result);}
  else if(url.pathname.includes('/items/')){const id=Number(url.pathname.split('/').at(-1));items=items.map(x=>x.id===id?{...x,...payload}:x);}
  return route.fulfill({json:result});
 });
 await page.goto('http://scenes.test/');
 await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-communication-phrases-view')));
 const root=page.locator('[data-phrase-library]'),dialog=root.locator('dialog');
 await root.locator('[data-phrase-category="1"]').click();
 assert.equal(await root.locator('[data-phrase-scene="all"]').count(),0);assert.equal(await root.locator('[data-phrase-scene="0"]').getAttribute('aria-pressed'),'true');assert.equal(await root.locator('.phrase-card').count(),1);
 async function addScene(name){await root.locator('[data-phrase-add-scene]').click();await dialog.locator('[name="name"]').fill(name);await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});}
 await addScene('收到询价');await addScene('缺少图纸');
 const first=scenes[0].id,second=scenes[1].id;
 await root.locator(`[data-phrase-scene="${first}"]`).click();assert.equal(await root.locator('.phrase-card').count(),0);
 await root.locator('[data-phrase-add]').click();
 assert.equal(await dialog.locator('[name="category_id"]').inputValue(),'1');assert.equal(await dialog.locator('[name="scene_id"]').inputValue(),String(first));
 await dialog.locator('[name="content"]').fill('Thank you for your enquiry.');await dialog.locator('[name="translation"]').fill('感谢您的询价。');await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});
 assert.equal(items[0].scene_id,first);assert.equal(await root.locator('.phrase-card').count(),1);
 await root.locator('[data-phrase-search]').fill('已有');assert.equal(await root.locator('.phrase-card').count(),0);
 await root.locator('[data-phrase-scene="0"]').click();assert.equal(await root.locator('.phrase-card').count(),1);await root.locator('[data-phrase-search]').clear();
 async function menu(id,action){const row=root.locator('.phrase-scene-row').filter({has:page.locator(`[data-phrase-scene="${id}"]`)});await row.locator('summary').click();await row.locator(action).click();}
 await menu(first,'[data-scene-edit]');await dialog.locator('[name="name"]').fill('收到客户询价');await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});assert.equal(scenes[0].name,'收到客户询价');
 await menu(second,'[data-scene-move][data-step="-1"]');await page.waitForFunction(id=>Number(document.querySelector('[data-phrase-scenes] [data-phrase-scene]:not([data-phrase-scene="0"])').dataset.phraseScene)===id,second);assert.equal(scenes[0].id,second);
 await root.locator(`[data-phrase-scene="${first}"]`).click();await root.locator('[data-phrase-edit]').click();
 await dialog.locator('[name="category_id"]').selectOption('2');assert.equal(await dialog.locator('[name="scene_id"]').inputValue(),'');assert.equal(await dialog.locator('[name="scene_id"] option').count(),1);assert.equal(await dialog.locator('[name="scene_id"]').evaluate(el=>el.checkValidity()),true);
 page.once('dialog',d=>d.accept());await dialog.locator('[data-phrase-close]').first().click();
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/phrase-scenes-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 const original=await root.locator('.phrase-original').boundingBox();assert.ok(original.width>260);await page.screenshot({path:'output/ui/phrase-scenes-mobile.png',fullPage:true});
 await menu(first,'[data-scene-delete]');await dialog.locator('[name="target_id"]').selectOption(String(second));await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});assert.equal(items[0].scene_id,second);assert.equal(await root.locator('[data-phrase-scene="0"]').getAttribute('aria-pressed'),'true');
 // Assign the last unassigned phrase: the virtual option disappears and selection stays valid.
 await root.locator('[data-phrase-scene="0"]').click();await root.locator('[data-phrase-edit="10"]').click();
 await dialog.locator('[name="scene_id"]').selectOption(String(second));await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});
 await root.locator('[data-phrase-scene="0"]').waitFor({state:'detached'});assert.equal(await root.locator('[data-phrase-scene="0"]').count(),0);assert.equal(await root.locator(`[data-phrase-scene="${second}"]`).getAttribute('aria-pressed'),'true');assert.equal(await root.locator('.phrase-card').count(),2);
 // Clearing a phrase's assignment brings it back; existing content is preserved.
 await root.locator('[data-phrase-edit="10"]').click();await dialog.locator('[name="scene_id"]').selectOption('');await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});
 assert.equal(await root.locator('[data-phrase-scene="0"]').getAttribute('aria-pressed'),'true');assert.equal(await root.locator('.phrase-card').count(),1);assert.equal(items.find(x=>x.id===10).content,'Existing original');
 await menu(second,'[data-scene-delete]');assert.equal(await dialog.locator('[type="submit"]').count(),0);assert.match(await dialog.innerText(),/请先新增其他场景/);await dialog.locator('[data-phrase-close]').last().click();assert.equal(items[0].scene_id,second);assert.equal(items.length,2);
 assert.equal(await root.locator('[data-phrase-category="0"]').count(),0);await root.locator('[data-phrase-category="2"]').click();assert.equal(await root.locator('.phrase-card').count(),0);
 canEdit=false;await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-communication-phrases-view')));await root.locator('[data-phrase-add]').waitFor({state:'hidden'});await root.locator('[data-phrase-category="1"]').click();assert.equal(await root.locator('[data-phrase-add-scene]').isVisible(),false);assert.equal(await root.locator('.phrase-scene-menu').count(),0);
 assert.deepEqual(errors,[]);console.log('PASS scenario creation, rename, ordering, filtering, assignment, category changes, lossless deletion, readonly and responsive layout. All writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
