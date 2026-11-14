// Isolated UI fixture: real scripts/styles, all business writes mocked.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const css=fs.readFileSync('app/templates/index.html','utf8').match(/<link rel="stylesheet"[^>]+>/g).join('');
 await context.route('**/__contact_scan_ui',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">${css}</head><body><section data-workflow-detail data-permission-module="leads"><section data-detail-people><div class="people-panel-heading"><h2>联系人信息</h2></div></section></section><script src="/static/js/lead-contact-scan.js"></script></body></html>`}));
 let reads=0,imports=0,starts=0,failImport=true,refreshes=0;
 const people=[{contact_name:'Jane Doe',email:'',phone:'',notes:'采购经理',is_primary:true},{contact_name:'Office',email:'info@factory.test'}];
 const row={id:'1',contact_name:'Jane Doe',title:'Purchasing Manager',email:'jane@factory.test',phone:'+46701234567',whatsapp:'',phone_kind:'公开电话，类型待核实',source_url:'https://factory.test/team',sources:['https://factory.test/team'],evidence:'Jane Doe Purchasing Manager jane@factory.test',verification:'公开披露，未验证有效性'};
 const result={items:[row,{...row,id:'2',contact_name:'',title:'',email:'info@factory.test',phone:'',evidence:'<img src=x onerror=alert(1)>'},...Array.from({length:17},(_,i)=>({...row,id:String(i+3),contact_name:'',title:'',email:`office${i+1}@factory.test`,phone:i%2?'':`+97143574${String(i).padStart(3,'0')}`}))],pages:[{url:'https://factory.test/team'},{url:'https://factory.test/contact'}],warnings:['官网未公开的个人手机号不会猜测填写。'],scanned_at:'2026-10-30T09:00:00'};
 result.items[0].matches=[{index:0,kind:'possible',reasons:['姓名相同，待核对']}];result.items[1].matches=[{index:1,kind:'existing',reasons:['邮箱相同']}];result.items[2].whatsapp='+971507084479';
 await context.route('**/api/**',r=>{const request=r.request(),path=new URL(request.url()).pathname;
  if(path.endsWith('/discard')){const ids=request.postDataJSON().candidate_ids;result.items=result.items.filter(row=>!ids.includes(row.id));return r.fulfill({json:{id:5,status:'completed',contacts:people,contacts_version:'b'.repeat(64),result}});}
  if(path.endsWith('/import')){imports++;const p=request.postDataJSON();assert.equal(p.choices.length,1);assert.equal(p.choices[0].target_index,0);if(failImport)return r.fulfill({json:{saved:false,conflicts:[{candidate_id:'1',message:'已有邮箱与结果冲突，请核对。'}]}});people[0].email=row.email;result.items[0].matches=[{index:0,kind:'existing',reasons:['邮箱相同']}];return r.fulfill({json:{saved:true,applied:1,contacts:people,contacts_version:'b'.repeat(64),result}});}
  if(request.method()==='POST'){starts++;return r.fulfill({status:202,json:{id:5,status:'pending',contacts:people,contacts_version:'a'.repeat(64),result:{},progress:{}}});}
  reads++;return r.fulfill({json:reads===1?{id:null,contacts:people,contacts_version:'a'.repeat(64)}:{id:5,status:'completed',contacts:people,contacts_version:'a'.repeat(64),result,progress:{scanned:1,found:2}}});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8002/__contact_scan_ui');
 await page.evaluate(()=>{document.addEventListener('tophoo-return-workflow-detail',()=>window.refreshed=true);document.dispatchEvent(new CustomEvent('tophoo-workflow-detail-ready',{detail:{project:7,id:694,view:'leads',item:{company_name:'NIBE 集团 · 官网联系人查找',company_website:'https://factory.test'}}}));});
 await page.locator('[data-scan-open]').click();const dialog=page.locator('.contact-scan-dialog');await dialog.waitFor({state:'visible'});
 await page.locator('.contact-scan-empty').waitFor();await page.locator('[data-scan-start]').click();
 await page.locator('.contact-scan-result').first().waitFor();assert.equal(starts,1);assert.equal(await page.locator('.contact-scan-result').count(),19);
 assert.equal(await page.locator('[data-scan-target="1"]').inputValue(),'0');assert.equal(await page.locator('[data-scan-import]').isDisabled(),true);
 assert.equal(await page.locator('[data-scan-target="1"]').isVisible(),false,'Save settings start collapsed');
 await page.locator('[data-scan-select="1"]').check();
 await page.locator('[data-scan-filter="existing"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),1);assert.ok((await page.locator('[data-scan-row="2"]').innerText()).includes('Office'));
 await page.locator('[data-scan-filter="whatsapp"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),1);
 await page.locator('[data-scan-filter="phone"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),10);
 await page.locator('[data-scan-filter="email"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),19);
 await page.locator('[data-scan-filter="new"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),17);
 await page.locator('[data-scan-all]').check();assert.equal(await page.locator('[data-scan-selected]').innerText(),'已选 18 项');
 await page.locator('[data-scan-all]').uncheck();assert.equal(await page.locator('[data-scan-selected]').innerText(),'已选 1 项');
 await page.locator('[data-scan-filter="all"]').click();
 await page.locator('[data-scan-search]').fill('jane@');assert.equal(await page.locator('[data-scan-row]:visible').count(),1);await page.locator('[data-scan-search]').fill('');
 await page.locator('[data-scan-import]').click();await page.locator('[data-scan-conflict="1"]').filter({hasText:'冲突'}).waitFor();assert.equal(imports,1);assert.equal(await page.locator('[data-scan-select="1"]').isChecked(),true);
 await page.locator('[data-scan-filter="conflicts"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),1);
 await page.locator('[data-scan-clear-conflicts]').click();assert.equal(await page.locator('[data-scan-import]').isDisabled(),true);await page.locator('[data-scan-select="1"]').check();await page.locator('[data-scan-filter="all"]').click();
 failImport=false;await page.locator('[data-scan-import]').click();await page.locator('[data-scan-message]').filter({hasText:'状态保持不变'}).waitFor();assert.equal(await page.evaluate(()=>window.refreshed),true);assert.equal(imports,2);await page.locator('[data-scan-filter="existing"]').click();assert.equal(await page.locator('[data-scan-row]:visible').count(),2);await page.locator('[data-scan-filter="all"]').click();
 assert.equal(await dialog.locator('img').count(),0,'Source text is escaped');
 const rowHeight=await page.locator('[data-scan-row="1"]').evaluate(el=>el.getBoundingClientRect().height);assert.ok(rowHeight<115,'Results are compact rather than tall cards');
 await page.screenshot({path:'output/ui/lead-contact-scan-desktop.png',fullPage:true});
 await page.locator('.contact-scan-result details').first().locator('summary').click();assert.ok(await page.locator('.contact-scan-row-expanded').first().evaluate(el=>el.getBoundingClientRect().width>500),'Expanded source uses full row width');await page.screenshot({path:'output/ui/lead-contact-scan-expanded.png',fullPage:true});await page.locator('.contact-scan-result details').first().locator('summary').click();
 await page.setViewportSize({width:390,height:844});assert.ok(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),'No horizontal dialog overflow');await page.screenshot({path:'output/ui/lead-contact-scan-mobile.png',fullPage:true});
 await page.locator('.contact-scan-result details').first().locator('summary').click();assert.ok(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),'Expanded mobile source fits dialog');await page.locator('.contact-scan-result details').first().locator('summary').click();
 await page.locator('[data-scan-select="3"]').check();await page.locator('[data-scan-delete="3"]').click();await page.locator('[data-scan-row="3"]').waitFor({state:'detached'});assert.equal(await page.locator('[data-scan-selected]').innerText(),'已选 0 项');await page.locator('[data-scan-refresh]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-scan-row]').length===18);
 page.once('dialog',d=>d.dismiss());await page.locator('[data-scan-clear]').click();assert.equal(await page.locator('[data-scan-row]').count(),18);
 page.once('dialog',d=>d.accept());await page.locator('[data-scan-clear]').click();await page.locator('.contact-scan-empty').waitFor();assert.equal(await page.locator('[data-scan-import]').isDisabled(),true);assert.equal(people.length,2);
 await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),false);assert.deepEqual(errors,[]);
 console.log('PASS contact scan: 19 compact rows, collapsed settings, category/search filters, filtered selection, conflict recovery, source escaping, save, desktop/mobile and Escape. All writes mocked.');
 }finally{await browser.close();}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
