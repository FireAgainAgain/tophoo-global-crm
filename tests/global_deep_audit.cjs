// Read-only browser diagnostics. Block all non-GET business requests.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const result=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
    if(result.status!==0)throw Error('Cannot initialize diagnostic session');
    const token=result.stdout.trim();
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
    await context.addInitScript(token=>{
      localStorage.setItem('tophoo-global-access-token',token);
      localStorage.setItem('tophoo-global-selected-project','7');
      localStorage.setItem('tophoo-global-selected-workspace','4');
    },token);
    await context.route('**/api/**',async route=>{
      if(!['GET','HEAD'].includes(route.request().method()))return route.fulfill({status:418,json:{detail:'Blocked by read-only audit'}});
      return route.continue();
    });
    const page=await context.newPage();
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8002/');
    await page.locator('.pm-project-row[data-project-id="4"]').waitFor();
    await page.waitForTimeout(1000);
    const visible=selector=>page.locator(selector).isVisible();
    const findings=[];
    for(const key of ['prospecting','leads','contacts','customer-pool']){
      await page.evaluate(key=>window.tophooNavigateGlobal(key),key);
      await page.waitForTimeout(100);
      findings.push({navigation:key,projectManagementVisible:await visible('[data-crm-project-management]'),workflowVisible:await visible('[data-customer-workflow]')});
    }
    console.log('Customer navigation:',JSON.stringify(findings));
    assert.ok(findings.every(x=>!x.projectManagementVisible&&x.workflowVisible),'Customer menus must not show project management');
    const serverErrors=[];
    page.on('response',r=>{if(r.status()>=500)serverErrors.push(new URL(r.url()).pathname)});
    const navigationKeys=await page.locator('.global-nav-item').evaluateAll(items=>items.filter(item=>!item.hidden).map(item=>item.dataset.crmSection));
    for(const key of navigationKeys){
      await page.evaluate(key=>window.tophooNavigateGlobal(key),key);
      await page.waitForTimeout(120);
    }
    assert.deepEqual(serverErrors,[]);
    console.log('Navigation modules inspected:',navigationKeys.length);

    const switchProject=async id=>{
      await page.evaluate(()=>window.tophooNavigateGlobal('project-management'));
      await page.locator(`.pm-project-row[data-project-id="${id}"]`).click();
      await page.waitForFunction(id=>localStorage.getItem('tophoo-global-selected-project')===String(id),id);
      await page.locator(`.pm-project-row.is-current[data-project-id="${id}"]`).waitFor();
    };

    // A slow Example Studio response must not replace the now-selected Demo table.
    let release,receivedResolve;
    const gate=new Promise(r=>release=r), received=new Promise(r=>receivedResolve=r);
    await page.route(/\/api\/product-tdk\/projects\/4\?/,async route=>{
      const response=await route.fetch();receivedResolve();await gate;await route.fulfill({response});
    });
    await switchProject(4);
    await received;
    await switchProject(7);
    await page.evaluate(()=>window.tophooNavigateGlobal('product-tdk'));
    await page.waitForFunction(()=>document.querySelector('#product-tdk-count').textContent.startsWith('0 '));
    release();
    await page.waitForTimeout(400);
    assert.ok((await page.locator('#product-tdk-count').textContent()).startsWith('0 '));
    console.log('PASS: delayed product TDK response ignored after project switch.');
    await page.unroute(/\/api\/product-tdk\/projects\/4\?/);

    let releaseArticle,articleSeenResolve;
    const articleGate=new Promise(r=>releaseArticle=r),articleSeen=new Promise(r=>articleSeenResolve=r);
    await page.route(/\/api\/article-tdk\/projects\/4\?/,async route=>{
      const response=await route.fetch();articleSeenResolve();await articleGate;await route.fulfill({response});
    });
    await switchProject(4);await articleSeen;
    await switchProject(7);
    await page.evaluate(()=>window.tophooNavigateGlobal('article-tdk'));
    await page.waitForFunction(()=>document.querySelector('#article-tdk-count').textContent.startsWith('0 '));
    releaseArticle();
    await page.waitForTimeout(400);
    assert.ok((await page.locator('#article-tdk-count').textContent()).startsWith('0 '));
    console.log('PASS: delayed article TDK response ignored after project switch.');
    await page.unroute(/\/api\/article-tdk\/projects\/4\?/);

    assert.equal(await page.locator('[data-crm-section="market-research"]').count(),0);
    assert.equal(await page.locator('[data-module="market-research"]').count(),0);
    console.log('PASS: retired market research has no navigation or page.');
    await page.goto('http://127.0.0.1:8002/seo');
    await page.locator('#keyword-tree').waitFor({state:'visible'});
    assert.equal(await page.locator('.global-nav-item[data-crm-section="keyword-system"]').evaluate(el=>el.classList.contains('active')),true);
    await page.goto('http://127.0.0.1:8002/?page=seo');
    await page.locator('#keyword-tree').waitFor({state:'visible'});
    console.log('PASS: both legacy SEO link forms select the unified SEO navigation.');
    assert.deepEqual(errors,[]);
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exit(1);});
