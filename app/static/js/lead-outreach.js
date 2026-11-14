(() => {
  let active=null,version=0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const defaults=data=>({recipient_name:data.recipient_name||'',recipient_email:data.recipient_email||'',subject:data.subject||'',content:data.content||'',content_html:data.content_html||'',content_translation:data.content_translation||''});
  const values=s=>({subject:s.editor.querySelector('[data-outreach-subject]').value,content_translation:s.editor.querySelector('[data-outreach-translation]').value,...s.rich.get()});
  const current=s=>active===s&&s.panel.isConnected&&s.project===Number(localStorage.getItem('tophoo-global-selected-project'));
  const editable=()=>!window.tophooProjectAccess||window.tophooProjectAccess.canEdit('leads');
  const dirty=s=>!!(s?.loaded&&current(s)&&s.editor.open&&s.baseline!==JSON.stringify(values(s)));
  function status(s,message,error=false){
    // Keep editor feedback from changing the drawer layout behind the modal.
    const root=s.editor.open?s.editor:s.panel;
    root.querySelectorAll('[data-outreach-status]').forEach(el=>{
      if(el.textContent!==message)el.textContent=message;
      el.title=message;el.classList.toggle('is-error',error);
    });
  }
  function fields(s,data){const d=defaults(data);s.editor.querySelector('[data-outreach-subject]').value=d.subject;s.rich.set(d.content_html,d.content);s.editor.querySelector('[data-outreach-translation]').value=d.content_translation;}
  function controls(s){
    s.panel.querySelector('[data-outreach-open]').disabled=!s.loaded;
    s.panel.querySelector('[data-outreach-copy]').disabled=!s.loaded||!s.saved.content.trim();
    s.panel.querySelector('[data-outreach-record]').disabled=!s.loaded||!s.saved.content.trim()||!editable();
    s.editor.querySelectorAll('input,textarea').forEach(el=>el.readOnly=!s.loaded||!editable()||s.busy);
    s.rich.lock(!s.loaded||!editable()||s.busy);
    s.editor.querySelector('[data-outreach-save]').disabled=!s.loaded||s.busy||!editable();
    s.editor.querySelector('[data-outreach-send]').disabled=!s.loaded||s.busy||!editable();
  }
  function preview(s){
    const has=!!(s.saved.subject||s.saved.content||s.saved.content_translation);
    s.panel.querySelector('[data-outreach-preview]').textContent=s.saved.content|| (has?'暂无正文':'尚未编写开发信');
    s.panel.querySelector('[data-outreach-title]').textContent=s.saved.subject|| (has?'开发信草稿':'');
    s.panel.querySelector('[data-outreach-date]').textContent=s.saved.updated_at?'更新于 '+s.saved.updated_at.slice(0,16).replace('T',' '):'';
    s.panel.querySelector('[data-outreach-open]').textContent=editable()?(has?'编辑开发信':'编写开发信'):'查看开发信';
    s.panel.querySelector('[data-outreach-record]').hidden=!has;
    s.panel.querySelector('[data-outreach-copy]').hidden=!has;
    controls(s);
  }
  async function request(s,method='GET',data){
    const r=await fetch(`/api/customer-workflow/projects/${s.project}/leads/${s.id}/outreach-draft`,{method,headers:{...(window.tophooAuth?.headers?.()||{}),...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});
    const result=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'开发信保存或读取失败，请重试。');return result;
  }
  async function save(s){
    if(!current(s)||s.busy||!s.loaded||!editable())return;
    s.busy=true;controls(s);status(s,'正在保存…');
    try{const data=await request(s,'PUT',values(s));if(!current(s))return;s.saved={...defaults(data),updated_at:data.updated_at};fields(s,s.saved);s.baseline=JSON.stringify(values(s));preview(s);status(s,'草稿已保存');return true;}
    catch(e){if(current(s))status(s,e.message,true);}
    finally{s.busy=false;if(current(s))controls(s);}
  }
  function resetEditor(s){
    fields(s,s.saved);s.baseline=null;s.rich.lock(true);
    s.editor.classList.remove('is-expanded');
    const maximize=s.editor.querySelector('[data-outreach-max]');
    maximize.textContent='放大';maximize.setAttribute('aria-pressed','false');maximize.setAttribute('aria-label','放大编写窗口');
    const translation=s.editor.querySelector('[data-outreach-toggle-translation]');
    translation.setAttribute('aria-expanded','false');translation.innerHTML='▸ 中文翻译 <span>选填</span>';
    s.editor.querySelector('.lead-outreach-translation label').hidden=true;
    s.editor.querySelector('.lead-outreach-writing').classList.remove('has-translation');
    s.editor.querySelectorAll('.lead-outreach-compose,[data-outreach-content],[data-outreach-translation]').forEach(node=>{node.scrollTop=0;if(!node.classList.contains('lead-outreach-compose'))node.style.removeProperty('height');});
    [s.panel,s.editor].forEach(root=>root.querySelectorAll('[data-outreach-status]').forEach(node=>{node.textContent='';node.title='';node.classList.remove('is-error');}));
  }
  function close(s){
    if(s.busy){status(s,'正在保存，请稍候。');return false;}
    if(dirty(s)&&!window.confirm('开发信尚未保存，确定放弃修改吗？'))return false;
    s.editor.close();resetEditor(s);if(s.standalone){const trigger=s.trigger;dispose();if(trigger?.isConnected)trigger.focus({preventScroll:true});}else s.panel.querySelector('[data-outreach-open]').focus({preventScroll:true});return true;
  }
  function dispose(){
    const previous=active;active=null;version++;
    if(previous){previous.rich.lock(true);previous.editor.close();previous.editor.remove();previous.panel.remove();}
  }
  async function copy(s,fromEditor){
    const d=fromEditor?values(s):s.saved,text=[d.subject,d.content].filter(Boolean).join('\n\n');
    try{await navigator.clipboard.writeText(text);status(s,'标题和正文已复制');}
    catch(e){status(s,'复制失败，请在编辑窗口中选中内容复制。',true);}
  }
  window.addEventListener('beforeunload',e=>{if(active?.editor.open&&(dirty(active)||active.busy)){e.preventDefault();e.returnValue='';}});
  document.addEventListener('tophoo-auth-changed',dispose);
  window.addEventListener('tophoo-project-changed',dispose);
  async function mount(context,standalone=false,trigger=null){
    if(active?.editor.open&&!close(active))return;
    dispose();const expected=version;
    if(context.view!=='leads')return;
    const person=(context.item.contacts||[]).find(p=>p.is_primary)||context.item.contacts?.[0]||context.item;
    const panel=document.createElement('section');panel.className='lead-outreach-card';panel.dataset.leadOutreach=String(context.id);
    panel.innerHTML=`<header><h3>开发信</h3><span data-outreach-date></span></header><div class="lead-outreach-summary"><strong data-outreach-title></strong><p data-outreach-preview>正在读取草稿…</p></div><footer><span role="status" data-outreach-status></span><button type="button" data-outreach-retry hidden>重新读取</button><button type="button" data-outreach-copy hidden>复制</button><button type="button" data-outreach-record hidden>转为跟进</button><button type="button" data-outreach-open disabled>编写开发信</button></footer>`;
    if(standalone){panel.hidden=true;document.body.append(panel);}else{const container=document.querySelector('[data-detail-content]'),records=container.querySelector('[data-detail-records]')?.closest('section');if(records)records.after(panel);else container.append(panel);}
    const editor=document.createElement('dialog');editor.className='lead-outreach-editor';editor.dataset.permissionModule='leads';editor.setAttribute('aria-labelledby','outreach-editor-heading');
    editor.innerHTML=`<header><div><h2 id="outreach-editor-heading">开发信草稿</h2><p>${esc(context.item.company_name||'未填写公司')}</p></div><button type="button" data-outreach-max aria-label="放大编写窗口" aria-pressed="false">放大</button><button type="button" data-outreach-close aria-label="关闭开发信">✕</button></header><div class="lead-outreach-compose"><label class="lead-outreach-subject">标题<input data-outreach-subject maxlength="260" placeholder="填写邮件标题"></label><div class="lead-outreach-writing"><label class="lead-outreach-body"><span>正文</span><div data-outreach-content spellcheck="false"></div></label><section class="lead-outreach-translation"><button type="button" data-outreach-toggle-translation aria-expanded="false" aria-controls="outreach-translation-field">▸ 中文翻译 <span>选填</span></button><label id="outreach-translation-field" hidden>中文翻译<textarea data-outreach-translation maxlength="50000" placeholder="填写对应的中文翻译（选填）"></textarea></label></section></div></div><footer><div><span role="status" data-outreach-status></span><small>保存草稿不会发送邮件或新增跟进</small></div><button type="button" data-outreach-editor-retry hidden>重新读取</button><button type="button" data-outreach-save>保存草稿</button><button type="button" data-outreach-send>发送邮件</button></footer>`;
    document.body.append(editor);
    const s={standalone,trigger,id:context.id,project:context.project,panel,editor,loaded:false,busy:false,saved:defaults({}),people:context.item.contacts||[person],rich:window.TophooRichMail.mount(editor.querySelector('[data-outreach-content]'))};active=s;
    panel.querySelector('[data-outreach-open]').onclick=()=>{if(!current(s))return;fields(s,s.saved);controls(s);editor.showModal();s.baseline=JSON.stringify(values(s));status(s,'');editor.querySelector('[data-outreach-content]').focus();};
    panel.querySelector('[data-outreach-copy]').onclick=()=>copy(s,false);
    panel.querySelector('[data-outreach-record]').onclick=()=>{
      if(!current(s)||!editable()||s.busy||!s.saved.content.trim())return;
      const dialog=document.createElement('dialog');dialog.className='mail-html-dialog outreach-convert-dialog';dialog.setAttribute('aria-labelledby','outreach-convert-title');
      dialog.innerHTML='<h3 id="outreach-convert-title">转为跟进</h3><p>将带入标题、正文和中文翻译，下一步可选择联系人并核对内容。</p><label class="outreach-clear-option"><input type="checkbox" data-outreach-clear>跟进保存成功后，清除当前开发信</label><small>默认保留。勾选后将清除草稿；取消或保存失败不会清除。</small><footer><button type="button" data-convert-cancel>取消</button><button type="button" data-convert-next>下一步</button></footer>';
      document.body.append(dialog);dialog.showModal();dialog.addEventListener('keydown',event=>event.stopPropagation());dialog.addEventListener('close',()=>dialog.remove());dialog.querySelector('[data-convert-cancel]').onclick=()=>dialog.close();
      dialog.querySelector('[data-convert-next]').onclick=()=>{
        if(!current(s)||!editable())return dialog.close();
        const conversion={clear_draft:dialog.querySelector('[data-outreach-clear]').checked,expected_draft:defaults(s.saved),request_key:crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)};
        dialog.close();document.dispatchEvent(new CustomEvent('tophoo-outreach-to-record',{detail:{project:s.project,id:s.id,prefill:{...s.saved,outreach_conversion:conversion,direction:'outbound',channel:'邮件',contact_name:s.saved.recipient_name||s.saved.recipient_email||''}}}));
      };
    };
    const signatureButton=document.createElement('button');signatureButton.type='button';signatureButton.dataset.outreachSignature='';signatureButton.textContent='插入默认邮箱签名';signatureButton.title='插入默认发件邮箱的签名；发送预览中可切换邮箱并添加对应签名';editor.querySelector('.mail-rich-toolbar').append(signatureButton);
    signatureButton.onclick=async()=>{
      if(!current(s)||!s.loaded||!editable()||s.busy)return;s.busy=true;controls(s);status(s,'正在读取签名…');
      try{
        const response=await fetch('/api/mail/configuration',{headers:window.tophooAuth?.headers?.()||{}}),data=await response.json();
        if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'读取签名失败，请重试。');
        if(!current(s))return;if(!data.signature?.trim())throw Error('请先在“系统 → 邮箱配置”中保存邮件签名。');
        s.busy=false;controls(s);const html=/<[a-z][\s\S]*>/i.test(data.signature)?data.signature:esc(data.signature).replace(/\n/g,'<br>');s.rich.insert('<br>'+html);status(s,'签名已插入，请保存草稿');
      }catch(error){if(current(s))status(s,error.message,true);}finally{s.busy=false;if(current(s))controls(s);}
    };
    editor.querySelector('[data-outreach-toggle-translation]').onclick=e=>{const open=e.currentTarget.getAttribute('aria-expanded')!=='true';e.currentTarget.setAttribute('aria-expanded',String(open));e.currentTarget.innerHTML=(open?'▾':'▸')+' 中文翻译 <span>选填</span>';editor.querySelector('.lead-outreach-translation label').hidden=!open;editor.querySelector('.lead-outreach-writing').classList.toggle('has-translation',open);};
    editor.querySelector('[data-outreach-send]').onclick=async()=>{
      if(!current(s)||!s.loaded||!editable()||s.busy)return;const data=values(s);
      if(!data.subject.trim()||!data.content.trim())return status(s,'请先填写邮件标题和正文。',true);
      if(!window.TophooMail)return status(s,'请刷新页面以加载邮箱发送功能。',true);
      if(!await save(s))return;
      const result=await window.TophooMail.compose({...values(s),id:s.id,project:s.project,company_name:context.item.company_name,recipient:'',contact_name:'',people:s.people});
      if(!current(s))return;
      if(result?.status==='accepted'){close(s);document.dispatchEvent(new CustomEvent(s.standalone?'tophoo-lead-outreach-sent':'tophoo-return-workflow-detail',{detail:{projectId:s.project,contactId:s.id,view:'leads',refresh:true}}));}
      else if(result?.accepted_count){status(s,`已有 ${result.accepted_count} 封获服务器接受，其余请查看邮箱发送记录。`);document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-sent',{detail:{projectId:s.project,contactId:s.id,view:'leads'}}));}
    };
    editor.querySelector('[data-outreach-save]').onclick=()=>save(s);
    editor.querySelector('[data-outreach-close]').onclick=()=>close(s);
    editor.querySelector('[data-outreach-max]').onclick=e=>{const large=editor.classList.toggle('is-expanded');e.currentTarget.textContent=large?'还原':'放大';e.currentTarget.setAttribute('aria-pressed',String(large));e.currentTarget.setAttribute('aria-label',large?'还原编写窗口':'放大编写窗口');};
    editor.addEventListener('close',()=>{if(current(s)&&!editor.open)resetEditor(s);});
    editor.addEventListener('cancel',e=>{e.preventDefault();close(s);});
    editor.addEventListener('input',()=>{status(s,dirty(s)?'尚未保存':'已保存');controls(s);});
    editor.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();e.stopPropagation();save(s);}});
    async function load(){
      if(!current(s))return;
      panel.querySelector('[data-outreach-retry]').hidden=true;editor.querySelector('[data-outreach-editor-retry]').hidden=true;status(s,'正在读取…');
      try{const data=await request(s);if(expected!==version||!current(s))return;s.saved={...defaults(data),updated_at:data.updated_at};fields(s,s.saved);s.loaded=true;s.baseline=JSON.stringify(values(s));preview(s);status(s,'');}
      catch(e){if(current(s)){status(s,e.message,true);panel.querySelector('[data-outreach-preview]').textContent='草稿读取失败，请重试';panel.querySelector('[data-outreach-retry]').hidden=false;editor.querySelector('[data-outreach-editor-retry]').hidden=false;}}
    }
    panel.querySelector('[data-outreach-retry]').onclick=load;editor.querySelector('[data-outreach-editor-retry]').onclick=load;
    controls(s);if(standalone)editor.showModal();await load();
  }
  document.addEventListener('tophoo-lead-outreach-open',event=>mount(event.detail,true,event.detail.trigger));
})();
