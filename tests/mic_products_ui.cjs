// Real catalogue is read-only; every browser write uses in-memory fixtures.
const {chromium}=require('playwright'),{spawnSync}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const root=path.resolve(__dirname,'..'),out=path.join(root,'output/ui');fs.mkdirSync(out,{recursive:true});
  const result=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:root,encoding:'utf8'});assert.equal(result.status,0);const token=result.stdout.trim();
  const context=await browser.newContext({viewport:{width:1500,height:1000}});
  await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  await context.addInitScript(token=>{if(window!==window.top)return;localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
  let fixture=false,writes=0,imageVersion=0;
  const items=[{id:9001,product_code:'vex31-vex40',product_name:'铜管不锈钢翅片蒸发器',product_group:'换热器',titles:Array.from({length:10},(_,i)=>({code:'sam'+(31+i),title:'Copper Tube Stainless Steel Fin Evaporator Coil for Industrial Refrigeration',optimization_suggestion:''})),images:[]}];
  const state=item=>!item.published_through?'pending':Number(item.published_through.replace(/\D/g,''))===Number(item.product_code.split('-').at(-1).replace(/\D/g,''))?(item.titles.some(t=>t.optimization_suggestion?.trim())?'optimizing':'published'):'publishing';
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII=','base64');
  await context.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url()),m=url.pathname.match(/^\/api\/mic-products\/projects\/(\d+)(.*)$/);
   if(!m){if(!['GET','HEAD'].includes(req.method()))return route.fulfill({status:418,json:{detail:'Writes blocked'}});return route.continue();}
   if(!fixture){if(req.method()!=='GET')return route.fulfill({status:418,json:{detail:'Writes blocked'}});return route.continue();}
   const suffix=m[2];items.forEach(item=>item.status=state(item));
   if(suffix.includes('/images/')&&req.method()==='GET')return route.fulfill({contentType:'image/png',body:png});
   if(req.method()==='GET'&&!suffix){const all=m[1]==='7'?items:[];let visible=all;const q=url.searchParams.get('q'),group=url.searchParams.get('group'),status=url.searchParams.get('status');if(q)visible=visible.filter(p=>p.product_code.includes(q)||p.titles.some(t=>t.title.includes(q)));if(group)visible=visible.filter(p=>p.product_group===group);if(status)visible=visible.filter(p=>p.status===status);const titlePub=(p,t)=>Boolean(p.published_through)&&Number(t.code.replace(/\D/g,''))<=Number(p.published_through.replace(/\D/g,''));const ts=url.searchParams.get('title_state');if(ts)visible=visible.filter(p=>p.titles.some(t=>titlePub(p,t)===(ts==='published')));const sp=url.searchParams.get('social_platform'),ss=url.searchParams.get('social_status');if(sp&&ss)visible=visible.filter(p=>Boolean(p.social?.[sp]?.published)===(ss==='published'));const counts={};all.forEach(p=>counts[p.product_group]=(counts[p.product_group]||0)+1);const dashboard={total:all.length,categories:Object.entries(counts).map(([name,count])=>({name,count,percentage:Math.round(count/all.length*1000)/10})),labels:Object.entries({pending:'待发布',publishing:'正在发布',optimizing:'待优化',published:'已发布'}).map(([status,name])=>({status,name,count:all.filter(p=>p.status===status).length}))};const allTitles=all.flatMap(p=>p.titles.map(t=>titlePub(p,t))),publishedTitles=allTitles.filter(Boolean).length;dashboard.titles={total:allTitles.length,published:publishedTitles,unpublished:allTitles.length-publishedTitles};dashboard.social=['linkedin','facebook','instagram','youtube'].map(platform=>({platform,published:all.filter(p=>p.social?.[platform]?.published).length,unpublished:all.filter(p=>!p.social?.[platform]?.published).length}));return route.fulfill({json:{items:visible,total:visible.length,title_count:visible.reduce((n,p)=>n+p.titles.length,0),page:1,pages:1,groups:Object.keys(counts),dashboard}});}
   if(req.method()==='GET'&&suffix.endsWith('/product-social')){const item=items.find(p=>p.id===Number(suffix.split('/')[1]));return route.fulfill({json:{title:item.titles[0]?.title||item.product_name,product_code:item.product_code,product_name:item.product_name,parameters:'',contact:'Tel&WAP: +1 202 555 0100',platforms:Object.fromEntries(['facebook','instagram','linkedin','youtube'].map(p=>[p,{content:'',translation:'',published:false,published_at:''}]))}});}
   if(req.method()==='GET')return route.fulfill({json:items.find(p=>p.id===Number(suffix.slice(1)))});
   writes++;
   if(suffix.endsWith('/progress')){const item=items.find(p=>p.id===Number(suffix.split('/')[1])),raw=req.postDataJSON().published_through;item.published_through=raw?'sam'+raw.replace(/\D/g,''):'';item.status=state(item);return route.fulfill({json:{id:item.id,published_through:item.published_through,status:item.status}});}
   if(suffix.endsWith('/social')){const item=items.find(p=>p.id===Number(suffix.split('/')[1]));item.social={...item.social,...req.postDataJSON()};return route.fulfill({json:{id:item.id,social:item.social}});}
   if(suffix.endsWith('/images')){const item=items.find(p=>p.id===Number(suffix.split('/')[1])),id=++imageVersion,base=`/api/mic-products/projects/7/${item.id}/images/${id}`;item.images=[{id,url:base,thumbnail_url:base+'/thumbnail',filename:'product.png'}];return route.fulfill({status:201,json:{images:item.images}});}
   if(suffix.includes('/images/')&&req.method()==='DELETE'){const item=items.find(p=>p.id===Number(suffix.split('/')[1]));item.images=[];return route.fulfill({json:{images:[]}});}
   if(req.method()==='DELETE'){const index=items.findIndex(item=>item.id===Number(suffix.slice(1)));if(index<0)return route.fulfill({status:404,json:{detail:'Not found'}});items.splice(index,1);return route.fulfill({json:{deleted:true}});}
   if(req.method()==='POST'){const item={...req.postDataJSON(),id:Math.max(...items.map(item=>item.id))+1,images:[]};item.status=state(item);items.push(item);return route.fulfill({status:201,json:item});}
   if(req.method()==='PUT'){const item=items.find(p=>p.id===Number(suffix.slice(1)));Object.assign(item,req.postDataJSON());item.status=state(item);return route.fulfill({json:item});}
   return route.fulfill({status:418,json:{detail:'Unexpected write'}});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.stack));page.on('dialog',d=>d.accept());
  await page.goto('http://127.0.0.1:8002/');await page.locator('.pm-project-row[data-project-id="4"]').waitFor({state:'attached'});await page.evaluate(()=>window.tophooNavigateGlobal('mic-products'));
  await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===10);if(await page.locator('#mic-sort-order').getAttribute('data-order')!=='asc')await page.locator('#mic-sort-order').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));
  async function openTab(id,tab){
   await page.locator(`[data-mic-open-record="${id}"]`).click();
   await page.locator(`[data-mic-editor-tab="${tab}"]`).click();
  }
  async function openTitles(id){
   await openTab(id,'mic');
   await page.locator('#mic-open-publish-tools').click();
  }
  async function openAssistant(index){
   const assistant=page.locator('[data-mic-assistant]').nth(index);
   if(!await assistant.evaluate(el=>el.open))await assistant.locator('summary').click();
  }
  async function checkInnerScroll(){
   const region=page.locator('.mic-table-scroll'),footer=page.locator('.mic-pagination'),filters=page.locator('.mic-filters');
   const area=await region.boundingBox(),footerBefore=await footer.boundingBox(),filterBefore=await filters.boundingBox();
   assert.ok(area.height>100,'List must have usable height');
   assert.ok(footerBefore.y+footerBefore.height<=page.viewportSize().height+1,'Pagination stays visible');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+1),'Outer page must fit viewport');
   await page.mouse.move(area.x+area.width-25,area.y+Math.min(80,area.height/2));await page.mouse.wheel(0,800);
   await page.waitForFunction(()=>document.querySelector('.mic-table-scroll').scrollTop>0);
   assert.equal((await footer.boundingBox()).y,footerBefore.y);assert.equal((await filters.boundingBox()).y,filterBefore.y);
   assert.equal(await page.evaluate(()=>scrollY),0);
   const header=page.locator('.mic-record-table th').first();if(await header.isVisible())assert.ok(Math.abs((await header.boundingBox()).y-area.y)<2,'Table header stays pinned');
   await region.evaluate(el=>el.scrollTop=0);
  }
  const realCatalogue=await page.evaluate(async()=>{const r=await fetch('/api/mic-products/projects/7?page_size=100',{headers:window.tophooAuth.headers()});return r.json();});const realTotal=realCatalogue.total,realPublished=realCatalogue.dashboard.labels.find(x=>x.status==='published').count;
  async function checkTitleTools(){
   await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:'http://127.0.0.1:8002'});
   const chosen=realCatalogue.items.find(p=>p.titles.length===10&&p.titles.some(t=>t.optimization_suggestion));await openTitles(chosen.id);await page.locator('#mic-titles-dialog[open]').waitFor();
   const pair=page.locator('.mic-name-pair').first(),title=await pair.locator('.mic-title-text').innerText();
   await pair.locator('[data-copy-title]').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),title);assert.equal(await pair.locator('[data-copy-title]').innerText(),'已复制');
   const names=pair.locator('xpath=ancestor::*[contains(@class,"mic-names-cell")]');assert.equal(await names.locator('.mic-name-pair').count(),10);
   const last=names.locator('.mic-name-pair').last();await last.locator('[data-copy-title]').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),await last.locator('.mic-title-text').innerText());
   assert.equal(await pair.locator('.mic-title-actions button').count(),3);
   assert.equal(await page.locator('[data-title-social]').count(),0);
   const suggestion=page.locator('.mic-suggestion-details').first();
   const original=await suggestion.locator('p').textContent();
   await suggestion.locator('p').evaluate(el=>el.textContent='长建议与超长链接 https://example.com/'+('LongKeywordWithoutSpaces'.repeat(120)+'\n').repeat(8));
   await suggestion.locator('summary').click();assert.equal(await suggestion.evaluate(el=>el.open),true);
   assert.ok(await suggestion.locator('p').evaluate(el=>el.clientHeight<=240&&el.scrollHeight>el.clientHeight&&el.scrollWidth<=el.clientWidth+1));
   await suggestion.locator('p').evaluate((el,value)=>el.textContent=value,original);
   await suggestion.locator('summary').click();assert.equal(await suggestion.evaluate(el=>el.open),false);
   await page.locator('#mic-titles-body').evaluate(el=>el.scrollTop=0);assert.ok(await page.locator('#mic-titles-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth));await page.screenshot({path:path.join(out,page.viewportSize().width<600?'mic-names-dialog-mobile.png':'mic-names-dialog-desktop.png')});
   await page.locator('[data-titles-close]').first().click();await page.locator('#mic-titles-dialog').waitFor({state:'hidden'});await page.locator('.mic-table-scroll').evaluate(el=>el.scrollTop=0);assert.equal(writes,0);
  }
  await checkTitleTools();
  assert.equal(await page.locator('#mic-social-summary [data-social-filter]').count(),8);
  await openAssistant(1);await page.locator('[data-social-filter="linkedin"][data-social-status="unpublished"]').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));
  assert.match(await page.locator('#mic-active-filters').innerText(),/领英 · 未发布/);
  assert.equal(await page.locator('[data-social-filter="linkedin"][data-social-status="unpublished"]').getAttribute('aria-pressed'),'true');
  await openAssistant(1);await page.locator('[data-social-filter="linkedin"][data-social-status="published"]').click();await page.waitForFunction(n=>document.querySelectorAll('[data-mic-id]').length===Math.min(n,10),realCatalogue.dashboard.social.find(x=>x.platform==='linkedin').published);
  await page.locator('.mic-social-all').click();await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===10);
  assert.equal(await page.locator('.mic-header').count(),0);
  await page.locator('#mic-page-size').fill('7');await page.locator('#mic-page-size').press('Enter');await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===7);
  assert.equal(await page.locator('#mic-page').innerText(),`1 / ${Math.ceil(realTotal/7)}`);await page.locator('#mic-next').click();await page.waitForFunction(()=>document.querySelector('#mic-page').textContent.startsWith('2 / '));
  assert.equal(await page.locator('[data-mic-id]').count(),7);
  await page.reload();await page.locator('.pm-project-row[data-project-id="4"]').waitFor({state:'attached'});await page.evaluate(()=>window.tophooNavigateGlobal('mic-products'));await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===7);
  assert.equal(await page.locator('#mic-page-size').inputValue(),'7');assert.equal(await page.locator('#mic-page').innerText(),`1 / ${Math.ceil(realTotal/7)}`);
  await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));
  await page.locator('#mic-page-size').fill('12');await page.locator('#mic-page-size').press('Enter');await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===12);
  assert.equal(await page.locator('#mic-import').count(),0);assert.equal(await page.locator('[data-mic-id]').count(),12);
  assert.equal(await page.locator('.mic-record-table tr[data-mic-id]').count(),12);assert.equal(await page.locator('[data-mic-assistant][open]').count(),0);await openAssistant(0);assert.equal(await page.locator('.mic-name-pair').count(),0);
  assert.deepEqual(await page.locator('#mic-status-filter option').allTextContents(),['全部状态','待发布','正在发布','待优化','已发布']);
  assert.equal(await page.locator('#mic-label-summary [data-title-state="published"] strong').textContent(),String(realCatalogue.dashboard.titles.published));assert.equal(await page.locator('#mic-category-panel').count(),0);
  assert.equal(await page.locator('#mic-group-status-summary [data-mic-status]').count(),4);
  for(const entry of realCatalogue.dashboard.labels)assert.equal(await page.locator(`#mic-group-status-summary [data-mic-status="${entry.status}"] strong`).innerText(),String(entry.count));
  await page.locator('#mic-group-status-summary [data-mic-status="optimizing"]').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(await page.locator('#mic-status-filter').inputValue(),'optimizing');assert.equal(await page.locator('#mic-name-view').inputValue(),'all');
  await page.locator('.mic-group-status-all').click();await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(await page.locator('#mic-status-filter').inputValue(),'');
  await page.locator('[data-mic-assistant] summary').first().click();
  assert.ok((await page.locator('#mic-overview').boundingBox()).height<150,'Overview must be compact by default');
  await page.screenshot({path:path.join(out,'mic-suggestions-desktop.png')});
  await checkInnerScroll();
  const productTop=(await page.locator('[data-mic-id]').first().boundingBox()).y;assert.ok(productTop<430,'Desktop product top: '+productTop);
  await page.screenshot({path:path.join(out,'mic-suggestions-desktop.png')});
  const realPublishing=realCatalogue.items.filter(p=>p.status==='publishing');await openAssistant(0);await page.locator('#mic-status-filter').selectOption('publishing');await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(await page.locator('[data-mic-id]').count(),Math.min(realPublishing.length,12));
  assert.deepEqual(await page.locator('[data-mic-id]').evaluateAll(rows=>rows.map(row=>Number(row.dataset.micId))),realPublishing.slice(0,12).map(p=>p.id));
  await page.screenshot({path:path.join(out,'mic-publication-progress.png')});
  await page.locator('#mic-reset').click();await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===12);
  await page.locator('#mic-search').fill('vex95');await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===1);await page.locator('[data-mic-id] .mic-edit-button').click();await page.locator('#mic-editor[open]').waitFor();
  assert.equal(await page.locator('#mic-name-fields textarea[data-code="vex95"]').inputValue(),'Stainless Steel Tube Copper Fin Condenser Coil');assert.equal(await page.locator('#mic-name-fields textarea[data-code="vex95"]').locator('..').locator('..').locator('[data-mic-suggestion]').inputValue(),realCatalogue.items.find(p=>p.titles.some(t=>t.code==='vex95')).titles.find(t=>t.code==='vex95').optimization_suggestion);
  await page.locator('[data-mic-editor-tab="mic"]').click();assert.equal(await page.locator('#mic-editor-status').innerText(),'待优化');assert.equal(await page.locator('#mic-form [name="status"]').count(),0);assert.equal(await page.locator('#mic-name-fields [data-mic-suggestion]').count(),10);
  await page.screenshot({path:path.join(out,'mic-suggestions-editor.png')});await page.keyboard.press('Escape');await page.locator('#mic-reset').click();await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===12);
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'mic-suggestions-mobile.png')});
  await checkTitleTools();
  await checkInnerScroll();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.ok((await page.locator('[data-mic-id]').first().boundingBox()).y<760,'Mobile first product must enter initial viewport');
  await page.locator('[data-mic-id] .mic-edit-button').first().click();await page.locator('#mic-editor[open]').waitFor();await page.screenshot({path:path.join(out,'mic-suggestions-editor-mobile.png')});assert.ok(await page.locator('#mic-editor').evaluate(el=>el.scrollWidth<=el.clientWidth));await page.keyboard.press('Escape');await page.setViewportSize({width:1500,height:1000});
  fixture=true;await page.evaluate(()=>window.tophooNavigateGlobal('mic-products'));await page.locator('[data-mic-id="9001"]').waitFor();
  await openTitles(9001);await page.locator('#mic-titles-dialog[open]').waitFor();const quickCard=page.locator('#mic-titles-dialog');assert.equal(await quickCard.locator('.mic-name-pair').count(),10);assert.equal(await page.locator('.mic-more-names').count(),0);
  await quickCard.locator('[data-title-code="vex31"] [data-copy-title]').click();assert.equal(items[0].published_through,undefined);
  await quickCard.locator('[data-publish-title="vex31"]').click();await page.waitForFunction(()=>document.querySelector('[data-title-code="vex31"]').dataset.titlePublished==='true');
  assert.equal(items[0].published_through,'vex31');assert.equal(await quickCard.locator('.is-title-published').count(),1);assert.equal(await quickCard.locator('.is-title-unpublished').count(),9);
  assert.notEqual(await quickCard.locator('.is-title-published').evaluate(el=>getComputedStyle(el).backgroundColor),await quickCard.locator('.is-title-unpublished').first().evaluate(el=>getComputedStyle(el).backgroundColor));
  assert.ok(await quickCard.locator('.mic-code-status code').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=12));
  await page.locator('#mic-titles-body').evaluate(el=>el.scrollTop=100);await quickCard.locator('[data-publish-title="vex36"]').scrollIntoViewIfNeeded();const progressScroll=await page.locator('#mic-titles-body').evaluate(el=>el.scrollTop);
  await quickCard.locator('[data-publish-title="vex36"]').click();await page.waitForFunction(()=>document.querySelectorAll('.is-title-published').length===6);assert.ok(Math.abs(await page.locator('#mic-titles-body').evaluate(el=>el.scrollTop)-progressScroll)<2,'Quick update preserves list position');
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await quickCard.screenshot({path:path.join(out,'mic-publishing-mobile.png')});await page.setViewportSize({width:1500,height:1000});
  await page.locator('#mic-titles-view').selectOption('unpublished');await page.waitForFunction(()=>document.querySelectorAll('.mic-name-pair').length===4);assert.equal(await quickCard.locator('.is-title-published').count(),0);
  assert.equal(await page.locator('[data-progress-input],.mic-inline-progress').count(),0);
  await quickCard.locator('[data-publish-title="vex40"]').click();await page.waitForFunction(()=>document.querySelector('.mic-all-published'));assert.equal(items[0].status,'published');await page.waitForFunction(()=>document.querySelector('[data-title-state="published"] strong').textContent==='10');
  await page.locator('#mic-titles-edit').click();await page.locator('#mic-editor[open]').waitFor();await page.locator('#mic-form [name=published_through]').fill('');await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));assert.equal(items[0].status,'pending');
  await openAssistant(0);await page.locator('#mic-name-view').selectOption('unpublished');await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));await openTitles(9001);await page.locator('#mic-titles-dialog[open]').waitFor();assert.equal(await page.locator('#mic-titles-view').inputValue(),'unpublished');
  await page.locator('#mic-titles-edit').click();await page.locator('#mic-editor[open]').waitFor();await page.keyboard.press('Escape');
  await page.locator('#mic-name-view').selectOption('all');await page.waitForFunction(()=>!document.querySelector('#mic-list').hasAttribute('aria-busy'));writes=0;
  await page.locator('[data-mic-id="9001"] .mic-edit-button').click();await page.locator('#mic-editor[open]').waitFor();
  await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('#mic-name-fields textarea[data-code]').first().fill('Edited product name');await page.locator('#mic-name-fields [data-remove-name]').last().click();await page.locator('#mic-add-name').click();await page.locator('#mic-name-fields textarea[data-code]').last().fill('Another name');assert.equal(await page.locator('#mic-name-fields textarea[data-code]').last().getAttribute('data-code'),'vex40');
  await page.locator('[data-mic-suggestion]').first().fill('建议补充具体用途');assert.equal(await page.locator('#mic-editor-status').innerText(),'待发布');await page.locator('#mic-form [name=published_through]').fill('36');assert.equal(await page.locator('#mic-editor-status').innerText(),'正在发布');await page.locator('#mic-image-upload').setInputFiles({name:'one.png',mimeType:'image/png',buffer:png});assert.equal(writes,0);await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});assert.equal(items[0].status,'publishing');assert.equal(items[0].titles[0].optimization_suggestion,'建议补充具体用途');assert.equal(items[0].images.length,1);
  await openAssistant(0);await page.locator('#mic-status-filter').selectOption('publishing');await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===1);await page.locator('[data-mic-id="9001"] .mic-edit-button').click();await page.locator('#mic-editor[open]').waitFor();await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('[data-mic-suggestion]').first().fill('');assert.equal(await page.locator('#mic-editor-status').innerText(),'正在发布');await page.locator('#mic-form [name=published_through]').fill('40');assert.equal(await page.locator('#mic-editor-status').innerText(),'已发布');await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===0);assert.equal(await page.locator('#mic-label-summary [data-title-state="published"] strong').textContent(),'10');await page.locator('.mic-status-all').click();await page.locator('[data-mic-id="9001"]').waitFor();
  await page.locator('[data-mic-id="9001"] .mic-edit-button').click();await page.locator('#mic-editor[open]').waitFor();await page.locator('#mic-image-upload').setInputFiles({name:'replacement.png',mimeType:'image/png',buffer:png});await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});assert.equal(items[0].images.length,1);assert.equal(imageVersion,2);
  await page.locator('#mic-add').click();await page.locator('#mic-form [name="product_name"]').fill('新产品');await page.locator('#mic-form [name="content"]').fill('简介、参数和联系方式');await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('#mic-form [name="product_code"]').fill('vex501-vex510');await page.locator('#mic-add-name').click();await page.locator('#mic-name-fields textarea[data-code]').fill('First name');await page.locator('#mic-add-name').click();await page.locator('#mic-name-fields textarea[data-code]').last().fill('Second name');await page.locator('[data-mic-suggestion]').last().fill('优化第二条');await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});assert.equal(items[1].titles.length,2);assert.equal(items[1].status,'pending');assert.equal(items[1].titles[0].code,'vex501');assert.equal(items[1].titles[1].code,'vex502');
  await page.locator('#mic-add').click();await page.locator('#mic-editor[open]').waitFor();
  assert.deepEqual(await page.locator('#mic-form input[required]').evaluateAll(inputs=>inputs.map(el=>el.name).sort()),['product_code','product_name']);
  assert.equal(await page.locator('#mic-name-fields textarea').count(),0);
  await page.locator('#mic-form [name=product_name]').fill('Only basic details');await page.locator('[data-mic-editor-tab="mic"]').click();await page.locator('#mic-form [name=product_code]').fill('vex601-vex610');
  await page.locator('#mic-save').click();await page.locator('#mic-editor').waitFor({state:'hidden'});
  assert.equal(items.at(-1).content,'');assert.deepEqual(items.at(-1).titles,[]);assert.deepEqual(items.at(-1).images,[]);
  await openTab(9001,'social');await page.locator('#mic-social-editor[open]').waitFor();
  assert.equal(await page.locator('[data-social-select]').count(),0);
  await page.locator('[data-social-tab="linkedin"]').click();assert.equal(await page.locator('[data-social-tab="linkedin"]').getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('[data-social-field="content"]').inputValue(),'');
  await page.locator('#mic-editor > header [data-mic-close]').first().click();
  const card=page.locator('[data-mic-id="9001"]');
  assert.deepEqual(await card.getByRole('button').allTextContents(),['编辑','删除']);
  await openTitles(9001);await page.locator('#mic-titles-dialog[open]').waitFor();
  assert.equal(await page.locator('[data-title-social]').count(),0);
  assert.equal(await page.locator('.mic-name-pair').first().locator('.mic-title-actions button').count(),3);
  await page.locator('[data-titles-close]').first().click();await openTab(9001,'social');await page.locator('#mic-social-editor[open]').waitFor();
  const beforeResetWrites=writes;await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('#mic-social-editor').waitFor({state:'hidden'});assert.equal(await page.locator('[data-social-field]').count(),0);assert.equal(writes,beforeResetWrites);
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('[data-mic-id="9001"]').waitFor();
  await openTitles(9001);await page.locator('#mic-titles-dialog[open]').waitFor();const beforeTitlesReset=writes;
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('#mic-titles-dialog').waitFor({state:'hidden'});assert.equal(await page.locator('#mic-titles-body .mic-name-pair').count(),0);assert.equal(writes,beforeTitlesReset);
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('[data-mic-id="9001"]').waitFor();
  await page.locator('[data-mic-id="9001"] .mic-edit-button').click();await page.locator('#mic-editor[open]').waitFor();await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('#mic-editor').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('[data-mic-id]').length===0);assert.equal(await page.locator('#mic-name-fields textarea').count(),0);assert.deepEqual(errors,[]);
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');window.dispatchEvent(new Event('tophoo-project-changed'));});
  const remove=page.locator('[data-mic-remove-record="9001"]');
  await remove.click();
  await page.locator('[data-mic-id="9001"]').waitFor({state:'detached'});
  assert.equal(items.some(item=>item.id===9001),false);
  assert.equal(await page.locator('#mic-export-md').count(),0);
  console.log('PASS: product table, editor tabs, exactly three title actions, product social library and project isolation, only two required fields, creation without optional details or titles, fixed outer viewport, independent list scrolling with pinned pagination/filters/header on desktop and mobile, custom page size and remembered preference, removed hero, compact first viewport on desktop/mobile, paired MIC suggestions, four publication states, entering last number updates filtered list/dashboard, images and new product, source history retained, project isolation. All UI writes mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

