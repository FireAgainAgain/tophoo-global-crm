// Every competitor write is served by in-memory fixtures; no business records are modified.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const result=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
    if(result.status!==0)throw Error('Cannot initialize isolated session');
    const token=result.stdout.trim(), context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
    await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
    await context.addInitScript(token=>{localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
    let records=Array.from({length:22},(_,i)=>({id:601+i,name:i===0?'Alpha Cooling':'Competitor '+i,country:'United States',notes:i===0?'测试调研备注：高效制造':'',websites:[{id:701+i,name:'官方网站',url:'https://competitor'+i+'.example.com'}],keywords:[{id:801+i,keyword:'dry cooler '+i,language:'English',category:'产品词'}]}));
    let releaseSlow, slowSeen, writes=0, failWebsiteOnce=true;
    await context.route('**/api/**',async route=>{
      const req=route.request(), url=new URL(req.url());
      if(url.pathname.startsWith('/api/competitors/projects/')){
        const parts=url.pathname.split('/'), id=Number(parts[5]);
        if(req.method()==='GET'){
          if(url.pathname.endsWith('/4')&&releaseSlow){slowSeen();await releaseSlow;return route.fulfill({json:[{...records[0],id:999,name:'旧项目数据'}]});}
          return route.fulfill({json:records});
        }
        writes++; const record=records.find(x=>x.id===id);
        if(req.method()==='POST'&&url.pathname.endsWith('/move')){
          const index=records.indexOf(record), next=index+(req.postDataJSON().direction==='up'?-1:1);
          if(next>=0&&next<records.length)[records[index],records[next]]=[records[next],records[index]];
          return route.fulfill({json:records});
        }
        if(req.method()==='PUT'&&parts.length===6){Object.assign(record,req.postDataJSON());return route.fulfill({json:record});}
        if(req.method()==='PUT'&&parts[6]==='websites'){
          if(failWebsiteOnce){failWebsiteOnce=false;return route.fulfill({status:409,json:{detail:'测试保存失败，请重试'}});}
          Object.assign(record.websites.find(value=>value.id===Number(parts[7])),req.postDataJSON());return route.fulfill({json:record});
        }
        if(req.method()==='POST'&&url.pathname.endsWith('/websites')){record.websites.push({...req.postDataJSON(),id:1701});return route.fulfill({json:record});}
        if(req.method()==='POST'&&url.pathname.endsWith('/keywords')){record.keywords.push({...req.postDataJSON(),id:1801});return route.fulfill({json:record});}
        return route.fulfill({status:418,json:{detail:'Unsupported fixture write'}});
      }
      if(!['GET','HEAD'].includes(req.method()))return route.fulfill({status:418,json:{detail:'Blocked by isolated UI test'}});
      return route.continue();
    });
    const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8002/');await page.locator('.pm-project-row[data-project-id="4"]').waitFor();
    await page.evaluate(()=>window.tophooNavigateGlobal('competitors'));
    await page.locator('[data-select-competitor="601"]').waitFor();
    assert.equal(await page.locator('.competitor-insights').count(),0,'Summary cards must be removed from DOM');
    assert.ok((await page.locator('.competitor-layout').boundingBox()).y<160,'Workspace starts without top statistics');
    const search=page.locator('[data-competitor-search]');await search.fill('competitor0.example.com');
    assert.equal(await page.locator('[data-select-competitor]').count(),1,'Search must include website URL');
    await search.fill('高效制造');assert.equal(await page.locator('[data-select-competitor]').count(),1,'Search must include notes');
    await search.fill('');
    await page.locator('[data-copy-keyword="801"]').click();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'dry cooler 0');
    await page.locator('[data-edit-competitor]').click();
    assert.equal(await page.locator('[data-editor-pane="company"]').isVisible(),true);
    assert.equal(await page.locator('[data-editor-pane="websites"]').isVisible(),false);
    await page.locator('[data-competitor-form] [name="notes"]').fill('尚未保存的公司备注');
    await page.locator('[data-editor-tab="keywords"]').click();
    await page.locator('[data-keyword-form] [name="keyword"]').fill('待添加关键词');
    await page.locator('[data-editor-tab="websites"]').click();
    assert.equal(await page.locator('[data-website-edit-form][data-website-id="701"]').isVisible(),false);
    await page.locator('[data-open-website="701"]').click();
    assert.equal(await page.locator('[data-website-edit-form][data-website-id="701"]').isVisible(),true);
    await page.locator('[data-cancel-website="701"]').click();
    await page.locator('[data-open-new-website]').click();
    await page.locator('[data-website-form] [name="name"]').fill('测试新网站');
    await page.locator('[data-website-form] [name="url"]').fill('new.example.com');
    await page.locator('[data-website-form] [name="name"]').focus();
    assert.equal(await page.locator('[data-website-form] [name="url"]').inputValue(),'https://new.example.com');
    await page.locator('[data-website-form] [type="submit"]').click();
    await page.locator('[data-website-edit-form][data-website-id="1701"]').waitFor({state:'attached'});
    assert.equal(await page.locator('[data-competitor-form] [name="notes"]').inputValue(),'尚未保存的公司备注','Website save must preserve unsaved company fields');
    assert.equal(await page.locator('[data-keyword-form] [name="keyword"]').inputValue(),'待添加关键词','Website save must preserve other form drafts');
    assert.equal(await page.locator('[data-editor-tab="websites"]').getAttribute('aria-selected'),'true','Saving website must keep the active tab');
    await page.locator('[data-open-website="701"]').click();
    await page.locator('[data-website-edit-form][data-website-id="701"] [name="name"]').fill('官网新名称');
    page.once('dialog',d=>d.dismiss());await page.locator('[data-select-competitor="602"]').click();
    assert.equal(await page.locator('[data-competitor-form] [name="notes"]').inputValue(),'尚未保存的公司备注');
    page.once('dialog',d=>d.dismiss());await search.fill('Competitor 1');assert.equal(await search.inputValue(),'');
    await page.locator('[data-editor-tab="company"]').click();
    await page.locator('[data-competitor-form] [name="notes"]').focus();await page.keyboard.press('Control+s');
    await page.waitForFunction(()=>document.querySelector('[data-competitor-notice]')?.textContent==='竞品资料已保存。');
    assert.equal(await page.locator('[data-keyword-form] [name="keyword"]').inputValue(),'待添加关键词','Company save must preserve keyword draft');
    await page.locator('[data-editor-tab="websites"]').click();
    const websiteEdit=page.locator('[data-website-edit-form][data-website-id="701"]');
    assert.equal(await websiteEdit.isVisible(),true,'Company save must preserve open website editor');
    assert.equal(await websiteEdit.locator('[name="name"]').inputValue(),'官网新名称');
    await websiteEdit.locator('[type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-competitor-notice]')?.textContent==='测试保存失败，请重试');
    assert.equal(await websiteEdit.locator('[name="name"]').inputValue(),'官网新名称','Failed save must retain inputs');
    await websiteEdit.locator('[type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-competitor-notice]')?.textContent==='竞品网站已保存。');
    assert.equal(await websiteEdit.isVisible(),false,'Saved website returns to readable card');
    await page.locator('[data-editor-tab="keywords"]').click();
    await page.locator('[data-keyword-form] [type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-competitor-notice]')?.textContent==='竞品关键词已添加。');
    await page.locator('[data-finish-edit]').click();
    assert.ok((await page.locator('.competitor-profile-notes').innerText()).includes('尚未保存'));
    assert.equal(await page.locator('[data-copy-keyword="1801"]').count(),1);
    await page.locator('[data-competitor-list]').evaluate(el=>el.scrollTop=el.scrollHeight);
    const before=await page.locator('[data-competitor-list]').evaluate(el=>el.scrollTop);
    await page.locator('[data-select-competitor="622"]').click();
    assert.equal(await page.locator('[data-competitor-list]').evaluate(el=>el.scrollTop),before,'Selection must preserve list scroll');
    await page.locator('[data-move-competitor="622"][data-direction="up"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-competitor-notice]')?.textContent==='竞品顺序已更新。');
    assert.equal(await page.locator('[data-select-competitor="622"]').getAttribute('aria-pressed'),'true');
    const output=path.resolve(__dirname,'../output/ui');fs.mkdirSync(output,{recursive:true});
    await page.screenshot({path:path.join(output,'competitors-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'competitors-mobile.png')});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile profile must not overflow');
    await page.locator('[data-edit-competitor]').click();
    assert.equal(await page.locator('.competitor-list-panel').isVisible(),false,'Mobile editor should hide the list to focus on the form');
    await page.evaluate(()=>scrollTo(0,0));
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile editor must not overflow');
    await page.screenshot({path:path.join(output,'competitors-editor-company-mobile.png')});
    await page.locator('[data-editor-tab="websites"]').click();
    await page.locator('[data-open-website="722"]').click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile website editor must not overflow');
    await page.screenshot({path:path.join(output,'competitors-editor-websites-mobile.png')});
    await page.locator('[data-finish-edit]').click();
    await page.setViewportSize({width:1440,height:1000});
    await page.waitForTimeout(400);
    assert.ok((await page.locator('.sidebar').boundingBox()).width<400,'Sidebar must settle to desktop width after mobile resize');
    await page.locator('[data-edit-competitor]').click();
    await page.screenshot({path:path.join(output,'competitors-editor-company-desktop.png')});
    await page.locator('[data-editor-tab="company"]').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('[data-editor-tab="websites"]').getAttribute('aria-selected'),'true','Tabs support arrow-key navigation');
    await page.locator('[data-open-website="722"]').click();
    await page.screenshot({path:path.join(output,'competitors-editor-websites-desktop.png')});
    await page.locator('[data-finish-edit]').click();
    let release, seenResolve;releaseSlow=new Promise(r=>release=r);const seen=new Promise(r=>seenResolve=r);slowSeen=seenResolve;
    await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');window.dispatchEvent(new Event('tophoo-project-changed'));});await seen;
    await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');window.dispatchEvent(new Event('tophoo-project-changed'));});
    await page.locator('[data-select-competitor="622"]').waitFor();release();await page.waitForTimeout(200);
    assert.equal(await page.locator('[data-select-competitor="999"]').count(),0,'Old project response must not leak');
    assert.deepEqual(errors,[]);assert.equal(writes,6);
    console.log('PASS: no summary cards, search, keyword copy, independent draft preservation, discard guards, shortcut save, ordering, list scroll, responsive profile/editor, stale project response. All writes mocked.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
