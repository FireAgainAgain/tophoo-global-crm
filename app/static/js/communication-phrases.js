/* Project phrase library. Plain text stays plain text in both viewing and copying. */
(()=>{
 const root=document.querySelector('[data-phrase-library]');if(!root)return;
 const q=s=>root.querySelector(s),dialog=q('[data-phrase-dialog]'),form=q('[data-phrase-form]'),body=q('[data-phrase-body]'),actions=q('[data-phrase-actions]');
 const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0,headers=()=>window.tophooAuth?.headers?.()||{};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const state={project:0,identity:'',version:0,categories:[],scenes:[],items:[],selected:0,scene:null,ordering:false,limit:40,canEdit:false,loading:false,busy:false,exporting:null,panel:null,baseline:'',opener:null};let timer;
 const cat=id=>state.categories.find(x=>x.id===Number(id));
 const scene=id=>state.scenes.find(x=>x.id===Number(id));
 const sceneOptions=(categoryId,selected=null)=>'<option value="" '+(!selected?'selected':'')+'>未分场景</option>'+state.scenes.filter(x=>x.category_id===Number(categoryId)).map(x=>`<option value="${x.id}" ${x.id===selected?'selected':''}>${esc(x.name)}</option>`).join('');
 const snapshot=()=>JSON.stringify([...new FormData(form)]),dirty=()=>dialog.open&&['phrase','category','scene'].includes(state.panel?.mode)&&snapshot()!==state.baseline;
 const context=()=>({project:state.project,identity:state.identity,version:state.version});
 const same=c=>c.project===pid()&&c.project===state.project&&c.identity===JSON.stringify(headers())&&c.version===state.version;
 const base=c=>`/api/phrases/projects/${c.project}`;
 function say(message){clearTimeout(timer);q('[data-phrase-toast]').textContent=message;q('[data-phrase-toast]').hidden=false;timer=setTimeout(()=>q('[data-phrase-toast]').hidden=true,2500);}
 function close(force=false){if(!force&&(state.busy||(dirty()&&!confirm('有未保存的修改，确定放弃吗？'))))return false;dialog.close();root.append(q('[data-phrase-toast]'));body.innerHTML='';actions.innerHTML='';state.panel=null;state.baseline='';state.opener?.isConnected&&state.opener.focus({preventScroll:true});return true;}
 async function api(url,options={}){const r=await fetch(url,{...options,headers:{...headers(),...(options.body?{'Content-Type':'application/json'}:{})}}),data=await r.json().catch(()=>({}));if(!r.ok)throw Error(Array.isArray(data.detail)?data.detail.map(x=>x.msg.replace(/^Value error, /,'')).join('；'):data.detail||'操作失败，请重试。');return data;}
 function fitReadingArea(){
  if(root.hidden)return;
  let padding=16;
  for(let node=root.parentElement;node&&node!==document.body;node=node.parentElement)padding+=parseFloat(getComputedStyle(node).paddingBottom)||0;
  const top=root.getBoundingClientRect().top;
  root.style.height=Math.max(300,window.innerHeight-top-padding)+'px';
 }
 window.addEventListener('resize',()=>requestAnimationFrame(fitReadingArea));
 function highlight(value,term){
  const text=String(value||'');if(!term)return esc(text);
  const lower=text.toLocaleLowerCase();let result='',from=0,index;
  while((index=lower.indexOf(term,from))!==-1){result+=esc(text.slice(from,index))+'<mark>'+esc(text.slice(index,index+term.length))+'</mark>';from=index+term.length;}
  return result+esc(text.slice(from));
 }
 function render(){
  requestAnimationFrame(fitReadingArea);
  if(!cat(state.selected)){state.selected=state.categories[0]?.id||0;state.scene=null;state.ordering=false;}
  const counts=new Map();state.items.forEach(x=>counts.set(x.category_id,(counts.get(x.category_id)||0)+1));
  const categoryRow=(id,name,count)=>`<div class="phrase-category-row ${state.selected===id?'is-active':''}"><button type="button" class="phrase-category-select" data-phrase-category="${id}" aria-pressed="${state.selected===id}"><span>${esc(name)}</span><small>${count}</small></button>${id&&state.canEdit?`<details class="phrase-category-menu"><summary aria-label="管理分类 ${esc(name)}">⋯</summary><div><button type="button" data-cat-edit="${id}">修改名称</button><button type="button" data-cat-move="${id}" data-step="-1" ${state.categories[0]?.id===id?'disabled':''}>上移</button><button type="button" data-cat-move="${id}" data-step="1" ${state.categories.at(-1)?.id===id?'disabled':''}>下移</button><button type="button" data-cat-delete="${id}">删除分类</button></div></details>`:''}</div>`;
  q('[data-phrase-categories]').innerHTML=state.categories.map(x=>categoryRow(x.id,x.name,counts.get(x.id)||0)).join('');
  const scenes=state.scenes.filter(x=>x.category_id===state.selected),inCategory=state.items.filter(x=>x.category_id===state.selected);
  const unassigned=inCategory.filter(x=>!x.scene_id).length;
  if(state.selected){if(!(state.scene===0&&unassigned)&&!scenes.some(x=>x.id===state.scene))state.scene=unassigned?0:scenes[0]?.id??null;}else state.scene=null;
  q('[data-phrase-heading]').textContent=state.scene===0?'未分场景':scene(state.scene)?.name||cat(state.selected)?.name||'沟通话术';
  const sceneTab=(id,name,count)=>`<div class="phrase-scene-row ${state.scene===id?'is-active':''}"><button type="button" data-phrase-scene="${id}" aria-pressed="${state.scene===id}">${esc(name)} <span>${count}</span></button>${id&&state.canEdit?`<details class="phrase-scene-menu"><summary aria-label="管理场景 ${esc(name)}">⋯</summary><div><button type="button" data-scene-edit="${id}">修改名称</button><button type="button" data-scene-move="${id}" data-step="-1" ${scenes[0]?.id===id?'disabled':''}>上移</button><button type="button" data-scene-move="${id}" data-step="1" ${scenes.at(-1)?.id===id?'disabled':''}>下移</button><button type="button" data-scene-delete="${id}">删除场景</button></div></details>`:''}</div>`;
  q('[data-phrase-scenes-panel]').hidden=!state.selected;
  q('[data-phrase-scenes]').innerHTML=state.selected?(unassigned?sceneTab(0,'未分场景',unassigned):'')+scenes.map(x=>sceneTab(x.id,x.name,inCategory.filter(i=>i.scene_id===x.id).length)).join(''):'';
  q('[data-phrase-scene-hint]').textContent=state.selected&&!scenes.length?'新增场景后，就能按用途整理话术。':'';
  q('[data-phrase-add-scene]').hidden=!state.canEdit||!state.selected;
  q('[data-phrase-add-scene]').disabled=state.loading||state.busy;
  const exportButton=q('[data-phrase-export]');exportButton.hidden=false;exportButton.disabled=state.loading||state.busy||!!state.exporting||!state.items.length;exportButton.textContent=state.exporting?'正在导出…':'导出全部 PDF';
  const term=q('[data-phrase-search]').value.trim().toLocaleLowerCase();
  const items=state.items.filter(x=>(x.category_id===state.selected)&&(state.scene===null||(state.scene===0?!x.scene_id:x.scene_id===state.scene))&&(!term||`${x.content}\n${x.translation||''}\n${cat(x.category_id)?.name||''}\n${scene(x.scene_id)?.name||''}`.toLocaleLowerCase().includes(term)));
  q('[data-phrase-search]').placeholder=state.selected?'搜索当前分类的话术或场景':'搜索话术、翻译或场景';
  q('[data-phrase-clear-search]').hidden=!q('[data-phrase-search]').value;
  q('[data-phrase-count]').textContent=state.loading?'正在加载…':`${items.length} 条话术${term?' · 搜索结果':''}${state.ordering?' · 点击箭头调整顺序':''}`;
  const sort=q('[data-phrase-sort]');sort.hidden=!state.canEdit||(items.length<2&&!state.ordering);sort.disabled=!!term||state.busy||state.loading;sort.textContent=state.ordering?'完成排序':'调整顺序';sort.setAttribute('aria-pressed',String(state.ordering));sort.title=term?'清空搜索后调整顺序':'调整当前列表顺序';
  let previousGroup='';
  q('[data-phrase-list]').innerHTML=state.loading?'<div class="phrase-empty">正在加载话术…</div>':items.slice(0,state.limit).map((x,index)=>{
   const group=`${x.category_id}/${x.scene_id||0}`,label=[!state.selected?cat(x.category_id)?.name:'',scene(x.scene_id)?.name].filter(Boolean).join(' / ');
   const heading=state.scene===null&&!state.ordering&&label&&group!==previousGroup?`<h3 class="phrase-group-heading">${esc(label)}<span>${items.filter(i=>i.category_id===x.category_id&&i.scene_id===x.scene_id).length} 条</span></h3>`:'';previousGroup=group;
   return heading+`<article class="phrase-card"><button type="button" class="phrase-open" data-phrase-open="${x.id}" aria-label="查看话术详情" title="查看全文"><span class="phrase-text-label">原文</span><span class="phrase-original">${highlight(x.content,term)}</span><span class="phrase-text-label">中文翻译</span><span class="phrase-translation">${highlight(x.translation||'暂未填写翻译',term)}</span></button><div class="phrase-card-actions" role="group" aria-label="话术操作"><button type="button" data-phrase-copy="${x.id}" class="phrase-copy-action" aria-label="复制原文" title="复制原文"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="7" width="9" height="10" rx="2"/><path d="M12 7V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h3"/></svg><span>复制原文</span></button>${state.canEdit?`<button type="button" data-phrase-edit="${x.id}" aria-label="编辑话术" title="编辑话术"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12 4 4 4M3 17l4-1L17 6a2.8 2.8 0 0 0-4-4L3 12Z"/></svg></button>${state.ordering?`<button type="button" data-phrase-move="${x.id}" data-direction="-1" ${index===0?'disabled':''} aria-label="上移话术" title="上移话术"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 12 5-5 5 5"/></svg></button><button type="button" data-phrase-move="${x.id}" data-direction="1" ${index===items.length-1?'disabled':''} aria-label="下移话术" title="下移话术"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg></button>`:''}`:''}</div></article>`;
  }).join('')||`<div class="phrase-empty">${term?'没有找到匹配的话术。<button type="button" data-phrase-clear-search>清空搜索</button>':!state.categories.length?'先新增分类，开始整理常用话术。':state.scene?'这个场景还没有话术。':state.selected?'这个分类还没有话术。':'还没有话术，新增一条开始使用。'}</div>`;
  q('[data-phrase-more]').hidden=items.length<=state.limit||state.loading;
  for(const selector of ['[data-phrase-add]','[data-phrase-add-category]']){q(selector).hidden=!state.canEdit;q(selector).disabled=state.loading||state.busy;}
 }
 async function load({quiet=false}={}){
  const project=pid(),identity=JSON.stringify(headers());
  if(project!==state.project||identity!==state.identity){close(true);state.project=project;state.identity=identity;state.categories=[];state.scenes=[];state.items=[];state.selected=0;state.scene=null;state.ordering=false;state.canEdit=false;q('[data-phrase-search]').value='';}
  const scrollTop=q('[data-phrase-scroll]').scrollTop;
  const c={project,identity,version:++state.version};state.loading=!quiet;q('[data-phrase-error]').hidden=true;if(!quiet)render();
  if(!project){state.loading=false;render();return;}
  try{const data=await api(base(c));if(!same(c))return;state.categories=data.categories;state.scenes=data.scenes||[];state.items=data.items;state.canEdit=data.can_edit;if(state.selected&&!cat(state.selected)){state.selected=0;state.scene=null;}if(state.scene&&scene(state.scene)?.category_id!==state.selected)state.scene=null;}
  catch(e){if(same(c)){q('[data-phrase-error]').textContent=e.message;q('[data-phrase-error]').hidden=false;}}
  finally{if(same(c)){state.loading=false;render();q('[data-phrase-scroll]').scrollTop=scrollTop;}}
 }
 function show(mode,title,html,footer,id=0){
  root.querySelectorAll('details[open]').forEach(el=>el.open=false);
  state.opener=document.activeElement;state.panel={mode,id};q('#phrase-dialog-title').textContent=title;body.innerHTML=html;actions.innerHTML=footer;q('[data-phrase-form-error]').hidden=true;state.baseline=snapshot();dialog.append(q('[data-phrase-toast]'));if(!dialog.open)dialog.showModal();body.scrollTop=0;body.querySelector('input,textarea,select')?.focus({preventScroll:true});
 }
 const cancel='<button type="button" data-phrase-close>取消</button>',save='<button type="submit" class="phrase-primary">保存</button>';
 async function exportAll(){
  if(state.exporting||state.busy||state.loading||!state.items.length)return;
  const c=context(),operation={...c};state.exporting=operation;render();
  q('[data-phrase-error]').hidden=true;
  try{
   const response=await fetch(base(c)+'/export/pdf',{headers:headers()});
   if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(data.detail||'导出失败，请重试。');}
   const blob=await response.blob();if(!same(c))return;
   if(!blob.size||!response.headers.get('Content-Type')?.includes('application/pdf'))throw Error('未能生成 PDF，请重试。');
   const match=/filename\*=UTF-8''([^;]+)/i.exec(response.headers.get('Content-Disposition')||'');
   const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;
   try{link.download=match?decodeURIComponent(match[1]):'沟通话术_全部内容.pdf';}catch{link.download='沟通话术.pdf';}
   document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);say('全部话术 PDF 已导出');
  }catch(e){if(same(c)){q('[data-phrase-error]').textContent=e.message;q('[data-phrase-error]').hidden=false;}}
  finally{if(state.exporting===operation){state.exporting=null;render();}}
 }
 async function createInlineScene(){
  if(state.busy||!state.canEdit||state.panel?.mode!=='phrase')return;
  const input=q('[data-phrase-scene-name]'),name=input.value.trim(),categoryId=Number(form.elements.category_id.value);
  if(!name){input.focus();say('请填写场景名称');return;}
  const c=context();state.busy=true;
  dialog.querySelectorAll('button').forEach(button=>button.disabled=true);
  q('[data-phrase-form-error]').hidden=true;
  try{
   const item=await api(base(c)+'/scenes',{method:'POST',body:JSON.stringify({category_id:categoryId,name})});
   if(!same(c))return;
   state.scenes.push(item);
   form.elements.scene_id.innerHTML=sceneOptions(form.elements.category_id.value,Number(form.elements.category_id.value)===categoryId?item.id:null);
   input.value='';q('[data-phrase-inline-create]').hidden=true;form.elements.content.focus();say('场景已创建');
  }catch(e){if(same(c)){q('[data-phrase-form-error]').textContent=e.message;q('[data-phrase-form-error]').hidden=false;}}
  finally{if(same(c)){state.busy=false;dialog.querySelectorAll('button').forEach(button=>button.disabled=false);render();}}
 }
 function closeMenus(except=null){root.querySelectorAll('.phrase-category-menu[open],.phrase-scene-menu[open]').forEach(el=>{if(el!==except)el.open=false;});}
 function positionMenu(details){
  const trigger=details.querySelector('summary'),menu=details.querySelector('div');if(!details.open||!trigger||!menu)return;
  const rect=trigger.getBoundingClientRect(),box=menu.getBoundingClientRect();
  menu.style.left=Math.max(8,Math.min(rect.right-box.width,window.innerWidth-box.width-8))+'px';
  menu.style.top=Math.max(8,rect.bottom+box.height+6<window.innerHeight?rect.bottom+6:rect.top-box.height-6)+'px';
 }
 root.addEventListener('toggle',e=>{if(e.target.matches('.phrase-category-menu,.phrase-scene-menu')&&e.target.open){closeMenus(e.target);positionMenu(e.target);}},true);
 document.addEventListener('click',e=>{if(!e.target.closest('.phrase-category-menu,.phrase-scene-menu'))closeMenus();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!dialog.open)closeMenus();});
 document.addEventListener('scroll',e=>{if(!e.target.closest?.('.phrase-category-menu,.phrase-scene-menu'))closeMenus();},true);
 window.addEventListener('resize',()=>closeMenus());
 function editPhrase(item={}){
  if(!state.canEdit||state.busy)return;
  if(!state.categories.length){say('请先新增分类');editCategory();return;}
  const selected=item.category_id||state.selected||state.categories[0].id;
  show('phrase',item.id?'编辑话术':'新增话术',`<div class="phrase-field-grid"><label>分类<select name="category_id" required>${state.categories.map(x=>`<option value="${x.id}" ${x.id===selected?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label><label>场景<select name="scene_id">${sceneOptions(selected,item.id?item.scene_id:state.scene)}</select></label></div><div class="phrase-inline-scene"><button type="button" class="phrase-text-button" data-phrase-inline-scene>＋ 新增场景</button><div class="phrase-inline-create" data-phrase-inline-create hidden><input type="text" maxlength="180" data-phrase-scene-name aria-label="新场景名称" placeholder="输入新场景名称"><button type="button" data-phrase-create-scene>创建场景</button></div></div><label class="phrase-original-field">原文<textarea name="content" required maxlength="15000" placeholder="填写可直接复制使用的原文。">${esc(item.content)}</textarea></label><label>翻译<textarea name="translation" maxlength="15000" placeholder="填写对应翻译，方便理解和查阅。">${esc(item.translation)}</textarea></label>`,`${item.id?'<button type="button" class="phrase-danger" data-phrase-delete="'+item.id+'">删除话术</button>':''}${cancel}${save}`,item.id);
 }
 function view(item){if(!item)return;show('view','话术详情',`<section class="phrase-read-section"><h4>原文</h4><div class="phrase-original phrase-read-content">${esc(item.content)}</div></section><section class="phrase-read-section"><h4>翻译</h4><div class="phrase-translation phrase-read-content">${esc(item.translation||'暂未填写翻译')}</div></section>`,`<button type="button" data-phrase-close>关闭</button>${state.canEdit?`<button type="button" data-phrase-edit="${item.id}">编辑</button>`:''}${item.translation?`<button type="button" data-phrase-copy="${item.id}" data-copy-translation>复制翻译</button>`:''}<button type="button" class="phrase-primary" data-phrase-copy="${item.id}">复制原文</button>`,item.id);}

 function editCategory(item={}){if(state.canEdit&&!state.busy)show('category',item.id?'修改分类名称':'新增分类',`<label>分类名称<input name="name" maxlength="180" required value="${esc(item.name)}" placeholder="例如：需求确认"></label>`,cancel+save,item.id);}
 function editScene(item={}){if(state.canEdit&&!state.busy&&state.selected)show('scene',item.id?'修改场景名称':'新增场景',`<p class="phrase-scene-context">所属分类：${esc(cat(state.selected)?.name)}</p><label>场景名称<input name="name" maxlength="180" required value="${esc(item.name)}" placeholder="例如：收到询价、缺少图纸、客户嫌贵"></label>`,cancel+save,item.id);}
 function deleteScene(id){const item=scene(id);if(!item||!state.canEdit)return;const count=state.items.filter(x=>x.scene_id===id).length,others=state.scenes.filter(x=>x.category_id===item.category_id&&x.id!==id);show('delete-scene','删除场景',`<p>删除“${esc(item.name)}”${count?`，请选择其中 ${count} 条话术的去向。`:'，此场景当前没有话术。'}</p>${count?others.length?`<label>话术移至<select name="target_id" required>${others.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></label>`:'<p>请先新增其他场景接收话术，或先移出此场景中的话术。</p>':''}`,cancel+(count&&!others.length?'':'<button type="submit" class="phrase-primary">确认删除</button>'),id);}
 function deleteCategory(id){
  const item=cat(id);if(!item||!state.canEdit)return;const count=state.items.filter(x=>x.category_id===id).length,others=state.categories.filter(x=>x.id!==id);
  show('delete-category','删除分类',`<p>删除“${esc(item.name)}”${count?`，其中 ${count} 条话术将移到其他分类。`:'，此分类当前没有话术。'}</p>${count?others.length?`<label>话术移至<select name="target_id" required>${others.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></label>`:'<p>请先新增其他分类，或先删除此分类中的话术。</p>':''}`,cancel+(count&&!others.length?'':'<button type="submit" class="phrase-primary">确认删除</button>'),id);
 }
 async function copy(id,translation=false){const item=state.items.find(x=>x.id===id);if(!item)return;const text=translation?item.translation:item.content;if(!text)return;try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);else{const box=document.createElement('textarea');box.value=text;box.style.cssText='position:fixed;left:-9999px';(dialog.open?dialog:root).append(box);box.select();const ok=document.execCommand('copy');box.remove();if(!ok)throw Error();}say(translation?'翻译已复制':'原文已复制');}catch{say('复制失败，请选中正文手动复制');}}
 async function mutate(path,method,payload){
  if(state.busy||!state.canEdit)return;const c=context();state.busy=true;root.querySelectorAll('button').forEach(b=>b.disabled=true);q('[data-phrase-form-error]').hidden=true;
  try{await api(base(c)+path,{method,...(payload?{body:JSON.stringify(payload)}:{})});if(!same(c))return;if(payload?.category_id&&/^\/items(?:\/\d+)?$/.test(path)&&((state.selected&&state.selected!==payload.category_id)||(state.scene!==null&&state.scene!==(payload.scene_id??0)))){state.selected=payload.category_id;state.scene=payload.scene_id??0;state.ordering=false;state.limit=40;}close(true);await load({quiet:true});if(c.project===state.project)say('已保存');}
  catch(e){if(same(c)){const el=dialog.open?q('[data-phrase-form-error]'):q('[data-phrase-error]');el.textContent=e.message;el.hidden=false;}}
  finally{if(c.project===state.project&&c.identity===state.identity){state.busy=false;root.querySelectorAll('button').forEach(b=>b.disabled=false);render();}}
 }
 form.addEventListener('change',e=>{if(state.panel?.mode==='phrase'&&e.target.name==='category_id'){form.elements.scene_id.innerHTML=sceneOptions(e.target.value);q('[data-phrase-scene-name]').value='';q('[data-phrase-inline-create]').hidden=true;}});
 form.addEventListener('submit',e=>{e.preventDefault();if(state.busy)return;const p=state.panel,data=Object.fromEntries(new FormData(form));if(p.mode==='phrase')mutate('/items'+(p.id?'/'+p.id:''),p.id?'PUT':'POST',{...data,category_id:Number(data.category_id),scene_id:Number(data.scene_id)||null});if(p.mode==='category')mutate('/categories'+(p.id?'/'+p.id:''),p.id?'PUT':'POST',data);if(p.mode==='scene')mutate('/scenes'+(p.id?'/'+p.id:''),p.id?'PUT':'POST',p.id?data:{...data,category_id:state.selected});if(p.mode==='delete-scene')mutate(`/scenes/${p.id}${data.target_id?'?target_id='+Number(data.target_id):''}`,'DELETE');if(p.mode==='delete-category')mutate(`/categories/${p.id}${data.target_id?'?target_id='+Number(data.target_id):''}`,'DELETE');});
 root.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b||state.busy)return;
  if(b.hasAttribute('data-phrase-close'))close();
  if(b.hasAttribute('data-phrase-sort')){state.ordering=!state.ordering;render();}
  if(b.hasAttribute('data-phrase-export'))exportAll();
  if(b.hasAttribute('data-phrase-clear-search')){q('[data-phrase-search]').value='';state.limit=40;render();q('[data-phrase-search]').focus();}
  if(b.hasAttribute('data-phrase-inline-scene')){q('[data-phrase-inline-create]').hidden=false;q('[data-phrase-scene-name]').focus();}
  if(b.hasAttribute('data-phrase-create-scene'))createInlineScene();
  if(b.hasAttribute('data-phrase-category')){state.selected=Number(b.dataset.phraseCategory);state.scene=null;state.ordering=false;state.limit=40;render();q('[data-phrase-scroll]').scrollTop=0;}
  if(b.hasAttribute('data-phrase-scene')){state.scene=Number(b.dataset.phraseScene);state.ordering=false;state.limit=40;render();q('[data-phrase-scroll]').scrollTop=0;}
  if(b.hasAttribute('data-phrase-add-scene'))editScene();
  if(b.hasAttribute('data-scene-edit'))editScene(scene(b.dataset.sceneEdit));
  if(b.hasAttribute('data-scene-delete'))deleteScene(Number(b.dataset.sceneDelete));
  if(b.hasAttribute('data-scene-move')){const ids=state.scenes.filter(x=>x.category_id===state.selected).map(x=>x.id),i=ids.indexOf(Number(b.dataset.sceneMove)),j=i+Number(b.dataset.step);if(j>=0&&j<ids.length){[ids[i],ids[j]]=[ids[j],ids[i]];mutate('/scenes/order','PUT',{category_id:state.selected,ids});}}
  if(b.hasAttribute('data-phrase-add-category'))editCategory();
  if(b.hasAttribute('data-phrase-add'))editPhrase();
  if(b.hasAttribute('data-phrase-open')&&!window.getSelection()?.toString())view(state.items.find(x=>x.id===Number(b.dataset.phraseOpen)));
  if(b.hasAttribute('data-phrase-move'))mutate('/items/'+Number(b.dataset.phraseMove)+'/move','POST',{direction:Number(b.dataset.direction),category_id:state.selected||null,scene_id:state.scene});
  if(b.hasAttribute('data-phrase-copy'))copy(Number(b.dataset.phraseCopy),b.hasAttribute('data-copy-translation'));
  if(b.hasAttribute('data-phrase-edit'))editPhrase(state.items.find(x=>x.id===Number(b.dataset.phraseEdit)));
  if(b.hasAttribute('data-phrase-delete')&&confirm('确认删除这条话术？'))mutate('/items/'+Number(b.dataset.phraseDelete),'DELETE');
  if(b.hasAttribute('data-cat-edit'))editCategory(cat(b.dataset.catEdit));
  if(b.hasAttribute('data-cat-delete'))deleteCategory(Number(b.dataset.catDelete));
  if(b.hasAttribute('data-cat-move')){const ids=state.categories.map(x=>x.id),i=ids.indexOf(Number(b.dataset.catMove)),j=i+Number(b.dataset.step);if(j>=0&&j<ids.length){[ids[i],ids[j]]=[ids[j],ids[i]];mutate('/categories/order','PUT',{ids});}}
  if(b.hasAttribute('data-phrase-more')){state.limit+=40;render();}
 });
 q('[data-phrase-search]').addEventListener('input',()=>{state.ordering=false;state.limit=40;render();q('[data-phrase-scroll]').scrollTop=0;});
 dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 window.addEventListener('beforeunload',e=>{if(dirty()||state.busy){e.preventDefault();e.returnValue='';}});
 document.addEventListener('click',e=>{if(dialog.open&&e.target.closest('.global-nav-item,.crm-primary-item,.pm-project-row')&&!close()){e.preventDefault();e.stopImmediatePropagation();}},true);
 const invalidate=()=>{state.version++;close(true);state.busy=false;state.exporting=null;state.project=0;state.items=[];state.categories=[];state.scenes=[];state.selected=0;state.scene=null;state.ordering=false;state.canEdit=false;render();if(!root.hidden)load();};
 window.addEventListener('tophoo-project-changed',invalidate);document.addEventListener('tophoo-auth-changed',invalidate);
 document.addEventListener('tophoo-communication-phrases-view',load);
})();
