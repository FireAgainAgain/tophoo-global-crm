/* Independent lead contact management; company and workflow fields stay untouched. */
(() => {
  const dialog=document.createElement('dialog');dialog.className='lead-contacts-dialog';dialog.dataset.permissionModule='leads';dialog.setAttribute('aria-labelledby','lead-contacts-title');document.body.append(dialog);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const $=s=>dialog.querySelector(s),auth=()=>window.tophooAuth?.headers?.()||{};
  const editable=()=>!window.tophooProjectAccess||window.tophooProjectAccess.canEdit('leads');
  let active=null;
  const current=s=>active===s&&s.project===Number(localStorage.getItem('tophoo-global-selected-project'))&&s.identity===JSON.stringify(auth());
  const values=()=>({...Object.fromEntries(new FormData($('form'))),is_primary:$('[name=is_primary]').checked});
  const dirty=()=>!!active&&active.editing!==null&&active.baseline!==JSON.stringify(values());
  function message(text='',error=false){$('[data-lc-message]').textContent=text;$('[data-lc-message]').classList.toggle('is-error',error);}
  function outreachBadge(s,p){const stat=s.stats?.[(p.email||'').trim().toLowerCase()],count=stat?.sent_count||0;return `<div class="lead-contact-outreach"><button type="button" class="${count?'is-sent':''}" data-contact-outreach data-outreach-project="${s.project}" data-outreach-lead="${s.id}" data-outreach-recipient="${esc(p.email||'')}" ${!p.email?'disabled':''} title="按当前邮箱统计服务器已接受的开发信">${count?`已发开发信 · ${count} 封`:'未发开发信'}</button>${stat?.last_sent_at?`<small>最近 ${esc(stat.last_sent_at.slice(5,16).replace('T',' '))}</small>`:''}</div>`;}
  function close(force=false){if(!force&&(active?.busy||(dirty()&&!confirm('联系人尚未保存，确定放弃修改吗？'))))return;const trigger=active?.trigger,id=active?.id;active=null;dialog.close();dialog.innerHTML='';const focus=trigger?.isConnected?trigger:document.querySelector(`[data-detail-contacts="${id}"],[data-lead-contacts-open="${id}"]`);focus?.focus();}
  async function request(s,method='GET',data){const r=await fetch(`/api/customer-workflow/projects/${s.project}/leads/${s.id}/contacts`,{method,headers:{...auth(),...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:Array.isArray(d.detail)?d.detail.map(x=>x.msg).join('；'):'联系人读取或保存失败，请重试。');return d;}
  function render(){const s=active;if(!s)return;const term=$('[data-lc-search]').value.trim().toLowerCase();
    $('[data-lc-count]').textContent=`${s.people.length} 位联系人`;
    $('[data-lc-list]').innerHTML=s.people.map((p,i)=>({p,i})).filter(({p})=>!term||Object.values(p).some(v=>String(v).toLowerCase().includes(term))).map(({p,i})=>`<article class="lead-contact-card"><header><div><strong>${esc(p.contact_name)||'未具名联系人'}</strong>${p.is_primary?'<span>主联系人</span>':''}</div><div class="lead-contact-actions">${editable()?`<button type="button" data-lc-edit="${i}">修改</button><button type="button" class="is-danger" data-lc-delete="${i}">删除</button>`:''}</div></header>${outreachBadge(s,p)}<dl>${[['邮箱','email'],['电话','phone'],['WhatsApp','whatsapp'],['LinkedIn','linkedin'],['Facebook','facebook'],['Instagram','instagram'],['YouTube','youtube'],['备注','notes']].filter(([,key])=>p[key]).map(([label,key])=>`<div><dt>${label}</dt><dd>${esc(p[key])}</dd></div>`).join('')||'<p>暂无联系方式</p>'}</dl></article>`).join('')||`<div class="lead-contact-empty">${term?'没有匹配的联系人':'暂无联系人，可新增或从官网查找。'}</div>`;
    $('[data-lc-add]').disabled=s.busy||!s.loaded||!editable();$('[data-lc-find]').disabled=s.busy||!s.loaded||!editable();
    dialog.querySelectorAll('[data-lc-edit],[data-lc-delete]').forEach(b=>b.disabled=s.busy);$('[data-lc-save]').disabled=s.busy||!editable();
  }
  async function load(s){s.loaded=false;s.busy=true;render();message('正在读取联系人…');try{const d=await request(s);if(!current(s))return;s.people=d.contacts;s.stats=d.outreach_stats||{};s.version=d.version;s.loaded=true;message();}catch(e){if(current(s))message(e.message,true);}finally{if(current(s)){s.busy=false;render();$('[data-lc-retry]').hidden=s.loaded;}}}
  function edit(index){const s=active;if(!s?.loaded||s.busy||!editable())return;const p=index<0?{}:s.people[index];s.editing=index;
    $('form').reset();for(const key of ['contact_name','email','phone','whatsapp','linkedin','facebook','instagram','youtube','notes'])$(`[name=${key}]`).value=p[key]||'';
    $('[name=is_primary]').checked=!!p.is_primary||!s.people.length;$('[name=is_primary]').disabled=!!p.is_primary;
    $('[data-lc-edit-title]').textContent=index<0?'新增联系人':'修改联系人';$('[data-lc-editor]').hidden=false;$('[data-lc-overview]').hidden=true;s.baseline=JSON.stringify(values());message();$('[name=contact_name]').focus();
  }
  function back(){if(active.busy||(dirty()&&!confirm('联系人尚未保存，确定放弃修改吗？')))return;active.editing=null;$('[data-lc-editor]').hidden=true;$('[data-lc-overview]').hidden=false;message();render();}
  async function savePeople(s,people){s.busy=true;render();$('form').querySelectorAll('input,textarea,button').forEach(x=>x.disabled=true);message('正在保存…');
    try{const d=await request(s,'PUT',{contacts:people,version:s.version});if(!current(s))return;s.people=d.contacts;s.stats=d.outreach_stats||{};s.version=d.version;s.editing=null;s.baseline=null;$('[data-lc-editor]').hidden=true;$('[data-lc-overview]').hidden=false;message('联系人已保存。');document.dispatchEvent(new CustomEvent('tophoo-lead-contacts-updated',{detail:{project:s.project,id:s.id,contacts:d.contacts}}));}
    catch(e){if(current(s))message(e.message,true);}finally{if(current(s)){s.busy=false;$('form').querySelectorAll('input,textarea,button').forEach(x=>x.disabled=false);if(s.editing>=0)$('[name=is_primary]').disabled=!!s.people[s.editing]?.is_primary;render();}}
  }
  async function open(c){if(active?.busy)return;if(dialog.open){close();if(active)return;}const s={...c,identity:JSON.stringify(auth()),people:[],loaded:false,busy:false,editing:null,baseline:null,version:''};active=s;
    dialog.innerHTML=`<header class="lead-contacts-heading"><div><small>线索联系人</small><h2 id="lead-contacts-title">${esc(c.item.company_name)}</h2><p data-lc-count>正在读取…</p></div><button type="button" data-lc-close aria-label="关闭联系人">×</button></header><p class="lead-contacts-message" data-lc-message role="status"></p><button type="button" data-lc-retry hidden>重新读取</button><section data-lc-overview><div class="lead-contacts-tools"><input type="search" data-lc-search placeholder="搜索姓名、邮箱或电话" aria-label="搜索联系人"><button type="button" data-lc-find data-scan-open>查找联系人</button><button type="button" data-lc-add>＋ 添加联系人</button></div><div class="lead-contacts-list" data-lc-list></div></section><section data-lc-editor hidden><form><h3 data-lc-edit-title></h3><div class="lead-contact-fields">${[['姓名','contact_name',160],['邮箱','email',260],['电话','phone',80],['WhatsApp','whatsapp',80],['LinkedIn','linkedin',500],['Facebook','facebook',500],['Instagram','instagram',500],['YouTube','youtube',500]].map(([label,key,max])=>`<label>${label}<input name="${key}" type="${key==='email'?'email':'text'}" maxlength="${max}"></label>`).join('')}<label class="wide">备注<textarea name="notes" maxlength="5000" rows="4"></textarea></label></div><label class="lead-contact-primary"><input type="checkbox" name="is_primary"> 设为主联系人</label><footer><button type="button" data-lc-back>取消</button><button type="submit" data-lc-save>保存联系人</button></footer></form></section>`;
    dialog.showModal();await load(s);
  }
  dialog.addEventListener('input',e=>{if(e.target.matches('[data-lc-search]'))render();});
  dialog.addEventListener('click',async e=>{const b=e.target.closest('button'),s=active;if(!b||!s||b.disabled)return;
    if(b.hasAttribute('data-lc-close'))return close();if(b.hasAttribute('data-lc-retry'))return load(s);if(b.hasAttribute('data-lc-back'))return back();if(b.hasAttribute('data-lc-add'))return edit(-1);if(b.hasAttribute('data-lc-edit'))return edit(Number(b.dataset.lcEdit));
    if(b.hasAttribute('data-lc-find'))return document.dispatchEvent(new CustomEvent('tophoo-lead-contacts-find',{detail:{...s,view:'leads',trigger:b}}));
    if(b.hasAttribute('data-lc-delete')&&editable()&&!s.busy){const index=Number(b.dataset.lcDelete),p=s.people[index];if(confirm(`确定删除联系人“${p.contact_name||p.email||'未具名联系人'}”吗？历史联系记录会保留。`))await savePeople(s,s.people.filter((_,i)=>i!==index));}
  });
  dialog.addEventListener('submit',e=>{e.preventDefault();const s=active;if(!s||s.busy||!editable())return;const p=values();if(!Object.entries(p).some(([key,v])=>key!=='is_primary'&&String(v).trim()))return message('请至少填写一项联系人资料。',true);const people=s.people.map(x=>({...x}));if(p.is_primary)people.forEach(x=>x.is_primary=false);if(s.editing<0)people.push(p);else people[s.editing]=p;savePeople(s,people);});
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  document.addEventListener('tophoo-lead-contacts-open',e=>open(e.detail));
  document.addEventListener('tophoo-lead-contacts-updated',e=>{const s=active;if(s&&!s.busy&&s.editing===null&&e.detail.project===s.project&&e.detail.id===s.id)load(s);});
  document.addEventListener('tophoo-lead-outreach-updated',e=>{const s=active;if(s&&!s.busy&&s.editing===null&&e.detail.project===s.project&&e.detail.id===s.id)load(s);});
  window.addEventListener('tophoo-project-availability',()=>{if(active)queueMicrotask(render);});
  window.addEventListener('tophoo-project-changed',()=>close(true));document.addEventListener('tophoo-auth-changed',()=>close(true));document.addEventListener('tophoo-customer-workflow-view',()=>close(true));
  window.addEventListener('beforeunload',e=>{if(active&&(active.busy||dirty())){e.preventDefault();e.returnValue='';}});
})();
