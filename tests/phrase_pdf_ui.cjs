// Downloads and errors are mocked; no writes reach the CRM.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawnSync}=require('node:child_process');
(async()=>{
 const sample=spawnSync('python',['-c',"from types import SimpleNamespace as N; from app.services.communication_phrase_pdf import export_phrases_pdf; import sys; sys.stdout.buffer.write(export_phrases_pdf([N(id=1,name='PDF sample')],[],[N(category_id=1,scene_id=None,content='Original text',translation='Translation')]))"]);
 assert.equal(sample.status,0,sample.stderr.toString());
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900},acceptDownloads:true}),page=await context.newPage(),errors=[],exports=[];
  page.on('pageerror',e=>errors.push(e.message));let fail=false,release,hold=false;
  await context.route('http://phrase-pdf.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/workbench.css"><body style="margin:20px"><script>localStorage.setItem("tophoo-global-selected-project","7")</script>'+fs.readFileSync('app/templates/partials/communication_phrases.html','utf8').replace('data-phrase-library hidden','data-phrase-library')});
   if(url.pathname.startsWith('/static/'))return route.fulfill({path:path.resolve('app'+url.pathname)});
   if(url.pathname.endsWith('/export/pdf')){
    exports.push(url.pathname+url.search);
    if(hold)await new Promise(resolve=>{release=resolve;});
    return fail?route.fulfill({status:500,json:{detail:'导出失败，请重试。'}}):route.fulfill({contentType:'application/pdf',headers:{'Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent('沟通话术_全部内容_2026-11-02.pdf')},body:sample.stdout});
   }
   return route.fulfill({json:{categories:[{id:1,name:'聊天'},{id:2,name:'空分类'}],scenes:[{id:1,category_id:1,name:'询价'},{id:2,category_id:1,name:'报价'}],items:[{id:1,category_id:1,scene_id:null,content:'Original',translation:'原文'},{id:2,category_id:1,scene_id:1,content:'Inquiry',translation:'询价'},{id:3,category_id:1,scene_id:2,content:'Quotation',translation:'报价'}],can_edit:false}});
  });
  await page.goto('http://phrase-pdf.test/');await page.evaluate(()=>document.dispatchEvent(new CustomEvent('tophoo-communication-phrases-view')));
  const root=page.locator('[data-phrase-library]'),button=root.locator('[data-phrase-export]');await button.waitFor({state:'visible'});
  await root.locator('[data-phrase-scene="1"]').click();await root.locator('[data-phrase-search]').fill('no match');assert.equal(await root.locator('.phrase-card').count(),0);
  const downloadPromise=page.waitForEvent('download');await button.click();const download=await downloadPromise;
  assert.equal(download.suggestedFilename(),'沟通话术_全部内容_2026-11-02.pdf');assert.deepEqual(exports,['/api/phrases/projects/7/export/pdf']);
  assert.ok(fs.readFileSync(await download.path()).subarray(0,5).equals(Buffer.from('%PDF-')));
  await root.locator('[data-phrase-category="2"]').click();assert.equal(await button.isDisabled(),false);
  await root.locator('[data-phrase-category="1"]').click();fail=true;await button.click();await root.locator('[data-phrase-error]').waitFor({state:'visible'});assert.match(await root.locator('[data-phrase-error]').innerText(),/导出失败/);assert.equal(await button.isEnabled(),true);
  fail=false;hold=true;await button.click();assert.equal(await button.isDisabled(),true);
  while(!release)await page.waitForTimeout(10);const retry=page.waitForEvent('download');release();await retry;
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);console.log('PASS complete PDF download, filename, readonly export, filter-independent scope, empty category, failure recovery, pending state and mobile layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
