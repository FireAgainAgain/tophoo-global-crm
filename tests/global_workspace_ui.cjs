// Local browser integration check. Tokens stay in the isolated test context.
const { chromium } = require('playwright');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

async function session(browser, userId) {
  const process = spawnSync('python', ['-c', `from app.core.security import create_access_token; print(create_access_token(${userId}))`], { encoding:'utf8', cwd:path.resolve(__dirname, '..') });
  if (process.status !== 0) throw new Error('Could not initialize isolated test session');
  const token = process.stdout.trim();
  const context = await browser.newContext({ viewport:{width:1440,height:1000} });
  await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  const response = await context.request.get('http://127.0.0.1:8002/api/auth/me', {headers:{Authorization:`Bearer ${token}`}});
  if (!response.ok()) throw new Error('Test session rejected');
  const user = await response.json();
  await context.addInitScript(({token,user}) => {
    if (window.top !== window) return;
    localStorage.setItem('tophoo-global-access-token', token);
    localStorage.setItem('tophoo-global-current-user', JSON.stringify(user));
    localStorage.setItem('tophoo-global-selected-project', '7');
    localStorage.setItem('tophoo-global-selected-workspace', '4');
  }, {token,user});
  return context;
}

(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const errors = [], serverErrors = [];
  try {
    const context = await session(browser,4);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {if(response.status()>=500)serverErrors.push(new URL(response.url()).pathname);});
    await page.goto('http://127.0.0.1:8002/');
    await page.locator('.pm-project-row[data-project-id="4"]').waitFor();
    assert.equal(await page.title(),'TOPHOO Global');
    assert.equal(await page.locator('.crm-primary-item:visible').count(),4);
    assert.deepEqual(await page.locator('.crm-primary-item:visible').evaluateAll(items=>items.map(el=>el.dataset.crmNavGroup)),['projects','seo','crm','system']);
    await page.waitForTimeout(350);
    assert.ok((await page.locator('.sidebar').boundingBox()).width < 400,'Desktop sidebar must not cover main content');
    assert.ok((await page.locator('.crm-secondary-panel').boundingBox()).width < 300,'Secondary panel must fit sidebar');
    const output = path.resolve(__dirname,'../output/ui');
    fs.mkdirSync(output,{recursive:true});
    await page.screenshot({path:path.join(output,'projects-desktop.png'),fullPage:false});
    await page.locator('#sidebar-user').click();
    assert.equal(await page.locator('#crm-user-menu-popover').isVisible(),true);
    assert.equal(await page.locator('#sidebar-admin-plans').innerText(),'工作区授权');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#crm-user-menu-popover').isVisible(),false);
    await page.locator('.pm-project-row[data-project-id="4"]').click();
    await page.waitForFunction(() => document.querySelector('#sidebar-current-project-name')?.textContent==='Example Studio');
    await page.locator('.crm-primary-item[data-crm-nav-group="seo"]').click();
    await page.locator('[data-crm-section="keyword-system"]').click();
    await page.locator('#keyword-tree').waitFor({state:'visible'});
    await page.locator('[data-crm-section="mic-products"]').click();
    await page.locator('[data-module="mic-products"]').waitFor({state:'visible'});
    assert.equal(await page.locator('[data-module="keyword-system"]').isVisible(),false);
    assert.equal(await page.locator('[data-crm-section="product-tdk"], [data-crm-section="action-tasks"]').count(),0);
    await page.locator('.crm-primary-item[data-crm-nav-group="projects"]').click();
    await page.locator('[data-crm-section="project-management"]').click();
    await page.locator('.pm-project-row[data-project-id="7"]').click();
    await page.waitForFunction(() => document.querySelector('#sidebar-current-project-name')?.textContent==='Demo');
    await page.locator('.crm-primary-item[data-crm-nav-group="crm"]').click();
    assert.deepEqual(await page.locator('.global-nav-item:visible').evaluateAll(items=>items.map(el=>el.dataset.crmSection)),['communication-assistant','communication-phrases']);
    await page.getByRole('button',{name:'客户',exact:true}).click();
    assert.deepEqual(await page.locator('.global-nav-item:visible').evaluateAll(items=>items.map(el=>el.dataset.crmSection)),['auto-prospecting','customer-search','leads','contacts','customer-pool']);
    assert.equal(await page.locator('[data-crm-project-management]').isVisible(),false);
    await context.route('**/api/customer-workflow/projects/7/pool', route => route.fulfill({
      json: {items: [{id: 901, company_name: 'Archive sample', has_archived_contracts: true, status: 'pool'}], owners: [], is_top_admin: true}
    }));
    await context.route('**/api/contracts/projects/7/customers/901', route => route.fulfill({
      json: [{id: 902, number: 'ARCHIVE-TEST', layout: 'export', currency: 'USD', total: '100.00', status: '已签署', has_signed: true}]
    }));
    await page.locator('[data-crm-section="customer-pool"]').click();
    await page.getByRole('button', {name:'合同归档'}).click();
    await page.getByRole('button', {name:'ARCHIVE-TEST', exact:true}).waitFor();
    assert.equal(await page.locator('[data-contract-add]').isVisible(),false);
    assert.equal(await page.locator('[data-inquiry-export]').count(),0);
    await page.getByRole('button', {name:'返回列表'}).click();
    await page.getByRole('button', {name:'合同归档'}).waitFor();
    assert.equal(await page.locator('[data-global-module="product_catalog"], [data-global-module="capabilities"]').count(),0);
    await page.waitForTimeout(350);
    await page.screenshot({path:path.join(output,'ever-crm.png'),fullPage:false});
    await page.locator('#sidebar-toggle').click();
    assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('secondary-nav-collapsed')),true);
    await page.locator('#sidebar-toggle').click();
    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(350);
    await page.screenshot({path:path.join(output,'mobile.png'),fullPage:false});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),true,'Mobile horizontal overflow');
    assert.equal(await page.locator('.global-nav-item:visible').count(),5);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),true,'Mobile category overflow');
    assert.equal(await page.locator('#crm-navigation').getAttribute('aria-label'),'功能导航');
    await context.close();
    const sales = await session(browser,8);
    const memberPage = await sales.newPage();
    memberPage.on('pageerror', error=>errors.push(error.message));
    await memberPage.goto('http://127.0.0.1:8002/');
    await memberPage.locator('.pm-project-row[data-project-id="7"]').waitFor();
    assert.equal(await memberPage.locator('.crm-primary-item[data-crm-nav-group="system"]').isVisible(),true,'Members can configure their own AI connections');
    assert.equal(await memberPage.locator('.pm-project-row[data-project-id="4"]').count(),0);
    await sales.close();
    assert.deepEqual(serverErrors,[],'Server errors during navigation');
    assert.deepEqual(errors,[],'Browser script errors');
    console.log('PASS: unified project switch, customer and project views, account menu, collapse, mobile and member permissions.');
    console.log('Screenshots:',output);
  } finally { await browser.close(); }
})().catch(error => {console.error(error.stack?.replace(/Bearer\s+[A-Za-z0-9_.-]+/g,'Bearer [redacted]') || error.message);process.exit(1);});
