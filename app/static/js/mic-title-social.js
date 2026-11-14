(() => {
  const dialog=document.querySelector('#mic-social-editor');if(!dialog)return;
  const $=selector=>dialog.querySelector(selector),form=$('#mic-social-form');
  const platforms={facebook:'Facebook',instagram:'Instagram',linkedin:'LinkedIn',youtube:'YouTube'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const project=()=>Number(localStorage.getItem('tophoo-global-selected-project'));
  const identity=()=>JSON.stringify([project(),window.tophooAuth?.token?.(),window.tophooAuth?.currentUser?.()?.id]);
  const canEdit=()=>!window.tophooProjectAccess||window.tophooProjectAccess.canEdit('mic_products');
  let state=null,opening=0;
  const current=s=>state===s&&s.identity===identity();
  const message=(text='',error=false)=>{const node=error?$('#mic-social-error'):$('#mic-social-feedback');node.textContent=text;if(error)node.hidden=!text;};
  async function request(s,suffix,method='GET',data){
    const response=await fetch(`/api/mic-products/projects/${s.project}/${s.id}${suffix}`,{method,headers:{...(window.tophooAuth?.headers?.()||{}),...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});
    const result=await response.json().catch(()=>({}));if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'操作失败，请重试。');return result;
  }
  function payload(){
    if(!state?.draft)return null;
    return {platforms:state.draft.platforms};
  }
  const dirty=()=>Boolean(state?.draft&&dialog.open&&JSON.stringify(payload())!==state.baseline);
  function close(force=false){
    if(!force&&(state?.busy||(dirty()&&!confirm('这款产品的社媒内容尚未保存，确认放弃修改？'))))return false;
    const trigger=state?.trigger;opening++;state=null;dialog.close();$('#mic-social-fields').innerHTML='';message('',true);
    if(trigger?.isConnected)trigger.focus({preventScroll:true});return true;
  }
  function controls(){
    if(!state)return;const locked=state.busy||!state.draft||!canEdit();
    $('#mic-social-save').disabled=locked;
    $('#mic-social-save').textContent=state.saving?'正在保存…':'保存社媒内容';
    dialog.querySelectorAll('textarea').forEach(el=>el.readOnly=locked);
    dialog.querySelectorAll('[data-social-published]').forEach(el=>el.disabled=locked);
    dialog.querySelectorAll('[data-social-copy]').forEach(button=>{
      button.disabled=!copyText(state.draft.platforms[button.dataset.socialCopy],button.dataset.copyField);
    });
  }
  function copyText(entry, language){
    const keys=language==='zh'?['video_title_zh','translation','tags_zh']:['video_title','content','tags'];
    return keys.map(key=>entry[key]?.trim()).filter(Boolean).join('\n\n');
  }
  function field(label,key,platform,{english=false,rows=3}={}){
    const value=state.draft.platforms[platform][key]||'';
    return `<label class="mic-social-text-field ${english?'is-english':'is-chinese'}"><span>${label}</span><textarea rows="${rows}" maxlength="${key.startsWith('video_title')?260:key.startsWith('tags')?2000:20000}" data-social-field="${key}" data-social-platform="${platform}" aria-label="${esc(platforms[platform]+' '+label)}" placeholder="${english?'填写英文文案':'对应的简体中文翻译'}">${esc(value)}</textarea></label>`;
  }
  function platformStatus(entry){
    if(entry.published)return ['已发布','published'];
    return entry.content.trim()?['已备稿','ready']:['待编写','empty'];
  }
  function publicationPanel(platform,entry){
    const [label,tone]=platformStatus(entry);
    return `<div class="mic-publication-panel">
      <div class="mic-publication-heading"><strong>发布确认</strong><span class="mic-social-state ${tone}">${label}</span></div>
      <label class="mic-studio-published mic-publish-switch"><input type="checkbox" role="switch" data-social-published="${platform}" ${entry.published?'checked':''}><span class="mic-switch-track" aria-hidden="true"></span>已发布</label>
    </div>`;
  }
  function renderPlatform(){
    if(!state?.draft)return;const p=state.platform,e=state.draft.platforms[p],youtube=p==='youtube';
    $('#mic-social-tabs').innerHTML=Object.entries(platforms).map(([key,name])=>{
      const [label,tone]=platformStatus(state.draft.platforms[key]);
      return `<button type="button" role="tab" id="mic-social-tab-${key}" aria-controls="mic-social-panel" aria-selected="${p===key}" tabindex="${p===key?0:-1}" data-social-tab="${key}">${name}<span class="mic-social-state ${tone}">${label}</span></button>`;
    }).join('');
    $('#mic-social-fields').innerHTML=`<section id="mic-social-panel" role="tabpanel" aria-labelledby="mic-social-tab-${p}" class="mic-social-platform-panel"><header><strong>${platforms[p]}</strong><div class="mic-social-panel-actions"><button type="button" data-social-copy="${p}" data-copy-field="all">复制英文</button><button type="button" data-social-copy="${p}" data-copy-field="zh">复制中文</button></div></header>${publicationPanel(p,e)}${youtube?`<div class="mic-social-language-pair">${field('视频标题','video_title',p,{english:true,rows:2})}${field('标题翻译','video_title_zh',p,{rows:2})}</div>`:''}<div class="mic-social-language-pair">${field(youtube?'视频描述 · English':'英文文案 · English','content',p,{english:true,rows:9})}${field(youtube?'描述翻译 · 中文':'中文对照','translation',p,{rows:9})}</div>${youtube?`<div class="mic-social-language-pair">${field('Tags · 英文逗号分隔','tags',p,{english:true,rows:2})}${field('标签翻译','tags_zh',p,{rows:2})}</div>`:''}</section>`;
    controls();
  }
  async function open(id,platform='facebook'){
    if(dialog.open)return;const seq=++opening,trigger=document.activeElement;
    const note=document.querySelector('#mic-social-editor-note');note.textContent='正在读取社媒文案…';note.hidden=false;
    const s={id,project:project(),identity:identity(),trigger,platform:platforms[platform]?platform:'facebook',busy:false,draft:null};
    try{
      const data=await request(s,'/product-social');
      if(seq!==opening||s.identity!==identity())return;
      note.hidden=true;
      state={...s,draft:structuredClone(data)};
      $('#mic-social-title').textContent='产品社媒内容';$('#mic-social-product').textContent=data.product_code+' · '+data.product_name;
      $('#mic-social-code').textContent=data.product_code;$('#mic-social-selected-title').textContent=data.product_name;
      $('#mic-social-title-warning').hidden=!data.name_changed;
      state.baseline=JSON.stringify(payload());message('',true);message('');renderPlatform();dialog.show();
    }catch(error){if(seq===opening&&s.identity===identity()){const note=document.querySelector('#mic-social-editor-note');note.textContent=error.message;note.hidden=dialog.hidden;}}
  }
  function changed(){if(!state)return;message(dirty()?'这款产品有未保存的修改':'已保存');controls();}
  form.addEventListener('input',event=>{
    if(!state?.draft)return;const el=event.target;
    if(el.dataset.socialField)state.draft.platforms[el.dataset.socialPlatform][el.dataset.socialField]=el.value;
    if(el.dataset.socialField==='content'){
      const platform=el.dataset.socialPlatform;
      const [label,tone]=platformStatus(state.draft.platforms[platform]);
      dialog.querySelectorAll(`[data-social-tab="${platform}"] .mic-social-state,.mic-publication-heading .mic-social-state`).forEach(badge=>{
        badge.className=`mic-social-state ${tone}`;
        badge.textContent=label;
      });
    }
    changed();
  });
  form.addEventListener('change',event=>{
    if(!state?.draft||!event.target.matches('[data-social-published]'))return;
    const el=event.target,e=state.draft.platforms[el.dataset.socialPublished];
    if(el.checked&&!e.content.trim()){el.checked=false;message('请先填写文案，再登记已发布。',true);return;}
    e.published=el.checked;if(!el.checked)e.published_at='';renderPlatform();$('[data-social-published]').focus({preventScroll:true});changed();
  });
  form.addEventListener('click',async event=>{
    const b=event.target.closest('button');if(!b||!state)return;
    if(b.hasAttribute('data-social-tab')){state.platform=b.dataset.socialTab;renderPlatform();return;}
    if(b.hasAttribute('data-social-copy')){
      const s=state,e=s.draft?.platforms[b.dataset.socialCopy];if(!e)return;
      const text=copyText(e,b.dataset.copyField);
      if(!text?.trim())return message('当前文案为空。',true);
      try{await navigator.clipboard.writeText(text);if(current(s)){message(b.dataset.copyField==='zh'?'中文文案已复制':'英文文案已复制');}}catch{if(current(s))message('浏览器未允许自动复制，请选中文案后手动复制。',true);}
    }
  });
  form.onsubmit=async event=>{
    event.preventDefault();const s=state;if(!s?.draft||s.busy||!canEdit())return;
    s.busy=s.saving=true;controls();message('',true);
    try{const entry=await request(s,'/product-social','PUT',payload());if(!current(s))return;
      s.draft=structuredClone(entry);s.baseline=JSON.stringify(payload());$('#mic-social-title-warning').hidden=!entry.name_changed;message('这款产品的四个平台内容已保存。');
      document.dispatchEvent(new CustomEvent('tophoo-mic-social-saved',{detail:{project:s.project,id:s.id}}));
    }catch(error){if(current(s))message(error.message,true);}finally{if(current(s)){s.busy=s.saving=false;controls();}}
  };
  dialog.querySelectorAll('[data-social-close]').forEach(b=>b.onclick=()=>close());
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();if(!$('#mic-social-save').disabled)form.requestSubmit();}
    if(event.target.matches('[role="tab"]')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      event.preventDefault();const keys=Object.keys(platforms),i=keys.indexOf(state.platform);state.platform=keys[event.key==='Home'?0:event.key==='End'?keys.length-1:(i+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length];renderPlatform();$(`[data-social-tab="${state.platform}"]`).focus();
    }
  });
  window.addEventListener('tophoo-project-changed',()=>close(true));document.addEventListener('tophoo-auth-changed',()=>close(true));
  window.addEventListener('beforeunload',event=>{if(dialog.open&&(dirty()||state?.busy)){event.preventDefault();event.returnValue='';}});
  window.TophooMicSocial={open,close,dirty,busy:()=>Boolean(state?.busy)};
})();
