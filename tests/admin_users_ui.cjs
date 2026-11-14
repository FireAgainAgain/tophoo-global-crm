// All user/account mutations are intercepted; production accounts are never modified.
const {chromium}=require('playwright');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const auth=spawnSync('python',['-c','from sqlalchemy import select; from app.models import User; from app.core.database import SessionLocal; from app.core.security import create_access_token; s=SessionLocal(); print(create_access_token(s.scalar(select(User.id).where(User.is_admin.is_(True))))); s.close()'],{encoding:'utf8'});
  assert.equal(auth.status,0);
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.addCookies([{name:'tophoo_global_access_token',value:auth.stdout.trim(),domain:'127.0.0.1',path:'/',httpOnly:true}]);
    const plans=[{code:'free',name:'CRM 基础授权',is_active:true},{code:'professional',name:'CRM 完整授权',is_active:true}];
    let users=[{id:99999,display_name:'Sales <img src=x onerror=alert(1)>',email:'sales@example.com',phone:'13800138000',wechat_id:'sales-wechat',is_admin:false,is_active:true,project_count:3,plan:plans[0]},
      {id:99998,display_name:'Inactive user',email:'inactive@example.com',phone:null,wechat_id:null,is_admin:false,is_active:false,project_count:0,plan:null}];
    let failSave=false,patches=[],creates=0,releaseSave=null,passwordRequests=[],passwordFail=false;
    await context.route('**/api/**',async route=>{
      const request=route.request(),path=new URL(request.url()).pathname;
      if(path==='/api/admin/users' && request.method()==='GET')return route.fulfill({json:users});
      if(path==='/api/admin/plans' && request.method()==='GET')return route.fulfill({json:{plans}});
      if(path.endsWith('/password') && request.method()==='PATCH') {
        passwordRequests.push(request.postDataJSON());
        if(passwordFail)return route.fulfill({status:500,json:{detail:'保存失败，请重试。'}});
        if(releaseSave)await releaseSave;
        return route.fulfill({json:{message:'密码已修改，下次登录请使用新密码。'}});
      }
      if(path.startsWith('/api/admin/users/') && request.method()==='PATCH') {
        const payload=request.postDataJSON();patches.push(payload);
        if(failSave)return route.fulfill({status:409,json:{detail:'该邮箱已经存在。'}});
        if(releaseSave)await releaseSave;
        const user=users.find(x=>x.id===Number(path.split('/').pop()));Object.assign(user,payload);
        if(payload.plan_code)user.plan=plans.find(p=>p.code===payload.plan_code);
        return route.fulfill({json:user});
      }
      if(path==='/api/admin/users' && request.method()==='POST') {
        creates++;const data=request.postDataJSON();const user={...data,id:99997,is_admin:false,is_active:true,project_count:0,plan:plans.find(p=>p.code===data.plan_code)};users.unshift(user);return route.fulfill({status:201,json:user});
      }
      if(!['GET','HEAD'].includes(request.method()))throw Error('Unexpected mutation '+path);
      return route.continue();
    });
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8002/admin/users');
    await page.locator('[data-edit="99999"]').waitFor();
    assert.equal(await page.locator('#admin-user-rows img').count(),0);
    assert.ok(await page.locator('.admin-users-card').evaluate(el=>el.clientWidth)>1200,'List must use available width');
    const search=page.locator('#user-search'),status=page.locator('#user-status');
    await search.fill('sales-wechat');assert.equal(await page.locator('[data-edit]').count(),1);
    await search.fill('not-here');assert.ok((await page.locator('#admin-user-rows').innerText()).includes('没有符合条件'));
    await search.fill('');await status.selectOption('inactive');assert.equal(await page.locator('[data-edit]').count(),1);
    await status.selectOption('all');
    await page.locator('[data-password="99999"]').click();
    const passwordDialog=page.locator('#user-password-dialog'),passwordForm=page.locator('#user-password-form');
    const newPassword=passwordForm.locator('[name=new_password]'),confirmPassword=passwordForm.locator('[name=confirm_password]');
    await newPassword.fill('SamplePassword2026');await confirmPassword.fill('Mismatch2026');
    await passwordForm.locator('[type=submit]').click();
    assert.equal(passwordRequests.length,0);
    assert.ok((await page.locator('#user-password-message').innerText()).includes('不一致'));
    await confirmPassword.fill('SamplePassword2026');passwordFail=true;
    await passwordForm.locator('[type=submit]').click();
    await page.locator('#user-password-message').filter({hasText:'保存失败'}).waitFor();
    assert.equal(await newPassword.inputValue(),'SamplePassword2026');passwordFail=false;
    let passwordRelease;releaseSave=new Promise(resolve=>{passwordRelease=resolve;});
    await passwordForm.locator('[type=submit]').click();
    assert.equal(await newPassword.isDisabled(),true);await page.keyboard.press('Escape');
    assert.equal(await passwordDialog.isVisible(),true);passwordRelease();
    await passwordDialog.waitFor({state:'hidden'});releaseSave=null;
    assert.deepEqual(passwordRequests.at(-1),{new_password:'SamplePassword2026'});
    assert.equal(await newPassword.inputValue(),'');
    await page.locator('[data-password="99999"]').click();await newPassword.fill('CancelPassword2026');
    await page.keyboard.press('Escape');assert.equal(await newPassword.inputValue(),'');
    await page.locator('[data-edit="99999"]').click();
    const dialog=page.locator('#user-editor-dialog'),form=page.locator('#user-editor-form');
    const field=name=>form.locator(`[name="${name}"]`);
    assert.equal(await dialog.isVisible(),true);assert.equal(await field('password').isVisible(),false);
    assert.equal(await field('email').inputValue(),'sales@example.com');
    await field('display_name').fill('Updated sales');await field('email').fill('updated@example.com');await field('phone').fill('');await field('wechat_id').fill('new-wechat');
    failSave=true;await form.locator('[type=submit]').click();await page.locator('#user-editor-message').filter({hasText:'该邮箱已经存在'}).waitFor();
    assert.equal(await field('email').inputValue(),'updated@example.com');assert.equal(await dialog.isVisible(),true);
    failSave=false;await form.locator('[type=submit]').click();await dialog.waitFor({state:'hidden'});
    assert.equal(patches.at(-1).phone,null);assert.equal(patches.at(-1).wechat_id,'new-wechat');assert.equal('password' in patches.at(-1),false);
    assert.equal('plan_code' in patches.at(-1),false,'Unchanged grants must not be reassigned');
    assert.ok((await page.locator('#admin-user-rows').innerText()).includes('updated@example.com'));
    await page.locator('[data-edit="99999"]').click();await field('display_name').fill('Unsaved');
    page.once('dialog',d=>d.dismiss());await form.locator('[data-close-editor]').last().click();assert.equal(await dialog.isVisible(),true);
    page.once('dialog',d=>d.accept());await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),false);
    fs.mkdirSync('output/ui',{recursive:true});await page.screenshot({path:'output/ui/admin-users-desktop.png'});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('[data-edit="99999"]').click();await field('display_name').fill('Mobile sales');
    assert.ok(await page.evaluate(()=>document.querySelector('#user-editor-dialog').scrollWidth<=document.querySelector('#user-editor-dialog').clientWidth));
    await field('plan_code').selectOption('professional');
    let release;releaseSave=new Promise(resolve=>{release=resolve;});
    await form.locator('[type=submit]').click();assert.equal(await field('email').isDisabled(),true);
    await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true);release();
    await dialog.waitFor({state:'hidden'});releaseSave=null;
    assert.equal(patches.at(-1).plan_code,'professional');
    await page.locator('[data-password="99999"]').click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:'output/ui/admin-users-mobile.png'});
    await page.keyboard.press('Escape');
    await page.locator('#open-create-user').click();assert.equal(await field('password').isVisible(),true);
    await field('display_name').fill('New user');await field('email').fill('new@example.com');await field('password').fill('testpassword123');
    await form.locator('[type=submit]').click();await dialog.waitFor({state:'hidden'});assert.equal(creates,1);
    // Current-admin edits remain available but cannot disable or delete that account.
    const ownId=await page.locator('.admin-layout').getAttribute('data-current-admin-id');
    users.push({id:Number(ownId),display_name:'Admin',email:'admin@example.com',is_admin:true,is_active:true,project_count:0,plan:plans[0]});
    await page.reload();await page.locator(`[data-edit="${ownId}"]`).click();
    assert.equal(await field('is_active').isDisabled(),true);
    assert.equal(await page.locator(`[data-delete="${ownId}"]`).count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: full-width users, escaped data, search/status filter, edit and retry, contact clearing, unchanged grants, unsaved cancel, mobile cards/dialog, pending-save protection, create and self protection; all mutations mocked.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
