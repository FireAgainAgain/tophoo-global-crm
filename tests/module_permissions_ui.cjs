// Isolated permission presentation: no account or business data is loaded.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext();
 await context.route('**/__permission_ui',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="UTF-8"><link rel="stylesheet" href="/static/css/workbench.css"></head><body class="global-shell">
 <span id="crm-breadcrumb-current">客户</span><button class="global-nav-item" data-global-module="leads" aria-current="page">客户</button>
 <section data-customer-workflow data-permission-module="leads"><button data-workflow-add>新增</button><button data-records>查看记录</button><button data-customer-export>导出</button><input type="search" id="filter"><select data-contact-status><option>背调中</option></select><textarea data-outreach-content>可复制的开发信</textarea><button data-outreach-save>保存草稿</button></section>
 <section data-auto-prospecting><button data-acq-submit>搜索</button><button data-save-source>保存我的 Key</button><button data-acq-reveal>显示 Key</button><button data-test-source>测试</button></section>
 <section data-crm-communication-scripts><button data-reader-edit>编辑</button><button data-reader-copy>复制</button><button data-reader-preview>放大阅读</button><button data-reader-export>导出</button></section>
 <section data-module="mic-products"><button data-mic-status="published">已发布筛选</button><button id="mic-save">保存</button></section>
 <div id="clock-tick"></div><button id="unscoped-save" data-outreach-save>独立窗口保存</button>
 <script src="/static/js/module-permissions.js"></script></body></html>`}));
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('http://127.0.0.1:8002/__permission_ui');
 const grant=async writes=>page.evaluate(writePermissions=>window.dispatchEvent(new CustomEvent('tophoo-project-availability',{detail:{hasProject:true,permissions:['leads','auto_prospecting','knowledge_base','mic_products'],writePermissions}})),writes);
 await grant([]);
 assert.equal(await page.locator('[data-workflow-add]').isVisible(),false);
 assert.equal(await page.locator('[data-contact-status]').isDisabled(),true);
 assert.equal(await page.locator('[data-outreach-content]').evaluate(el=>el.readOnly),true);
 assert.equal(await page.locator('[data-customer-workflow] [data-outreach-save]').isVisible(),false);
 assert.equal(await page.locator('[data-acq-submit]').isVisible(),false);
 for(const selector of ['[data-records]','[data-customer-export]','[data-save-source]','[data-acq-reveal]','[data-test-source]','[data-reader-copy]','[data-reader-preview]','[data-reader-export]','[data-mic-status]','#filter','#module-readonly-badge'])assert.equal(await page.locator(selector).isVisible(),true,selector);
 await page.evaluate(()=>document.querySelector('[data-crm-communication-scripts]').insertAdjacentHTML('beforeend','<button data-reader-delete>删除</button>'));
 await page.waitForFunction(()=>document.querySelector('[data-reader-delete]').classList.contains('module-write-hidden'));
 await grant(['knowledge_base']);assert.equal(await page.locator('[data-reader-edit]').isVisible(),true);assert.equal(await page.locator('[data-workflow-add]').isVisible(),false);
 await grant(['leads','auto_prospecting','knowledge_base','mic_products']);
 assert.equal(await page.locator('[data-workflow-add]').isVisible(),true);assert.equal(await page.locator('[data-contact-status]').isDisabled(),false);assert.equal(await page.locator('[data-outreach-content]').evaluate(el=>el.readOnly),false);assert.equal(await page.locator('#module-readonly-badge').isVisible(),false);
 await grant(['leads']);
 await page.evaluate(()=>document.querySelector('[data-customer-workflow]').dataset.permissionModule='customer_list');
 await page.waitForFunction(()=>document.querySelector('[data-workflow-add]').classList.contains('module-write-hidden'));
 assert.equal(await page.locator('[data-acq-submit]').isVisible(),false,'Lead edit does not grant acquisition edits');
 await page.evaluate(()=>document.querySelector('[data-customer-workflow]').dataset.permissionModule='leads');
 await page.waitForFunction(()=>!document.querySelector('[data-workflow-add]').classList.contains('module-write-hidden'));
 // Background clocks trigger the body observer even while an editor is idle.
 const visibility=await page.evaluate(async()=>{
   const button=document.querySelector('#unscoped-save'),changes=[];
   const observer=new MutationObserver(()=>changes.push(button.className));
   observer.observe(button,{attributes:true,attributeFilter:['class']});
   for(let tick=0;tick<12;tick++){
     document.querySelector('#clock-tick').textContent=String(tick);
     await new Promise(resolve=>requestAnimationFrame(resolve));
   }
   observer.disconnect();return {changes,hidden:button.classList.contains('module-write-hidden')};
 });
 assert.deepEqual(visibility,{changes:[],hidden:false},'Unscoped actions must not alternate visibility on unrelated mutations');
 assert.deepEqual(errors,[]);console.log('PASS permission UI: read-only actions, dynamic drawers, mixed grants, filters, export/copy and personal credentials.');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
