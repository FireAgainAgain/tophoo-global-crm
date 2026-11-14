// Read-only regression: a valid HttpOnly cookie without port-specific localStorage.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');

(async()=>{
 const base=process.env.TOPHOO_TEST_URL||'http://localhost:8002';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const session=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
  assert.equal(session.status,0);
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addCookies([{name:'tophoo_global_access_token',value:session.stdout.trim(),domain:new URL(base).hostname,path:'/',httpOnly:true,sameSite:'Lax'}]);
  await context.addInitScript(()=>{
   localStorage.setItem('tophoo-global-selected-project','7');
   localStorage.setItem('tophoo-global-selected-workspace','4');
  });
  let keywordReads=0;
  await context.route('**/api/**',route=>{
   const request=route.request();
   if(!['GET','HEAD'].includes(request.method()))return route.fulfill({status:418,json:{detail:'Read-only regression'}});
   if(request.url().includes('/api/keywords/projects/7/'))keywordReads++;
   return route.continue();
  });
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base+'/');
  await page.locator('#keyword-list [data-keyword-id]').first().waitFor({state:'attached'});
  await page.evaluate(()=>window.tophooNavigateGlobal('keyword-system'));
  assert.ok(await page.locator('#keyword-tree [data-select]').count()>0);
  assert.ok(await page.locator('#keyword-list [data-keyword-id]').count()>0);
  assert.equal(await page.locator('#keyword-add').isEnabled(),true);
  assert.ok(keywordReads>=2);
  assert.equal(await page.evaluate(()=>localStorage.getItem('tophoo-global-access-token')),null,'HttpOnly cookie must remain sufficient; do not expose it to localStorage');
  assert.ok(await page.evaluate(()=>Boolean(window.tophooAuth.currentUser())));
  await page.screenshot({path:path.resolve(__dirname,'../output/ui/keywords-cookie-session-restored.png')});
  await page.locator('[data-select="103"]').click();
  await page.locator('[data-toggle="103"]').click();
  await page.locator('[data-select="114"]').click();
  await page.locator('#keyword-list .keyword-text').filter({hasText:'Custom'}).first().waitFor();
  assert.equal(await page.locator('#keyword-list [data-keyword-id]').count(),5);
  assert.deepEqual(errors,[]);
  console.log('PASS: cookie-only session restores categories, words, editing availability and subcategory navigation. All business writes blocked.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
