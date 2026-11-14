// Product social UI checks. Every write and model call is mocked.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://mic.test'});
  const template=fs.readFileSync('app/templates/partials/mic_products.html','utf8').replace('class="project-library-view" hidden','class="project-library-view active"');
  const contact='Tel&WAP: +1 202 555 0100\nE-mail: sales@example.com',platforms=['facebook','instagram','linkedin','youtube'];
  const blank=()=>({content:'',translation:'',video_title:'',video_title_zh:'',tags:'',tags_zh:'',published:false,published_at:''});
  const products=[{id:1,product_code:'vex1-vex2',product_name:'铜管铝翅片换热器',product_group:'换热器',status:'pending',titles:[{code:'vex1',title:'Copper Cooling Coil'},{code:'vex2',title:'Custom Coil'}],images:[]},{id:2,product_code:'vex3-vex4',product_name:'不锈钢换热器',product_group:'换热器',status:'pending',titles:[],images:[]}];
  const docs=Object.fromEntries(products.map(p=>[p.id,{title:p.id===1?'Copper Tube Aluminum Fin Coil':'Stainless Steel Coil',parameters:'',contact,product_name:p.product_name,product_code:p.product_code,platforms:Object.fromEntries(platforms.map(p=>[p,blank()]))}]));
  let saves=0,failSave=false;
  await context.route('https://mic.test/**',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html data-ui-theme="green"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/workbench.css"><link rel="stylesheet" href="/static/css/ui-themes.css"></head><body>${template}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/mic-title-social.js"></script><script src="/static/js/mic-products.js"></script></body></html>`});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   const id=Number(url.pathname.match(/projects\/7\/(\d+)/)?.[1]||1);
   if(url.pathname.endsWith('/product-social')){
    if(req.method()==='PUT'){if(failSave)return route.fulfill({status:500,json:{detail:'模拟保存失败'}});saves++;docs[id]={...docs[id],...req.postDataJSON()};}
    return route.fulfill({json:docs[id]});
   }
   if(req.method()!=='GET')return route.fulfill({status:418,json:{detail:'Unexpected business write blocked'}});
   if(url.pathname.endsWith('/1')||url.pathname.endsWith('/2'))return route.fulfill({json:products.find(p=>p.id===id)});
   const items=url.pathname.includes('/projects/7')?products:[];
   items.forEach(p=>p.social_progress=Object.fromEntries(platforms.map(k=>[k,{total:1,ready:Number(!!docs[p.id].platforms[k].content),published:Number(docs[p.id].platforms[k].published)}])));
   return route.fulfill({json:{items,total:items.length,title_count:2,page:1,pages:1,groups:['换热器'],dashboard:{total:items.length,categories:[],social:[]}}});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://mic.test/test');await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-project-library-view',{detail:{section:'mic-products'}})));
  const open=async id=>{await page.locator(`[data-mic-open-record="${id}"]`).click();await page.locator('[data-mic-editor-tab="social"]').click();await page.locator('#mic-social-editor[open]').waitFor();};
  await open(1);assert.equal(await page.locator('[data-social-select]').count(),0);assert.equal(await page.locator('.mic-studio-sidebar').count(),0);assert.equal(await page.locator('#mic-social-tabs [role="tab"]').count(),4);
  assert.equal(await page.locator('[data-social-generate],#mic-social-generate-all,[data-social-date]').count(),0);
  assert.equal(await page.getByRole('switch').count(),1);
  await page.locator('[data-social-field="content"]').fill('facebook: Product introduction.');
  await page.locator('[data-social-field="translation"]').fill('中文产品介绍');
  await page.locator('[data-copy-field="all"]').click();assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/^facebook:/);
  await page.locator('[data-copy-field="zh"]').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'中文产品介绍');
  await page.locator('[data-social-tab="youtube"]').click();assert.equal(await page.locator('[data-social-field]').count(),6);
  await page.locator('[data-social-field="video_title"]').fill('Copper Tube Coil');
  await page.locator('[data-social-field="content"]').fill('Cooling coil description');
  await page.locator('[data-social-field="tags"]').fill('coil, HVAC');
  await page.locator('[data-copy-field="all"]').click();assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n'),'Copper Tube Coil\n\nCooling coil description\n\ncoil, HVAC');
  fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/mic-product-social-desktop.png'});
  await page.locator('[data-social-tab="facebook"]').click();await page.locator('[data-social-published]').check();
  page.once('dialog',d=>d.dismiss());await page.locator('#mic-editor > header [data-mic-close]').first().click();assert.equal(await page.locator('#mic-social-editor').isVisible(),true);
  failSave=true;await page.locator('#mic-social-save').click();await page.waitForFunction(()=>document.querySelector('#mic-social-error').textContent==='模拟保存失败');assert.match(await page.locator('[data-social-field="content"]').inputValue(),/^facebook:/);
  failSave=false;await page.locator('#mic-social-save').click();await page.waitForFunction(()=>document.querySelector('#mic-social-feedback').textContent.includes('已保存'));
  assert.equal(saves,1);assert.equal(docs[1].platforms.facebook.published,true);assert.equal(docs[2].platforms.facebook.content,'');
  await page.locator('#mic-editor > header [data-mic-close]').first().click();await open(1);assert.match(await page.locator('[data-social-field="content"]').inputValue(),/^facebook:/);await page.locator('#mic-editor > header [data-mic-close]').first().click();
  // A product without MIC names still gets exactly one working social set.
  await open(2);assert.equal(await page.locator('[data-social-field="content"]').inputValue(),'');
  await page.locator('[data-social-field="content"]').fill('Stainless steel coil');
  await page.locator('#mic-social-save').click();await page.waitForFunction(()=>!document.querySelector('#mic-social-save').disabled);assert.equal(saves,2);
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'output/ui/mic-product-social-mobile.png'});assert.ok(await page.locator('#mic-social-editor').evaluate(el=>el.scrollWidth<=el.clientWidth));
  await page.locator('#mic-editor > header [data-mic-close]').first().click();await page.evaluate(()=>window.tophooProjectAccess={canEdit:()=>false});await open(1);assert.equal(await page.locator('#mic-social-save').isDisabled(),true);assert.equal(await page.locator('[data-social-field="content"]').evaluate(el=>el.readOnly),true);await page.locator('#mic-editor > header [data-mic-close]').first().click();await page.evaluate(()=>delete window.tophooProjectAccess);
  await open(2);await page.locator('[data-social-field="content"]').fill('Unsaved draft');
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','8');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('#mic-social-editor').waitFor({state:'hidden'});assert.equal(await page.locator('#mic-social-fields').innerText(),'');assert.equal(saves,2);assert.deepEqual(errors,[]);
  console.log('PASS: one product / four platforms, no title sidebar, empty-title products, bilingual copy, YouTube metadata, manual publication, save failures, dirty close, product isolation, manual copy and editing, readonly, mobile and stale project cleanup. All writes mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
