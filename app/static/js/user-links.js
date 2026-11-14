(() => {
  const page=document.querySelector('[data-user-links]');if(!page)return;
  const q=selector=>page.querySelector(selector),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={categories:[],items:[],category:'all',busy:false,loaded:false,version:0,mode:'',editing:null,baseline:''};
  const dialog=q('[data-ul-dialog]'),form=q('[data-ul-form]');
  const projectId=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||null;
  const endpoint=path=>'/api/user-links'+path+(projectId()?'?project_id='+projectId():'');
  async function api(path='',options={}){const response=await fetch(endpoint(path),{...options,headers:{...(window.tophooAuth?.headers?.()||{}),'Content-Type':'application/json',...(options.headers||{})}});const data=await response.json().catch(()=>({}));if(!response.ok)throw Error(Array.isArray(data.detail)?data.detail.map(item=>item.msg.replace(/^Value error,\s*/,'')).join('；'):data.detail||'操作失败，请重试。');return data;}
  function notice(message,error=false){q('[data-ul-notice]').textContent=message;q('[data-ul-notice]').hidden=!message;q('[data-ul-notice]').classList.toggle('is-error',error);q('[data-ul-notice]').setAttribute('role',error?'alert':'status');clearTimeout(notice.timer);if(error){const retry=document.createElement('button');retry.type='button';retry.dataset.ulRetry='';retry.textContent='重新加载';q('[data-ul-notice]').append(retry);}else if(message)notice.timer=setTimeout(()=>q('[data-ul-notice]').hidden=true,4000);}
  function busy(value){state.busy=value;page.querySelectorAll('button,input,select,textarea').forEach(item=>item.disabled=value);page.setAttribute('aria-busy',String(value));}
  function categoryName(id){return state.categories.find(item=>item.id===id)?.name||'未分类';}
  function visible(){const text=q('[data-ul-search]').value.trim().toLowerCase();return state.items.filter(item=>(state.category==='all'||String(item.category_id??'none')===state.category)&&(!text||[item.name,item.url,categoryName(item.category_id)].join(' ').toLowerCase().includes(text)));}
  function render(){
    const count=id=>state.items.filter(item=>String(item.category_id??'none')===String(id)).length;
    const uncategorized=count('none');
    q('[data-ul-clear]').hidden=!q('[data-ul-search]').value;
    if(state.category==='none'&&!uncategorized)state.category='all';
    q('[data-ul-category-hint]').hidden=state.category!=='none';
    q('[data-ul-categories]').innerHTML=[{id:'all',name:'全部网址',count:state.items.length},...(uncategorized?[{id:'none',name:'待归类',count:uncategorized}]:[]),...state.categories.map(item=>({...item,count:count(item.id)}))].map(item=>`<div class="ul-category-row ${String(item.id)===state.category?'is-active':''}"><button type="button" data-ul-category="${item.id}" ${item.id==='none'?'title="未选择分类的网址；归类后此入口自动隐藏"':''} aria-pressed="${String(item.id)===state.category}"><strong>${esc(item.name)}</strong><small>${item.count}</small></button>${typeof item.id==='number'?`<button type="button" class="ul-category-edit" data-ul-category-edit="${item.id}" title="编辑分类" aria-label="编辑 ${esc(item.name)}">⋯</button>`:''}</div>`).join('');
    const items=visible(),mixedCategories=new Set(items.map(item=>item.category_id)).size>1;q('[data-ul-count]').textContent=`${state.category==='all'?'全部网址':state.category==='none'?'待归类':categoryName(Number(state.category))} · ${items.length} 个${q('[data-ul-search]').value?'匹配结果':'网址'}`;
    q('[data-ul-links]').innerHTML=items.length?`<div class="ul-card-grid">${items.map(item=>{
      let host='';try{host=new URL(item.url).hostname.replace(/^www\./,'');}catch{}
      const peers=state.items.filter(link=>link.category_id===item.category_id),index=peers.findIndex(link=>link.id===item.id);
      const palette=['mint','blue','amber','violet'];const tone=palette[[...host].reduce((sum,char)=>sum+char.charCodeAt(0),0)%palette.length];
      return `<article class="ul-card"><a class="ul-card-link" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer" title="${esc(item.name)} · ${esc(item.url)}"><span class="ul-link-icon is-${tone}" aria-hidden="true">${esc((item.name||host).slice(0,1).toUpperCase())}</span><div class="ul-link-copy"><strong>${esc(item.name)}</strong><small>${esc(host)}</small>${state.category==='all'&&mixedCategories?`<span class="ul-card-category">${esc(categoryName(item.category_id))}</span>`:''}</div><span class="ul-open-arrow" aria-hidden="true">↗</span></a><details class="ul-link-menu"><summary aria-label="管理 ${esc(item.name)}" title="管理网址">⋯</summary><div class="ul-menu-panel"><button type="button" data-ul-edit="${item.id}">编辑网址</button><button type="button" data-ul-assign="${item.id}">移动分类</button><button type="button" data-ul-move="${item.id}" data-direction="up" ${index===0?'disabled':''}>分类内上移</button><button type="button" data-ul-move="${item.id}" data-direction="down" ${index===peers.length-1?'disabled':''}>分类内下移</button><button type="button" class="ul-danger" data-ul-delete="${item.id}">删除网址</button></div></details></article>`;
    }).join('')}</div>`:`<div class="ul-empty"><span aria-hidden="true">▱</span><h3>${q('[data-ul-search]').value?'没有匹配的网址':state.category==='all'?'还没有常用网址':'这个分类还没有网址'}</h3><p>${q('[data-ul-search]').value?'试试其他名称或清空搜索。':'点击“新增网址”，保存常用网站。'}</p>${q('[data-ul-search]').value?'<button type="button" data-ul-clear>清空搜索</button>':'<button type="button" class="ul-primary" data-ul-add>＋ 新增网址</button>'}</div>`;

  }
  async function load(){const version=++state.version;try{const data=await api();if(version!==state.version)return;state.categories=data.categories;state.items=data.items;state.loaded=true;if(!['all','none',...state.categories.map(item=>String(item.id))].includes(state.category))state.category='all';render();}catch(error){if(version===state.version)notice(error.message,true);}}
  const snapshot=()=>JSON.stringify([...new FormData(form)]);
  function close(force=false){if(state.busy&&!force)return;if(!force&&state.baseline!==snapshot()&&!confirm('修改尚未保存，确定放弃吗？'))return;dialog.close();state.mode='';state.editing=null;state.baseline='';}
  function open(mode,item={}){
    if(state.busy)return;state.mode=mode;state.editing=item.id||null;q('[data-ul-title]').textContent=(item.id?'编辑':'新增')+(mode==='category'?'分类':'网址');q('[data-ul-error]').hidden=true;
    const input=(name,label,value,max)=>`<label>${label}<input name="${name}" value="${esc(value||'')}" maxlength="${max}" required></label>`;
    const categoryField=`<label>分类<select name="category_id"><option value="">暂不分类</option>${state.categories.map(category=>`<option value="${category.id}">${esc(category.name)}</option>`).join('')}</select></label>`;
    q('[data-ul-fields]').innerHTML=mode==='category'?input('name','分类名称',item.name,80):mode==='assign'?`<p class="ul-assign-name">${esc(item.name)}</p>${categoryField}`:input('name','网址名称',item.name,150)+input('url','网址地址',item.url,1000)+categoryField;
    if(mode!=='category')form.elements.category_id.value=String(item.category_id??(Number(state.category)||''));
    if(mode==='assign')q('[data-ul-title]').textContent='移动分类';
    if(mode==='link'){
      form.elements.url.placeholder='粘贴链接或输入 example.com';form.elements.url.inputMode='url';form.elements.url.autocomplete='url';
      form.elements.name.placeholder='例如：GSC、Google Search Console';
      let generatedName='';
      const fillName=()=>{
        if(form.elements.name.value.trim()&&form.elements.name.value!==generatedName)return;
        try{const raw=form.elements.url.value.trim(),url=new URL(raw.includes('://')?raw:'https://'+raw);
          if(['http:','https:'].includes(url.protocol)&&url.hostname){
            generatedName=url.hostname.replace(/^www\./,'');form.elements.name.value=generatedName;
          }
        }catch{}
      };
      form.elements.name.addEventListener('input',()=>{generatedName='';});
      form.elements.url.addEventListener('input',fillName);
      form.elements.url.addEventListener('change',fillName);
      form.elements.url.addEventListener('blur',fillName);
    }
    let deleteButton=form.querySelector('[data-ul-category-delete]');deleteButton?.remove();
    if(mode==='category'&&item.id){deleteButton=document.createElement('button');deleteButton.type='button';deleteButton.className='ul-danger';deleteButton.dataset.ulCategoryDelete='';deleteButton.textContent='删除分类';deleteButton.onclick=()=>removeCategory(item);form.querySelector('footer').prepend(deleteButton);}
    state.baseline=snapshot();dialog.showModal();(mode==='assign'?form.elements.category_id:form.elements.name).focus();
  }
  async function removeCategory(item){if(!confirm(`删除分类“${item.name}”？其中的网址会保留并移到“未分类”。`))return;busy(true);try{await api('/categories/'+item.id,{method:'DELETE'});close(true);await load();notice('分类已删除，网址已移至未分类。');}catch(error){q('[data-ul-error]').textContent=error.message;q('[data-ul-error]').hidden=false;}finally{busy(false);render();}}
  form.onsubmit=async event=>{
    event.preventDefault();if(state.busy)return;
    const version=state.version,mode=state.mode,isNew=!state.editing,payload=Object.fromEntries(new FormData(form));
    if(mode==='assign'){const item=state.items.find(item=>item.id===state.editing);if(!item)return;payload.name=item.name;payload.url=item.url;}
    payload.name=payload.name.trim();if(!payload.name)return;
    if(mode!=='category')payload.category_id=payload.category_id?Number(payload.category_id):null;
    const path=(mode==='category'?'/categories':'')+(state.editing?'/'+state.editing:'');busy(true);
    try{await api(path,{method:state.editing?'PUT':'POST',body:JSON.stringify(payload)});if(version!==state.version)return;
      close(true);
      if(mode==='link'&&isNew){q('[data-ul-search]').value='';if(state.category!=='all')state.category=String(payload.category_id??'none');}
      await load();notice(mode==='assign'?`已移动至${categoryName(payload.category_id)}。`:'已保存。');
    }catch(error){if(version===state.version){q('[data-ul-error]').textContent=error.message;q('[data-ul-error]').hidden=false;}}
    finally{busy(false);render();}
  };

  page.onclick=async event=>{const menu=event.target.closest('.ul-link-menu');page.querySelectorAll('.ul-link-menu[open]').forEach(item=>{if(item!==menu)item.open=false;});const button=event.target.closest('button');if(!button||state.busy)return;
    if(button.hasAttribute('data-ul-clear')){q('[data-ul-search]').value='';render();q('[data-ul-search]').focus();}
    else if(button.hasAttribute('data-ul-retry')){notice('');await load();}
    else if(button.hasAttribute('data-ul-add'))open('link');
    else if(button.hasAttribute('data-ul-category-add'))open('category');
    else if(button.hasAttribute('data-ul-close'))close();
    else if(button.dataset.ulCategory){state.category=button.dataset.ulCategory;render();}
    else if(button.dataset.ulCategoryEdit)open('category',state.categories.find(item=>item.id===Number(button.dataset.ulCategoryEdit)));
    else if(button.dataset.ulAssign)open('assign',state.items.find(item=>item.id===Number(button.dataset.ulAssign)));
    else if(button.dataset.ulEdit)open('link',state.items.find(item=>item.id===Number(button.dataset.ulEdit)));
    else if(button.dataset.ulDelete){const item=state.items.find(item=>item.id===Number(button.dataset.ulDelete));if(!confirm(`删除网址“${item.name}”？`))return;busy(true);try{await api('/'+item.id,{method:'DELETE'});await load();notice('网址已删除。');}catch(error){notice(error.message,true);}finally{busy(false);render();}}
    else if(button.dataset.ulMove){busy(true);try{await api('/'+button.dataset.ulMove+'/move',{method:'POST',body:JSON.stringify({direction:button.dataset.direction})});await load();}catch(error){notice(error.message,true);}finally{busy(false);render();}}
    else if(button.hasAttribute('data-ul-export')){const version=state.version;try{const response=await fetch(endpoint('/export/pdf'),{headers:window.tophooAuth?.headers?.()||{}});if(!response.ok)throw Error('导出失败，请重试。');const blob=await response.blob();if(version!==state.version)return;const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='个人网址导航.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message,true);}}
  };
  document.addEventListener('click',event=>{if(!event.target.closest('.ul-link-menu'))page.querySelectorAll('.ul-link-menu[open]').forEach(menu=>menu.open=false);});
  document.addEventListener('keydown',event=>{if(page.hidden||dialog.open)return;if(event.key==='/'&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.target.closest('input,textarea,select,[contenteditable="true"]')){event.preventDefault();q('[data-ul-search]').focus();return;}if(event.key==='Escape'&&event.target===q('[data-ul-search]')){q('[data-ul-search]').value='';render();return;}if(event.key==='Escape'&&!dialog.open)page.querySelectorAll('.ul-link-menu[open]').forEach(menu=>{menu.open=false;menu.querySelector('summary').focus();});});
  q('[data-ul-search]').oninput=render;
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  document.addEventListener('tophoo-user-links-view',()=>{if(!dialog.open&&!state.busy)load();});
  function resetContext(){state.version++;close(true);state.categories=[];state.items=[];state.category='all';state.loaded=false;busy(false);q('[data-ul-search]').value='';notice('');render();if(!page.hidden)load();}
  document.addEventListener('tophoo-auth-changed',resetContext);
  window.addEventListener('tophoo-project-changed',resetContext);
})();