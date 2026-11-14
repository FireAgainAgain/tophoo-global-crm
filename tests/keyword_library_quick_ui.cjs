// Keyword writes are intercepted and applied only to fixture records.
const {chromium}=require('playwright');const {spawnSync}=require('node:child_process');const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const result=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});if(result.status!==0)throw Error('Cannot initialize isolated session');
  const token=result.stdout.trim(),context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  await context.addInitScript(token=>{if (window.top !== window) return;localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
  const cats=[{id:901,name:'产品关键词',parent_id:null,keyword_count:2},{id:902,name:'推广关键词',parent_id:901,keyword_count:1}];
  const records=[{id:911,keyword:'dry cooler',chinese_translation:'干冷器',volume_label:'1000',category_ids:[901],tdk_usage:{product_count:1,primary_count:1}},{id:912,keyword:'air cooler',chinese_translation:'空气冷却器',volume_label:'500',category_ids:[901],tdk_usage:{article_count:1,pending_count:1}},{id:913,keyword:'industrial cooling',chinese_translation:'工业冷却',volume_label:'100',category_ids:[902],tdk_usage:{product_count:2,primary_count:2,has_conflict:true}}];
  let writes=0,failOnce=false,releaseSlow,slowSeen;
  await context.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.pathname.startsWith('/api/keywords/projects/')){
    if(req.method()==='GET'){
     if(/\/(template|export\/xlsx)$/.test(url.pathname)) return route.fulfill({contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',body:'fixture',headers:{'Content-Disposition':"attachment; filename*=UTF-8''keywords.xlsx"}});
     if(url.pathname.endsWith('/categories')){
      if(url.pathname.includes('/4/')&&releaseSlow){slowSeen();await releaseSlow;return route.fulfill({json:{categories:[{id:999,name:'旧项目分类',parent_id:null,keyword_count:0}]}});}
      return route.fulfill({json:{categories:cats}});
     }
     const id=Number(url.pathname.split('/').at(-2)),q=url.searchParams.get('q')||'';
     let items=records.filter(item=>(url.pathname.endsWith('/keywords')&&!url.pathname.includes('/categories/')||item.category_ids.includes(id))&&(item.keyword+' '+item.chinese_translation).includes(q));
     if(url.searchParams.get('usage')==='used')items=[];
     return route.fulfill({json:{keywords:items}});
    }
    if(req.method()==='POST'&&url.pathname.endsWith('/imports/preview')) return route.fulfill({json:{format:'纵向表',unique_keywords:8,existing_keywords:2,category_count:3}});
    writes++;
    if(req.method()==='POST'&&url.pathname.endsWith('/keywords/clear')){
     assert.deepEqual(req.postDataJSON(),{confirmation:'清空'});
     return route.fulfill({json:{keywords:records.splice(0).length,categories:cats.splice(0).length,imports:0}});
    }
    if(failOnce){failOnce=false;return route.fulfill({status:409,json:{detail:'测试保存失败'}});}
    if(req.method()==='POST'&&url.pathname.endsWith('/keywords')){const item={...req.postDataJSON(),id:920+writes,tdk_usage:{}};records.push(item);return route.fulfill({json:item});}
    return route.fulfill({status:418,json:{detail:'Unsupported fixture write'}});
   }
   if(!['GET','HEAD'].includes(req.method()))return route.fulfill({status:418,json:{detail:'Blocked by isolated UI test'}});
   return route.continue();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8002/');await page.locator('.pm-project-row[data-project-id="4"]').waitFor();await page.evaluate(()=>window.tophooNavigateGlobal('keyword-system'));
  await page.locator('[data-keyword-id="911"]').waitFor();
  assert.equal(await page.locator('#keyword-category-name').innerText(),'全部关键词');
  assert.deepEqual(await page.locator('.keyword-content-actions .keyword-tool-button').allTextContents(),['下载模板','导入 Excel','导出 Excel','＋ 新增','清空数据']);
  assert.equal(await page.locator('.keyword-more-actions,#keyword-sort').count(),0);
  for(const id of ['keyword-download-template','keyword-export-xlsx']){
   const download=page.waitForEvent('download');await page.locator('#'+id).click();assert.equal((await download).suggestedFilename(),'keywords.xlsx');
  }

  const treePanelBox=await page.locator('#keyword-tree-panel').boundingBox(),treeBox=await page.locator('#keyword-tree').boundingBox();
  assert.ok(treeBox.y-treePanelBox.y<=135,'Compact heading and search must leave space for the category tree');
  assert.equal(await page.locator('.keyword-layout-state,#keyword-usage-filter,#keyword-rebuild-usage,#keyword-usage-drawer').count(),0);
  assert.deepEqual(await page.locator('.keyword-table thead th').allTextContents(),['','关键词','中文翻译','操作']);
  assert.equal(await page.locator('[data-crm-nav-group="seo"] [data-global-module="keyword_library"]').count(),1);
  assert.equal(await page.locator('[data-crm-nav-group="projects"] [data-global-module="keyword_library"]').count(),0);
  assert.equal(await page.locator('#keyword-manage-toggle').count(),0,'Management mode must be removed');
  assert.equal(await page.locator('#keyword-expand-all, #keyword-collapse-all').count(),0,'Global category expansion controls must be removed');
  await page.locator('#keyword-search').fill('industrial');await page.waitForFunction(()=>document.querySelectorAll('[data-keyword-id]').length===1&&document.querySelector('[data-keyword-id="913"]'));
  assert.equal(await page.locator('[data-keyword-id]').count(),1,'All-keyword search must find another category');
  await page.locator('#keyword-search').fill('');await page.locator('[data-keyword-id="911"]').waitFor();
  const row=page.locator('[data-select="901"]').locator('..');await page.mouse.move(1200,70);const beforeHover=await row.boundingBox();await row.hover();assert.equal((await row.boundingBox()).height,beforeHover.height,'Category hover must not change row height');
  await page.locator('[data-category-menu="901"]').click();assert.equal(await page.locator('#keyword-category-menu').isVisible(),true);
  assert.equal(await page.locator('#keyword-category-menu [data-action="up"]').isDisabled(),true);
  await page.locator('#keyword-category-menu [data-action="edit"]').click();assert.equal(await page.locator('#keyword-editor-title').innerText(),'编辑分类');await page.locator('#keyword-editor [data-close-editor]').first().click();
  await page.locator('[data-category-menu="901"]').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#keyword-category-menu').isVisible(),false);
  await page.locator('[data-select="901"]').click();await page.locator('[data-keyword-id="913"]').waitFor({state:'detached'});
  assert.equal(await page.locator('[data-keyword-id]').count(),2,'Parent view contains only its directly assigned keywords');
  assert.equal(await page.locator('.keyword-content-heading>small').count(),0);
  await page.locator('[data-toggle="901"]').click();
  await page.locator('[data-select="902"]').waitFor();
  const parentRow=page.locator('[data-select="901"]').locator('..'),childRow=page.locator('[data-select="902"]').locator('..');
  await page.mouse.move(1200,70);
  assert.equal(await parentRow.locator('.keyword-tree-folder.is-folder').count(),1,'Parent uses a folder icon');
  assert.equal(await childRow.locator('.keyword-tree-folder.is-tag').count(),1,'Leaf category uses a distinct tag icon');
  assert.equal(await parentRow.locator('.keyword-folder-open').count(),1,'Expanded folders use an open-folder icon');
  const tableBeforeCopy=await page.locator('.keyword-table-wrap').boundingBox();
  await page.locator('[data-copy-keyword="911"]').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'dry cooler');
  assert.equal(await page.locator('#keyword-status').isVisible(),true);
  const tableAfterCopy=await page.locator('.keyword-table-wrap').boundingBox();
  assert.deepEqual(tableAfterCopy,tableBeforeCopy,'Copy feedback must not move or resize the list');
  assert.equal(await page.locator('#keyword-status').evaluate(el=>getComputedStyle(el).position),'fixed');
  await page.locator('#keyword-status').waitFor({state:'hidden',timeout:5000});
  assert.deepEqual(await page.locator('.keyword-table-wrap').boundingBox(),tableBeforeCopy,'Dismissed feedback must not move the list');
  await page.locator('[data-check-keyword="911"]').check();assert.equal(await page.locator('#keyword-select-all').evaluate(el=>el.indeterminate),true);
  assert.notEqual(await page.locator('[data-keyword-id="911"]').evaluate(el=>getComputedStyle(el).backgroundColor),await page.locator('[data-keyword-id="912"]').evaluate(el=>getComputedStyle(el).backgroundColor),'Selected rows must be visually distinct');
  await page.locator('#keyword-select-all').check();await page.locator('#keyword-copy-selected').click();assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n'),'dry cooler\nair cooler');
  assert.deepEqual(await page.locator('#keyword-selection-bar button').allTextContents(),['复制','修改分类','删除']);
  await page.locator('#keyword-delete-selected').click();await page.locator('#keyword-dialog-cancel').click();
  assert.equal(writes,0);
  await page.locator('#keyword-search').fill('air');await page.waitForFunction(()=>document.querySelectorAll('[data-keyword-id]').length===1);
  assert.ok((await page.locator('#keyword-selection-count').innerText()).includes('1 条'));
  await page.locator('#keyword-search').fill('');await page.locator('[data-keyword-id="911"]').waitFor();assert.equal(await page.locator('#keyword-search').inputValue(),'');
  await page.locator('[data-keyword-id="911"] .keyword-text').dblclick();assert.equal(await page.locator('#keyword-editor').evaluate(el=>el.open),true);
  assert.equal(await page.locator('#keyword-selected-categories').innerText(),'产品关键词');
  assert.equal(await page.locator('#keyword-picker-search').isVisible(),false);
  await page.locator('.keyword-category-disclosure summary').click();
  await page.locator('#keyword-picker-search').fill('推广');
  await page.locator('[name="category_ids"][value="902"]').check();
  assert.ok((await page.locator('#keyword-selected-categories').innerText()).includes('推广关键词'));
  await page.locator('[name="category_ids"][value="902"]').uncheck();
  await page.locator('.keyword-category-disclosure summary').click();
  await page.locator('#keyword-editor-fields [name="keyword"]').fill('未保存内容');await page.locator('#keyword-editor [data-close-editor]').first().click();await page.locator('#keyword-dialog-cancel').click();assert.equal(await page.locator('#keyword-editor-fields [name="keyword"]').inputValue(),'未保存内容');
  await page.locator('#keyword-editor [data-close-editor]').first().click();await page.locator('#keyword-dialog-confirm').click();assert.equal(await page.locator('#keyword-editor').evaluate(el=>el.open),false);
  await page.locator('#keyword-add').click();await page.locator('#keyword-editor-continue').check();
  await page.locator('#keyword-editor-fields [name="keyword"]').fill('new cooling term');failOnce=true;await page.keyboard.press('Control+s');await page.locator('#keyword-editor-error').waitFor();assert.equal(await page.locator('#keyword-editor-fields [name="keyword"]').inputValue(),'new cooling term');
  await page.keyboard.press('Control+s');await page.waitForFunction(()=>document.querySelector('#keyword-editor-fields [name="keyword"]').value==='');
  assert.equal(await page.locator('#keyword-editor').evaluate(el=>el.open),true);assert.equal(await page.locator('#keyword-editor-fields [name="category_ids"][value="901"]').isChecked(),true);
  await page.locator('#keyword-editor-fields [name="keyword"]').fill('second cooling term');await page.keyboard.press('Control+s');await page.waitForFunction(()=>document.querySelector('#keyword-editor-fields [name="keyword"]').value==='');await page.locator('#keyword-editor [data-close-editor]').first().click();
  await page.locator('[data-select="902"]').click();await page.locator('[data-keyword-id="913"]').waitFor();
  await page.reload();await page.locator('.pm-project-row[data-project-id="4"]').waitFor({state:'attached'});await page.evaluate(()=>window.tophooNavigateGlobal('keyword-system'));await page.locator('[data-keyword-id="913"]').waitFor();assert.equal(await page.locator('#keyword-category-name').innerText(),'推广关键词');
  records[2].keyword='industrial cooling keyword with a very long name to check wrapping and a fixed copy button on the right';
  await page.locator('#keyword-all').click();await page.locator('[data-keyword-id="911"]').waitFor();
  assert.equal(await page.locator('[data-select="901"]').locator('..').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)','Unselected parent has no row color block');
  assert.equal(await page.locator('[data-select="902"]').locator('..').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)','Unselected child has no row color block');
  const longCell=page.locator('[data-keyword-id="913"] .keyword-text-cell'),copy=page.locator('[data-copy-keyword="913"]'),text=page.locator('[data-keyword-id="913"] .keyword-text');
  const copyBox=await copy.boundingBox(),textBox=await text.boundingBox();assert.ok(Math.abs(copyBox.y-textBox.y)<5,'Copy button stays aligned to first line');assert.ok(copyBox.x>=textBox.x+textBox.width,'Copy button stays to the right, not below text');
  const output=path.resolve(__dirname,'../output/ui');fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'keywords-quick-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(350);await page.screenshot({path:path.join(output,'keywords-quick-mobile.png')});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile table must scroll inside its panel');
  await page.locator('#keyword-add').click();await page.screenshot({path:path.join(output,'keywords-quick-editor-mobile.png')});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile editor must fit viewport');await page.locator('#keyword-editor [data-close-editor]').first().click();
  let release,seenResolve;releaseSlow=new Promise(r=>release=r);const seen=new Promise(r=>seenResolve=r);slowSeen=seenResolve;
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');window.dispatchEvent(new Event('tophoo-project-changed'));});await seen;
  await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');window.dispatchEvent(new Event('tophoo-project-changed'));});await page.locator('[data-keyword-id="913"]').waitFor();release();await page.waitForTimeout(200);assert.equal(await page.locator('[data-select="999"]').count(),0);
  cats.push({id:950,name:'修饰词',parent_id:null,keyword_count:0},{id:951,name:'定制类',parent_id:950,keyword_count:1});
  records.push({id:961,keyword:'Custom',chinese_translation:'定制',volume_label:'',category_ids:[951],tdk_usage:{}});
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>window.dispatchEvent(new Event('tophoo-project-changed')));
  await page.locator('[data-select="950"]').waitFor();await page.locator('[data-toggle="950"]').click();
  await page.locator('[data-select="951"]').click();await page.locator('[data-keyword-id="961"]').waitFor();
  assert.equal(await page.locator('#keyword-category-name').innerText(),'定制类');
  assert.equal(await page.locator('#keyword-combination-guide, .keyword-combination-example').count(),0);
  await page.locator('[data-copy-keyword="961"]').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'Custom');
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.equal(writes,3);
  await page.locator('#keyword-import-file').setInputFiles({name:'fixture.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('fixture')});
  await page.getByText('识别到 8 个关键词', {exact:false}).waitFor();
  await page.locator('#keyword-dialog-cancel').click();
  assert.equal(writes,3);
  await page.locator('#keyword-clear-library').click();
  assert.equal(await page.locator('#keyword-dialog-confirm').isDisabled(),true);
  await page.locator('#keyword-dialog-input').fill('清');
  assert.equal(await page.locator('#keyword-dialog-confirm').isDisabled(),true);
  await page.locator('#keyword-dialog-cancel').click();
  assert.equal(writes,3);
  await page.locator('#keyword-clear-library').click();
  await page.locator('#keyword-dialog-input').fill('清空');
  await page.locator('#keyword-dialog-confirm').click();
  await page.getByText('已清空：删除', {exact:false}).waitFor();
  assert.equal(await page.locator('#keyword-category-name').innerText(),'全部关键词');
  assert.equal(await page.locator('[data-keyword-id]').count(),0);
  assert.deepEqual(errors,[]);assert.equal(writes,4);console.log('PASS: keyword library regression, import preview, clear confirmation and mobile layout. All writes mocked.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
