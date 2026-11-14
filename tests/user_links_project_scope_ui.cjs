const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:950}}),content=fs.readFileSync('app/templates/partials/user_links.html','utf8').replace('data-user-links hidden','data-user-links');
 const stores={'a:7':{categories:[{id:1,name:'业务'}],items:[{id:1,name:'Demo site',url:'https://demo.example.test',category_id:1}]},'a:8':{categories:[],items:[]},'b:7':{categories:[],items:[{id:9,name:'Other user',url:'https://other.example.test',category_id:null}]}};
 let release,slow=false,nextId=20;const writes=[],exports=[];
 await context.route('http://links.test/**',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.pathname==='/test')return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/user-links.css"></head><body>${content}<script>localStorage.setItem('tophoo-global-selected-project','7');window.testUser='a';window.tophooAuth={headers:()=>({'X-Test-User':window.testUser})};</script><script src="/static/js/user-links.js"></script></body></html>`});
  if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
  const project=url.searchParams.get('project_id'),user=req.headers()['x-test-user'];assert.ok(project,'Every request carries project context');const store=stores[user+':'+project];assert.ok(store);
  if(url.pathname.endsWith('/export/pdf')){exports.push(user+':'+project);return route.fulfill({contentType:'application/pdf',body:'fixture PDF'});}
  if(req.method()==='GET'){const body=JSON.stringify(store);if(slow&&project==='7')await new Promise(resolve=>release=resolve);return route.fulfill({contentType:'application/json',body});}
  const data=req.postDataJSON();writes.push({project,user,data});const item={id:nextId++,...data};store.items.push(item);return route.fulfill({status:201,json:item});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://links.test/test');await page.evaluate(()=>document.dispatchEvent(new Event('tophoo-user-links-view')));
 const root=page.locator('[data-user-links]');await root.getByText('Demo site',{exact:true}).waitFor();
 const change=project=>page.evaluate(project=>{localStorage.setItem('tophoo-global-selected-project',String(project));window.dispatchEvent(new Event('tophoo-project-changed'));},project);
 await change(8);await root.getByText('还没有常用网址',{exact:true}).waitFor();assert.equal(await root.getByText('Demo site',{exact:true}).count(),0);
 await root.locator('[data-ul-add]').first().click();await root.locator('[name=name]').fill('Project 8 tool');await root.locator('[name=url]').fill('https://eight.example.test');await root.locator('[type=submit]').click();await root.getByText('Project 8 tool',{exact:true}).waitFor();assert.equal(writes[0].project,'8');
 const download=page.waitForEvent('download');await root.locator('[data-ul-export]').click();await download;assert.deepEqual(exports,['a:8']);
 await change(7);await root.getByText('Demo site',{exact:true}).waitFor();assert.equal(await root.getByText('Project 8 tool',{exact:true}).count(),0);
 await root.locator('[data-ul-add]').click();await root.locator('[name=name]').fill('Unsaved old project');await change(8);assert.equal(await root.locator('dialog').isVisible(),false);await root.getByText('Project 8 tool',{exact:true}).waitFor();
 slow=true;await change(7);await page.waitForFunction(()=>document.querySelector('[data-ul-links]').textContent.includes('还没有常用网址'));await change(8);await root.getByText('Project 8 tool',{exact:true}).waitFor();slow=false;release();await page.waitForTimeout(100);assert.equal(await root.getByText('Demo site',{exact:true}).count(),0,'Late old project response cannot replace current bookmarks');
 await change(7);await root.getByText('Demo site',{exact:true}).waitFor();await page.evaluate(()=>{window.testUser='b';document.dispatchEvent(new Event('tophoo-auth-changed'));});await root.getByText('Other user',{exact:true}).waitFor();assert.equal(await root.getByText('Demo site',{exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log('PASS user+project bookmark scoping: CRUD/PDF context, project switching, draft reset, stale response guard and account switch; all writes mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
