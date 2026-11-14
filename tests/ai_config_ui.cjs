// Isolated AI configuration tests: never call a provider or write business data.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
const session=spawnSync('python',['-c','from app.core.security import create_access_token; print(create_access_token(4))'],{encoding:'utf8'});assert.equal(session.status,0);const token=session.stdout.trim();
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
const context=await browser.newContext({viewport:{width:1600,height:1000}});
await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
await context.addInitScript(token=>{localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
let models=[{id:901,name:'百炼连接',provider:'deepseek',model:'qwen-plus',base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1',api_key_masked:'••••TEST',enabled:true,temperature:0.1,max_tokens:1024,request_timeout_seconds:60,notes:'现有备注',features:[],last_test_status:'success',last_test_message:'连接成功：OK'}];
const providers={items:[{id:'qwen',name:'通义千问',base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus'},{id:'deepseek',name:'DeepSeek',base_url:'https://api.deepseek.com/v1',model:'deepseek-chat'},{id:'custom',name:'自定义兼容接口',base_url:'',model:''}]};
let tests=0,saves=0,deletes=0,failTest=false,failSave=false,failLoad=false,lastPayload,slowTest=false,releaseTest,testSeen,slowLoad=false,releaseLoad,loadSeen;
await context.route('**/api/**',async route=>{
 const req=route.request(),url=new URL(req.url());
 if(url.pathname.startsWith('/api/ai-config')){
  if(req.method()==='GET'){
   if(url.pathname.endsWith('/providers'))return route.fulfill({json:providers});
   if(slowLoad&&url.pathname.endsWith('/4')){loadSeen();await releaseLoad;return route.fulfill({json:{models:[{...models[0],name:'过期项目连接'}],features:[],can_manage:true}});}
   if(failLoad)return route.fulfill({status:500,json:{detail:'模拟加载失败'}});
   return route.fulfill({json:{models,features:[],can_manage:true}});
  }
  if(url.pathname.endsWith('/test-draft')){
   tests++;if(slowTest){testSeen();await releaseTest;}if(failTest)return route.fulfill({status:422,json:{detail:'模拟连接失败'}});
   return route.fulfill({json:{status:'success',message:'连接成功：OK',verification_token:'fixture-verification'}});
  }
  if(['POST','PUT'].includes(req.method())){
   saves++;lastPayload=req.postDataJSON();if(failSave)return route.fulfill({status:500,json:{detail:'模拟保存失败'}});
   const id=req.method()==='PUT'?Number(url.pathname.split('/').pop()):902;
   const item={...(models.find(item=>item.id===id)||{}),...lastPayload,id,api_key_masked:'••••TEST',features:[],last_test_status:lastPayload.verification_token?'success':'',last_test_message:''};
   const index=models.findIndex(item=>item.id===id);if(index>=0)models[index]=item;else models.push(item);return route.fulfill({json:item});
  }
  if(req.method()==='DELETE'){deletes++;models=models.filter(item=>item.id!==Number(url.pathname.split('/').pop()));return route.fulfill({json:{deleted:true}});}
 }
 if(!['GET','HEAD'].includes(req.method()))return route.fulfill({status:418,json:{detail:'All business writes blocked'}});
 return route.continue();
});
const page=await context.newPage(),errors=[];page.on('pageerror',err=>errors.push(err.message));
await page.goto('http://127.0.0.1:8002/');await page.locator('.pm-project-row[data-project-id="4"]').waitFor();await page.evaluate(()=>window.tophooNavigateGlobal('ai-config'));
const root=page.locator('[data-ai-config]'),dialog=root.locator('[data-ai-editor]');await root.locator('[data-ai-new]:enabled').waitFor();
assert.equal(await root.locator('[data-ai-binding-section]').isVisible(),false);assert.ok((await root.locator('[data-ai-usage-summary]').innerText()).includes('已绑定 0'));
assert.equal(await root.locator('[data-ai-project-name]').innerText(),'Demo');
fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/ai-config-desktop.png',fullPage:true});
await root.locator('.ai-model-actions button').first().click();assert.equal(await dialog.locator('[name="provider"]').inputValue(),'qwen','Historical provider label is inferred from endpoint');
assert.equal(await dialog.locator('[name="base_url"]').inputValue(),models[0].base_url,'Editing never overwrites custom address');
await dialog.locator('[name="notes"]').fill('只修改备注');await dialog.locator('[data-ai-save]').click();await dialog.waitFor({state:'hidden'});assert.equal(tests,0,'Verified unchanged connection needs no paid retest');assert.equal(lastPayload.provider,'qwen');assert.equal(lastPayload.api_key,null);
await root.locator('[data-ai-new]').click();assert.equal(await dialog.locator('[name="provider"]').inputValue(),'qwen');assert.ok((await dialog.locator('[name="base_url"]').inputValue()).includes('dashscope'));
await dialog.locator('[name="model"]').fill('test-chat');await dialog.locator('[name="api_key"]').fill('fixture-key');
page.once('dialog',dialog=>dialog.dismiss());await dialog.locator('[data-ai-close]').click();assert.equal(await dialog.evaluate(el=>el.open),true,'Dirty close is guarded');
failTest=true;await dialog.locator('[data-ai-save]').click();await dialog.locator('[data-ai-editor-error]').filter({hasText:'模拟连接失败'}).waitFor();assert.equal(saves,1,'Failed test must not save');assert.equal(await dialog.locator('[name="api_key"]').inputValue(),'fixture-key');
failTest=false;failSave=true;await dialog.locator('[data-ai-save]').click();await dialog.locator('[data-ai-editor-error]').filter({hasText:'模拟保存失败'}).waitFor();assert.equal(await dialog.locator('[name="model"]').inputValue(),'test-chat');
const testCount=tests;failSave=false;await dialog.locator('[data-ai-save]').click();await dialog.waitFor({state:'hidden'});assert.equal(tests,testCount,'Retry saving does not repeat a successful test');assert.equal(lastPayload.enabled,true);
await root.locator('[data-ai-new]').click();await dialog.locator('[name="provider"]').selectOption('custom');assert.equal(await dialog.locator('[data-ai-advanced]').evaluate(el=>el.open),true);
await dialog.locator('[name="base_url"]').fill('https://custom.example.test/v1');await dialog.locator('[name="model"]').fill('custom-chat');await dialog.locator('[name="api_key"]').fill('fixture-key');
const draftTests=tests;await dialog.locator('[data-ai-save-draft]').click();await dialog.waitFor({state:'hidden'});assert.equal(tests,draftTests);assert.equal(lastPayload.enabled,false);assert.equal(lastPayload.provider,'custom');
await root.locator('[data-ai-new]').click();await dialog.locator('[name="model"]').fill('test-chat');await dialog.locator('[name="api_key"]').fill('fixture-key');
slowTest=true;let resolveTest;releaseTest=new Promise(resolve=>{resolveTest=resolve});const testStarted=new Promise(resolve=>{testSeen=resolve});
await dialog.locator('[data-ai-save]').click();await testStarted;const savesBefore=saves;await page.keyboard.press('Control+s');assert.equal(await dialog.locator('[data-ai-close]').isDisabled(),true);resolveTest();await dialog.waitFor({state:'hidden'});assert.equal(saves,savesBefore+1);slowTest=false;
await root.locator('[data-ai-new]').click();await dialog.locator('[name="model"]').fill('fixture-model');await dialog.locator('[name="api_key"]').fill('fixture-key');
await page.screenshot({path:'output/ui/ai-config-editor.png',fullPage:true});await page.setViewportSize({width:390,height:844});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:'output/ui/ai-config-mobile.png',fullPage:true});
page.once('dialog',dialog=>dialog.accept());await dialog.locator('[data-ai-close]').click();await page.setViewportSize({width:1600,height:1000});
failLoad=true;await root.locator('[data-ai-refresh]').click();await root.getByRole('button',{name:'重新加载'}).waitFor();assert.equal(await root.locator('[data-ai-new]').isDisabled(),true);
failLoad=false;await root.getByRole('button',{name:'重新加载'}).click();await root.locator('[data-ai-new]:enabled').waitFor();
slowLoad=true;let resolveLoad;releaseLoad=new Promise(resolve=>{resolveLoad=resolve});const loadStarted=new Promise(resolve=>{loadSeen=resolve});
await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','4');dispatchEvent(new Event('tophoo-project-changed'))});await loadStarted;assert.equal(await root.locator('[data-ai-new]').isDisabled(),true);
await page.evaluate(()=>{localStorage.setItem('tophoo-global-selected-project','7');dispatchEvent(new Event('tophoo-project-changed'))});await root.locator('[data-ai-new]:enabled').waitFor();resolveLoad();await page.waitForTimeout(150);assert.ok(!(await root.locator('[data-ai-model-list]').innerText()).includes('过期项目连接'));
page.once('dialog',dialog=>dialog.dismiss());await root.locator('.ai-model-actions .danger').first().click();assert.equal(deletes,0);
page.once('dialog',dialog=>dialog.accept());await root.locator('.ai-model-actions .danger').first().click();await page.waitForTimeout(100);assert.equal(deletes,1);
assert.deepEqual(errors,[]);console.log('AI configuration UI passed: project scope, compact empty bindings, provider inference, draft save, test/save failure recovery, key preservation, dirty guard, duplicate submission, mobile layout, retry, stale project response, delete confirmation.');
}finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
