/* Personal email settings and one explicit SMTP submission per request key. */
(() => {
  const root=document.querySelector('[data-mail-config]');if(!root)return;
  const q=selector=>root.querySelector(selector),form=q('[data-mail-form]');
  const signatureField=form.elements.signature,signatureBody=document.createElement('div');signatureField.hidden=true;signatureField.after(signatureBody);const signatureEditor=window.TophooRichMail.mount(signatureBody);signatureBody.addEventListener('input',()=>{signatureField.value=signatureEditor.get().content_html;});
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const requestKey=()=>{const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const h=[...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;};
  const labels={accepted:'服务器已接受',failed:'发送失败',unknown:'结果待核实',pending:'处理中 / 待核实'};
  const fieldNames=['sender_name','email','host','port','encryption','username','signature'];
  let baseline='',loaded=false,busy=false,generation=0,sendDialog=null,editing=false,savedConfig=null,accounts=[],selectedAccount=null,creating=false,beforeCreate=null;
  const snapshot=()=>JSON.stringify(Object.fromEntries([...fieldNames,'password'].map(name=>[name,form.elements[name].value])));
  const dirty=()=>loaded&&snapshot()!==baseline;
  const stamp=value=>value?value.slice(0,19).replace('T',' '):'';
  const fieldLabels={host:'SMTP 服务器',port:'端口',encryption:'加密方式',email:'发件邮箱',username:'登录账号',password:'授权码',sender_name:'发件人名称',signature:'邮件签名'};
  function apiError(data,status){
    if(typeof data.detail==='string')return data.detail;
    if(Array.isArray(data.detail))return data.detail.map(item=>{
      const field=item.loc?.at(-1),label=fieldLabels[field];
      const message=String(item.msg||'填写内容不正确').replace(/^Value error,\s*/, '');
      return (label?label+'：':'')+message;
    }).join('；');
    if(status===401)return '登录已失效，请重新登录后再试。';
    if(status===413)return '提交内容过大，请缩减签名或图片后再试。';
    return '操作失败，请稍后重试。';
  }
  function validateConnectionFields(){
    const host=form.elements.host,mode=form.elements.encryption;
    const name=host.value.trim();
    host.setCustomValidity(name&&(!/^[A-Za-z0-9.-]+$/.test(name)||name.includes('..'))?'请填写 SMTP 域名，例如 smtp.163.com，不要填写网页地址。':'');
    mode.setCustomValidity(Number(form.elements.port.value)===465&&mode.value!=='ssl'?'465 端口请搭配 SSL / TLS，不要选择 STARTTLS。':'');
  }
  async function api(path,options={}){
    const response=await fetch('/api/mail'+path,{...options,headers:{...(window.tophooAuth?.headers?.()||{}),...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const error=Error(apiError(data,response.status));error.status=response.status;throw error;}return data;
  }
  function feedback(message='',error=false){const node=q('[data-mail-feedback]');if(node.textContent!==message)node.textContent=message;node.classList.toggle('is-error',error);}
  function controls(){
    form.hidden=!editing;q('[data-mail-saved]').hidden=editing||!savedConfig?.configured;
    form.querySelectorAll('input,select,textarea,button').forEach(node=>node.disabled=busy||!loaded||!editing);
    signatureEditor.lock(busy||!loaded||!editing);
    q('[data-mail-edit]').disabled=busy||!loaded;
    q('[data-mail-test]').disabled=busy||!loaded||editing||!savedConfig?.configured;
    q('[data-mail-test-message]').disabled=busy||!loaded||editing||!savedConfig?.configured;
    q('[data-mail-cancel]').hidden=!savedConfig?.configured&&!accounts.length;
    root.querySelectorAll('[data-mail-account],[data-mail-account-add],[data-mail-account-default],[data-mail-account-delete]').forEach(node=>node.disabled=busy||!loaded);
    q('[data-mail-account-default]').hidden=accounts.some(a=>a.account_id===selectedAccount&&a.is_default);
    q('[data-mail-account-add]').disabled=busy||!loaded;
    q('[data-mail-save-hint]').textContent=dirty()?'有未保存的修改':savedConfig?.configured?'授权码留空保留，输入新值替换':'填写后保存，再测试连接';
    if(loaded&&savedConfig){
      const changed=editing&&dirty(),config=savedConfig,badge=q('[data-mail-test-status]');
      const text=changed?'修改未保存':config.last_test_status==='passed'?'测试通过 · '+stamp(config.last_tested_at):config.last_test_status==='failed'?'测试失败 · '+stamp(config.last_tested_at):config.configured?'已保存 · 尚未测试':'未配置';
      if(badge.textContent!==text)badge.textContent=text;
      badge.className='mail-status'+(!changed&&config.last_test_status?' is-'+config.last_test_status:'');
      badge.title=changed?'当前修改尚未生效，保存后重新测试连接。':config.last_test_message||'';
    }
  }
  function render(config){
    savedConfig={...config};editing=!config.configured;creating=!config.configured;selectedAccount=config.configured?(config.account_id??0):null;
    fieldNames.forEach(name=>form.elements[name].value=config[name]??'');signatureEditor.set(/<[a-z][\s\S]*>/i.test(config.signature||'')?config.signature:'',config.signature||'');form.elements.password.value='';form.elements.password.type='password';
    q('[data-mail-reveal]').textContent='显示';q('[data-mail-reveal]').setAttribute('aria-pressed','false');
    form.elements.password.placeholder=config.has_password?'授权码已保存，留空保留；输入新值可替换':'填写邮箱授权码或客户端专用密码';
    const badge=q('[data-mail-test-status]');badge.className='mail-status'+(config.last_test_status?' is-'+config.last_test_status:'');
    badge.textContent=config.last_test_status==='passed'?'测试通过 · '+stamp(config.last_tested_at):config.last_test_status==='failed'?'测试失败 · '+stamp(config.last_tested_at):config.configured?'已保存 · 尚未测试':'未配置';
    badge.title=config.last_test_message||'';
    q('[data-mail-saved-email]').textContent=config.email||'';
    q('[data-mail-saved-name]').textContent=config.sender_name||'未设置发件人名称';
    q('[data-mail-saved-server]').textContent=(config.host||'')+':'+(config.port||'');
    q('[data-mail-saved-encryption]').textContent=config.encryption==='starttls'?'STARTTLS':'SSL / TLS';
    q('[data-mail-saved-username]').textContent=config.username||'';
    q('[data-mail-saved-secret]').textContent=config.has_password?'已安全保存':'未设置';
    q('[data-mail-signature-view]').hidden=!config.signature;q('[data-mail-signature-view]').open=false;
    const frame=q('[data-mail-signature-preview]');frame.removeAttribute('srcdoc');
    validateConnectionFields();loaded=true;baseline=snapshot();controls();renderAccounts();
  }
  async function history(){
    const version=generation;
    try{const data=await api('/deliveries');if(version!==generation)return;
      q('[data-mail-history]').innerHTML=data.items.length?data.items.map(row=>`<article class="mail-history-row"><div><strong>${esc(row.subject)}</strong><p>${esc(row.sender)} → ${esc(row.recipient)}</p><p>${esc(row.message)}</p></div><div><span class="mail-status ${row.status==='accepted'?'is-passed':row.status==='failed'?'is-failed':''}">${esc(labels[row.status]||row.status)}</span><p><small>${esc(stamp(row.created_at))}</small></p></div><details><summary>查看邮件与附件</summary><pre>${esc(row.content)}</pre>${row.content_html?`<button type="button" data-mail-rich-history="${row.id}">查看图文邮件</button>`:''}<p>${row.attachments.length?'附件：'+row.attachments.map(file=>esc(file.name)).join('、'):'无附件'}</p></details></article>`).join(''):'<div class="mail-empty">暂无发送记录</div>';
      q('[data-mail-history]').querySelectorAll('[data-mail-rich-history]').forEach(button=>button.onclick=()=>{const row=data.items.find(item=>item.id===Number(button.dataset.mailRichHistory));const view=document.createElement('dialog');view.className='mail-html-dialog';view.innerHTML='<h3>邮件图文内容</h3><iframe sandbox="" title="邮件图文内容"></iframe><button type="button">关闭</button>';view.querySelector('iframe').srcdoc='<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; img-src https: data:; style-src &apos;unsafe-inline&apos;">'+window.TophooRichMail.clean(row.content_html);view.querySelector('button').onclick=()=>view.close();view.addEventListener('close',()=>view.remove());document.body.append(view);view.showModal();});
    }catch(e){if(version===generation)q('[data-mail-history]').textContent=e.message;}
  }
  function renderAccounts(){
    q('[data-mail-account-count]').textContent=accounts.length;
    q('[data-mail-account-list]').innerHTML=accounts.length?accounts.map(account=>`<button type="button" class="mail-account-choice" data-mail-account="${account.account_id}" aria-pressed="${!creating&&account.account_id===selectedAccount}"><span class="mail-account-choice-icon" aria-hidden="true">✉</span><span><strong>${esc(account.sender_name||account.email)}</strong><small>${esc(account.email)}</small><em class="${account.last_test_status==='passed'?'is-passed':account.last_test_status==='failed'?'is-failed':''}">${account.last_test_status==='passed'?'连接通过':account.last_test_status==='failed'?'连接失败':'尚未测试'}</em></span>${account.is_default?'<b>默认</b>':''}</button>`).join(''):'<div class="mail-accounts-empty">尚未添加邮箱<br>点击右上角添加第一个邮箱</div>';
  }
  async function refreshAccounts(){const version=generation,data=await api('/accounts');if(version===generation){accounts=data.items||[];renderAccounts();}return data;}
  async function chooseAccount(id){
    if(busy||(dirty()&&!confirm('邮箱配置尚未保存，确定放弃修改吗？')))return;
    const version=++generation;busy=true;controls();feedback('正在读取…');
    try{const config=await api('/configuration?account_id='+id);if(version===generation){render(config);feedback();}}
    catch(e){if(version===generation)feedback(e.message,true);}finally{if(version===generation){busy=false;controls();}}
  }
  q('[data-mail-account-list]').onclick=e=>{const button=e.target.closest('[data-mail-account]');if(button)chooseAccount(Number(button.dataset.mailAccount));};
  q('[data-mail-account-add]').onclick=()=>{if(busy||(dirty()&&!confirm('邮箱配置尚未保存，确定放弃修改吗？')))return;beforeCreate=savedConfig;render({configured:false,port:465,encryption:'ssl'});feedback('填写新邮箱，签名和连接设置将独立保存。');form.elements.email.focus();};
  q('[data-mail-account-default]').onclick=async()=>{if(busy||selectedAccount===null)return;busy=true;controls();const version=generation;
    try{await api(`/accounts/${selectedAccount}/default`,{method:'POST'});if(version===generation){await refreshAccounts();feedback('已设为默认发件邮箱。');}}catch(e){if(version===generation)feedback(e.message,true);}finally{if(version===generation){busy=false;controls();}}
  };
  q('[data-mail-account-delete]').onclick=async()=>{if(busy||selectedAccount===null||!confirm(`确定删除邮箱 ${savedConfig.email} 的配置吗？历史发送记录会保留。`))return;busy=true;controls();const version=generation;
    try{await api(`/accounts/${selectedAccount}`,{method:'DELETE'});if(version===generation){const data=await refreshAccounts();const next=await api(data.default_account_id==null?'/configuration':'/configuration?account_id='+data.default_account_id);if(version===generation){render(next);feedback('邮箱配置已删除，发送记录已保留。');}}}catch(e){if(version===generation)feedback(e.message,true);}finally{if(version===generation){busy=false;controls();}}
  };
  async function load(){
    if(busy||dirty())return;const version=++generation;busy=true;controls();
    try{const list=await refreshAccounts();const data=await api(list.default_account_id==null?'/configuration':'/configuration?account_id='+list.default_account_id);if(version!==generation)return;render(data);feedback(data.last_test_status==='failed'?data.last_test_message||'连接测试失败，请重新测试。':'',data.last_test_status==='failed');await history();}
    catch(e){if(version===generation)feedback(e.message,true);}
    finally{if(version===generation){busy=false;controls();}}
  }
  form.addEventListener('input',()=>{validateConnectionFields();controls();if(dirty())feedback('尚未保存；修改连接信息后需重新测试。');});
  form.elements.email.addEventListener('change',()=>{if(!form.elements.username.value){form.elements.username.value=form.elements.email.value;controls();}});
  q('[data-mail-reveal]').onclick=()=>{const visible=form.elements.password.type==='password';form.elements.password.type=visible?'text':'password';q('[data-mail-reveal]').textContent=visible?'隐藏':'显示';q('[data-mail-reveal]').setAttribute('aria-pressed',String(visible));};
  form.onsubmit=async event=>{
    event.preventDefault();validateConnectionFields();if(busy||!editing||!form.reportValidity())return;
    const data=Object.fromEntries(new FormData(form));data.port=Number(data.port);if(!data.password)delete data.password;
    busy=true;controls();feedback('正在保存…');const version=generation;
    try{const config=await api(creating?'/accounts':`/accounts/${selectedAccount}`,{method:creating?'POST':'PUT',body:JSON.stringify(data)});if(version===generation){render(config);await refreshAccounts();feedback('配置已保存。');}}
    catch(e){if(version===generation)feedback(e.message,true);}
    finally{if(version===generation){busy=false;controls();}}
  };
  q('[data-mail-test]').onclick=async()=>{
    if(busy||editing||dirty())return;const version=generation;busy=true;controls();feedback('正在验证 TLS 连接和邮箱账号…');
    try{const config=await api('/configuration/test?account_id='+selectedAccount,{method:'POST'});if(version===generation){render(config);await refreshAccounts();feedback(config.last_test_message,config.last_test_status!=='passed');}}
    catch(e){if(version===generation)feedback(e.message,true);}
    finally{if(version===generation){busy=false;controls();}}
  };
  q('[data-mail-test-message]').onclick=async()=>{
    if(busy||editing||dirty()||!confirm(`确认发送一封测试邮件到自己的邮箱 ${form.elements.email.value}？`))return;
    busy=true;controls();feedback('正在发送测试邮件…');const version=generation;
    try{const row=await api('/test-message',{method:'POST',body:JSON.stringify({request_key:requestKey(),account_id:selectedAccount})});if(version===generation){feedback(row.message,row.status!=='accepted');await history();}}
    catch(e){if(version===generation)feedback('未能确认发送结果，请先刷新发送记录核实，勿直接重发。',true);}
    finally{if(version===generation){busy=false;controls();}}
  };
  q('[data-mail-edit]').onclick=()=>{if(busy||!loaded)return;editing=true;feedback('');controls();form.elements.sender_name.focus({preventScroll:true});};
  q('[data-mail-cancel]').onclick=()=>{if(busy)return;if(dirty()&&!confirm('确定放弃本次邮箱配置修改吗？'))return;render(creating&&beforeCreate?.configured?beforeCreate:savedConfig);feedback('');q('[data-mail-edit]').focus({preventScroll:true});};
  q('[data-mail-signature-view]').addEventListener('toggle',()=>{
    const frame=q('[data-mail-signature-preview]');if(!q('[data-mail-signature-view]').open||frame.hasAttribute('srcdoc')||!savedConfig?.signature)return;
    const signature=/<[a-z][\s\S]*>/i.test(savedConfig.signature)?window.TophooRichMail.clean(savedConfig.signature):'<p>'+esc(savedConfig.signature).replace(/\n/g,'<br>')+'</p>';
    frame.srcdoc='<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; img-src https: data:; style-src &apos;unsafe-inline&apos;"><style>body{margin:0;font:13px/1.7 Arial,sans-serif;color:#253044;overflow-wrap:anywhere}img,table{max-width:100%}img{height:auto}</style>'+signature;
  });
  q('[data-mail-history-refresh]').onclick=history;
  document.addEventListener('tophoo-mail-config-view',load);
  document.addEventListener('tophoo-auth-changed',()=>{generation++;loaded=false;busy=false;baseline='';editing=false;savedConfig=null;accounts=[];selectedAccount=null;creating=false;beforeCreate=null;renderAccounts();form.reset();signatureEditor.set('','');q('[data-mail-saved]').hidden=true;form.hidden=true;q('[data-mail-signature-preview]').removeAttribute('srcdoc');controls();form.elements.password.value='';q('[data-mail-history]').textContent='';feedback('');sendDialog?.close();sendDialog?.remove();sendDialog=null;if(!root.hidden)load();});
  document.addEventListener('click',event=>{
    if(root.hidden||!event.target.closest('.global-nav-item,.crm-primary-item')||event.target.closest('[data-crm-section="mail-config"]'))return;
    if(busy){event.preventDefault();event.stopImmediatePropagation();return;}
    if(dirty()){
      if(!confirm('邮箱配置尚未保存，确定放弃修改吗？')){event.preventDefault();event.stopImmediatePropagation();return;}
      render(savedConfig);feedback('');
    }
  },true);
  window.addEventListener('beforeunload',event=>{if(dirty()||busy){event.preventDefault();event.returnValue='';}});

  async function compose(context){
    if(sendDialog?.open)return null;
    const dialog=document.createElement('dialog');dialog.className='mail-send-dialog mail-send-review';dialog.dataset.permissionModule='leads';dialog.setAttribute('aria-labelledby','mail-send-title');sendDialog=dialog;
    const validEmail=value=>/^[\x21-\x7e]+$/.test(value)&&/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(value);
    const people=[],seen=new Set(),unavailable=[];
    for(const person of context.people||[]){const email=(person.email||'').trim();if(!validEmail(email)){unavailable.push(person.contact_name||email||'未具名联系人');continue;}const key=email.toLowerCase();if(seen.has(key))continue;seen.add(key);people.push({name:person.contact_name||'',email});}
    const initial=(context.recipient||'').trim(),initialMatch=people.findIndex(p=>p.email.toLowerCase()===initial.toLowerCase());
    dialog.innerHTML=`<header><div><h2 id="mail-send-title">发送开发信</h2>${context.company_name?`<p class="mail-send-company">${esc(context.company_name)}</p>`:''}</div><button type="button" data-mail-send-close aria-label="关闭发送预览">×</button></header>
    <div class="mail-send-content"><aside class="mail-send-sidebar"><label class="mail-sender-picker">发件邮箱<select data-mail-sender-select aria-label="选择发件邮箱" disabled><option>正在读取…</option></select></label><div class="mail-send-from" data-mail-from>正在读取发件邮箱…</div>
      <section class="mail-recipient-picker" aria-label="选择该客户的收件联系人"><div class="mail-recipient-heading"><strong>收件人 <span data-mail-recipient-count>0</span></strong><label><input type="checkbox" data-mail-recipient-all>全选</label></div>
      <div class="mail-recipient-options">${people.map((p,i)=>`<label class="mail-recipient-option"><input type="checkbox" data-mail-contact="${i}" ${i===initialMatch?'checked':''}><span><strong>${esc(p.name&&p.name.toLowerCase()!==p.email.toLowerCase()?p.name:p.email)}</strong>${p.name&&p.name.toLowerCase()!==p.email.toLowerCase()?`<small>${esc(p.email)}</small>`:''}<em data-mail-outreach="${i}">正在读取发送次数…</em></span></label>`).join('')||'<p class="mail-recipient-empty">暂无联系人邮箱，请在下方添加。</p>'}</div>
      ${unavailable.length?`<details class="mail-recipient-unavailable"><summary>${unavailable.length} 位联系人未填有效邮箱</summary><p>${unavailable.map(esc).join('、')}</p></details>`:''}
      <details class="mail-recipient-extra-box" ${initialMatch<0&&initial?'open':''}><summary>＋ 其他收件人</summary><label class="mail-recipient-extra">邮箱<input type="email" maxlength="260" data-mail-recipient placeholder="name@company.com" value="${esc(initialMatch<0?initial:'')}"></label></details>
      <p class="mail-recipient-hint">每位联系人单独收到一封邮件。</p></section></aside>
      <main class="mail-send-preview"><section class="mail-batch-results" data-mail-batch-results hidden aria-label="逐人发送结果"></section><div class="mail-preview-heading"><span>邮件预览</span><button type="button" data-mail-add-signature hidden>＋ 添加签名</button></div><h3>${esc(context.subject)}</h3><p class="mail-preview-hint">请确认正文称呼适用于所选联系人</p><div class="mail-rich-preview" data-mail-body></div>
      <section class="mail-send-files" aria-label="邮件附件"><div class="mail-attachment-heading"><strong>附件 <span data-mail-file-count></span></strong><button type="button" data-mail-add-files>＋ 添加附件</button><input type="file" multiple data-mail-files aria-label="选择邮件附件" hidden></div><ul data-mail-file-list hidden></ul><small>目录、图纸、报价等 · 最多 5 个 / 10 MB · 随每封邮件发送</small></section></main></div>
    <footer><span role="status" data-mail-send-status>选择收件人后即可发送</span><div class="mail-send-footer-actions"><button type="button" data-mail-send-query hidden>查询发送结果</button><button type="button" data-mail-send-close>返回修改</button><button type="button" class="mail-primary" data-mail-send-confirm disabled>确认发送</button></div></footer>`;
    document.body.append(dialog);dialog.showModal();
    const find=s=>dialog.querySelector(s),version=generation;
    let sending=false,started=false,config=null,body=context.content,bodyHtml=context.content_html||'',targets=[],stopped=false,hasAttempted=false,attachments=[],senderVersion=0,signatureAdded=false,senderAccountsReady=false;
    const sameContext=()=>version===generation&&dialog.isConnected&&context.project===Number(localStorage.getItem('tophoo-global-selected-project'));
    const say=message=>find('[data-mail-send-status]').textContent=message;
    const selectedPeople=()=>{
      const list=people.filter((p,i)=>find(`[data-mail-contact="${i}"]`).checked).map(p=>({...p})),extra=find('[data-mail-recipient]').value.trim();
      if(extra&&!list.some(p=>p.email.toLowerCase()===extra.toLowerCase())){const person=(context.people||[]).find(p=>p.email?.toLowerCase()===extra.toLowerCase());list.push({email:extra,name:person?.contact_name||(extra.toLowerCase()===initial.toLowerCase()?context.contact_name||'':'')});}
      return list;
    };
    const renderBody=()=>{const node=find('[data-mail-body]');node.style.whiteSpace=bodyHtml?'normal':'pre-wrap';if(bodyHtml)node.innerHTML=window.TophooRichMail.clean(bodyHtml);else node.textContent=body;};renderBody();
    async function refreshOutreach(){try{const data=await api(`/projects/${context.project}/leads/${context.id}/outreach-summary`,{cache:'no-store'});if(!sameContext())return;people.forEach((person,index)=>{const badge=find(`[data-mail-outreach="${index}"]`);if(!badge)return;const count=data.outreach_stats?.[person.email.toLowerCase()]?.sent_count||0;badge.textContent=count?`已发开发信 · ${count} 封`:'未发开发信';badge.classList.toggle('is-sent',count>0);});}catch{if(sameContext())dialog.querySelectorAll('[data-mail-outreach]').forEach(node=>node.textContent='发送记录暂不可用');}}
    function outreachUpdated(){refreshOutreach();document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-updated',{detail:{project:context.project,id:context.id}}));}
    const stateLabels={ready:'待发送',sending:'发送中',accepted:'服务器已接受',failed:'发送失败',unknown:'结果待核实',pending:'处理中 / 待核实',retry_same:'可继续提交'};
    function renderResults(){find('[data-mail-batch-results]').hidden=!started;find('[data-mail-batch-results]').innerHTML=targets.map((t,i)=>`<div class="mail-batch-result" data-mail-result="${i}" data-state="${esc(t.status)}"><div><strong>${esc(t.name||t.email)}</strong>${t.name?`<small>${esc(t.email)}</small>`:''}</div><span>${stateLabels[t.status]||'待核实'}</span>${t.message?`<p>${esc(t.message)}</p>`:''}</div>`).join('');}
    function summary(){const count=status=>targets.filter(t=>t.status===status).length,accepted=count('accepted'),failed=count('failed'),unknown=count('unknown')+count('pending'),ready=count('ready')+count('retry_same');return `服务器已接受 ${accepted} / ${targets.length} 封${failed?' · 失败 '+failed+' 封':''}${unknown?' · 待核实 '+unknown+' 封':''}${ready?' · 未完成 '+ready+' 封':''}。${accepted?'开发信发送次数已更新。':''}`;}
    function lock(){
      dialog.querySelectorAll('input,select').forEach(node=>node.disabled=sending||started);
      find('[data-mail-sender-select]').disabled=sending||started||!senderAccountsReady;
      dialog.querySelectorAll('button').forEach(node=>node.disabled=sending);
      find('[data-mail-add-signature]').disabled=sending||started;find('[data-mail-add-files]').disabled=sending||started;
      const count=started?targets.length:selectedPeople().length;find('[data-mail-recipient-count]').textContent=`已选 ${count} 位`;
      const checks=[...dialog.querySelectorAll('[data-mail-contact]')],checked=checks.filter(c=>c.checked).length,all=find('[data-mail-recipient-all]');all.checked=checks.length>0&&checked===checks.length;all.indeterminate=checked>0&&checked<checks.length;all.disabled=sending||started||!checks.length;
      const actionable=targets.filter(t=>['ready','failed','retry_same'].includes(t.status));
      const confirm=find('[data-mail-send-confirm]');confirm.disabled=sending||stopped||!config||!sameContext()||(!started?!count:!actionable.length);
      confirm.textContent=sending?'正在发送…':!started?`确认发送${count?' · '+count+' 位':''}`:actionable.length?`继续发送 · ${actionable.length} 位`:'本次发送已处理';
      find('[data-mail-send-query]').hidden=!hasAttempted;
    }
    const promise=new Promise(resolve=>{
      let finished=false;
      const finish=()=>{if(finished)return;finished=true;const accepted=targets.filter(t=>t.status==='accepted').length;dialog.remove();if(sendDialog===dialog)sendDialog=null;resolve(started?{status:accepted===targets.length?'accepted':'partial',accepted_count:accepted,total:targets.length,items:targets.map(t=>({recipient:t.email,status:t.status,id:t.row?.id}))}:null);};
      const close=()=>{if(sending)return say('正在发送，请稍候。');dialog.close();finish();};dialog.addEventListener('close',finish,{once:true});
      dialog.querySelectorAll('[data-mail-send-close]').forEach(node=>node.onclick=close);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});dialog.addEventListener('keydown',e=>{if(e.key==='Escape')e.stopPropagation();});
    });
    function beforeUnload(e){if(sending||targets.some(t=>['unknown','pending'].includes(t.status))){e.preventDefault();e.returnValue='';}}window.addEventListener('beforeunload',beforeUnload);promise.then(()=>window.removeEventListener('beforeunload',beforeUnload));
    const contextChanged=()=>{stopped=true;if(dialog.isConnected){say('项目或账号已切换，后续联系人已停止发送。');lock();}};
    window.addEventListener('tophoo-project-changed',contextChanged);document.addEventListener('tophoo-auth-changed',contextChanged);promise.then(()=>{window.removeEventListener('tophoo-project-changed',contextChanged);document.removeEventListener('tophoo-auth-changed',contextChanged);});
    dialog.addEventListener('change',e=>{if(e.target.matches('[data-mail-recipient-all]'))dialog.querySelectorAll('[data-mail-contact]').forEach(node=>node.checked=e.target.checked);lock();});
    find('[data-mail-recipient]').addEventListener('input',lock);
    function renderFiles(){find('[data-mail-file-list]').hidden=!attachments.length;find('[data-mail-file-count]').textContent=attachments.length?`${attachments.length} 个`:'';find('[data-mail-file-list]').innerHTML=attachments.map((file,i)=>`<li><span>${esc(file.name)}</span><small>${file.size>=1024*1024?(file.size/1024/1024).toFixed(1)+' MB':Math.max(1,Math.ceil(file.size/1024))+' KB'}</small><button type="button" data-mail-remove-file="${i}" aria-label="移除附件 ${esc(file.name)}">×</button></li>`).join('');}
    find('[data-mail-add-files]').onclick=()=>{if(!sending&&!started)find('[data-mail-files]').click();};
    find('[data-mail-files]').onchange=()=>{if(sending||started)return;const chosen=[...find('[data-mail-files]').files],next=[...attachments];for(const file of chosen)if(!next.some(old=>old.name===file.name&&old.size===file.size&&old.lastModified===file.lastModified))next.push(file);find('[data-mail-files]').value='';if(next.length>5||next.reduce((size,file)=>size+file.size,0)>10*1024*1024){say('附件最多5个、合计10 MB，超限文件尚未添加。');return;}attachments=next;renderFiles();};
    find('[data-mail-file-list]').onclick=e=>{const button=e.target.closest('[data-mail-remove-file]');if(!button||sending||started)return;attachments.splice(Number(button.dataset.mailRemoveFile),1);renderFiles();};
    find('[data-mail-add-signature]').onclick=()=>{if(started)return;if(config?.signature&&!body.trimEnd().endsWith(config.signature.trim())){const isHtml=/<[a-z][\s\S]*>/i.test(config.signature);const html=isHtml?window.TophooRichMail.clean(config.signature):'<p>'+window.TophooRichMail.escape(config.signature).replace(/\n/g,'<br>')+'</p>';bodyHtml=(bodyHtml||'<p>'+window.TophooRichMail.escape(body).replace(/\n/g,'<br>')+'</p>')+'<br>'+html;body=body.trimEnd()+'\n\n'+(isHtml?window.TophooRichMail.plain(html):config.signature);renderBody();}signatureAdded=true;find('[data-mail-add-signature]').hidden=true;};
    find('[data-mail-send-query]').onclick=async()=>{
      if(sending||!sameContext())return;sending=true;lock();
      try{for(const target of targets.filter(t=>['unknown','pending'].includes(t.status))){if(!sameContext()||stopped)break;try{const row=await api('/deliveries/by-request/'+target.key);target.row=row;target.status=row.status;target.message=row.message;}catch(e){if(e.status===404){target.status='retry_same';target.message='暂无记录，可点击继续发送；将沿用原发送编号核对，避免重复。';}else target.message=e.message;}}if(sameContext()){renderResults();say(summary());outreachUpdated();}}
      finally{sending=false;if(dialog.isConnected)lock();}
    };
    find('[data-mail-send-confirm]').onclick=async()=>{
      if(sending||!config||stopped)return;if(!sameContext())return say('当前项目已切换，请重新打开开发信。');
      if(!find('[data-mail-recipient]').validity.valid)find('.mail-recipient-extra-box').open=true;if(!find('[data-mail-recipient]').reportValidity())return;
      const files=attachments;if(files.length>5||files.reduce((n,f)=>n+f.size,0)>10*1024*1024)return say('附件最多 5 个，总大小不能超过 10 MB。');
      if(!started){const chosen=selectedPeople();if(!chosen.length)return say('请至少选择一位收件人。');if(chosen.length>100)return say('每次最多选择100个不同邮箱。');if(chosen.some(p=>!validEmail(p.email)))return say('请核对收件邮箱格式。');targets=chosen.map(p=>({...p,status:'ready',key:requestKey(),message:''}));started=true;}
      const pending=targets.filter(t=>['ready','failed','retry_same'].includes(t.status));if(!pending.length)return;
      sending=true;lock();renderResults();
      try{for(const target of pending){
        if(!sameContext()||stopped)break;
        if(target.status==='failed')target.key=requestKey();
        target.status='sending';target.message='';renderResults();say(`正在发送 ${targets.indexOf(target)+1} / ${targets.length}：${target.email}`);
        const payload=new FormData();for(const [k,v] of Object.entries({request_key:target.key,recipient:target.email,subject:context.subject,content:body,content_html:bodyHtml,content_translation:context.content_translation||'',contact_name:target.name}))payload.set(k,v);if(config.account_id!=null)payload.set('account_id',String(config.account_id));files.forEach(file=>payload.append('attachments',file));hasAttempted=true;
        try{const row=await api(`/projects/${context.project}/leads/${context.id}/send`,{method:'POST',body:payload});target.row=row;target.status=['accepted','failed','pending','unknown'].includes(row.status)?row.status:'unknown';target.message=row.message||'';if(['pending','unknown'].includes(target.status))break;}
        catch(e){if(e.status>=400&&e.status<500&&e.status!==409){target.status='retry_same';target.message=e.message;}else{target.status='unknown';target.message='未能确认发送结果，请先查询发送记录。';}break;}
        finally{if(dialog.isConnected)renderResults();}
      }
      if(sameContext()){say(summary());outreachUpdated();if(targets.every(t=>t.status==='accepted'))dialog.querySelectorAll('[data-mail-send-close]').forEach(node=>{if(!node.hasAttribute('aria-label'))node.textContent='完成';});else dialog.querySelectorAll('[data-mail-send-close]').forEach(node=>{if(!node.hasAttribute('aria-label'))node.textContent='关闭';});}
      }finally{sending=false;if(dialog.isConnected)lock();}
    };
    lock();refreshOutreach();
    async function selectSender(id){
      if(started||sending)return;const run=++senderVersion;config=null;lock();say('正在读取发件邮箱…');
      try{const next=await api(id==null?'/configuration':'/configuration?account_id='+id);if(!sameContext()||run!==senderVersion)return;
        if(!next.configured){find('[data-mail-from]').textContent='尚未配置发件邮箱';say('请先在“系统 → 邮箱配置”中添加邮箱，再回来发送。');return;}
        config=next;if(signatureAdded){body=context.content;bodyHtml=context.content_html||'';signatureAdded=false;renderBody();}
        find('[data-mail-from]').textContent=`${config.sender_name||''} <${config.email}>`;
        find('[data-mail-add-signature]').hidden=!config.signature||body.trimEnd().endsWith(config.signature.trim());say('请确认收件人、发件邮箱和邮件内容。');
      }catch(e){if(sameContext()&&run===senderVersion)say(e.message);}finally{if(sameContext()&&run===senderVersion)lock();}
    }
    find('[data-mail-sender-select]').onchange=()=>selectSender(Number(find('[data-mail-sender-select]').value));
    try{const list=await api('/accounts');if(sameContext()){
      const items=list.items||[];senderAccountsReady=items.length>0;find('[data-mail-sender-select]').innerHTML=items.length?items.map(a=>`<option value="${a.account_id}" ${a.account_id===list.default_account_id?'selected':''}>${esc(a.email)}${a.is_default?' · 默认':''}</option>`).join(''):'<option value="">尚未配置邮箱</option>';
      await selectSender(list.default_account_id);}}
    catch(e){if(sameContext())say(e.message);}
    return promise;
  }
  window.TophooMail={compose};
})();
