// Exercise the phrase workspace against isolated data; all writes are intercepted.
const { chromium }=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const fixture=process.env.PHRASE_PREVIEW_FILE?JSON.parse(fs.readFileSync(process.env.PHRASE_PREVIEW_FILE,'utf8')):{
   categories:[{id:1,name:'客户开发'},{id:2,name:'询价沟通'}],
   scenes:[{id:1,category_id:1,name:'初次联系'},{id:2,category_id:2,name:'收到询价'}],
   items:Array.from({length:55},(_,i)=>({id:i+1,category_id:i<45?1:2,scene_id:i<45?1:2,content:`Could you send the drawing for unit ${i+1}?`,translation:`方便发一下 ${i+1} 号产品的图纸吗？`}))
  };
  let categories=fixture.categories,scenes=fixture.scenes,items=fixture.items,canEdit=true,next=10000;
  const originalCount=items.length,firstCategoryCount=items.filter(x=>x.category_id===categories[0].id).length,errors=[];
  const context=await browser.newContext({viewport:{width:1440,height:950}}),page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  await context.route('http://phrase-experience.test/**',async route=>{
   const request=route.request(),url=new URL(request.url()),method=request.method(),payload=request.postDataJSON();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/workbench.css"><body style="margin:24px"><script>localStorage.setItem("tophoo-global-selected-project","7")</script>'+fs.readFileSync('app/templates/partials/communication_phrases.html','utf8').replace('data-phrase-library hidden','data-phrase-library')+'</body></html>'});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   if(method==='GET')return route.fulfill({json:{categories,scenes,items,can_edit:canEdit}});
   if(url.pathname.endsWith('/scenes')){
    if(scenes.some(x=>x.category_id===payload.category_id&&x.name===payload.name))return route.fulfill({status:409,json:{detail:'场景名称重复'}});
    const item={id:next++,...payload};scenes.push(item);return route.fulfill({json:item});
   }
   if(url.pathname.endsWith('/items')){const item={id:next++,...payload};items.unshift(item);return route.fulfill({json:item});}
   throw Error('Unexpected write: '+method+' '+url.pathname);
  });
  await page.goto('http://phrase-experience.test/');
  const root=page.locator('[data-phrase-library]'),dialog=root.locator('dialog');
  async function load(){await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-communication-phrases-view')));await root.locator('[data-phrase-count]').filter({hasText:'条话术'}).waitFor();}
  await load();
  assert.equal(await root.locator('[data-phrase-scenes-panel]').isVisible(),true);assert.equal(await root.locator('[data-phrase-category="0"]').count(),0);assert.equal(await root.locator('[data-phrase-category="'+categories[0].id+'"]').getAttribute('aria-pressed'),'true');
  assert.equal(await root.locator('[data-phrase-move]').count(),0);
  assert.equal(await root.locator('[data-phrase-scenes] [data-phrase-scene="all"]').count(),0);
  if(firstCategoryCount>40)await root.locator('[data-phrase-more]').click();assert.equal(await root.locator('.phrase-card').count(),firstCategoryCount);
  await root.locator('[data-phrase-sort]').click();assert.equal(await root.locator('[data-phrase-move]').count(),firstCategoryCount*2);
  await root.locator('[data-phrase-sort]').click();assert.equal(await root.locator('[data-phrase-move]').count(),0);
  const search=root.locator('[data-phrase-search]'),firstScene=scenes[0];
  await search.fill(firstScene.name);
  assert.equal(await root.locator('.phrase-card').count(),Math.min(40,items.filter(x=>x.scene_id===firstScene.id).length));
  await root.locator('[data-phrase-clear-search]').first().click();
  await search.fill(items[0].content.split(' ').slice(0,3).join(' '));assert.ok(await root.locator('.phrase-original mark').count()>0);
  await root.locator('[data-phrase-clear-search]').first().click();
  await root.locator('[data-phrase-category="'+categories[0].id+'"]').click();
  const summary=root.locator('.phrase-category-menu summary').first();await summary.click();
  const menu=root.locator('.phrase-category-menu[open]>div');await menu.waitFor({state:'visible'});
  let bounds=await menu.boundingBox(),trigger=await summary.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=1440&&Math.abs(bounds.y-trigger.y)<200);
  await page.keyboard.press('Escape');assert.equal(await root.locator('.phrase-category-menu[open]').count(),0);
  const sceneSummary=root.locator('.phrase-scene-menu summary').first();await sceneSummary.click();
  const sceneMenu=root.locator('.phrase-scene-menu[open]>div');await sceneMenu.waitFor({state:'visible'});
  bounds=await sceneMenu.boundingBox();trigger=await sceneSummary.boundingBox();assert.ok(Math.abs(bounds.x-trigger.x)<150);
  await root.locator('[data-phrase-heading]').click();assert.equal(await root.locator('.phrase-scene-menu[open]').count(),0);
  fs.mkdirSync('output/ui',{recursive:true});
  await page.screenshot({path:'output/ui/phrase-library-desktop.png'});
  await root.locator('[data-phrase-add]').click();await page.screenshot({path:'output/ui/phrase-library-editor.png'});await dialog.locator('[data-phrase-close]').last().click();
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'output/ui/phrase-library-mobile.png'});
  await sceneSummary.click();await sceneMenu.waitFor({state:'visible'});bounds=await sceneMenu.boundingBox();assert.ok(bounds.x>=0&&bounds.y>=0&&bounds.x+bounds.width<=390&&bounds.y+bounds.height<=844);await page.keyboard.press('Escape');
  // A category with no scenes can create one without losing the phrase draft.
  categories.push({id:999,name:'新分类'});await load();await root.locator('[data-phrase-category="999"]').click();
  await root.locator('[data-phrase-add]').click();await dialog.locator('[name="content"]').fill('Keep this unsaved draft.');await dialog.locator('[name="translation"]').fill('保留这段尚未保存的内容。');
  assert.equal(await dialog.locator('[name="scene_id"]').evaluate(el=>el.checkValidity()),true);
  await dialog.locator('[data-phrase-inline-scene]').click();await dialog.locator('[data-phrase-scene-name]').fill('新的场景');await dialog.locator('[data-phrase-create-scene]').click();
  await dialog.locator('[data-phrase-inline-create]').waitFor({state:'hidden'});
  assert.equal(await dialog.locator('[name="content"]').inputValue(),'Keep this unsaved draft.');
  assert.equal(await dialog.locator('[name="scene_id"]').evaluate(el=>el.checkValidity()),true);
  await dialog.locator('[data-phrase-inline-scene]').click();await dialog.locator('[data-phrase-scene-name]').fill('新的场景');await dialog.locator('[data-phrase-create-scene]').click();await dialog.locator('[data-phrase-form-error]').waitFor({state:'visible'});
  assert.equal(await dialog.locator('[name="content"]').inputValue(),'Keep this unsaved draft.');
  await dialog.locator('[type="submit"]').click();await dialog.waitFor({state:'hidden'});assert.equal(items.length,originalCount+1);assert.equal(await root.locator('.phrase-card').count(),1);
  canEdit=false;await load();assert.equal(await root.locator('[data-phrase-sort]').isVisible(),false);assert.equal(await root.locator('[data-phrase-add]').isVisible(),false);assert.equal(await root.locator('[data-phrase-edit]').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS grouping, scene search, highlighting, paging, sort mode, anchored menus, mobile layout, inline scene creation, draft preservation, error recovery and readonly. All writes mocked.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
