// Full UI with fixture CRM writes; only pure time conversion reaches the live API.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),{spawnSync}=require('node:child_process');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const generated=spawnSync('python',['-c',`import json; from datetime import datetime,timezone; from app.services.communication import catalog,overview,place_from_key; from app.core.modules import PROJECT_MODULES; from app.core.security import create_access_token; c=catalog(); print(json.dumps({'catalog':c,'details':{k:overview(place_from_key(k),now=datetime(2026,10,19,8,30,tzinfo=timezone.utc),details=True) for k in c['recommended']},'permissions':list(PROJECT_MODULES),'token':create_access_token(4)},ensure_ascii=False))`],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'},maxBuffer:4*1024*1024,windowsHide:true});
 assert.equal(generated.status,0,generated.stderr);const fixture=JSON.parse(generated.stdout),token=fixture.token;
 const context=await browser.newContext({viewport:{width:1500,height:1080},timezoneId:'Asia/Shanghai'});
 await context.addCookies([{name:'tophoo_global_access_token',value:token,domain:'127.0.0.1',path:'/',httpOnly:true}]);
 await context.addInitScript(token=>{if(window!==window.top)return;localStorage.setItem('tophoo-global-access-token',token);localStorage.setItem('tophoo-global-selected-project','7');localStorage.setItem('tophoo-global-selected-workspace','4');},token);
 let prefs={favorites:fixture.catalog.recommended,overrides:{},home_timezone:'Asia/Shanghai',home_schedule:{weekdays:[0,1,2,3,4],periods:[{start:'09:00',end:'12:00'},{start:'13:00',end:'18:00'}]}},editable=true,fail=false;const saved=new Map(),writes=[];
 const people=[{id:21,contact_name:'Alice',email:'alice@example.test',is_primary:true},{id:22,contact_name:'Bob',email:'bob@example.test'}];
 const customer={id:301,company_name:'Coil Factory',country:'美国',grade:'A',contacts:people,owner_user_id:4,created_at:'2026-10-01',source_type:'自主开发'};
 const result=config=>{const key=config.country+':'+config.timezone,row=fixture.catalog.places.find(p=>p.key===key),base=fixture.details[key]||fixture.details['GB:Europe/London'];return {...structuredClone(base),...row,config:structuredClone(config)};};
 const entity=(kind,id,person='')=>{const own=saved.get(kind+':'+id+':'+person),company=saved.get(kind+':'+id+':'),config=own||company;return {entity_id:id,kind,company_name:kind==='leads'?'Equipment Lead':customer.company_name,country_text:'美国',country_code:'US',person,people:people.map(x=>({key:kind==='leads'?'lead-'+x.id:String(x.id),name:x.contact_name})),origin:own?(person?'person':'company'):company?'company':'unconfigured',has_override:!!own,can_edit:editable,overview:config?result(config):null};};
 await context.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();
  if(/\/api\/projects\/\d+\/visit$/.test(path))return route.fulfill({json:{recorded:true}});
  if(path.startsWith('/api/communication/')){
   const suffix=path.replace('/api/communication/projects/7','');
   if(suffix==='/catalog')return route.fulfill({json:fixture.catalog});
   if(suffix==='/preferences'){if(method==='PUT'){writes.push({kind:'preferences',body:req.postDataJSON()});prefs=req.postDataJSON();}return route.fulfill({json:prefs});}
   if(suffix==='/overview'){if(url.searchParams.has('at'))return route.continue();if(fail)return route.fulfill({status:503,json:{detail:'模拟地区读取失败'}});const keys=url.searchParams.get('keys').split(',');return route.fulfill({json:{items:keys.map(key=>{const row=fixture.catalog.places.find(x=>x.key===key),config=prefs.overrides[key]||{country:row.country,timezone:row.timezone,city:'',subdivision:null,schedule:{weekdays:[0,1,2,3,4],periods:[{start:'09:00',end:'12:00'},{start:'13:00',end:'17:00'}]},closures:[],confirmed:false,respect_public_holidays:true};return result(config);})}});}
   if(suffix==='/preview')return route.fulfill({json:result(req.postDataJSON().config)});
   if(suffix==='/convert')return route.continue(); // No persistence, AI or external provider calls.
   if(suffix.startsWith('/subdivisions/'))return route.fulfill({json:fixture.details['US:America/New_York'].subdivisions});
   if(suffix==='/related-customers')return route.fulfill({json:{items:[{id:301,company_name:'Coil Factory'}],total:1}});
   const match=suffix.match(/^\/entities\/(leads|customers)\/(\d+)$/);if(match){const person=url.searchParams.get('person')||'',id=Number(match[2]),key=match[1]+':'+id+':'+person;if(method==='PUT'){assert.ok(editable);saved.set(key,req.postDataJSON());writes.push({kind:'entity',key,body:req.postDataJSON()});}if(method==='DELETE')saved.delete(key);return route.fulfill({json:entity(match[1],id,person)});}
   throw Error('Unexpected communication request '+method+' '+suffix);
  }
  if(method!=='GET')return route.fulfill({status:418,json:{detail:'Real business writes blocked by UI test'}});
  if(path==='/api/auth/me')return route.continue();
  if(path==='/api/workspaces')return route.fulfill({json:[{id:4,name:'Fixture workspace',role:'owner'}]});
  if(path==='/api/workspaces/4/projects')return route.fulfill({json:[{id:7,name:'Demo',site_url:'https://example.test',role:'top_admin',permissions:fixture.permissions,write_permissions:fixture.permissions}]});
  if(path.endsWith('/members'))return route.fulfill({json:{members:[],modules:[]}});
  if(path.endsWith('/roles'))return route.fulfill({json:[]});
  if(path==='/api/contacts/projects/7')return route.fulfill({json:{customers:[customer],is_top_admin:true,owners:[{id:4,name:'本人'}]}});
  if(path==='/api/customer-workflow/projects/7/leads')return route.fulfill({json:{items:[{...customer,id:201,company_name:'Equipment Lead',workflow_status:'ready'}],is_top_admin:true,owners:[]}});
  if(path.startsWith('/api/followups/'))return route.fulfill({json:path.endsWith('/context')?{company_name:'Coil Factory',people:people.map(p=>({id:p.id,name:p.contact_name})),owners:[{id:4,name:'本人'}],current_user_id:4,can_write:true}:{items:[],counts:{pending:0,today:0,overdue:0,future:0,completed:0,cancelled:0},total:0,is_top_admin:true,can_write:true}});
  if(path.endsWith('/records')||path.endsWith('/interactions'))return route.fulfill({json:{records:[],contact:{name:'Alice',company_name:'Coil Factory'}}});
  if(path.endsWith('/outreach-draft'))return route.fulfill({json:{content:'',content_translation:''}});
  return route.fulfill({json:{items:[],categories:[],scripts:[],sources:[],models:[],features:[],imports:[],customers:[]}});
 });
 async function checkReadability(scope,selectors){
  for(const theme of ['green','blue','purple']){
   await page.evaluate(theme=>document.documentElement.dataset.uiTheme=theme,theme);
   const violations=await scope.evaluate((root,selectors)=>{
    const rgb=value=>(value.match(/[\d.]+/g)||[]).map(Number);
    const luminance=color=>rgb(color).slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
    return selectors.flatMap(selector=>[...root.querySelectorAll(selector)].map(el=>{
     const style=getComputedStyle(el);let bg='rgb(255,255,255)';
     for(let node=el;node;node=node.parentElement){const value=getComputedStyle(node).backgroundColor,parts=rgb(value);if(parts.length===3||parts[3]===1){bg=value;break;}}
     const a=luminance(style.color),b=luminance(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
     return ratio<4.5||parseFloat(style.fontSize)<12?{selector,ratio,font:style.fontSize,color:style.color,bg}:null;
    }).filter(Boolean));
   },selectors);assert.deepEqual(violations,[],theme+' readable text');
  }
  await page.evaluate(()=>document.documentElement.dataset.uiTheme='green');
 }
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8002/?section=communication-assistant');
 const root=page.locator('[data-communication-assistant]'),panel=page.locator('[data-comm-panel]');await root.waitFor({state:'visible'});await root.locator('[data-comm-place="US:America/New_York"]').waitFor();
 assert.equal(await root.locator('[data-comm-place]').count(),8);assert.equal(await root.locator('[data-comm-favorite-count]').innerText(),'8');assert.equal(writes.length,0);
 assert.equal(await root.locator('h1').innerText(),'全球时间 实时');
 assert.equal(await root.locator('[data-comm-place]').first().getAttribute('data-comm-place'),prefs.favorites[0],'Favorites preserve the saved insertion order');
 const compare=root.locator('[data-comm-compare]'),newYork=root.locator('.comm-city-card').filter({has:page.locator('[data-comm-place="US:America/New_York"]')});
 await compare.fill('2026-11-01T13:30');await compare.dispatchEvent('change');await newYork.filter({hasText:'UTC-04:00'}).waitFor();await newYork.locator('.comm-row-clock').filter({hasText:'01:30'}).waitFor();
 await compare.fill('2026-11-01T14:30');await compare.dispatchEvent('change');await newYork.filter({hasText:'UTC-05:00'}).waitFor();assert.equal(await newYork.locator('.comm-row-clock').innerText(),'01:30:00');
 assert.equal(await root.locator('[data-comm-mode]').innerText(),'时间对照');assert.equal(writes.length,0);
 await newYork.locator('[data-comm-place]').click();await panel.locator('[data-comm-conversion]').filter({hasText:'14:30'}).waitFor();assert.equal(await panel.locator('[name="source"]').inputValue(),'beijing');assert.equal(await panel.locator('[name="value"]').inputValue(),'2026-11-01T14:30');await panel.locator('[data-comm-close]').click();

 await root.locator('[data-comm-now]').click();await root.locator('[data-comm-mode]').filter({hasText:'实时'}).waitFor();await newYork.locator('.comm-row-clock').filter({hasText:'04:30'}).waitFor();
 await checkReadability(root,['.comm-place-name strong','.comm-place-name span','.comm-city-date span','.comm-city-card .comm-status','.comm-city-card>footer>span:last-child']);
 fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/communication-assistant-desktop.png',fullPage:true});
 await root.locator('[data-comm-place="US:America/New_York"]').click();await panel.locator('.comm-big-clock').waitFor();
 const convert=panel.locator('[data-comm-convert-form]');await convert.locator('[name="value"]').fill('2026-11-01T01:30');await convert.locator('[type="submit"]').click();await panel.locator('[data-comm-conversion]').filter({hasText:'出现两次'}).waitFor();await convert.locator('[name="fold"]').selectOption('1');await convert.locator('[type="submit"]').click();await panel.locator('[data-comm-conversion]').filter({hasText:'14:30'}).waitFor();assert.equal(writes.length,0,'Time conversion must never save a business record');
 await panel.locator('[data-comm-edit-settings]').click();await panel.locator('[name="period_start"]').first().fill('10:00');await panel.locator('[data-comm-save-settings]').click();await panel.locator('.comm-big-clock').waitFor();assert.equal(prefs.overrides['US:America/New_York'].schedule.periods[0].start,'10:00');assert.equal(writes.at(-1).kind,'preferences');await panel.locator('[data-comm-close]').click();
 await root.locator('[data-comm-star="US:America/New_York"]').click();await root.locator('[data-comm-favorite-count]').filter({hasText:'7'}).waitFor();assert.equal(await root.locator('[data-comm-place="US:America/New_York"]').count(),0);await root.locator('[data-comm-search]').fill('New York');await root.locator('[data-comm-star="US:America/New_York"]').waitFor();await root.locator('[data-comm-star="US:America/New_York"]').click();await root.locator('[data-comm-favorite-count]').filter({hasText:'8'}).waitFor();await root.locator('[data-comm-search]').fill('');
 await root.locator('[data-comm-home]').click();const home=page.locator('[data-comm-home-dialog]');await home.locator('[name="period_end"]').last().fill('18:30');await home.locator('[type="submit"]').click();await home.waitFor({state:'hidden'});assert.equal(prefs.home_schedule.periods[1].end,'18:30');
 await page.evaluate(()=>window.tophooNavigateGlobal('contacts'));await page.locator('[data-detail="301"]').click();await page.locator('[data-comm-inline]').filter({hasText:'补选城市'}).waitFor();await page.locator('[data-comm-open-entity]').click();await panel.locator('[data-comm-edit-settings]').click();await panel.locator('[name="timezone"]').selectOption('America/New_York');await panel.locator('[name="confirmed"]').check();await panel.locator('[data-comm-save-settings]').click();await panel.locator('.comm-big-clock').waitFor();assert.equal(saved.get('customers:301:').timezone,'America/New_York');
 await panel.locator('[data-comm-person]').selectOption('21');await panel.locator('.comm-big-clock').waitFor();assert.match(await panel.innerText(),/公司安排/);await panel.locator('[data-comm-edit-settings]').click();await panel.locator('[name="country"]').selectOption('GB');await panel.locator('[name="timezone"]').selectOption('Europe/London');await panel.locator('[data-comm-save-settings]').click();await panel.locator('.comm-big-clock').waitFor();assert.equal(saved.get('customers:301:21').timezone,'Europe/London');assert.equal(saved.get('customers:301:').timezone,'America/New_York');await page.locator('[data-comm-inline]').filter({hasText:'Alice'}).waitFor();await panel.locator('[data-comm-close]').click();await checkReadability(page.locator('[data-comm-inline]'),['strong','strong>span','small','.comm-status','.comm-inline-meta>span','button']);await page.locator('[data-comm-inline]').scrollIntoViewIfNeeded();await page.screenshot({path:'output/ui/customer-communication-strip.png',fullPage:false});await page.locator('[data-comm-open-entity]').click();await panel.locator('.comm-big-clock').waitFor();
 await convert.locator('[name="value"]').fill('2026-10-26T10:00');await convert.locator('[type="submit"]').click();await panel.locator('[data-comm-create-plan]').waitFor();await panel.locator('[data-comm-create-plan]').click();const plan=page.locator('[data-followup-dialog]');await plan.waitFor({state:'visible'});assert.equal(await plan.locator('[name="due_at"]').inputValue(),'2026-10-26T18:00');assert.equal(await plan.locator('[name="person_id"]').inputValue(),'21');assert.match(await plan.locator('.followup-time-reference').innerText(),/18:00/);await plan.locator('[data-fu-close]').first().click();
 editable=false;await page.locator('[data-comm-open-entity]').click();await panel.locator('.comm-big-clock').waitFor();await panel.locator('[data-comm-edit-settings]').click();assert.equal(await panel.locator('[data-comm-save-settings]').isVisible(),false);await panel.locator('[data-comm-settings-cancel]').click();await panel.locator('[data-comm-close]').click();await page.locator('button[data-detail-close]').click();
 await page.evaluate(()=>window.tophooNavigateGlobal('leads'));await page.locator('[data-detail="201"]').click();await page.locator('[data-comm-inline]').filter({hasText:'补选城市'}).waitFor();await checkReadability(page.locator('[data-comm-inline]'),['strong','small','button']);await page.setViewportSize({width:320,height:740});assert.ok(await page.locator('[data-comm-inline]').evaluate(el=>el.scrollWidth<=el.clientWidth),'Time strip fits a small screen');await page.setViewportSize({width:1500,height:1080});await page.locator('button[data-detail-close]').click();
 await page.evaluate(()=>window.tophooNavigateGlobal('communication-assistant'));await root.locator('[data-comm-place="US:America/New_York"]').waitFor();await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile workspace must not overflow');await page.screenshot({path:'output/ui/communication-assistant-mobile.png',fullPage:true});
 await root.locator('[data-comm-place="US:America/New_York"]').click();await panel.locator('.comm-big-clock').waitFor();assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth),'Side panel must not overflow');assert.ok(await panel.evaluate(el=>el.matches(':modal')&&Math.abs(el.getBoundingClientRect().top)<1&&Math.abs(el.getBoundingClientRect().height-innerHeight)<2),'Panel must cover the viewport in the top layer');await page.screenshot({path:'output/ui/communication-assistant-panel-mobile.png',fullPage:false});await panel.locator('[data-comm-close]').click();
 await page.setViewportSize({width:320,height:740});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Global time fits a 320px screen');await page.setViewportSize({width:390,height:844});
 fail=true;await root.locator('[data-comm-refresh]').click();await root.locator('[data-comm-error]').filter({hasText:'模拟地区读取失败'}).waitFor();fail=false;await root.locator('[data-comm-refresh]').click();await root.locator('[data-comm-place="US:America/New_York"]').waitFor();
 assert.deepEqual(errors,[]);assert.ok(writes.every(x=>['preferences','entity'].includes(x.kind)));console.log('PASS communication assistant: clocks, DST conversion, personal favorites/schedules, company/person inheritance, read-only preview, lead strip, prefilled follow-up, retry and mobile. All persistence mocked.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
