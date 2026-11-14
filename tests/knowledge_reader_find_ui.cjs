// All knowledge writes are blocked; fixtures are served only to this browser context.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');

(async()=>{
  const result=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{encoding:'utf8'});
  assert.equal(result.status,0);
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1600,height:1000}}), token=result.stdout.trim();
    await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true}]);
    await context.addInitScript(token=>{
      if(window!==window.top)return;
      localStorage.setItem('tophoo-global-access-token',token);
      localStorage.setItem('tophoo-global-selected-project','7');
      localStorage.setItem('tophoo-global-selected-workspace','4');
    },token);
    const filler=Array.from({length:70},(_,i)=>`第 ${i+1} 段产品说明与参数。`).join('\n\n');
    const content=`# 功能说明\n\n首段文字。\n\n${filler}\n\n## 加热功能\n\n热**回收**系统：中文检索。\n\n${filler}\n\n## 表格信息\n\n| 材料 | 功能 |\n| --- | --- |\n| 铜管 | 热回收系统 |\n\n\`Heat Recovery\` / HEAT recovery\n\n查找特殊字符：[a+b](test).*\n\n<script>alert(1)</script>\n\n## 结尾\n\n最后的热回收系统。`;
    const library={categories:[{id:901,name:'产品资料',parent_id:null}],scripts:[{id:911,category_id:901,title:'功能说明',content,sort_order:1},{id:912,category_id:901,title:'第二篇',content:'只有第二篇的正文。',sort_order:2}]};
    let mutations=0;
    await context.route('**/api/**',route=>{
      const request=route.request();
      if (!['GET','HEAD'].includes(request.method())) {if(new URL(request.url()).pathname.startsWith('/api/communication-scripts/'))mutations++;return route.fulfill({status:418,json:{detail:'Read only'}});}
      if(new URL(request.url()).pathname.startsWith('/api/communication-scripts/projects/')) return route.fulfill({json:library});
      return route.continue();
    });
    const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8002/');
    await page.locator('.pm-project-row[data-project-id="4"]').waitFor();
    await page.evaluate(()=>window.tophooNavigateGlobal('communication-scripts'));
    const reader=page.locator('[data-script-reader]'), body=reader.locator(':scope > .script-markdown-render');
    const input=page.locator('[data-reader-find]'), status=page.locator('[data-reader-find-status]');
    await input.waitFor();
    const textBefore=await body.textContent();
    const current=()=>body.locator('mark.is-current').first();
    const waitStatus=async text=>{await page.waitForFunction(text=>document.querySelector('[data-reader-find-status]')?.textContent===text,text);};
    const isCurrentVisible=async()=>{
      const a=await current().boundingBox(), b=await body.boundingBox();
      assert.ok(a.y>=b.y-1 && a.y+a.height<=b.y+b.height+1,'Current match must be visible in the body viewport');
    };
    await input.fill('热回收系统');await waitStatus('1 / 3 处');
    assert.equal(await body.locator('mark[data-reader-hit="0"]').count(),3,'Phrase crossing bold markup is one hit with three highlighted pieces');
    assert.ok(await body.evaluate(el=>el.scrollTop)>500);await isCurrentVisible();
    assert.equal(await body.textContent(),textBefore,'Highlighting must preserve the content text');
    await input.press('Enter');await waitStatus('2 / 3 处');await isCurrentVisible();
    await page.locator('[data-reader-find-next]').click();await waitStatus('3 / 3 处');await isCurrentVisible();
    await page.locator('[data-reader-find-next]').click();await waitStatus('1 / 3 处');
    await input.press('Shift+Enter');await waitStatus('3 / 3 处');
    await page.locator('[data-reader-find-prev]').click();await waitStatus('2 / 3 处');
    await body.evaluate(el=>window.readerBodyForFind=el);
    await page.locator('[data-reader-preview]').click();assert.equal(await page.locator('[data-script-content-preview]').isVisible(),true);assert.equal(await page.locator('[data-script-preview-body] mark').count(),0);await page.locator('[data-script-preview-close]').click();
    assert.equal(await input.inputValue(),'热回收系统');assert.equal(await status.innerText(),'2 / 3 处');
    assert.ok(await input.isVisible());assert.equal(await body.evaluate(el=>el===window.readerBodyForFind),true);
    await page.keyboard.press('Control+f');assert.equal(await input.evaluate(el=>document.activeElement===el),true);
    await input.fill('heat RECOVERY');await waitStatus('1 / 2 处');
    await input.fill('[a+b](test).*');await waitStatus('1 / 1 处');assert.equal(await current().innerText(),'[a+b](test).*');
    await input.fill('查不到的文字');await waitStatus('未找到匹配内容');
    assert.equal(await body.locator('mark').count(),0);assert.equal(await page.locator('[data-reader-find-next]').isDisabled(),true);
    await input.fill('   ');await waitStatus('输入关键词定位正文');assert.equal(await body.locator('mark').count(),0);
    await input.fill('<script>');await waitStatus('1 / 1 处');assert.equal(await body.locator('script').count(),0);
    await input.press('Escape');assert.equal(await input.inputValue(),'');
    assert.equal(await page.locator('[data-script-content-preview]').isVisible(),false,'Reader search is independent from the preview dialog');
    await input.fill('热回收系统');await waitStatus('1 / 3 处');
    await page.locator('[data-reader-find-clear]').click();assert.equal(await body.textContent(),textBefore);
    assert.equal(await body.locator('mark').count(),0);assert.equal(await body.locator('strong').innerText(),'回收');
    // Library-wide search also locates its text inside the selected entry.
    await page.locator('[data-script-search]').fill('热回收系统');await waitStatus('1 / 3 处');await isCurrentVisible();
    await page.locator('[data-script-clear-search]').click();
    await page.locator('[data-script-read="912"]').click();assert.equal(await input.inputValue(),'');
    await input.fill('第二篇');await waitStatus('1 / 1 处');
    await page.locator('[data-script-read="911"]').click();assert.equal(await input.inputValue(),'');
    await input.fill('热回收系统');await waitStatus('1 / 3 处');
    fs.mkdirSync('output/ui',{recursive:true});
    await page.screenshot({path:'output/ui/knowledge-reader-find-expanded.png'});
    await page.setViewportSize({width:390,height:844});
    await input.scrollIntoViewIfNeeded();await input.press('Enter');await waitStatus('2 / 3 处');await isCurrentVisible();
    assert.ok(await input.isVisible());assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const box=await input.boundingBox();assert.ok(box.x>=0 && box.x+box.width<=390);
    await page.screenshot({path:'output/ui/knowledge-reader-find-mobile.png'});
    await page.locator('[data-reader-edit]').click();
    assert.equal(await page.locator('[name="content"]').inputValue(),content,'Find marks must never enter the editor or persisted content');
    assert.equal(mutations,0);assert.deepEqual(errors,[]);
    console.log('PASS: literal and case-insensitive body search, inline-spanning phrase, table matches, auto location, library search integration, previous/next wrap, shortcuts, enlarged/mobile layout, clear and no-match state, safe markup, unchanged source; no writes.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
