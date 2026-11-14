(() => {
  const page=document.querySelector('[data-contact-records-page]');
  if(!page)return;
  const form=page.querySelector('[data-record-form]');
  const field=page.querySelector('[data-record-content]');
  const save=page.querySelector('[data-record-save]');
  const status=page.querySelector('[data-record-status]');
  const title=page.querySelector('[data-record-contact-name]');
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const legacyTranslation=x=>x.content_translation?`<details class="record-translation"><summary>查看历史翻译（保留）</summary><p>${esc(x.content_translation)}</p></details>`:'';
  const chineseTranslation=x=>x.content_translation?`<section class="record-translation"><strong>中文翻译</strong><p>${esc(x.content_translation)}</p></section>`:'';
  const outreachSource=x=>{const source=x.outreach_source;if(!source)return '';const body=source.content_html&&window.TophooRichMail?window.TophooRichMail.clean(source.content_html):esc(source.content||'').replace(/\n/g,'<br>');return `<details class="record-outreach-source"><summary>查看原开发信（含图文）</summary><p>${esc([source.recipient_name,source.recipient_email].filter(Boolean).join(' · '))}</p><strong>${esc(source.subject||'')}</strong><div class="mail-rich-preview">${body}</div></details>`;};
  const card=(x,{editable=true,kind='contacts'}={})=>`<article class="record-card"><header><div>${x.subject?`<h3>${esc(x.subject)}</h3>`:''}<small class="record-meta"><span>联系人：${esc(x.contact_name||'未填写')}</span><time datetime="${esc(x.occurred_at||'')}">${esc((x.occurred_at||'').slice(0,10)||'未填写日期')}</time><span>${esc(x.channel||'未填写方式')}</span></small></div>${editable?`<div class="record-card-actions"><button type="button" data-edit="${x.id}">编辑</button><button type="button" class="danger" data-delete="${x.id}">删除</button></div>`:''}</header>${kind==='contacts'&&x.content_translation?'<div class="record-reading-grid"><section class="record-original"><strong class="record-section-label">原文内容</strong>':''}${x.content_html?`<div class="mail-rich-preview record-rich-content">${window.TophooRichMail.clean(x.content_html)}</div>`:kind==='leads'&&(x.content||'').length>600?`<details class="record-long-content"><summary>${esc(x.content.slice(0,180))}… <span>展开完整内容</span></summary><p>${esc(x.content)}</p></details>`:`<p>${esc(x.content)}</p>`}${kind==='contacts'&&x.content_translation?`</section>${chineseTranslation(x)}</div>`:legacyTranslation(x)}${outreachSource(x)}</article>`;
  window.TophooContactRecords={card};
  let active=null, busy=false;
  const current=op=>active===op&&op.project===pid()&&page.open;
  const resize=()=>{
    field.style.height='auto';
    field.style.height=`${field.scrollHeight+field.offsetHeight-field.clientHeight}px`;
  };
  field.addEventListener('input',resize);
  let width=0;
  new ResizeObserver(([entry])=>{
    if(entry.contentRect.width===width)return;
    width=entry.contentRect.width;
    resize();
  }).observe(page);
  function message(value,error=false){
    status.textContent=value;
    status.classList.toggle('error',error);
    status.hidden=!value;
  }
  async function request(url,method='GET',body){
    const response=await fetch(url,{method,headers:{...window.tophooAuth?.headers?.(),
      ...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'操作失败，请重试。');
    return data;
  }
  function close(){
    if(busy)return;
    if(active?.loaded&&field.value!==active.baseline&&!confirm('跟进尚未保存，是否放弃修改？'))return;
    dismiss();
  }
  function dismiss(){
    const op=active;
    active=null;
    page.close();
    if(op?.changed)document.dispatchEvent(new CustomEvent('tophoo-followup-notes-changed',{detail:{projectId:op.project}}));
  }
  page.querySelector('[data-record-back]').onclick=close;
  page.addEventListener('cancel',e=>{e.preventDefault();close();});
  function invalidate(){active=null;page.close();}
  window.addEventListener('tophoo-project-changed',invalidate);
  document.addEventListener('tophoo-customer-workflow-view',invalidate);
  document.addEventListener('tophoo-auth-changed',invalidate);
  document.addEventListener('tophoo-open-contact-records',async ({detail})=>{
    if(busy||page.open)return;
    const project=pid(),id=detail.contactId,lead=detail.view==='leads';
    const prefix=lead?`/api/customer-workflow/projects/${project}/leads/${id}`:`/api/contacts/projects/${project}/${id}`;
    const editable=!window.tophooProjectAccess||window.tophooProjectAccess.canEdit(lead?'leads':'customer_list');
    const op=active={project,prefix,editable,prefill:editable?detail.prefill:null,loaded:false};
    title.textContent=detail.company||'';
    field.value='';
    field.readOnly=true;
    save.hidden=!editable;
    save.disabled=true;
    message('正在读取跟进…');
    page.showModal();
    try{
      const note=await request(prefix+'/followup-note');
      if(!current(op))return;
      op.loaded=true;
      op.baseline=note.content;
      op.revision=note.revision;
      const draft=op.prefill;
      field.value=[note.content,draft&&[draft.subject,draft.content,draft.content_translation].filter(Boolean).join('\n')].filter(Boolean).join('\n\n');
      field.readOnly=!editable;
      save.disabled=!editable;
      message(draft?.outreach_conversion?.clear_draft?'保存后将清除当前开发信草稿。':'');
      resize();
      if(editable)field.focus();
    }catch(e){if(current(op))message(e.message,true);}
  });
  page.addEventListener('keydown',e=>{
    if(e.isComposing||!e.ctrlKey||e.altKey||e.shiftKey||e.key.toLowerCase()!=='s')return;
    e.preventDefault();
    e.stopPropagation();
    if(!e.repeat&&!save.disabled&&!save.hidden)form.requestSubmit();
  });
  form.onsubmit=async e=>{
    e.preventDefault();
    const op=active;
    if(busy||!op?.loaded||!op.editable)return;
    const content=field.value,draft=op.prefill;
    if(content===op.baseline&&!draft){dismiss();return;}
    busy=save.disabled=field.readOnly=true;
    try{
      const note={content,revision:op.revision};
      if(draft?.outreach_conversion){
        await request(op.prefix+'/outreach-draft/to-interaction','POST',{
          ...draft.outreach_conversion,contact_name:draft.contact_name,subject:draft.subject,
          channel:'邮件',content:draft.content,content_translation:draft.content_translation,note
        });
      }else{
        await request(op.prefix+'/followup-note','PUT',note);
      }
      if(current(op)){op.changed=true;dismiss();}
    }catch(e){if(current(op))message(e.message,true);}
    finally{
      busy=false;
      if(current(op))save.disabled=field.readOnly=false;
    }
  };
})();
