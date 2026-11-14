(() => {
  const workflow=document.querySelector('[data-customer-workflow]');if(!workflow)return;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const project=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const toast=(text,error=false)=>{const el=document.querySelector('[data-workflow-toast]');el.textContent=text;el.hidden=false;el.className='workflow-toast '+(error?'error':'success');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,4000);};
  const queue=document.createElement('dialog');queue.dataset.followupQueue='';queue.className='followup-dialog followup-queue followup-simple';
  queue.innerHTML='<header><div><h2>我的跟进</h2><p>需要联系的客户，处理完即可移除。</p></div><div class="followup-section-actions"><button type="button" class="followup-primary" data-fu-queue-add hidden>＋ 添加跟进</button><button type="button" data-fu-queue-close aria-label="关闭跟进列表">×</button></div></header><div data-fu-queue-rows></div><footer><span data-fu-total></span><div><button type="button" data-fu-prev>上一页</button><button type="button" data-fu-next>下一页</button></div></footer>';
  const editor=document.createElement('dialog');editor.dataset.followupDialog='';editor.className='followup-dialog followup-editor followup-simple';
  editor.innerHTML='<form><header><div><h2 data-fu-title>添加跟进</h2><p data-fu-company></p></div><button type="button" data-fu-close aria-label="关闭跟进编辑">×</button></header><label>跟进内容<textarea name="title" maxlength="260" required placeholder="例如：联系客户确认工况参数，或询问报价反馈"></textarea></label><label>跟进日期<input type="date" name="due_date" required aria-label="跟进日期"></label><p data-fu-error role="alert" hidden></p><footer><button type="button" data-fu-close>取消</button><button type="submit" class="followup-primary">保存</button></footer></form>';
  document.body.append(queue,editor);
  const form=editor.querySelector('form'),field=selector=>editor.querySelector(selector);
  let scope='mine',bucket='pending',page=1,queueTotal=0,queueCustomer=null,queueItems=[],detailItems=[],queueVersion=0,detailVersion=0,formVersion=0,operation=null,baseline='',busy=false;
  const day=value=>new Date(value||Date.now()).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
  const draft=()=>JSON.stringify({title:form.elements.title.value,due_date:form.elements.due_date.value});
  const dirty=()=>editor.open&&draft()!==baseline;
  async function api(pid,path='',options={}){const r=await fetch(`/api/followups/projects/${pid}${path}`,{...options,headers:{...(window.tophooAuth?.headers?.()||{}),'Content-Type':'application/json'}});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(Array.isArray(d.detail)?d.detail.map(x=>x.msg.replace(/^Value error,\s*/,'' )).join('；'):d.detail||'操作失败，请重试。');return d;}
  function closeEditor(force=false){if(busy&&!force)return false;if(!force&&dirty()&&!confirm('跟进内容尚未保存，确定放弃吗？'))return false;++formVersion;editor.close();operation=null;baseline='';return true;}
  function planRow(item,canWrite,showCustomer=false){
    const due=item.due_date||(item.due_at?day(item.due_at):day()),today=day(),timing=due>today?'future':due<today?'overdue':'today',label={future:'未到期',today:'今日跟进',overdue:'已逾期'}[timing];
    return `<article class="followup-row followup-todo is-${timing}"><span class="followup-todo-dot" aria-hidden="true"></span><div class="followup-row-main">${showCustomer?`<button class="followup-customer-link" type="button" data-fu-customer="${item.customer_id}">${esc(item.company_name)}</button>`:''}<div class="followup-row-heading"><strong>${esc(item.title)}</strong></div><time class="followup-due" datetime="${esc(due)}">${label} · ${esc(due)}</time>${item.notes?`<p class="followup-note">${esc(item.notes)}</p>`:''}</div>${canWrite?`<div class="followup-row-actions" role="group" aria-label="跟进操作"><button type="button" class="followup-done" data-fu-complete="${item.id}" title="完成后移除此条跟进">✓ 完成</button><button type="button" data-fu-edit="${item.id}">编辑</button><button type="button" data-fu-delete="${item.id}">删除</button></div>`:''}</article>`;
  }
  async function refreshQueue(){
    const version=++queueVersion,pid=project(),customerId=queueCustomer;
    queueItems=[];queue.querySelector('[data-fu-queue-add]').hidden=true;queue.querySelector('[data-fu-queue-rows]').innerHTML='<p class="followup-empty">正在读取…</p>';
    try{
      const [d,context]=await Promise.all([api(pid,`?bucket=${bucket}&scope=${scope}&page=${page}${customerId?`&customer_id=${customerId}`:''}`),customerId?api(pid,`/customers/${customerId}/context`):Promise.resolve(null)]);
      if(version!==queueVersion||pid!==project()||!queue.open)return;
      queueItems=d.items;queueTotal=d.total;queue.querySelector('h2').textContent=customerId?'客户跟进':bucket==='today'?'今日跟进':bucket==='overdue'?'逾期跟进':scope==='all'?'项目跟进':'我的跟进';
      queue.querySelector('header p').textContent=context?.company_name||(bucket==='today'?'北京时间今日计划':bucket==='overdue'?'已超过计划时间且未完成':'需要联系的客户，处理完即可移除。');
      queue.querySelector('[data-fu-queue-add]').hidden=!context?.can_write;
      queue.querySelector('[data-fu-queue-rows]').innerHTML=d.items.length?d.items.map(item=>planRow(item,d.can_write,!customerId)).join(''):`<div class="followup-empty-state"><span aria-hidden="true">✓</span><div><strong>暂无待跟进事项</strong><p>${customerId?'需要联系时，添加一条跟进即可。':'可在客户列表中添加跟进。'}</p></div></div>`;
      queue.querySelector('[data-fu-total]').textContent=`${d.total} 条待跟进`;
      queue.querySelector('[data-fu-prev]').hidden=queue.querySelector('[data-fu-next]').hidden=d.total<=20;
      queue.querySelector('[data-fu-prev]').disabled=page===1;queue.querySelector('[data-fu-next]').disabled=page*20>=d.total;
    }catch(error){if(version===queueVersion&&pid===project()&&queue.open){queue.querySelector('[data-fu-total]').textContent='';queue.querySelector('[data-fu-queue-rows]').innerHTML=`<p class="followup-empty">${esc(error.message)} <button type="button" data-fu-retry>重试</button></p>`;}}
  }
  async function loadCustomer(customerId,pid=project()){
    const version=++detailVersion,section=document.querySelector(`[data-followup-customer="${customerId}"]`);if(!section)return;
    try{const d=await api(pid,`?customer_id=${customerId}&scope=mine&bucket=pending&page_size=100`);if(version!==detailVersion||pid!==project()||!section.isConnected)return;detailItems=d.items;section.innerHTML=`<header><h3>跟进 <span class="followup-count">${d.total}</span></h3>${d.can_write?`<button type="button" data-fu-add="${customerId}">＋ 添加跟进</button>`:''}</header>${d.items.map(item=>planRow(item,d.can_write)).join('')||'<p class="followup-empty">暂无待跟进事项</p>'}`;}catch(error){if(version===detailVersion&&pid===project()&&section.isConnected)section.innerHTML=`<p class="followup-empty">${esc(error.message)}</p>`;}
  }
  async function openEditor(customerId,item=null){
    if(busy||editor.open)return;const version=++formVersion,pid=project();
    try{const context=await api(pid,`/customers/${customerId}/context`);if(version!==formVersion||pid!==project())return;if(!context.can_write)return toast('当前项目只有查看权限。',true);operation={customerId,item,pid};field('[data-fu-company]').textContent=context.company_name;field('[data-fu-title]').textContent=item?'编辑跟进':'添加跟进';field('[data-fu-error]').hidden=true;form.elements.title.value=item?.title||'';form.elements.due_date.value=item?.due_date||day(item?.due_at);baseline=draft();editor.showModal();form.elements.title.focus();}catch(error){if(version===formVersion)toast(error.message,true);}
  }
  function changed(pid){document.dispatchEvent(new CustomEvent('tophoo-followups-changed',{detail:{projectId:pid}}));if(queue.open)refreshQueue();}
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!operation)return;const op=operation,version=formVersion,title=form.elements.title.value.trim();if(!title){form.elements.title.setCustomValidity('请填写跟进内容。');form.elements.title.reportValidity();return;}
    busy=true;form.querySelectorAll('button,textarea,input').forEach(el=>el.disabled=true);field('[data-fu-error]').hidden=true;
    try{await api(op.pid,op.item?`/${op.item.id}`:`/customers/${op.customerId}`,{method:op.item?'PUT':'POST',body:JSON.stringify({title,due_date:form.elements.due_date.value})});if(version!==formVersion||op.pid!==project())return;closeEditor(true);toast('跟进已保存。');changed(op.pid);}catch(error){if(version===formVersion&&op.pid===project()){field('[data-fu-error]').textContent=error.message;field('[data-fu-error]').hidden=false;}}finally{busy=false;form.querySelectorAll('button,textarea,input').forEach(el=>el.disabled=false);}
  };
  form.elements.title.oninput=()=>form.elements.title.setCustomValidity('');
  async function remove(item,completed=false){
    if(busy||(!completed&&!confirm(`删除这条跟进：${item.title}？`)))return;const pid=project();busy=true;queue.querySelectorAll('button').forEach(el=>el.disabled=true);
    try{await api(pid,`/${item.id}${completed?'?completed=true':''}`,{method:'DELETE'});if(pid!==project())return;toast(completed?'已完成，跟进已移除。':'跟进已删除。');if(queueItems.length===1&&page>1)page--;changed(pid);}catch(error){if(pid===project())toast(error.message,true);}finally{busy=false;queue.querySelectorAll('button').forEach(el=>el.disabled=false);queue.querySelector('[data-fu-prev]').disabled=page===1;queue.querySelector('[data-fu-next]').disabled=page*20>=queueTotal;}
  }
  function openQueue(customerId=null,wantedScope='mine',wantedBucket='pending'){
    queueCustomer=customerId;scope=wantedScope;bucket=['pending','today','overdue'].includes(wantedBucket)?wantedBucket:'pending';page=1;queueItems=[];queue.querySelector('h2').textContent=customerId?'客户跟进':'我的跟进';queue.querySelector('header p').textContent='正在读取…';queue.querySelector('[data-fu-queue-add]').hidden=true;if(!queue.open)queue.showModal();refreshQueue();
  }
  document.addEventListener('click',event=>{
    const b=event.target.closest('button');if(!b||busy)return;
    if(b.hasAttribute('data-followup-mine'))openQueue();
    else if(b.hasAttribute('data-followup-open')||b.hasAttribute('data-fu-history'))openQueue(Number(b.dataset.followupOpen||b.dataset.fuHistory),b.dataset.followupScope==='all'?'all':'mine');
    else if(b.hasAttribute('data-fu-queue-add')&&queueCustomer)openEditor(queueCustomer);
    else if(b.hasAttribute('data-fu-add'))openEditor(Number(b.dataset.fuAdd));
    else if(b.hasAttribute('data-fu-prev')||b.hasAttribute('data-fu-next')){page+=b.hasAttribute('data-fu-prev')?-1:1;refreshQueue();}
    else if(b.hasAttribute('data-fu-retry'))refreshQueue();
    else if(b.hasAttribute('data-fu-queue-close')){++queueVersion;++formVersion;queue.close();}
    else if(b.hasAttribute('data-fu-close'))closeEditor();
    else if(b.dataset.fuCustomer){++queueVersion;queue.close();document.dispatchEvent(new CustomEvent('tophoo-followup-open-customer',{detail:{customerId:Number(b.dataset.fuCustomer),projectId:project()}}));}
    else{const id=Number(b.dataset.fuComplete||b.dataset.fuEdit||b.dataset.fuDelete),item=[...queueItems,...detailItems].find(x=>x.id===id);if(!item)return;if(b.dataset.fuComplete)remove(item,true);else if(b.dataset.fuDelete)remove(item);else if(b.dataset.fuEdit)openEditor(item.customer_id,item);}
  });
  editor.addEventListener('cancel',event=>{event.preventDefault();closeEditor();});
  queue.addEventListener('close',()=>{++queueVersion;queueItems=[];queue.querySelector('[data-fu-queue-rows]').innerHTML='';});
  queue.addEventListener('cancel',event=>{if(busy){event.preventDefault();return;}++queueVersion;++formVersion;});
  document.addEventListener('tophoo-followup-queue-open',event=>{if(!busy)openQueue(null,event.detail?.scope==='all'?'all':'mine',event.detail?.bucket);});
  document.addEventListener('tophoo-communication-followup',event=>{if(event.detail.projectId===project())openEditor(event.detail.customerId);});
  document.addEventListener('tophoo-followup-detail',event=>loadCustomer(event.detail.customerId,event.detail.projectId));
  function reset(){++queueVersion;++detailVersion;++formVersion;closeEditor(true);queue.close();queueItems=[];detailItems=[];}
  window.addEventListener('tophoo-project-changed',reset);document.addEventListener('tophoo-auth-changed',reset);
  window.addEventListener('beforeunload',event=>{if(dirty()||busy){event.preventDefault();event.returnValue='';}});
  document.addEventListener('click',event=>{if(!event.target.closest('.global-nav-item,.crm-primary-item,[data-project-id],#sidebar-current-project'))return;if(busy||(editor.open&&!closeEditor())){event.preventDefault();event.stopImmediatePropagation();}},true);
})();
