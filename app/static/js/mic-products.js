(() => {
  const host=document.querySelector('[data-module="mic-products"]');if(!host)return;
  const $=selector=>host.querySelector(selector),form=$('#mic-form'),editor=$('#mic-editor');
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const socialPlatforms={linkedin:'领英',facebook:'Facebook',instagram:'Instagram',youtube:'YouTube'};
  const socialEditor=$('#mic-social-editor');
  const micAssistant=$('#mic-status-filter').closest('details');
  let socialPlatform='',socialStatus='';
  const statusLabels={pending:'待发布',publishing:'正在发布',optimizing:'待优化',published:'已发布'};
  const project=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||null;
  let version=0,sequence=0,page=1,pages=1,active=null,editorContext=null,initial='',busy=false,pendingImage=null,imageRemoved=false,previewUrl='',timer,messageTimer;
  const pageSizeKey=()=>`tophoo-mic-page-size:${window.tophooAuth?.currentUser?.()?.id||'local'}`;
  function savedPageSize(){const value=Number(localStorage.getItem(pageSizeKey()));return Number.isInteger(value)&&value>=1&&value<=100?value:10;}
  let pageSize=savedPageSize();$('#mic-page-size').value=pageSize;
  const sortOrderKey=()=>`tophoo-mic-sort-order:${window.tophooAuth?.currentUser?.()?.id||'local'}`;
  const savedSortOrder=()=>localStorage.getItem(sortOrderKey())==='asc'?'asc':'desc';
  let sortOrder=savedSortOrder();
  function renderSortOrder(){const button=$('#mic-sort-order'),descending=sortOrder==='desc',state=descending?'倒序':'正序',next=descending?'正序':'倒序';button.dataset.order=sortOrder;button.setAttribute('aria-pressed',String(descending));button.setAttribute('aria-label',`编号${state}，点击切换为${next}`);button.title=`当前：编号${state}；点击切换为${next}`;}
  renderSortOrder();
  $('#mic-sort-order').onclick=()=>{sortOrder=sortOrder==='desc'?'asc':'desc';renderSortOrder();localStorage.setItem(sortOrderKey(),sortOrder);page=1;clearTimeout(timer);load();};

  const nameViewKey=()=>`tophoo-mic-name-view:${window.tophooAuth?.currentUser?.()?.id||'local'}`;
  const savedNameView=()=>['published','unpublished','optimizing'].includes(localStorage.getItem(nameViewKey()))?localStorage.getItem(nameViewKey()):'all';
  let nameView=savedNameView();$('#mic-name-view').value=nameView;
  const progressBusy=new Set(),optimizationBusy=new Set();
  function numberParts(value){const match=String(value||'').toLowerCase().match(/^([a-z]*)(\d+)$/);return match?{prefix:match[1],number:Number(match[2])}:null;}
  function titlePublished(name,item){const code=numberParts(name.code),through=numberParts(item.published_through);return Boolean(code&&through&&code.prefix===through.prefix&&code.number<=through.number);}
  const snapshot=()=>({id:project(),version,token:window.tophooAuth?.token?.(),user:window.tophooAuth?.currentUser?.()?.id});
  const current=ctx=>ctx&&ctx.id===project()&&ctx.version===version&&ctx.token===window.tophooAuth?.token?.()&&ctx.user===window.tophooAuth?.currentUser?.()?.id;
  const api=(ctx,suffix='')=>`/api/mic-products/projects/${ctx.id}${suffix}`;
  const placeholder='<span class="mic-image-placeholder" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m4 18 5-5 4 4 3-3 5 5"/></svg></span>';
  function say(text,error=false){clearTimeout(messageTimer);$('#mic-message').textContent=text;$('#mic-message').hidden=!text;$('#mic-message').classList.toggle('is-error',error);if(text)messageTimer=setTimeout(()=>$('#mic-message').hidden=true,5000);}
  function error(text=''){$('#mic-editor-error').textContent=text;$('#mic-editor-error').hidden=!text;}
  async function request(url,options={}){const response=await fetch(url,{...options,headers:{...(window.tophooAuth?.headers?.()||{}),...(options.headers||{})}});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'请检查填写内容后重试。');return data;}
  function catalogueFilters(){
    const micOnly = micAssistant.open;
    return {q:$('#mic-search').value.trim(),status:micOnly?$('#mic-status-filter').value:'',
      title_state:micOnly&&nameView!=='all'?nameView:'',mic_only:micOnly,
      social_platform:socialPlatform,social_status:socialStatus,sort_order:sortOrder};
  }
  const write=(method,data)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function payload(){return {product_code:form.elements.product_code.value.trim(),record_code:form.elements.record_code.value.trim(),published_through:form.elements.published_through.value.trim(),product_name:form.elements.product_name.value.trim(),english_title:form.elements.english_title.value.trim(),seo_description:form.elements.seo_description.value.trim(),content:form.elements.content.value.trim(),titles:[...$('#mic-name-fields').querySelectorAll('.mic-name-row')].map(row=>{const title=row.querySelector('textarea[data-code]');return {...(title.dataset.socialId?{social_id:title.dataset.socialId}:{}),code:title.dataset.code||'',title:title.value.trim(),optimization_suggestion:row.querySelector('[data-mic-suggestion]').value.trim(),core_keywords:[...row.querySelectorAll('[data-core-keyword]')].map(field=>field.value.trim()).filter(Boolean)};}).filter(item=>item.title||item.optimization_suggestion||item.core_keywords.length)};}
  const keywordWords=value=>value.match(/[A-Za-z0-9]+(?:['’][A-Za-z]+)?/g)||[];
  function keywordError(values){
    if(!values.length)return '';
    if(values.length!==10)return '每个标题需填写 10 个核心关键词；未配置时可全部留空。';
    const seen=new Set();
    for(let i=0;i<values.length;i++){
      const value=values[i],words=keywordWords(value),key=words.join(' ').toLowerCase();
      if(value.length>160||! /^[A-Za-z0-9 /'’.-]+$/.test(value)||!/[A-Za-z]/.test(value))return `第 ${i+1} 个关键词请填写英文产品词。`;
      if(words.length>4)return `第 ${i+1} 个关键词超过 4 个单词。`;
      if(seen.has(key))return '同一标题的核心关键词不能重复。';seen.add(key);
    }
    return '';
  }
  function updateKeywordFields(row){
    const fields=[...row.querySelectorAll('[data-core-keyword]')],values=fields.map(f=>f.value.trim()).filter(Boolean);
    row.querySelector('[data-keyword-count]').textContent=values.length+' / 10';
    row.querySelector('[data-keyword-count]').classList.toggle('is-complete',values.length===10&&!keywordError(values));
    fields.forEach(field=>field.setAttribute('aria-invalid',String(Boolean(field.value.trim()&&keywordWords(field.value).length>4))));
  }
  function keywordEditor(name){return `<details class="mic-keyword-editor"><summary>核心关键词 <span data-keyword-count>${(name.core_keywords||[]).length} / 10</span><small>前三个优先</small></summary><p class="mic-field-hint">每个词最多 4 个英文单词，按重要性排序。暂未配置可全部留空，填写后需满 10 个。</p><div class="mic-keyword-grid">${Array.from({length:10},(_,i)=>`<div class="mic-keyword-field ${i<3?'is-priority':''}"><label><span>${i+1}${i<3?' · 重点':''}</span><input data-core-keyword maxlength="160" aria-label="核心关键词 ${i+1}" value="${esc(name.core_keywords?.[i]||'')}" placeholder="${i<3?'最能代表产品本身的词':'相关材质、类型或应用词'}"></label><div><button type="button" data-keyword-move="-1" aria-label="关键词 ${i+1} 上移" ${i===0?'disabled':''}>↑</button><button type="button" data-keyword-move="1" aria-label="关键词 ${i+1} 下移" ${i===9?'disabled':''}>↓</button></div></div>`).join('')}</div></details>`;}
  function keywordView(name){const values=name.core_keywords||[];return `<details class="mic-keyword-view"><summary>核心关键词 <span>${values.length} / 10</span><small>前三个优先</small></summary>${values.length?`<ol>${values.map((value,i)=>`<li class="${i<3?'is-priority':''}"><span>${i+1}</span>${esc(value)}</li>`).join('')}</ol>`:'<p class="mic-field-hint">尚未配置，点击“编辑名称、关键词与建议”补充。</p>'}</details>`;}
  function updateEditorStatus(){const value=form.elements.published_through.value.trim().toLowerCase(),range=form.elements.product_code.value.trim().toLowerCase().match(/^([a-z]*)(\d+)(?:-([a-z]*)(\d+))?$/),number=value.match(/^([a-z]*)(\d+)$/);const complete=range&&number&&(!number[1]||number[1]===range[1])&&Number(number[2])===Number(range[4]||range[2]);const status=!value?'pending':complete?(payload().titles.some(item=>item.optimization_suggestion.trim())?'optimizing':'published'):'publishing';$('#mic-editor-status').textContent=statusLabels[status];$('#mic-editor-status').className=status;}

  const dirty=()=>editor.open&&(JSON.stringify(payload())!==initial||pendingImage||imageRemoved);
  function renderDashboard(data){
    const dashboard=data.dashboard||{total:data.total,categories:[],labels:[]},status=$('#mic-status-filter').value;
    const counts=dashboard.titles||{total:0,published:0,unpublished:0};
    $('.mic-status-all').setAttribute('aria-pressed',String(nameView==='all'));$('.mic-status-all').textContent=`全部 ${counts.total} 个标题`;
    $('#mic-label-summary').innerHTML=['published','unpublished','optimizing'].map(state=>`<button type="button" class="mic-title-stat ${state}" data-title-state="${state}" aria-pressed="${nameView===state}"><span class="mic-label-dot"></span><span>${state==='optimizing'?'待优化标题':state==='published'?'已发布':'未发布'}</span><strong>${counts[state]??0}</strong><small>个标题</small></button>`).join('');
    $('.mic-group-status-all').textContent=`全部 ${dashboard.mic_total ?? dashboard.total} 组`;$('.mic-group-status-all').setAttribute('aria-pressed',String(!status));
    $('#mic-group-status-summary').innerHTML=(dashboard.labels||[]).map(item=>`<button type="button" class="${item.status}" data-mic-status="${item.status}" aria-pressed="${status===item.status}" aria-label="${esc(item.name)}，${item.count} 组产品"><span class="mic-label-dot"></span><span>${esc(item.name)}</span><strong>${item.count}</strong><small>组</small></button>`).join('');
    $('.mic-social-all').setAttribute('aria-pressed',String(!socialPlatform));
    $('#mic-social-summary').innerHTML=(dashboard.social||[]).map(item=>`<div class="mic-social-filter-group"><span>${esc(socialPlatforms[item.platform])}</span>${['unpublished','published'].map(state=>`<button type="button" class="${state}" data-social-filter="${item.platform}" data-social-status="${state}" aria-label="${esc(socialPlatforms[item.platform])}${state==='published'?'已发布':'未发布'}，${item[state]} 个产品" aria-pressed="${socialPlatform===item.platform&&socialStatus===state}">${state==='published'?'已发布':'未发布'} <strong>${item[state]}</strong></button>`).join('')}</div>`).join('');
    const filters=micAssistant.open?['已分配 MIC 编号',statusLabels[status]].filter(Boolean):[];
    if(micAssistant.open&&nameView!=='all')filters.push(nameView==='optimizing'?'待优化标题':nameView==='published'?'已发布标题':'未发布标题');if(socialPlatform)filters.push(socialPlatforms[socialPlatform]+' · '+(socialStatus==='published'?'已发布':'未发布'));if($('#mic-search').value.trim())filters.push('搜索：'+$('#mic-search').value.trim());$('#mic-active-filters').textContent=filters.join(' / ');
  }
    const titleBadge=name=>name.optimization_suggestion?'<small class="mic-title-badge pending">待优化</small>':name.review_status?`<small class="mic-title-badge ${esc(name.review_status)}">${name.review_status==='optimized'?'已优化':name.review_status==='corrected'?'已修正':name.review_status==='pending'?'待确认':'已编辑'}</small>`:'';
  function optimizationView(name){
    const note=String(name.optimization_suggestion||'').trim();if(!note)return '<span class="mic-suggestion-empty">—</span>';
    const title=note.match(/^(?:建议标题|优化标题|新标题)[：:]\s*(.+)$/m)?.[1]?.trim()||name.suggested_title||'';
    const same=title&&title.toLowerCase().replace(/[^a-z0-9]+/g,'')===String(name.title||'').toLowerCase().replace(/[^a-z0-9]+/g,'');
    return `${same?'<p class="mic-suggestion-applied">当前标题已与建议一致，核对平台后可清除此建议。</p>':title?`<div class="mic-suggested-title"><small>建议标题</small><p>${esc(title)}</p><button type="button" class="mic-title-copy" data-copy-suggested-title="${esc(title)}">复制新标题</button></div>`:''}<details class="mic-suggestion-details"><summary>查看修改说明</summary><p>${esc(note)}</p></details><button type="button" class="mic-mark-published" data-complete-title-optimization title="将建议标题保存为当前标题，并清除此条优化建议">已优化</button>`;
  }
    const titleLine=(name,item,nextCode)=>{const published=titlePublished(name,item),next=!published&&name.code===nextCode;return `<li class="mic-name-pair ${published?'is-title-published':'is-title-unpublished'} ${next?'is-next-title':''}" data-title-code="${esc(name.code||'')}" data-title-published="${published}"><div class="mic-name-pair-title"><div class="mic-code-status"><code>${esc(name.code||'未编号')}</code><span class="mic-name-state">${published?'✓ 已发布':next?'● 下一条':'未发布'}</span></div><span class="mic-title-content"><span class="mic-title-text">${esc(name.title)}</span>${titleBadge(name)}</span><div class="mic-title-actions"><button type="button" class="mic-title-copy" data-copy-title aria-label="复制 ${esc(name.code||'MIC名称')} 的标题" title="复制标题"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/></svg><span>复制标题</span></button><button type="button" class="mic-title-keywords" data-copy-keywords ${(name.core_keywords||[]).length!==10?'disabled':''}>复制关键词</button><button type="button" class="mic-mark-published" ${published||!numberParts(name.code)?'disabled':''} data-publish-title="${esc(name.code)}" aria-label="登记已发布到 ${esc(name.code)}" title="实际发布后点击，将本地进度登记到此编号">${published?'已发布':'标为已发'}</button></div></div><div class="mic-name-pair-suggestion">${optimizationView(name)}</div>${keywordView(name)}</li>`;};
  const emptyRow=text=>`<tr><td colspan="5" class="mic-empty">${esc(text)}</td></tr>`;
  function render(data){
    
    page=data.page;pages=data.pages;
    pageSize=data.page_size||pageSize;$('#mic-page-size').value=pageSize;
    $('#mic-source-details').hidden=!data.source_notice;$('#mic-source-notice').hidden=!data.source_notice;$('#mic-source-notice').textContent=data.source_notice?'原目录说明：'+data.source_notice:'';
    renderDashboard(data);
    const writable=canEditRecords();
    $('#mic-list').innerHTML=data.items.length?data.items.map(item=>`<tr data-mic-id="${item.id}">
      <td>${item.images[0]?`<img class="mic-record-image" src="${esc(item.images[0].thumbnail_url)}" loading="lazy" alt="">`:'<span class="mic-record-no-image">—</span>'}</td>
      <td>${item.record_code?`<code>${esc(item.record_code)}</code>`:'—'}</td>
      <td><strong class="mic-record-name">${esc(item.product_name||'—')}</strong></td>
      <td><strong class="mic-seo-title">${esc(item.english_title||'—')}</strong>${item.seo_description?`<p class="mic-seo-description" title="${esc(item.seo_description)}">${esc(item.seo_description)}</p>`:''}</td>
      <td><div class="mic-record-actions"><button type="button" class="mic-edit-button" data-mic-open-record="${item.id}">${writable?'编辑':'查看'}</button>${writable?`<button type="button" class="mic-delete-button" data-mic-remove-record="${item.id}" ${pendingDeletes.has(item.id)?'disabled':''}>删除</button>`:''}</div></td>
    </tr>`).join(''):emptyRow('暂无匹配产品。');
    $('.mic-table-scroll').scrollTop=0;
    $('#mic-result-count').textContent=`共 ${data.total} 个产品`;$('#mic-page').textContent=`${page} / ${pages}`;$('#mic-prev').disabled=page<=1;$('#mic-next').disabled=page>=pages;
  }
  const titlesDialog=$('#mic-titles-dialog');
  let titlesActive=null,titlesContext=null,titlesView='all',titlesSequence=0;
  function renderTitles(){
    if(!titlesActive)return;const item=titlesActive,region=$('#mic-titles-body'),scroll=region.scrollTop;
    const published=item.titles.filter(name=>titlePublished(name,item)).length,shown=item.titles.filter(name=>titlesView==='optimizing'?Boolean(name.optimization_suggestion?.trim()):titlesView==='all'||titlePublished(name,item)===(titlesView==='published'));
    const suggestions=shown.some(name=>name.optimization_suggestion),nextCode=item.titles.find(name=>!titlePublished(name,item))?.code;
    $('#mic-titles-title').textContent=item.product_code+' · MIC名称';$('#mic-titles-product').textContent=item.product_name||'';
    $('#mic-titles-counts').textContent=`共 ${item.titles.length} 条 · 已发 ${published} · 未发 ${item.titles.length-published} · 待优化 ${item.titles.filter(name=>name.optimization_suggestion?.trim()).length}`;
    region.innerHTML=`<div class="mic-product-card mic-titles-surface"><div class="mic-names-cell ${suggestions?'has-suggestions':''}"><div class="mic-card-columns"><div>MIC名称</div>${suggestions?'<div>优化建议</div>':''}</div>${!shown.length?'<p class="mic-all-published">当前条件下没有标题，可切换“全部名称”查看。</p>':''}<ol class="mic-title-list">${shown.map(name=>titleLine(name,item,nextCode)).join('')}</ol></div></div>`;
    region.scrollTop=scroll;
    if(optimizationBusy.has(item.id))titlesDialog.querySelectorAll('[data-complete-title-optimization]').forEach(el=>el.disabled=true);
    if(progressBusy.has(item.id))titlesDialog.querySelectorAll('[data-publish-title]').forEach(el=>el.disabled=true);
  }
  function closeTitles(){titlesSequence++;titlesDialog.close();titlesActive=null;titlesContext=null;delete titlesDialog.dataset.titleProduct;$('#mic-titles-body').innerHTML='';$('#mic-titles-feedback').textContent='';$('#mic-titles-error').hidden=true;}
  async function openTitles(id){const ctx=snapshot(),seq=++titlesSequence;if(!ctx.id||editor.open||socialEditor.open||titlesDialog.open)return;try{const item=await request(api(ctx,`/${id}`));if(!current(ctx)||seq!==titlesSequence||editor.open||socialEditor.open||titlesDialog.open)return;titlesActive=item;titlesContext=ctx;titlesView=nameView;$('#mic-titles-view').value=titlesView;titlesDialog.dataset.titleProduct=item.id;renderTitles();titlesDialog.showModal();$('#mic-titles-body').scrollTop=0;}catch(e){if(current(ctx)&&seq===titlesSequence)say(e.message,true);}}

  $('#mic-titles-view').onchange=()=>{titlesView=$('#mic-titles-view').value;renderTitles();$('#mic-titles-body').scrollTop=0;};
  host.querySelectorAll('[data-titles-close]').forEach(button=>button.onclick=closeTitles);
  titlesDialog.addEventListener('cancel',event=>{event.preventDefault();closeTitles();});
  $('#mic-titles-edit').onclick=()=>{const id=titlesActive?.id,ctx=titlesContext;closeTitles();if(id&&current(ctx))open(id,"mic");};
  async function saveProgress(card,value){
    const id=Number(card.dataset.micId||card.dataset.titleProduct),ctx=snapshot();if(!ctx.id||progressBusy.has(id))return;
    progressBusy.add(id);card.querySelectorAll('[data-publish-title]').forEach(el=>el.disabled=true);
    try{const saved=await request(api(ctx,`/${id}/progress`),write('PUT',{published_through:value}));if(!current(ctx))return;if(titlesDialog.open&&titlesActive?.id===id){Object.assign(titlesActive,saved);renderTitles();$('#mic-titles-feedback').textContent='发布进度已更新';$('#mic-titles-error').hidden=true;}say(value?'已登记发布进度，标题状态已更新。':'发布进度已清空。');await load({preserveScroll:true,anchorId:id});}
    catch(e){if(current(ctx)){say(e.message,true);if(titlesDialog.open&&titlesActive?.id===id){$('#mic-titles-error').textContent=e.message;$('#mic-titles-error').hidden=false;}}}
    finally{progressBusy.delete(id);if(card.isConnected)card.querySelectorAll('[data-publish-title]').forEach(el=>el.disabled=false);if(titlesDialog.open&&titlesActive?.id===id)titlesDialog.querySelectorAll('[data-publish-title]').forEach(el=>el.disabled=false);}
  }
  async function completeTitleOptimization(button){
    const item=titlesActive,ctx=titlesContext,row=button.closest('[data-title-code]');if(!item||!row||!current(ctx)||optimizationBusy.has(item.id))return;
    const name=item.titles.find(entry=>(entry.code||'')===row.dataset.titleCode&&entry.title===row.querySelector('.mic-title-text').textContent);if(!name?.optimization_suggestion)return;
    optimizationBusy.add(item.id);titlesDialog.querySelectorAll('[data-complete-title-optimization]').forEach(el=>el.disabled=true);$('#mic-titles-error').hidden=true;
    try{
      const saved=await request(api(ctx,`/${item.id}/titles/complete-optimization`),write('POST',{code:name.code||'',expected_title:name.title,expected_suggestion:name.optimization_suggestion}));
      if(!current(ctx))return;
      if(titlesDialog.open&&titlesActive?.id===item.id){Object.assign(titlesActive,saved);renderTitles();$('#mic-titles-feedback').textContent='已优化，建议已清除';}
      say('已保存优化后的标题，并清除此条建议。');await load({preserveScroll:true,anchorId:item.id});
    }catch(error){if(current(ctx)){say(error.message,true);if(titlesDialog.open&&titlesActive?.id===item.id){$('#mic-titles-error').textContent=error.message;$('#mic-titles-error').hidden=false;}}}
    finally{optimizationBusy.delete(item.id);if(titlesDialog.open&&titlesActive?.id===item.id)titlesDialog.querySelectorAll('[data-complete-title-optimization]').forEach(el=>el.disabled=false);}
  }
  host.addEventListener('click',async event=>{
    const complete=event.target.closest('[data-complete-title-optimization]');if(complete){await completeTitleOptimization(complete);return;}
    const mark=event.target.closest('[data-publish-title]');if(mark){await saveProgress(mark.closest('[data-mic-id],[data-title-product]'),mark.dataset.publishTitle);return;}
    const toggle=event.target.closest('[data-toggle-suggestion]');
    if(toggle){const expanded=toggle.getAttribute('aria-expanded')!=='true';toggle.setAttribute('aria-expanded',String(expanded));toggle.closest('.mic-name-pair-suggestion').classList.toggle('is-expanded',expanded);toggle.innerHTML=expanded?'收起建议 <span aria-hidden="true">⌃</span>':'展开建议 <span aria-hidden="true">⌄</span>';return;}
    const button=event.target.closest('[data-copy-title],[data-copy-keywords],[data-copy-suggested-title]');if(!button)return;
    const keywords=button.hasAttribute('data-copy-keywords'),suggested=button.hasAttribute('data-copy-suggested-title'),text=suggested?button.dataset.copySuggestedTitle:keywords?[...button.closest('.mic-name-pair').querySelectorAll('.mic-keyword-view li')].map(li=>li.lastChild.textContent).join('\n'):button.closest('.mic-name-pair-title').querySelector('.mic-title-text').textContent,ctx=snapshot();
    try{await navigator.clipboard.writeText(text);}catch(e){
      const field=document.createElement('textarea');field.value=text;field.setAttribute('readonly','');field.style.cssText='position:fixed;top:0;left:-9999px';(button.closest('dialog')||document.body).append(field);field.select();let copied=false;try{copied=document.execCommand('copy');}catch(ignore){}finally{field.remove();button.focus({preventScroll:true});}
      if(!copied){if(current(ctx))say('自动复制未成功，请选中标题后复制。',true);return;}
    }
    if(current(ctx)){const label=button.querySelector('span')||button;label.textContent='已复制';if(titlesDialog.open)$('#mic-titles-feedback').textContent=keywords?'关键词已按顺序复制':'标题已复制，发布进度未改变';say(keywords?'核心关键词已复制。':'MIC名称已复制。');setTimeout(()=>{if(button.isConnected)label.textContent=suggested?'复制新标题':keywords?'复制关键词':'复制标题';},1800);}
  });
  async function load({jump=false,preserveScroll=false,anchorId=null}={}){const region=$('.mic-table-scroll'),oldScroll=region.scrollTop,anchor=anchorId?$(`[data-mic-id="${anchorId}"]`):null,oldTop=anchor?.getBoundingClientRect().top;const ctx=snapshot(),seq=++sequence;if(!ctx.id)return;$('#mic-list').setAttribute('aria-busy','true');try{const data=await request(api(ctx,'?'+new URLSearchParams({...catalogueFilters(),page,page_size:pageSize})));if(current(ctx)&&seq===sequence){render(data);if(preserveScroll){const updated=anchorId?$(`[data-mic-id="${anchorId}"]`):null;region.scrollTop=updated&&oldTop!==undefined?updated.getBoundingClientRect().top-oldTop:oldScroll;}if(jump){$('#mic-list-anchor').focus({preventScroll:true});$('.mic-table-scroll').scrollTop=0;}}}catch(e){if(current(ctx)&&seq===sequence){say(e.message,true);$('#mic-list').innerHTML=emptyRow('加载失败，请重试。');}}finally{if(current(ctx)&&seq===sequence){$('#mic-list').removeAttribute('aria-busy');}}}
  function clearPreview(){if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl='';}}
  function renderImage(){const image=pendingImage?{thumbnail_url:previewUrl}:(!imageRemoved?active?.images?.[0]:null);$('#mic-image-preview').innerHTML=image?`<img src="${esc(image.thumbnail_url)}" alt="产品图片预览">`:`${placeholder}<span>添加一张产品图片</span>`;$('#mic-remove-image').hidden=!image;}
  function countNames(){const rows=[...$('#mic-name-fields').querySelectorAll('.mic-name-row')];$('#mic-name-count').textContent=`${rows.length} / ${Math.max(10,active?.titles?.length||0)}`;rows.forEach((row,index)=>{row.querySelector('label>span').textContent=row.querySelector('textarea').dataset.code||`名称 ${index+1}`;row.querySelector('[data-remove-name]').disabled=false;});$('#mic-add-name').disabled=rows.length>=10;showMissingCodes();updateEditorStatus();}
  function editorCodes() {
    const range = form.elements.product_code.value.trim().toLowerCase()
      .match(/^([a-z]*)(\d+)(?:\s*[-~～—–至]\s*([a-z]*)(\d+))?$/);
    if (!range || (range[3] && range[1] !== range[3])) return [];
    const start = Number(range[2]), end = Number(range[4] || range[2]);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || end < start || end - start > 1000) return [];
    const used = new Set([...$('#mic-name-fields').querySelectorAll('textarea[data-code]')]
      .map(field => field.dataset.code.toLowerCase()));
    return Array.from({length:end - start + 1}, (_, offset) => range[1] + (start + offset))
      .filter(code => !used.has(code));
  }
  function showMissingCodes() {
    const field = $('#mic-missing-note');
    const missing = editorCodes();
    field.hidden = !missing.length;
    field.textContent = missing.length ? '该编号范围暂缺：' + missing.join('、') + '。未自动补造名称。' : '';
  }
  function fitName(field){field.style.height='auto';field.style.height=Math.min(180,Math.max(56,field.scrollHeight))+'px';}
  form.addEventListener('input',event=>{if(event.target.matches('[data-core-keyword]')){updateKeywordFields(event.target.closest('.mic-name-row'));error();}if(event.target.matches('[name=published_through],[name=product_code]'))updateEditorStatus();if(event.target.matches('#mic-name-fields textarea')){fitName(event.target);updateEditorStatus();}});
  function addName(name={code:'',title:'',optimization_suggestion:''}){const row=document.createElement('div');row.className='mic-name-row';const status=name.review_status==='corrected'?'已按目录修正':name.review_status==='pending'?'待确认':'已编辑';const history=name.original_title?`<details class="mic-title-history"><summary>${status} · 查看原文</summary><p><strong>原名称：</strong>${esc(name.original_title)}</p>${name.correction_note?`<p>${esc(name.correction_note)}</p>`:''}${name.suggested_title?`<p><strong>目录建议：</strong>${esc(name.suggested_title)}</p>`:''}</details>`:'';row.innerHTML=`<div class="mic-name-content"><div class="mic-name-inputs"><label><span>${esc(name.code||'MIC名称')}</span><textarea rows="2" maxlength="1000" data-code="${esc(name.code||'')}" data-social-id="${esc(name.social_id||'')}" aria-label="MIC名称">${esc(name.title||'')}</textarea></label><label class="mic-suggestion-label"><span>MIC名称优化建议</span><textarea rows="2" maxlength="4000" data-mic-suggestion aria-label="MIC名称优化建议" placeholder="填写需要优化的内容；无建议留空">${esc(name.optimization_suggestion||'')}</textarea></label></div>${keywordEditor(name)}${history}</div><button type="button" data-remove-name aria-label="移除此名称">×</button>`;$('#mic-name-fields').append(row);updateKeywordFields(row);countNames();if(editor.open)row.querySelectorAll('textarea').forEach(fitName);return row;}

  function nextCode(){return editorCodes()[0] || '';}
  function close(force=false){if(!force&&(busy||window.TophooMicSocial?.busy()||((dirty()||socialDirty())&&!confirm('产品记录尚有未保存的修改，确认关闭？'))))return false;closeSocial(true);editor.close();active=null;editorContext=null;pendingImage=null;imageRemoved=false;initial='';busy=false;$('#mic-record-feedback').textContent='';clearPreview();form.reset();$('#mic-name-fields').innerHTML='';$('#mic-image-preview').innerHTML='';$('#mic-image-upload').value='';error();return true;}
  async function open(id,tab="product"){const ctx=snapshot();if(!ctx.id)return say('请先选择项目。',true);if(editor.open||titlesDialog.open||socialEditor.open)return;try{const item=id?await request(api(ctx,`/${id}`)):{titles:[],images:[]};if(!current(ctx)||editor.open||titlesDialog.open||socialEditor.open)return;active=item;editorContext=ctx;busy=false;pendingImage=null;imageRemoved=false;clearPreview();form.reset();form.elements.product_code.value=item.product_code||'';form.elements.record_code.value=item.record_code||'';form.elements.published_through.value=item.published_through||'';form.elements.product_name.value=item.product_name||'';form.elements.english_title.value=item.english_title||'';form.elements.seo_description.value=item.seo_description||'';form.elements.content.value=item.content??item.description??'';$('#mic-name-fields').innerHTML='';item.titles.forEach(addName);countNames();initial=JSON.stringify(payload());$('#mic-editor-title').textContent=id?`编辑产品 · ${item.product_name||item.product_code}`:'新增产品';$('#mic-save').disabled=false;$('#mic-save').textContent='保存产品';error();renderImage();editor.showModal();selectEditorTab(tab);requestAnimationFrame(()=>{$('#mic-name-fields').querySelectorAll('textarea').forEach(fitName);});}catch(e){if(current(ctx))say(e.message,true);}}
  const editorTabs=[...editor.querySelectorAll('[data-mic-editor-tab]')];
  function selectEditorTab(tab){
    for(const button of editorTabs){
      const selected=button.dataset.micEditorTab===tab;
      button.setAttribute('aria-selected',String(selected));
      button.tabIndex=selected?0:-1;
    }
    form.hidden=tab==='social';
    $('#mic-edit-product').hidden=tab!=='product';
    $('#mic-edit-mic').hidden=tab!=='mic';
    socialEditor.hidden=tab!=='social';
    $('#mic-open-publish-tools').hidden=!active?.id;
    const note=$('#mic-social-editor-note');
    note.hidden=tab!=='social'||Boolean(active?.id);
    if(!note.hidden)note.textContent='保存产品后可填写社媒文案。';
    if(tab==='social'&&active?.id&&!socialEditor.open)openSocial(active.id);
    if(tab==='mic')requestAnimationFrame(()=>$('#mic-name-fields').querySelectorAll('textarea').forEach(fitName));
    form.querySelector('.mic-editor-body').scrollTop=0;
  }
  editorTabs.forEach(button=>button.onclick=()=>selectEditorTab(button.dataset.micEditorTab));
  editor.querySelector('.mic-editor-tabs').addEventListener('keydown',event=>{
    const index=editorTabs.indexOf(event.target);
    if(index<0||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?editorTabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+editorTabs.length)%editorTabs.length;
    editorTabs[next].click();
    editorTabs[next].focus();
  });
  form.addEventListener('invalid',()=>{
    const panel=form.querySelector('input:invalid,textarea:invalid,select:invalid')?.closest('[role="tabpanel"]');
    if(panel?.hidden)selectEditorTab(panel.id==='mic-edit-mic'?'mic':'product');
  },true);
  $('#mic-open-publish-tools').onclick=()=>{
    const id=active?.id;
    if(id&&close())openTitles(id);
  };
  const pendingDeletes=new Map();
  const canEditRecords=()=>!window.tophooProjectAccess||window.tophooProjectAccess.canEdit('mic_products');
  async function removeRecord(button){
    const id=Number(button.dataset.micRemoveRecord),ctx=snapshot();
    if(!ctx.id||!canEditRecords()||pendingDeletes.has(id))return;
    const name=button.closest('tr').querySelector('.mic-record-name').textContent;
    if(!confirm(`删除「${name}」？该产品的图片、社媒文案和 MIC 标题也会删除。`))return;
    const pending={};
    pendingDeletes.set(id,pending);
    button.disabled=true;
    try{
      await request(api(ctx,`/${id}`),{method:'DELETE'});
      if(current(ctx)){
        say('产品已删除。');
        await load({preserveScroll:true});
      }
    }catch(error){
      if(current(ctx))say(error.message,true);
    }finally{
      if(pendingDeletes.get(id)===pending){
        pendingDeletes.delete(id);
        const visible=$(`[data-mic-remove-record="${id}"]`);
        if(visible&&current(ctx))visible.disabled=false;
      }
    }
  }
  $('#mic-list').onclick=event=>{
    const remove=event.target.closest('[data-mic-remove-record]');
    if(remove)return removeRecord(remove);
    const button=event.target.closest('[data-mic-open-record]');
    if(button&&!pendingDeletes.has(Number(button.dataset.micOpenRecord)))open(Number(button.dataset.micOpenRecord));
  };
  $('#mic-add').onclick=()=>open();

  host.querySelectorAll('[data-mic-close]').forEach(button=>button.onclick=()=>close());editor.addEventListener('cancel',event=>{event.preventDefault();close();});
  function assignCodes(){for(const field of $('#mic-name-fields').querySelectorAll('textarea[data-code]'))if(!field.dataset.code)field.dataset.code=nextCode();countNames();}
  form.elements.product_code.onchange=()=>{assignCodes();showMissingCodes();};
  $('#mic-add-name').onclick=()=>{assignCodes();addName({code:nextCode(),title:''}).querySelector('textarea').focus();};
  $('#mic-name-fields').onclick=event=>{const move=event.target.closest('[data-keyword-move]');if(move){const row=move.closest('.mic-name-row'),fields=[...row.querySelectorAll('[data-core-keyword]')],field=move.closest('.mic-keyword-field').querySelector('input'),index=fields.indexOf(field),next=index+Number(move.dataset.keywordMove);if(next>=0&&next<fields.length){[field.value,fields[next].value]=[fields[next].value,field.value];updateKeywordFields(row);fields[next].focus();}return;}const button=event.target.closest('[data-remove-name]');if(button){button.closest('.mic-name-row').remove();countNames();}};
  $('#mic-image-upload').onchange=event=>{const file=event.target.files[0];event.target.value='';if(!file)return;if(file.size>8*1024*1024)return error('图片不能超过 8 MB。');if(!['image/jpeg','image/png','image/webp'].includes(file.type))return error('请选择 JPG、PNG 或 WebP 图片。');clearPreview();pendingImage=file;previewUrl=URL.createObjectURL(file);imageRemoved=false;error();renderImage();};
  $('#mic-remove-image').onclick=()=>{clearPreview();pendingImage=null;imageRemoved=Boolean(active?.images?.length);renderImage();};
  form.onsubmit=async event=>{event.preventDefault();if(busy||!current(editorContext))return;const ctx=editorContext;const invalid=payload().titles.map(item=>({code:item.code,message:keywordError(item.core_keywords)})).find(item=>item.message);if(invalid)return error((invalid.code?invalid.code+'：':'')+invalid.message);if(payload().titles.some(item=>!item.title))return error('填写关键词或优化建议时，请同时填写对应的 MIC名称。');busy=true;$('#mic-save').disabled=true;$('#mic-save').textContent='正在保存…';error();let fieldsSaved=false;
    try{const saved=await request(api(ctx,active.id?`/${active.id}`:''),write(active.id?'PUT':'POST',payload()));if(!current(ctx))return;active.id=saved.id;active.product_code=saved.product_code;fieldsSaved=true;
      if(pendingImage){const body=new FormData();body.append('files',pendingImage);const result=await request(api(ctx,`/${saved.id}/images`),{method:'POST',body});if(!current(ctx))return;active.images=result.images;pendingImage=null;clearPreview();}
      else if(imageRemoved&&active.images?.[0]){await request(api(ctx,`/${saved.id}/images/${active.images[0].id}`),{method:'DELETE'});if(!current(ctx))return;active.images=[];imageRemoved=false;}
      if(socialDirty()||window.TophooMicSocial?.busy()){
        initial=JSON.stringify(payload());renderImage();error();
        $('#mic-record-feedback').textContent='产品已保存';
      }else close(true);
      say('产品已保存。');load();
    }catch(e){if(current(ctx)&&editor.open){error((fieldsSaved?'产品资料已保存，图片处理未完成：':'')+e.message);if(fieldsSaved){initial=JSON.stringify(payload());$('#mic-editor-title').textContent=`编辑 ${active.product_code}`;}}}
    finally{if(current(ctx)){busy=false;$('#mic-save').disabled=false;$('#mic-save').textContent='保存产品';}}
  };

  document.addEventListener('tophoo-mic-social-saved',event=>{if(event.detail.project===project())load({preserveScroll:true,anchorId:event.detail.id});});
  const socialDirty=()=>window.TophooMicSocial?.dirty()||false;
  const closeSocial=(force=false)=>window.TophooMicSocial?.close(force);
  const openSocial=(id,platform,title)=>window.TophooMicSocial?.open(id,platform,title);

  $('#mic-overview').onclick=event=>{const title=event.target.closest('[data-title-state]');if(title){clearTimeout(timer);nameView=title.dataset.titleState;$('#mic-name-view').value=nameView;localStorage.setItem(nameViewKey(),nameView);$('#mic-status-filter').value='';page=1;load({jump:true});return;}const social=event.target.closest('[data-social-filter]');if(social){clearTimeout(timer);socialPlatform=social.dataset.socialFilter;socialStatus=social.dataset.socialStatus||'';page=1;load({jump:true});return;}const status=event.target.closest('[data-mic-status]');if(!status)return;clearTimeout(timer);$('#mic-status-filter').value=status.dataset.micStatus;nameView='all';$('#mic-name-view').value=nameView;localStorage.setItem(nameViewKey(),nameView);page=1;load({jump:true});};
  const assistants=[...host.querySelectorAll('[data-mic-assistant]')];
  micAssistant.addEventListener('toggle',()=>{
    clearTimeout(timer);
    page=1;
    if(host.classList.contains('active'))load();
  });
  assistants.forEach(panel=>panel.querySelector('summary').addEventListener('click',()=>{
    if(!panel.open)assistants.forEach(other=>{if(other!==panel)other.open=false;});
  }));
  $('#mic-search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{page=1;load();},250);};$('#mic-status-filter').onchange=()=>{page=1;load();};$('#mic-reset').onclick=()=>{clearTimeout(timer);nameView='all';$('#mic-name-view').value=nameView;localStorage.setItem(nameViewKey(),nameView);socialPlatform='';socialStatus='';$('#mic-search').value='';$('#mic-status-filter').value='';page=1;load();};$('#mic-prev').onclick=()=>{if(page>1){page--;load();}};$('#mic-next').onclick=()=>{if(page<pages){page++;load();}};
  function applyPageSize(){const input=$('#mic-page-size');if(!input.checkValidity()||!input.value){input.reportValidity();return;}const value=Number(input.value);if(value===pageSize)return;pageSize=value;localStorage.setItem(pageSizeKey(),String(value));page=1;clearTimeout(timer);load();}
  $('#mic-name-view').onchange=()=>{page=1;nameView=$('#mic-name-view').value;localStorage.setItem(nameViewKey(),nameView);load();};
  $('#mic-page-size').onchange=applyPageSize;$('#mic-page-size').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();applyPageSize();}};
  function reset(){pendingDeletes.clear();host.querySelectorAll('[data-mic-assistant]').forEach(panel=>panel.open=false);sortOrder=savedSortOrder();renderSortOrder();nameView=savedNameView();$('#mic-name-view').value=nameView;socialPlatform='';socialStatus='';$('#mic-social-summary').innerHTML='';$('.mic-social-all').setAttribute('aria-pressed','true');version++;sequence++;clearTimeout(timer);close(true);closeSocial(true);closeTitles();page=1;$('#mic-search').value='';pageSize=savedPageSize();$('#mic-page-size').value=pageSize;$('#mic-status-filter').value='';$('#mic-label-summary').innerHTML='';$('#mic-group-status-summary').innerHTML='';$('.mic-group-status-all').textContent='全部产品组';$('.mic-group-status-all').setAttribute('aria-pressed','true');$('#mic-active-filters').textContent='';$('#mic-source-details').hidden=true;$('#mic-source-details').open=false;$('#mic-source-notice').hidden=true;$('#mic-source-notice').textContent='';$('#mic-list').innerHTML=emptyRow('选择项目后查看产品记录。');$('#mic-result-count').textContent='';$('#mic-page').textContent='';$('#mic-prev').disabled=true;$('#mic-next').disabled=true;say('');if(host.classList.contains('active'))load();}
  document.addEventListener('tophoo-project-library-view',event=>{if(event.detail?.section==='mic-products')load();});window.addEventListener('tophoo-project-changed',reset);document.addEventListener('tophoo-auth-changed',reset);window.addEventListener('beforeunload',event=>{if(dirty()||socialDirty()){event.preventDefault();event.returnValue='';}});
})();
