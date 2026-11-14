const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:950}});
 const template=fs.readFileSync('app/templates/partials/crm_communication_scripts.html','utf8').replace('data-crm-communication-scripts hidden','data-crm-communication-scripts');
 const library={categories:[{id:1,name:'Delete folder',parent_id:null},{id:2,name:'Child folder',parent_id:1},{id:3,name:'Keep folder',parent_id:null}],scripts:[{id:10,category_id:1,title:'First note',content:'Note one'},{id:11,category_id:2,title:'Child note',content:'Note two'},{id:12,category_id:3,title:'Keep note',content:'Keep content'}]};let deletions=0;
 await context.route('http://knowledge.test/**',route=>{const req=route.request(),url=new URL(req.url());
  if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/workbench.css"></head><body>${template}<script>localStorage.setItem('tophoo-global-selected-project','7')</script><script src="/static/js/crm-communication-scripts.js"></script></body></html>`});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  if(req.method()==='DELETE'){assert.equal(url.pathname,'/api/communication-scripts/projects/7/categories/1');assert.equal(url.searchParams.get('confirmed'),'true');deletions++;library.categories=library.categories.filter(c=>c.id===3);library.scripts=library.scripts.filter(s=>s.category_id===3);return route.fulfill({json:{deleted:true}});}
  assert.equal(req.method(),'GET');return route.fulfill({json:library});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://knowledge.test/test');
 const remove=async()=>{await page.locator('[data-script-category-menu-toggle="1"]').click();await page.locator('[data-category-action="delete"]').click();};
 await page.locator('[data-script-category="1"]').waitFor();
 page.once('dialog',async d=>{assert.match(d.message(),/Delete folder/);assert.match(d.message(),/1 个子分类、2 条知识条目/);await d.dismiss();});await remove();assert.equal(deletions,0);assert.equal(await page.locator('[data-script-category="1"]').count(),1);
 page.once('dialog',async d=>d.accept());await remove();await page.locator('[data-script-category="1"]').waitFor({state:'detached'});assert.equal(deletions,1);assert.equal(await page.locator('[data-script-category="3"]').count(),1);assert.equal(await page.locator('[data-script-read="12"]').count(),1);
 assert.deepEqual(errors,[]);console.log('PASS nonempty knowledge folder delete: explicit confirmation with counts, cancel sends nothing, confirm deletes subtree and preserves unrelated notes; writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
