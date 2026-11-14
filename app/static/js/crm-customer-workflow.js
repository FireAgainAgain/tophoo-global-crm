(() => {
  const root=document.querySelector('[data-customer-workflow]'); if(!root)return;
  const $=s=>root.querySelector(s)||document.querySelector(s);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const companyTypes=window.TophooCompanyTypes;
  const sourceTypes=['MIC询盘','MIC RFQ','独立站询盘','邮件','自动获客','自主开发'];
  const sourceTypeOf=item=>{const value=String(item.source_type||'').trim();return value.toUpperCase()==='RFQ'?'RFQ':value;};
  const matchesSourceType=(item,type)=>!type||(type==='__unknown__'?!sourceTypeOf(item):sourceTypeOf(item)===type);
  const sourceTypeChoices=()=>[...new Set(state.items.map(sourceTypeOf).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
  function sourceTypeFacet(){
    const el=$('[data-filter-source-type]'),value=el.value,values=sourceTypeChoices(),hasEmpty=state.items.some(item=>!sourceTypeOf(item));
    el.innerHTML='<option value="">全部来源</option>'+values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')+(hasEmpty?'<option value="__unknown__">未填写</option>':'');
    el.value=values.includes(value)||(value==='__unknown__'&&hasEmpty)?value:'';
  }
  // Display-only: never attach completeness to a lead or to a write payload.
  const completenessRules=[['company_name','公司名称',10],['country','国家',10],['company_website','官网',15],['company_address','公司地址',10],['email','邮箱',25],['phone','电话',15],['contact_name','具名联系人',15]];
  function completeness(item){
    const has=value=>String(value??'').trim().length>0;
    const fields=completenessRules.map(([key,label,weight])=>({key,label,weight,present:has(item[key])||(['email','phone','contact_name'].includes(key)&&(item.contacts||[]).some(person=>has(person[key])))}));
    return {score:fields.reduce((sum,field)=>sum+(field.present?field.weight:0),0),fields,missing:fields.filter(field=>!field.present)};
  }
  function matchesCompleteness(item,value){const info=completeness(item);return !value||(value==='complete'?info.score===100:value==='incomplete'?info.score<100:info.missing.some(field=>field.key===value));}
  function completenessCell(item){
    const info=completeness(item),description=info.missing.length?'缺少：'+info.missing.map(field=>field.label).join('、'):'七项资料已填写；联系方式有效性仍需核实';
    return `<td class="workflow-completeness-cell"><button type="button" class="workflow-completeness ${info.score===100?'is-complete':''}" data-completeness-detail="${item.id}" title="${esc(description)}" aria-label="${esc(item.company_name)}，资料完整度 ${info.score}%，${esc(description)}。点击查看评分明细"><span><strong>${info.score}%</strong><small>${info.missing.length?`缺 ${info.missing.length} 项`:'资料齐全'}</small></span><i aria-hidden="true" style="--completeness:${info.score}%"></i></button></td>`;
  }
  function showCompleteness(id){
    if(state.view!=='leads')return;const item=state.items.find(x=>x.id===id);if(!item)return;const info=completeness(item);
    actionDialog({title:'资料完整度 · '+info.score+'%',content:`<p>${esc(item.company_name)}</p><ul class="workflow-completeness-breakdown">${info.fields.map(field=>`<li><span>${field.present?'✓':'○'} ${field.label}</span><span>${field.present?field.weight:0} / ${field.weight} 分${field.present?'':' · 待补充'}</span></li>`).join('')}</ul><p class="workflow-completeness-note">按现有资料自动计算，任意一位联系人填写对应信息即可计分。资料齐全不代表邮箱、电话已验证有效；此评分仅用于线索列表。</p>`,confirm:'知道了'});
  }
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const headers=()=>window.tophooAuth?.headers?.()||{};
  const meta={prospecting:{title:'搜客清单',endpoint:'prospecting',add:'新增搜客',main:'放入线索',source:['自主开发','自动获客']},leads:{title:'线索列表',endpoint:'leads',add:'新增线索',main:'转为客户',source:['自主开发','主动询盘','自动获客','MIC RFQ']},contacts:{title:'客户列表',endpoint:'contacts',add:'新增客户',main:'放入公池',source:['自主开发','主动询盘','自动获客','MIC RFQ']},'customer-pool':{title:'客户公池',endpoint:'pool',add:'',main:'恢复客户',source:[]}};
  const state={view:'contacts',items:[],admin:false,owners:[],selected:new Set(),customerQuickFilter:'',editing:null,page:1,size:10,sortDirection:'desc',loading:false,busy:false};
  let loadVersion=0,controller=null,loadedContext='',detailVersion=0,editContext=null,formSnapshot='',previousFocus=null,detailFocus=null,searchTimer=0,personEdit=null;
  let exportingLeads=false;
  const memories=new Map();
  let pendingCustomerOpen=null;
  const context=()=>({project:pid(),view:state.view});
  const contextKey=c=>`${c.project}:${c.view}`;
  const sameContext=c=>contextKey(c)===contextKey(context());
  const baseFor=c=>c.view==='contacts'?`/api/contacts/projects/${c.project}`:`/api/customer-workflow/projects/${c.project}/${meta[c.view].endpoint}`;
  async function api(url,opt={}){const r=await fetch(url,{...opt,headers:{...headers(),...(typeof opt.body==='string'?{'Content-Type':'application/json'}:{}),...(opt.headers||{})}}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(Array.isArray(d.detail)?d.detail.map(x=>x.msg).join('；'):d.detail||'操作失败。');if(opt.method&&!['GET','HEAD'].includes(opt.method)&&url.startsWith('/api/contacts/projects/')){const info={project:Number(url.split('/')[4]),nonce:Date.now()+Math.random()};document.dispatchEvent(new CustomEvent('tophoo-linked-data-updated',{detail:info}));try{localStorage.setItem('tophoo-linked-data-updated',JSON.stringify(info));}catch{}}return d;}
  function toast(message,type='success'){const el=$('[data-workflow-toast]');el.textContent=message;el.className=`workflow-toast ${type}`;el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,4000);}
  function formValue(){return JSON.stringify([...new FormData($('[data-workflow-form]'))]);}
  const dirty=()=>!$('[data-workflow-dialog]').hidden&&formValue()!==formSnapshot;
  function close(force=false){if(state.busy&&!force)return false;if(!force&&dirty()&&!window.confirm('资料尚未保存，确定放弃修改吗？'))return false;const dialog=$('[data-workflow-dialog]');dialog.hidden=true;delete dialog.dataset.permissionModule;state.editing=null;personEdit=null;editContext=null;previousFocus?.focus();return true;}
  function setBusy(value){state.busy=value;root.setAttribute('aria-busy',String(value||state.loading));root.querySelectorAll('button,[data-select],[data-select-all],[data-contact-status],[data-manual-research],[data-customer-grade],[data-customer-category]').forEach(el=>el.disabled=value||state.loading);$('[data-workflow-form]').querySelector('[type="submit"]').disabled=value;$('[data-workflow-form]').querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=value);if(personEdit?.wasPrimary&&$('[data-workflow-form]').elements.is_primary)$('[data-workflow-form]').elements.is_primary.disabled=true;$('[data-workflow-detail]').querySelectorAll('button').forEach(el=>el.disabled=value);syncLeadExport();root.querySelectorAll('[data-activity-unavailable]').forEach(el=>el.disabled=true);root.querySelectorAll('[data-customer-workflow-status]').forEach(el=>el.disabled=value||state.loading||!window.tophooProjectAccess?.canEdit('customer_list'));}
  let cancelAction=null;
  function actionDialog({title,content,confirm='确认',danger=false,variant='',setup}){return new Promise(resolve=>{
    const dialog=$('[data-action-dialog]'),form=$('[data-action-form]'),submit=$('[data-action-submit]'),focus=document.activeElement;
    cancelAction?.();dialog.dataset.actionVariant=variant;$('[data-action-title]').textContent=title;$('[data-action-content]').innerHTML=content;submit.textContent=confirm;submit.classList.toggle('danger',danger);dialog.hidden=false;
    let done=false;const finish=value=>{if(done)return;done=true;dialog.hidden=true;delete dialog.dataset.actionVariant;form.onsubmit=null;document.removeEventListener('keydown',onKey);cancelAction=null;focus?.focus();resolve(value);};
    const onKey=e=>{if(e.key==='Escape'){e.preventDefault();finish(null);}};cancelAction=()=>finish(null);
    form.onsubmit=e=>{e.preventDefault();finish(Object.fromEntries(new FormData(form)));};dialog.querySelectorAll('[data-action-cancel]').forEach(x=>x.onclick=()=>finish(null));document.addEventListener('keydown',onKey);setup?.(form);(form.querySelector('input,textarea,select')||submit).focus();
  });}
  const date=v=>String(v||'').slice(0,10)||'—';
  function days(v){const t=Date.parse(v);return Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/86400000)):null;}
  function ownerSelect(){const el=$('[data-workflow-owner]'),value=el.value;el.hidden=!state.admin;$('[data-owner-filter]').hidden=!state.admin;el.innerHTML='<option value="">全部归属</option>'+state.owners.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');el.value=value;}
  function facet(selector,key,label){const el=$(selector),value=el.value,values=[...new Set(state.items.map(x=>x[key]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));el.innerHTML=`<option value="">${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');el.value=values.includes(value)?value:'';}
  function typeFacet(){const el=$('[data-filter-company-type]'),value=el.value,values=[...new Set(state.items.map(x=>x.company_type).filter(Boolean))];el.innerHTML='<option value="">全部企业类型</option><option value="__unknown__">未知</option>'+values.map(v=>`<option value="${esc(v)}">${esc(companyTypes.label(v))}</option>`).join('');el.value=value==='__unknown__'||values.includes(value)?value:'';}
  let countryOptions=[],countryLookup=new Map();
  const countryKey=value=>String(value||'').normalize('NFKC').trim().toLocaleLowerCase();
  function countryInfo(value){return countryLookup.get(countryKey(value));}
  function matchesCountry(value,term){
    const query=countryKey(term);if(!query)return true;
    const info=countryInfo(value);return [value,info?.name,...(info?.aliases||[])].some(alias=>countryKey(alias).includes(query));
  }
  function countryFacet(){
    const values=[...new Set(state.items.map(item=>item.country).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
    $('[data-country-options]').innerHTML=values.map(value=>`<option value="${esc(value)}"></option>`).join('');
  }
  const memoryKey=key=>'tophoo-workflow-list-'+key;
  function listMemory(key){if(memories.has(key))return memories.get(key);try{return JSON.parse(sessionStorage.getItem(memoryKey(key))||'{}');}catch{return {};}}
  function remember(){if(!loadedContext)return;const key=loadedContext,m={customerQuickFilter:state.customerQuickFilter,search:$('[data-workflow-search]').value,country:$('[data-filter-country]').value,companyType:$('[data-filter-company-type]').value,sourceType:$('[data-filter-source-type]').value,productCategory:$('[data-filter-product-category]').value,grade:$('[data-filter-grade]').value,leadStatus:$('[data-filter-contacted]').value,completeness:$('[data-filter-completeness]').value,manualResearch:$('[data-filter-manual-research]').value,followup:$('[data-filter-followup]').value,owner:$('[data-workflow-owner]').value,sort:$('[data-workflow-sort]').value,sortVersion:5,direction:state.sortDirection,dateFrom:$('[data-filter-date-from]').value,dateTo:$('[data-filter-date-to]').value,developmentFrom:$('[data-filter-development-from]').value,developmentTo:$('[data-filter-development-to]').value,page:state.page,size:state.size,scroll:$('.workflow-table-wrap').scrollTop};memories.set(key,m);try{sessionStorage.setItem(memoryKey(key),JSON.stringify(m));}catch{}}
  const gradeNames={A:'订单客户',B:'样单客户',C:'重潜客户',D:'普潜客户',E:'无潜客户'};
  const gradeHints={A:'已有正式订单的客户。',B:'已有样单的客户。',C:'重点潜在客户。',D:'普通潜在客户。',E:'暂无业务潜力的客户。'};
  const gradeLabel=grade=>gradeNames[grade]?`${grade} · ${gradeNames[grade]}`:'未分级 · 待评估';
  const gradeHint=grade=>gradeHints[grade]||'信息不足或身份待核验，先保留未分级，核实后再评估。';
  const defaultSort=()=>state.view==='leads'?'development':'recent';
  const dateSort=()=>state.view==='leads'?'development':'updated';
  const defaultDirection=()=>'desc';
  const sortMode=()=>$('[data-workflow-sort]').value==='recent'?(state.sortDirection==='asc'?'oldest':'recent'):$('[data-workflow-sort]').value;
  function syncSortControl(){
    const field=$('[data-workflow-sort]'),value=field.value;
    const options=[['recent',state.view==='customer-pool'?'释放日期':'添加日期'],['name','公司名称'],...(['leads','contacts'].includes(state.view)?[[dateSort(),state.view==='leads'?'开发时间':'更新时间']]:[]),...(['leads','contacts'].includes(state.view)?[['grade','分级']]:[]),...(state.view==='leads'?[['completeness','资料完整度']]:[])];
    const signature=options.map(([key,label])=>key+label).join('|');
    if(field.dataset.options!==signature){field.innerHTML=options.map(([key,label])=>`<option value="${key}">${label}</option>`).join('');field.dataset.options=signature;field.value=options.some(([key])=>key===value)?value:'recent';if(field.value!==value)state.sortDirection='desc';}
    const ascending=state.sortDirection==='asc',label=field.value==='grade'?(ascending?'A → E':'E → A'):field.value==='name'?(ascending?'A → Z':'Z → A'):field.value==='completeness'?(ascending?'低到高':'高到低'):(ascending?'旧到新':'新到旧');
    const button=$('[data-sort-direction]');button.textContent=(ascending?'↑ ':'↓ ')+label;button.setAttribute('aria-label','排序方向：'+label+'，点击反向排列');button.title='点击切换排序方向';
  }

  function restoreMemory(){const m=listMemory(contextKey(context()));if(state.view==='leads'&&m.sortVersion!==5&&(!m.sort||m.sort==='updated')){m.sort=defaultSort();m.direction=defaultDirection();}const savedStatus=m.customerQuickFilter??(Array.isArray(m.customerQuickFilters)?m.customerQuickFilters.at(-1):'');state.customerQuickFilter=Object.hasOwn(customerStatusNames,savedStatus)?savedStatus:'';if(m.source?.startsWith('type:')){m.sourceType=m.source.slice(5);m.source='';}if(sourceTypes.includes(m.source)||m.source==='RFQ'){m.sourceType=m.source==='RFQ'?'RFQ':m.source;m.source='';}if(m.sourceType&&!sourceTypeChoices().includes(m.sourceType)&&!(m.sourceType==='__unknown__'&&state.items.some(item=>!sourceTypeOf(item))))m.sourceType='';if(m.sort==='product_match'){m.sort='recent';m.direction='desc';}if(m.leadStatus==='fake')m.leadStatus='unfit';if(['checked','checking'].includes(m.leadStatus))m.leadStatus='ready';if(!m.leadStatus&&m.leadStage)m.leadStatus={todo:'unviewed',developing:'contacted',following:'contacted',replied:'replied',unfit:'unfit'}[m.leadStage]||'';for(const [selector,key] of [['[data-workflow-search]','search'],['[data-filter-country]','country'],['[data-filter-company-type]','companyType'],['[data-filter-source-type]','sourceType'],['[data-filter-product-category]','productCategory'],['[data-filter-grade]','grade'],['[data-filter-contacted]','leadStatus'],['[data-filter-completeness]','completeness'],['[data-filter-manual-research]','manualResearch'],['[data-filter-followup]','followup'],['[data-workflow-owner]','owner'],['[data-filter-date-from]','dateFrom'],['[data-filter-date-to]','dateTo'],['[data-filter-development-from]','developmentFrom'],['[data-filter-development-to]','developmentTo']])$(selector).value=(key==='leadStatus'?(m.leadStatus||({true:'contacted',false:'unviewed'}[m.contacted])):m[key])||'';$('[data-workflow-sort]').value=['recent','name',...(['leads','contacts'].includes(state.view)?[dateSort()]:[]),...(['leads','contacts'].includes(state.view)?['grade']:[]),...(state.view==='leads'?['completeness']:[])].includes(m.sort)?m.sort:defaultSort();state.sortDirection=['asc','desc'].includes(m.direction)?m.direction:m.sort==='oldest'?'asc':m.sort==='name'||m.sort==='grade'?'asc':defaultDirection();state.page=Math.max(1,Number(m.page)||1);state.size=validPageSize(Number(m.size))?Number(m.size):10;syncPageSize();return m;}
  const addedAt=x=>x.added_at||x.created_at||'';
  const updatedAt=x=>x.updated_at||addedAt(x);
  const listDate=x=>state.view==='customer-pool'?x.released_at:addedAt(x);
  function filtered({ignoreStatus=false,ignoreGrade=false}={}){const key=$('[data-workflow-search]').value.trim().toLowerCase(),country=$('[data-filter-country]').value,sourceType=$('[data-filter-source-type]').value,companyType=$('[data-filter-company-type]').value,grade=$('[data-filter-grade]').value,owner=$('[data-workflow-owner]').value;
    const from=$('[data-filter-date-from]').value,to=$('[data-filter-date-to]').value,contacted=$('[data-filter-contacted]').value;
    const developmentFrom=state.view==='leads'?$('[data-filter-development-from]').value:'',developmentTo=state.view==='leads'?$('[data-filter-development-to]').value:'';
    const items=state.items.filter(x=>(!key||[x.company_name,x.product_category,companyTypes.label(x.company_type),x.company_type,x.contact_name,x.source_type,x.country,x.email,x.phone,x.whatsapp,x.company_website,...socials.map(([key])=>x['company_'+key]),x.notes,x.release_reason,x.owner_name,...Object.values(x.activity_documents||{}).flat().map(doc=>doc.number),...(x.contacts||[]).flatMap(person=>[person.contact_name,person.email,person.phone,person.whatsapp,person.notes,...socials.map(([key])=>person[key])])].join(' ').toLowerCase().includes(key))&&matchesCountry(x.country,country)&&(!companyType||(companyType==='__unknown__'?!x.company_type:x.company_type===companyType))&&(!['leads','contacts'].includes(state.view)||!$('[data-filter-manual-research]').value||String(!!x.is_manually_researched)===$('[data-filter-manual-research]').value)&&(state.view!=='contacts'||!$('[data-filter-followup]').value||($('[data-filter-followup]').value==='scheduled'?!!x.next_followup:!x.next_followup))&&matchesSourceType(x,sourceType)&&(!owner||!state.admin||String(x.owner_user_id)===owner)&&(state.view!=='leads'||((ignoreStatus||!contacted||leadStatus(x)===contacted)&&matchesCompleteness(x,$('[data-filter-completeness]').value)))&&(state.view!=='contacts'||!$('[data-filter-product-category]').value||(x.product_category||'').toLowerCase().includes($('[data-filter-product-category]').value.trim().toLowerCase()))&&(!['leads','contacts'].includes(state.view)||ignoreGrade||!grade||(grade==='none'?!gradeNames[x.grade]:x.grade===grade))&&(state.view!=='contacts'||ignoreStatus||!state.customerQuickFilter||state.customerQuickFilter===x.workflow_status)&&(!from||(listDate(x)&&listDate(x).slice(0,10)>=from))&&(!to||(listDate(x)&&listDate(x).slice(0,10)<=to))&&(!developmentFrom||(x.development_date&&x.development_date>=developmentFrom))&&(!developmentTo||(x.development_date&&x.development_date<=developmentTo)));
    if(ignoreStatus||ignoreGrade)return items;
    const sort=sortMode(),direction=state.sortDirection==='asc'?1:-1,time=x=>Date.parse(listDate(x))||0;
    if(sort==='development'){
      return items.sort((a,b)=>Number(!a.development_date)-Number(!b.development_date)||
        direction*(a.development_date||'').localeCompare(b.development_date||'')||time(b)-time(a)||b.id-a.id);
    }
    if(sort==='updated'){
      const updated=item=>Date.parse(updatedAt(item))||0;
      return items.sort((a,b)=>direction*(updated(a)-updated(b))||b.id-a.id);
    }
    const rank=item=>({A:0,B:1,C:2,D:3,E:4})[item.grade]??7;
    if(sort==='completeness'&&state.view==='leads')return items.sort((a,b)=>direction*(completeness(a).score-completeness(b).score)||time(b)-time(a)||b.id-a.id);
    if(state.view==='customer-pool')return items.sort(sort==='name'?(a,b)=>direction*String(a.company_name).localeCompare(String(b.company_name),'zh-CN'):(a,b)=>sort==='oldest'?time(a)-time(b):time(b)-time(a));
    if(sort==='grade'&&['leads','contacts'].includes(state.view))return items.sort((a,b)=>Number(rank(a)===7)-Number(rank(b)===7)||direction*(rank(a)-rank(b))||time(b)-time(a)||b.id-a.id);
    return items.sort(sort==='name'?(a,b)=>direction*String(a.company_name).localeCompare(String(b.company_name),'zh-CN')||a.id-b.id:(a,b)=>sort==='oldest'?time(a)-time(b)||a.id-b.id:time(b)-time(a)||b.id-a.id);
  }
  function shown(items=filtered()){state.page=Math.min(Math.max(1,state.page),Math.max(1,Math.ceil(items.length/state.size)));return items.slice((state.page-1)*state.size,state.page*state.size);}
  function dateHeader(){
    const active=sortMode()===dateSort(), ascending=state.sortDirection==='asc';
    return `<th aria-sort="${active?(ascending?'ascending':'descending'):'none'}"><button type="button" data-sort-updated>${state.view==='leads'?'开发时间':'更新时间'} ${active?(ascending?'↑':'↓'):'↕'}</button></th>`;
  }
  function updatedCell(item){
    const value=updatedAt(item);
    return `<td class="workflow-date">${esc(date(value))}</td>`;
  }
  function developmentDateCell(item){
    const value=esc(item.development_date||'未填写');
    if(window.tophooProjectAccess?.canEdit('leads')===false)return `<td class="workflow-date">${value}</td>`;
    return `<td class="workflow-date"><button type="button" class="workflow-company" data-lead-development-date="${item.id}" aria-label="设置 ${esc(item.company_name)} 的开发时间" title="点击选择开发日期">${value}</button></td>`;
  }
  async function editLeadDevelopmentDate(id){
    const c=context(),item=state.items.find(row=>row.id===id);
    if(c.view!=='leads'||!item||window.tophooProjectAccess?.canEdit('leads')===false)return;
    const today=new Date(),year=today.getFullYear(),month=today.getMonth(),day=today.getDate();
    const shortcuts=Array.from({length:7},(_,index)=>{
      const offset=index-3,preset=new Date(year,month,day+offset);
      const value=[preset.getFullYear(),preset.getMonth()+1,preset.getDate()].map(part=>String(part).padStart(2,'0')).join('-');
      const label=offset===0?'今天':`${preset.getMonth()+1}/${preset.getDate()}`;
      return `<button type="button" data-date-shortcut="${value}" aria-label="${offset===0?'今天，':''}${value}" aria-pressed="false" ${offset===0?'data-date-today':''}>${label}</button>`;
    }).join('');
    const answer=await actionDialog({
      title:'设置开发时间',
      variant:'development-date',
      content:`<p class="development-date-company">${esc(item.company_name)}</p>
        <label>开发日期<input type="date" name="development_date" value="${esc(item.development_date)}"></label>
        <div class="development-date-shortcut-heading"><span id="development-date-shortcut-label">快捷选择</span><button type="button" data-date-clear>清除日期</button></div>
        <div class="development-date-shortcuts" role="group" aria-labelledby="development-date-shortcut-label">${shortcuts}</div>`,
      confirm:'保存',
      setup(form){
        const input=form.elements.development_date,buttons=[...form.querySelectorAll('[data-date-shortcut]')],clear=form.querySelector('[data-date-clear]');
        const sync=()=>{
          for(const button of buttons)button.setAttribute('aria-pressed',String(button.dataset.dateShortcut===input.value));
          clear.setAttribute('aria-disabled',String(!input.value));
        };
        const select=value=>{input.value=value;sync();};
        for(const button of buttons)button.onclick=()=>select(button.dataset.dateShortcut);
        clear.onclick=()=>select('');
        input.addEventListener('input',sync);
        sync();
      }
    });
    if(!answer||!sameContext(c)||state.loading||state.busy)return;
    const developmentDate=answer.development_date||null;
    if(developmentDate===(item.development_date||null))return;
    const wrap=$('.workflow-table-wrap'),scroll=wrap.scrollTop;
    setBusy(true);
    try{
      const saved=await api(`${baseFor(c)}/${id}/development-date`,{method:'PATCH',body:JSON.stringify({development_date:developmentDate})});
      if(sameContext(c)){
        item.development_date=saved.development_date;
        item.updated_at=saved.updated_at;
        toast('开发时间已保存');
      }
    }catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{setBusy(false);}
    if(!sameContext(c))return;
    render();
    wrap.scrollTop=scroll;
    const visibleIds=new Set(shown().map(row=>row.id));
    for(const selectedId of state.selected)if(!visibleIds.has(selectedId))state.selected.delete(selectedId);
    syncSelection();
    (root.querySelector(`[data-lead-development-date="${id}"]`)||$('[data-sort-updated]')).focus({preventScroll:true});
    remember();
  }
  function gradeHeader(){return `<th class="workflow-grade-column" aria-sort="${sortMode()==='grade'?(state.sortDirection==='asc'?'ascending':'descending'):'none'}"><button type="button" data-sort-grade title="点击切换分级排序，未分级始终在最后">分级 ${sortMode()==='grade'?(state.sortDirection==='asc'?'↑':'↓'):'↕'}</button></th>`;}
  function cols(){if(state.view==='leads')return `<tr><th><input type="checkbox" data-select-all aria-label="选择本页全部记录"></th><th>客户</th><th aria-sort="${sortMode()==='recent'?'descending':sortMode()==='oldest'?'ascending':'none'}"><button type="button" data-sort-added title="点击切换添加时间排序">添加时间 ${sortMode()==='recent'?'↓':sortMode()==='oldest'?'↑':'↕'}</button></th>${dateHeader()}<th>国家</th><th>来源</th><th>当前状态</th>${gradeHeader()}<th>资料完整度</th><th>人工背调</th><th class="workflow-fixed-action workflow-fixed-outreach">操作</th></tr>`;if(state.view==='contacts')return `<tr><th><input type="checkbox" data-select-all aria-label="选择本页全部记录"></th><th>客户</th><th aria-sort="${sortMode()==='recent'?'descending':sortMode()==='oldest'?'ascending':'none'}"><button type="button" data-sort-added title="点击切换添加日期排序">添加日期 ${sortMode()==='recent'?'↓':sortMode()==='oldest'?'↑':'↕'}</button></th>${dateHeader()}<th>国家</th><th>来源</th><th>产品类别</th><th>状态</th>${gradeHeader()}<th>人工背调</th><th class="workflow-fixed-action workflow-fixed-records workflow-activity-cell">操作</th></tr>`;return `<tr><th><input type="checkbox" data-select-all aria-label="选择本页全部记录"></th><th>公司 / 联系人</th>${state.view==='leads'?'<th>当前状态</th><th>资料完整度</th>':''}${['leads','contacts'].includes(state.view)?'<th>人工背调</th>':''}<th>国家</th><th>${state.view==='contacts'?'当前时间':'联系方式'}</th>${state.view==='contacts'?'<th>联系记录</th>':''}<th>来源</th>${state.view==='leads'?'<th>开发信</th>':''}${state.view==='contacts'?`<th aria-sort="${sortMode()==='grade'?(state.sortDirection==='asc'?'ascending':'descending'):'none'}"><button type="button" data-sort-grade title="点击切换分级排序，未分级始终在最后">分级 ${sortMode()==='grade'?(state.sortDirection==='asc'?'↑':'↓'):'↕'}</button></th><th>下次跟进</th>`:''}${state.view==='customer-pool'?'<th>释放信息</th>':`<th aria-sort="${sortMode()==='recent'?'descending':sortMode()==='oldest'?'ascending':'none'}"><button type="button" data-sort-added title="点击切换添加日期排序">添加日期 ${sortMode()==='recent'?'↓':sortMode()==='oldest'?'↑':'↕'}</button></th>`}</tr>`;}
  function siteLabel(value){try{return new URL(/^https?:\/\//i.test(value)?value:`https://${value}`).host.replace(/^www\./i,'');}catch{return value;}}
  const leadStatuses={unviewed:'未查看',contacted:'开发中',priority_developing:'有回复'};
  const retiredLeadStatuses={ready:'unviewed',checking:'unviewed',checked:'unviewed',low_match:'unviewed',unfit:'unviewed',fake:'unviewed',replied:'priority_developing',company_contacted:'contacted'};
  const leadStatus=item=>Object.hasOwn(leadStatuses,item.workflow_status)?item.workflow_status:retiredLeadStatuses[item.workflow_status]||(item.is_contacted?'contacted':'unviewed');
  function contactSwitch(x){const value=leadStatus(x);return `<td class="workflow-contact-status"><select class="workflow-lead-status ${['contacted','priority_developing'].includes(value)?'is-success':''}" data-contact-status="${x.id}" data-status="${value}" aria-label="${esc(x.company_name)}：当前状态" ${state.busy?'disabled':''}>${Object.entries(leadStatuses).map(([key,label])=>`<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('')}</select></td>`;}
  async function changeLeadStatus(id,value){
    const c=context(),item=state.items.find(x=>x.id===id);
    if(c.view!=='leads'||!item||state.busy||state.loading||!leadStatuses[value]||leadStatus(item)===value)return;
    const scroll=$('.workflow-table-wrap').scrollTop;setBusy(true);
    try{const updated=await api(`${baseFor(c)}/${id}/status`,{method:'PATCH',body:JSON.stringify({workflow_status:value})});if(sameContext(c)){Object.assign(item,updated);toast('已设为'+leadStatuses[leadStatus(updated)]);}}
    catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{setBusy(false);if(sameContext(c)){render();$('.workflow-table-wrap').scrollTop=scroll;if(!shown().some(x=>x.id===id))state.selected.delete(id);syncSelection();(root.querySelector(`[data-contact-status="${id}"]`)||$('[data-filter-contacted]')).focus({preventScroll:true});remember();}}
  }
  function customerGradeSelect(item){
    return `<select class="grade workflow-grade-select grade-${esc((item.grade||'x').toLowerCase())}" data-customer-grade="${item.id}" aria-label="${esc(item.company_name)}：客户分级" title="点击更改分级，选择后自动保存。${esc(gradeHint(item.grade))}" ${state.busy||state.loading?'disabled':''}><option value="" ${!item.grade?'selected':''}>${state.view==='leads'?'未分级':'未分级 · 待评估'}</option>${Object.keys(gradeNames).map(value=>`<option value="${value}" ${item.grade===value?'selected':''}>${esc(gradeLabel(value))}</option>`).join('')}</select>`;
  }
  async function changeCustomerGrade(id,value){
    const c=context(),item=state.items.find(x=>x.id===id),grade=value||null;
    if(!['leads','contacts'].includes(c.view)||!item||state.busy||state.loading||(grade&&!gradeNames[grade])||(item.grade||null)===grade)return;
    const scroll=$('.workflow-table-wrap').scrollTop;setBusy(true);
    root.querySelector(`[data-customer-grade="${id}"]`)?.setAttribute('aria-busy','true');
    try{const updated=await api(`${baseFor(c)}/${id}/grade`,{method:'PATCH',body:JSON.stringify({grade})});if(sameContext(c)){Object.assign(item,updated);toast('分级已保存：'+gradeLabel(updated.grade));}}
    catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{setBusy(false);if(sameContext(c)){render();$('.workflow-table-wrap').scrollTop=scroll;if(!shown().some(x=>x.id===id))state.selected.delete(id);syncSelection();(root.querySelector(`[data-customer-grade="${id}"]`)||$('[data-filter-grade]')).focus({preventScroll:true});remember();}}
  }
  const customerStatusNames = {won:'已成交', following:'跟单中', quoting:'报价中', inquiring:'询价中', closed:'已关闭'};
  function customerStatusSelect(item){
    const current = Object.hasOwn(customerStatusNames, item.workflow_status) ? item.workflow_status : '';
    const placeholder = current ? '' : '<option value="" selected disabled hidden>—</option>';
    return `<select class="workflow-customer-status" data-customer-workflow-status="${item.id}" data-tone="${current}" aria-label="${esc(item.company_name)}：状态" title="选择客户状态">${placeholder}${Object.entries(customerStatusNames).map(([value,label])=>`<option value="${value}" ${current===value?'selected':''}>${label}</option>`).join('')}</select>`;
  }
  async function changeCustomerStatus(select){
    const c=context(),id=Number(select.dataset.customerWorkflowStatus);
    const item=state.items.find(row=>row.id===id),value=select.value||null;
    if(c.view!=='contacts'||!item||state.busy||state.loading||!window.tophooProjectAccess?.canEdit('customer_list'))return;
    if((item.workflow_status||null)===value)return;
    const scroller=$('.workflow-table-wrap'),scroll=scroller.scrollTop;
    setBusy(true);
    try{
      const updated=await api(`${baseFor(c)}/${id}/workflow-status`,{method:'PATCH',body:JSON.stringify({workflow_status:value})});
      if(sameContext(c)){
        Object.assign(item,updated);
        toast('状态已保存');
      }
    }catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{
      setBusy(false);
      if(sameContext(c)){
        render();
        scroller.scrollTop=scroll;
        root.querySelector(`[data-customer-workflow-status="${id}"]`)?.focus({preventScroll:true});
        remember();
      }
    }
  }
  root.addEventListener('change',event=>{
    if(event.target.matches('[data-customer-workflow-status]'))changeCustomerStatus(event.target);
  });
  function customerCategoryInput(item){
    return `<input class="workflow-product-category" data-customer-category="${item.id}" maxlength="160" value="${esc(item.product_category||'')}" placeholder="填写产品类别" aria-label="${esc(item.company_name)}：产品类别" title="填写后按 Enter 或移开光标保存" ${state.busy||state.loading?'disabled':''}>`;
  }
  async function changeCustomerCategory(id,value){
    const c=context(),item=state.items.find(x=>x.id===id),product_category=value.trim()||null;
    if(c.view!=='contacts'||!item||state.busy||state.loading||(item.product_category||null)===product_category)return;
    const scroll=$('.workflow-table-wrap').scrollTop;let saved=false;setBusy(true);
    try{
      const updated=await api(`${baseFor(c)}/${id}/product-category`,{method:'PATCH',body:JSON.stringify({product_category})});
      if(sameContext(c)){saved=true;Object.assign(item,updated);toast('产品类别已保存');}
    }catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{setBusy(false);if(sameContext(c)){if(saved)render();$('.workflow-table-wrap').scrollTop=scroll;remember();}}
  }
  function manualResearchButton(reviewed,attrs,label='是否人工背调'){
    return `<button type="button" class="workflow-manual-research" ${attrs} aria-pressed="${!!reviewed}" aria-label="${esc(label)}" title="${reviewed?'已人工背调，点击取消标记':'未人工背调，点击点亮标记'}"><span class="workflow-research-icon" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none"><path d="m4 8 2.5 2.5L12 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span>${reviewed?'已背调':'未背调'}</span></button>`;
  }
  function manualResearchCell(item){return `<td class="workflow-manual-research-cell">${manualResearchButton(item.is_manually_researched,`data-manual-research="${item.id}" ${state.busy?'disabled':''}`,item.company_name+'：是否人工背调')}</td>`;}
  async function changeManualResearch(id,value){
    const c=context(),item=state.items.find(x=>x.id===id);
    if(!['leads','contacts'].includes(c.view)||!item||state.busy||state.loading)return;
    const scroll=$('.workflow-table-wrap').scrollTop;setBusy(true);root.querySelector(`[data-manual-research="${id}"]`)?.setAttribute('aria-busy','true');
    try{const updated=await api(`${baseFor(c)}/${id}/manual-research`,{method:'PATCH',body:JSON.stringify({is_manually_researched:value})});if(sameContext(c)){Object.assign(item,updated);toast('人工背调标记已保存');}}
    catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{setBusy(false);if(sameContext(c)){render();$('.workflow-table-wrap').scrollTop=scroll;if(!shown().some(x=>x.id===id))state.selected.delete(id);syncSelection();root.querySelector(`[data-manual-research="${id}"]`)?.focus({preventScroll:true});remember();}}
  }
  function followupCell(item){
    const plan=item.next_followup;
    return `<td class="workflow-followup-cell"><button type="button" data-followup-open="${item.id}" class="${plan?'has-followup':'no-followup'}"><span class="workflow-followup-status">${plan?'有跟进':'暂无跟进'}</span>${plan?`<small class="workflow-followup-summary">${esc(plan.title)}</small>`:''}</button></td>`;
  }
  function localClockContent(clock){
    if(!clock?.timezone)return `<span class="workflow-muted">${esc(clock?.hint||'待确认时区')}</span>`;
    try{
      let format=clockFormatters.get(clock.timezone);
      if(!format){format={time:new Intl.DateTimeFormat('zh-CN',{timeZone:clock.timezone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}),date:new Intl.DateTimeFormat('zh-CN',{timeZone:clock.timezone,month:'2-digit',day:'2-digit',weekday:'short'})};clockFormatters.set(clock.timezone,format);}
      const now=new Date();return `<time title="${esc(clock.timezone)}"><strong>${esc(format.time.format(now))}</strong><small>${esc(format.date.format(now))} · ${esc(clock.city||clock.timezone)}</small></time>`;
    }catch{return '<span class="workflow-muted">待确认时区</span>';}
  }
  function compactClockContent(clock){
    if(!clock?.timezone)return '';
    try{
      if(!clockFormatters.has(clock.timezone))localClockContent(clock);
      const now=new Date(),time=clockFormatters.get(clock.timezone).time.format(now);
      return `<small class="workflow-country-time"><time datetime="${now.toISOString()}" title="${esc(clock.timezone)}">${esc([clock.city,time].filter(Boolean).join(' '))}</time></small>`;
    }catch{return '';}
  }
  function countryHue(value){
    let hash=0;
    for(const char of countryKey(value))hash=Math.imul(hash,31)+char.codePointAt(0)|0;
    return ((hash>>>0)*137)%360;
  }
  function countryClockCell(item){
    const country=esc(item.country);
    const label=country?`<button type="button" class="workflow-country-tag" style="--country-hue:${Number.isInteger(item.country_hue)?item.country_hue:countryHue(item.country)}" data-country-shortcut="${country}" aria-pressed="${$('[data-filter-country]').value===item.country}" title="按国家筛选：${country}">${country}</button>`:'<span>—</span>';
    return `<td class="workflow-country">${label}<div data-country-clock="${item.id}">${compactClockContent(item.local_clock)}</div></td>`;
  }
  function refreshLocalClocks(){
    if(!['leads','contacts'].includes(state.view)||document.hidden)return;
    root.querySelectorAll('[data-country-clock]').forEach(node=>{const item=state.items.find(item=>item.id===Number(node.dataset.countryClock));if(item)node.innerHTML=compactClockContent(item.local_clock);});
    root.querySelectorAll('[data-lead-clock]').forEach(node=>{const item=state.items.find(item=>item.id===Number(node.dataset.leadClock));if(item)node.innerHTML=localClockContent(item.local_clock);});
  }
  setInterval(refreshLocalClocks,15000);
  document.addEventListener('visibilitychange',refreshLocalClocks);
  function followupTiming(plan){
    if(!plan?.due_at&&!plan?.due_date)return {state:'scheduled',label:'有跟进'};
    const day=value=>new Date(value).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}),due=plan.due_date||day(plan.due_at),today=day(Date.now());
    const state=due>today?'future':due<today?'overdue':'today';
    return {state,label:({future:'未到期',today:'今日跟进',overdue:'已逾期'})[state]+' · '+due};
  }
  function verifyButton(item){
    return `<button type="button" class="workflow-activity-button action-verify" data-list-verify="${item.id}" aria-label="查证 ${esc(item.company_name)}" title="带入资料并打开客户查证">查证</button>`;
  }
  function customerActivityButtons(item){
    const counts=item.activity_counts||{};
    return `<div class="workflow-activity-buttons">${[['followups','跟进'],['rfqs','询价'],['quotations','报价'],['contracts','合同']].map(([kind,label])=>{
      const pending=counts.followups||0, count=kind==='followups'?pending+(counts.records||0):counts[kind],unavailable=count===null;
      const activityState=kind==='followups'?(pending?followupTiming(item.next_followup).state:count?'active':'empty'):!count?'empty':kind==='rfqs'?'active':'';
      const action=kind==='followups'?`data-list-records="${item.id}"`:`data-customer-documents="${kind}" data-customer-id="${item.id}" data-customer-name="${esc(item.company_name)}"`;
      return `<div class="workflow-activity-item action-${kind}"><button type="button" class="workflow-activity-button action-${kind}" data-activity-state="${activityState}" ${action} ${unavailable?'disabled data-activity-unavailable':''} aria-label="${esc(item.company_name)}：${label}，${unavailable?'无权限':`${count??0} 条`}" title="${unavailable?'暂无此模块权限':kind==='followups'?`${counts.records||0} 条历史跟进，${pending} 条待跟进计划`+(pending?'；'+followupTiming(item.next_followup).label:''):kind==='rfqs'?`该客户有 ${count??0} 条询价`:'该客户下当前用户的单据'}">${label}${kind==='followups'?'':`<span class="workflow-activity-count" aria-hidden="true">${unavailable?'—':count??0}</span>`}</button></div>`;
    }).join('')}${verifyButton(item)}</div>`;
  }
  function sourceCell(item){
    const method=sourceTypeOf(item);
    return `<td class="workflow-source-cell"><span>${esc(method)||'未填写'}</span></td>`;
  }
  function listRow(x){
    const contact=[x.email?`<span class="workflow-email" title="${esc(x.email)}">${safeLink(x.email,'mail')}</span>`:'',x.phone?`<small>电话：${safeLink(x.phone,'phone')}</small>`:'',x.whatsapp?`<small title="${esc(x.whatsapp)}">WhatsApp：${esc(x.whatsapp)}</small>`:''].filter(Boolean).join('')||'<span class="workflow-muted">未填写</span>';
    const website=x.company_website?`<small class="workflow-site"><a href="${esc(/^https?:\/\//i.test(x.company_website)?x.company_website:`https://${x.company_website}`)}" target="_blank" rel="noopener noreferrer" title="${esc(x.company_website)}">${esc(siteLabel(x.company_website))} ↗</a></small>`:'';
    if(state.view==='leads')return `<tr data-workflow-row="${x.id}"><td><input type="checkbox" data-select="${x.id}" aria-label="选择 ${esc(x.company_name)}" ${state.selected.has(x.id)?'checked':''}></td><td><button type="button" class="workflow-company" data-detail="${x.id}" aria-label="查看 ${esc(x.company_name)} 的详情"><strong>${esc(x.company_name)}</strong></button>${website}</td><td class="workflow-date">${date(addedAt(x))}</td>${developmentDateCell(x)}${countryClockCell(x)}${sourceCell(x)}${contactSwitch(x)}<td>${customerGradeSelect(x)}</td>${completenessCell(x)}${manualResearchCell(x)}<td class="workflow-fixed-action workflow-fixed-outreach"><div class="workflow-activity-buttons"><button type="button" class="workflow-activity-button action-followups" data-list-records="${x.id}">跟进</button><button type="button" class="workflow-activity-button action-outreach" data-lead-outreach-open="${x.id}" aria-label="打开 ${esc(x.company_name)} 的开发信，当前用户已发送 ${x.activity_counts?.outreach??0} 封" title="当前用户已发送的开发信数量">开发信<span class="workflow-activity-count" aria-hidden="true">${x.activity_counts?.outreach??0}</span></button>${verifyButton(x)}</div></td></tr>`;
    if(state.view==='contacts')return `<tr data-workflow-row="${x.id}"><td><input type="checkbox" data-select="${x.id}" aria-label="选择 ${esc(x.company_name)}" ${state.selected.has(x.id)?'checked':''}></td><td><button type="button" class="workflow-company" data-detail="${x.id}" aria-label="查看 ${esc(x.company_name)} 的详情"><strong>${esc(x.company_name)}</strong></button>${website}</td><td class="workflow-date">${date(addedAt(x))}</td>${updatedCell(x)}${countryClockCell(x)}${sourceCell(x)}<td>${customerCategoryInput(x)}</td><td>${customerStatusSelect(x)}</td><td>${customerGradeSelect(x)}</td>${manualResearchCell(x)}<td class="workflow-fixed-action workflow-fixed-records workflow-activity-cell">${customerActivityButtons(x)}</td></tr>`;
    return `<tr data-workflow-row="${x.id}"><td><input type="checkbox" data-select="${x.id}" aria-label="选择 ${esc(x.company_name)}" ${state.selected.has(x.id)?'checked':''}></td><td><button type="button" class="workflow-company" data-detail="${x.id}" aria-label="查看 ${esc(x.company_name)} 的详情"><strong>${esc(x.company_name)}</strong><span class="workflow-person">${esc(x.contact_name||'未填写联系人')}${x.contacts?.length>1?` · ${x.contacts.length} 位联系人`:''}</span></button>${website}</td>${state.view==='leads'?contactSwitch(x)+completenessCell(x):''}${['leads','contacts'].includes(state.view)?manualResearchCell(x):''}${state.view==='leads'?`<td><button type="button" class="workflow-outreach-button" data-lead-outreach-open="${x.id}" aria-label="打开 ${esc(x.company_name)} 的开发信">开发信</button></td><td><button type="button" class="workflow-outreach-button" data-lead-contacts-open="${x.id}" aria-label="管理 ${esc(x.company_name)} 的联系人">联系人${x.contacts?.length?` · ${x.contacts.length}`:''}</button></td>`:''}<td class="workflow-country">${esc(x.country)||'—'}</td>${state.view==='leads'?`<td class="workflow-local-clock" data-lead-clock="${x.id}">${localClockContent(x.local_clock)}</td>`:`${state.view==='contacts'?`<td class="workflow-local-clock" data-lead-clock="${x.id}">${localClockContent(x.local_clock)}</td><td class="workflow-records-cell"><button type="button" class="workflow-outreach-button" data-list-records="${x.id}" aria-label="查看 ${esc(x.company_name)} 的联系记录">跟进</button></td>`:`<td class="workflow-contact-cell">${contact}</td>`}<td class="workflow-source"><span>${esc(sourceTypeOf(x))||'未填写'}</span></td>`}${state.view==='contacts'?`<td>${customerCategoryInput(x)}</td><td>${customerStatusSelect(x)}</td><td>${customerGradeSelect(x)}</td>${followupCell(x)}`:''}${state.view==='leads'?'':state.view==='customer-pool'?`<td class="workflow-release"><span title="${esc(x.release_reason)}">${esc(x.release_reason)||'—'}</span><small>${date(x.released_at)}${days(x.released_at)!==null?` · 已停留 ${days(x.released_at)} 天`:''}</small><small>释放人：${esc(x.released_by_name)||'—'}</small>${x.has_archived_contracts?`<button type="button" data-customer-documents="contracts" data-contract-archive data-customer-id="${x.id}" data-customer-name="${esc(x.company_name)}">合同归档</button>`:''}</td>`:`<td class="workflow-date">${date(addedAt(x))}</td>`}</tr>`;
  }
  function syncSelection(){const items=shown(),all=$('[data-select-all]'),count=items.filter(x=>state.selected.has(x.id)).length;if(all){all.checked=!!items.length&&count===items.length;all.indeterminate=count>0&&count<items.length;}$('[data-workflow-batch]').hidden=!state.selected.size;$('[data-workflow-selected]').textContent=`本页已选择 ${state.selected.size} 项`;$('[data-workflow-batch-main]').textContent=meta[state.view].main;$('[data-workflow-batch-delete]').hidden=state.view==='contacts';}
  function syncFilterSummary(){
    const extra=[...(['contacts','leads'].includes(state.view)?['[data-filter-manual-research]']:[]),'[data-filter-company-type]','[data-filter-source-type]','[data-filter-date-from]','[data-filter-date-to]',...(state.view==='leads'?['[data-filter-development-from]','[data-filter-development-to]']:[]),...(state.admin?['[data-workflow-owner]']:[])];
    $('[data-reset-filters]').dataset.inactive=String(!(state.view==='contacts'&&state.customerQuickFilter)&&![...extra,'[data-filter-country]','[data-workflow-search]',...(state.view==='leads'?['[data-filter-contacted]','[data-filter-completeness]','[data-filter-grade]']:[]),...(state.view==='contacts'?['[data-filter-product-category]','[data-filter-grade]','[data-filter-followup]']:[])].some(selector=>$(selector).value));
  }
  const listFiltersOpen={contacts:false,leads:false};
  function syncListToolbar(){
    const customer=['contacts','leads'].includes(state.view),open=!!listFiltersOpen[state.view],toggle=$('[data-customer-filters-toggle]'),filters=$('#workflow-filter-fields'),footer=$('#workflow-filter-footer');
    if(!toggle||!filters||!footer)return;
    const search=$('[data-workflow-search]');search.placeholder=state.view==='contacts'?'搜索客户、联系人、单据编号…':'搜索公司、联系人、邮箱…';search.setAttribute('aria-label',state.view==='contacts'?'搜索客户资料或询价、报价编号':'搜索客户资料');
    toggle.hidden=!customer;$('[data-customer-list-overview]').hidden=!['leads','contacts'].includes(state.view);
    const sort=$('.workflow-sort-control'),slot=$(customer?'[data-customer-sort-slot]':'[data-workflow-sort-slot]');
    if(sort&&slot&&sort.parentElement!==slot)slot.append(sort);
    filters.hidden=customer&&!open;footer.hidden=customer&&!open;
    const fields=['[data-filter-country]','[data-filter-manual-research]',...(state.view==='leads'?['[data-filter-contacted]','[data-filter-completeness]','[data-filter-grade]']:['[data-filter-product-category]','[data-filter-grade]',...(state.view==='contacts'?['[data-filter-followup]']:[])]),'[data-filter-company-type]','[data-filter-source-type]',...(state.admin?['[data-workflow-owner]']:[])];
    const count=fields.filter(selector=>$(selector).value).length+Number(!!($('[data-filter-date-from]').value||$('[data-filter-date-to]').value))+Number(state.view==='leads'&&!!($('[data-filter-development-from]').value||$('[data-filter-development-to]').value));
    toggle.textContent=(open?'收起筛选':'筛选')+(count?' · '+count:'');toggle.setAttribute('aria-expanded',String(open));
    toggle.classList.toggle('has-filters',!!count);
    $('[data-workflow-reset]').hidden=customer&&$('[data-reset-filters]').dataset.inactive==='true';
  }
  function renderLeadFacet(row,kind,heading,options,selected,counts){
    const attribute=`data-lead-summary-${kind}`;
    if(!row.querySelector(`[${attribute}]`)){
      row.innerHTML=`<span class="lead-facet-label">${heading}</span><div class="lead-facet-options">`+
        options.map(([key,label])=>`<button type="button" ${attribute}="${key}" class="${kind==='grade'?'grade-'+key.toLowerCase():''}" aria-pressed="false"><span>${esc(label)}</span><strong></strong></button>`).join('')+'</div>';
    }
    row.style.setProperty('--facet-count-width',`${Math.max(2,state.items.length.toLocaleString('zh-CN').length)}ch`);
    row.querySelectorAll(`[${attribute}]`).forEach(button=>{
      const key=button.getAttribute(attribute);
      button.setAttribute('aria-pressed',String(key===selected));
      const number=button.querySelector('strong');
      const count=state.loading?'—':(counts.get(key)||0).toLocaleString('zh-CN');
      if(number.textContent!==count)number.textContent=count;
    });
  }

  function renderListSummary(){
    const node=$('[data-customer-list-summary]');if(!node)return;
    const gradeRow=$('[data-lead-grade-summary]');
    gradeRow.hidden=state.view!=='leads';
    node.classList.toggle('lead-facet-summary',state.view==='leads');
    node.hidden=!['contacts','leads'].includes(state.view);if(node.hidden){node.innerHTML='';return;}
    node.setAttribute('aria-label',state.view==='leads'?'线索状态统计':'客户状态筛选');
    if(state.view==='leads'){
      const items=filtered({ignoreStatus:true,ignoreGrade:true});
      const status=$('[data-filter-contacted]').value;
      const statusCounts=new Map([['all',items.length]]);
      const gradeCounts=new Map();
      for(const item of items){
        const current=leadStatus(item);
        statusCounts.set(current,(statusCounts.get(current)||0)+1);
        if(!status||status===current){
          const grade=Object.hasOwn(gradeNames,item.grade)?item.grade:'none';
          gradeCounts.set('',(gradeCounts.get('')||0)+1);
          gradeCounts.set(grade,(gradeCounts.get(grade)||0)+1);
        }
      }
      renderLeadFacet(node,'status','当前状态',[['all','全部'],...Object.entries(leadStatuses)],status||'all',statusCounts);
      const grades=[['','全部分级'],...Object.keys(gradeNames).map(grade=>[grade,gradeLabel(grade)]),['none','未分级']];
      renderLeadFacet(gradeRow,'grade','分级',grades,$('[data-filter-grade]').value,gradeCounts);
      return;
    }
    const items=filtered({ignoreStatus:true}),options=Object.entries(customerStatusNames);
    node.innerHTML=[['all','全部',items.length],...options.map(([key,label])=>[key,label,items.filter(item=>item.workflow_status===key).length])].map(([key,label,count])=>{
      const selected=key===(state.customerQuickFilter||'all');
      return `<button type="button" class="customer-quick-filter" data-customer-quick-filter="${key}" data-tone="${key}" aria-pressed="${selected}" title="${key==='all'?'清除快捷筛选，查看全部客户':'仅显示此状态的客户'}"><span>${key==='all'?'':'<i class="customer-status-dot" aria-hidden="true"></i>'}${label}</span><strong>${state.loading?'—':count.toLocaleString('zh-CN')}</strong></button>`;
    }).join('');

  }
  function render(){
    root.dataset.listView=state.view;
    const permissionModule=({leads:'leads',contacts:'customer_list','customer-pool':'customer_pool',prospecting:'auto_prospecting'})[state.view];
    root.dataset.permissionModule=permissionModule;
    document.querySelectorAll('[data-workflow-dialog],[data-workflow-detail],[data-action-dialog]').forEach(element=>element.dataset.permissionModule=permissionModule);
syncSortControl();renderListSummary();const items=filtered(),rows=shown(items),count=['leads','contacts'].includes(state.view)?11:6;
    $('[data-followup-mine]').hidden=state.view!=='contacts';$('[data-workflow-title]').textContent=meta[state.view].title;$('[data-workflow-eyebrow]').textContent='客户管理';$('[data-workflow-add]').textContent='＋ '+meta[state.view].add;$('[data-workflow-add]').hidden=!meta[state.view].add;$('[data-filter-grade]').hidden=!['leads','contacts'].includes(state.view);$('[data-filter-contacted]').hidden=state.view!=='leads';$('[data-contacted-filter]').hidden=true;$('[data-completeness-filter]').hidden=state.view!=='leads';$('[data-manual-research-filter]').hidden=!['leads','contacts'].includes(state.view);$('[data-grade-filter]').hidden=state.view!=='contacts';$('[data-category-filter]').hidden=state.view!=='contacts';$('[data-followup-filter]').hidden=state.view!=='contacts';$('[data-owner-filter]').hidden=!state.admin;syncFilterSummary();syncListToolbar();
    $('[data-development-date-range]').hidden=state.view!=='leads';
    $('[data-date-range-label]').textContent=state.view==='customer-pool'?'释放日期':'添加日期';
    $('[data-filter-date-from]').setAttribute('aria-label',state.view==='customer-pool'?'释放日期开始':'添加日期开始');$('[data-filter-date-to]').setAttribute('aria-label',state.view==='customer-pool'?'释放日期结束':'添加日期结束');
    $('[data-workflow-head]').innerHTML=cols();$('[data-workflow-body]').innerHTML=rows.length?rows.map(listRow).join(''):`<tr><td colspan="${count}" class="workflow-empty">${state.items.length?'没有符合筛选条件的记录。可清空筛选后重试。':`暂无${meta[state.view].title}数据。`}</td></tr>`;
    $('[data-workflow-count]').textContent=items.length===state.items.length?`${items.length} 条`:`${items.length} / ${state.items.length} 条`;$('[data-page-summary]').textContent=items.length?`第 ${(state.page-1)*state.size+1}–${Math.min(state.page*state.size,items.length)} 条，共 ${items.length} 条`:'共 0 条';$('[data-page-number]').textContent=`${state.page} / ${Math.max(1,Math.ceil(items.length/state.size))}`;const jump=$('[data-page-jump-input]');jump.max=String(Math.max(1,Math.ceil(items.length/state.size)));jump.value=String(state.page);$('[data-sort-added]')?.addEventListener('click',()=>{if(state.loading||state.busy)return;const direction=sortMode()==='recent'?'asc':'desc';$('[data-workflow-sort]').value='recent';state.sortDirection=direction;changeFilter();});$('[data-sort-updated]')?.addEventListener('click',()=>{if(state.loading||state.busy)return;state.sortDirection=sortMode()===dateSort()&&state.sortDirection==='desc'?'asc':'desc';$('[data-workflow-sort]').value=dateSort();changeFilter();});$('[data-sort-grade]')?.addEventListener('click',()=>{if(state.loading||state.busy)return;const direction=sortMode()==='grade'&&state.sortDirection==='asc'?'desc':'asc';$('[data-workflow-sort]').value='grade';state.sortDirection=direction;changeFilter();});syncSelection();setBusy(state.busy);$('[data-reset-filters]').disabled=state.busy||state.loading||$('[data-reset-filters]').dataset.inactive==='true';$('[data-page-prev]').disabled=state.loading||state.busy||state.page===1;$('[data-page-next]').disabled=state.loading||state.busy||state.page*state.size>=items.length;
  }
  async function load(){const c=context(),version=++loadVersion;controller?.abort();controller=new AbortController();state.selected.clear();state.loading=true;
    const changed=loadedContext!==contextKey(c);if(changed){state.items=[];state.admin=false;state.owners=[];closeDetail();render();}setBusy(state.busy);
    if(!c.project){state.loading=false;state.items=[];render();return;}
    try{const d=await api(baseFor(c),{signal:controller.signal});if(version!==loadVersion||!sameContext(c))return;state.items=d.items||d.customers||[];state.admin=!!d.is_top_admin;state.owners=d.owners||[];loadedContext=contextKey(c);ownerSelect();if(Array.isArray(d.country_options)){countryOptions=d.country_options;countryLookup=new Map(countryOptions.flatMap(row=>[row.name,...row.aliases].map(alias=>[countryKey(alias),row])));}countryFacet();typeFacet();sourceTypeFacet();const m=changed?restoreMemory():null;

      state.loading=false;render();if(pendingCustomerOpen&&c.view==='contacts'){const id=pendingCustomerOpen;pendingCustomerOpen=null;openDetail(id);}if(m)$('.workflow-table-wrap').scrollTop=m.scroll||0;}
    catch(e){if(e.name==='AbortError'||version!==loadVersion)return;state.loading=false;render();toast(`加载失败：${e.message}`,'error');$('[data-workflow-body]').innerHTML=`<tr><td colspan="${['contacts','leads'].includes(state.view)?11:6}" class="workflow-empty">${esc(e.message)} <button type="button" data-retry-workflow>重新加载</button></td></tr>`;}
    finally{if(version===loadVersion){state.loading=false;root.setAttribute('aria-busy',String(state.busy));}}
  }
  function field(name,label,type='text',wide=false,placeholder=''){const required=name==='company_name', limits={company_name:260,country:120,customer_source:160,contact_name:160,email:260,phone:80,whatsapp:80};return `<label class="${wide?'wide':''}">${label}${required?'<span class="workflow-required" aria-hidden="true">*</span>':''}<input name="${name}" type="${type}" ${required?'required':''} maxlength="${limits[name.replace(/^person_\d+_/,'')]||500}" ${name==='country'?'list="workflow-country-editor-options" autocomplete="off"':''} placeholder="${name==='country'?'输入国家名称，可搜索或填写':placeholder}"></label>`}
  const socials=[['linkedin','LinkedIn'],['facebook','Facebook'],['instagram','Instagram'],['youtube','YouTube']];
  function socialFields(prefix=''){return socials.map(([key,label])=>field(prefix+key,label+' 主页','url')).join('');}
  function socialDisclosure(fields,item={},prefix=''){const count=socials.filter(([key])=>detailValue(item[prefix+key])).length;return `<details class="wide workflow-social-disclosure" ${count?'open':''}><summary>社交主页<small>${count?`已填写 ${count} 项`:'按需补充'}</small></summary><div class="form-grid">${fields}</div></details>`;}
  function socialValues(item,prefix=''){return socials.filter(([key])=>item[prefix+key]).map(([key,label])=>[label,item[prefix+key],'web']);}
  function contactPeople(item){
    if(Array.isArray(item.contacts))return [...item.contacts].sort((a,b)=>Number(b.is_primary)-Number(a.is_primary));
    const person={contact_name:item.contact_name||'',email:item.email||'',phone:item.phone||'',whatsapp:item.whatsapp||'',notes:item.other_channels||'',is_primary:true};
    return ['contact_name','email','phone','whatsapp','notes'].some(key=>String(person[key]).trim())?[person]:[];
  }
  function appendPerson(person={},persisted=false){
    const form=$('[data-workflow-form]'),list=form.querySelector('[data-person-list]'),index=Number(list.dataset.nextIndex||0);list.dataset.nextIndex=String(index+1);
    const card=document.createElement('article');card.className='customer-person-editor';card.dataset.personCard='';if(person.id)card.dataset.personId=String(person.id);
    const input=(key,label,type='text')=>field(index===0?key:`person_${index}_${key}`,label,type).replace('<input ',`<input data-person-field="${key}" `);
    const panelId=`workflow-person-extra-${index}`;
    card.innerHTML=`<div class="person-compact-row">
      <span class="person-row-number" data-person-number></span>
      <div class="form-grid person-core-fields">${input('contact_name','联系人')}${input('email','邮箱','email')}${input('phone','电话')}${input('whatsapp','WhatsApp')}</div>
      <div class="person-row-actions">
        <label class="person-primary-choice"><input type="radio" name="primary_contact" value="${index}" data-person-primary ${person.is_primary||index===0?'checked':''}><span>主联系人</span></label>
        <button type="button" data-person-more aria-expanded="false" aria-controls="${panelId}">更多</button>
        <button type="button" data-person-remove class="danger">删除联系人</button>
      </div>
    </div>
    <div id="${panelId}" class="form-grid person-extra-fields" data-person-extra hidden>
      <label class="wide">联系人备注<textarea name="${index===0?'other_channels':`person_${index}_notes`}" data-person-field="notes" maxlength="5000" rows="2" placeholder="职务、沟通偏好等"></textarea></label>
      ${socials.map(([key,label])=>input(key,label+' 主页','url')).join('')}
    </div>`;
    card.querySelectorAll('[data-person-field]').forEach(el=>el.value=person[el.dataset.personField]||'');list.append(card);
    const extra=card.querySelector('[data-person-extra]'),more=card.querySelector('[data-person-more]');
    function updateMore(){
      const filled=[...extra.querySelectorAll('[data-person-field]')].filter(field=>field.value.trim()).length;
      more.textContent=extra.hidden?(filled?`更多 · ${filled}`:'更多'):'收起';
      more.setAttribute('aria-expanded',String(!extra.hidden));
    }
    more.addEventListener('click',()=>{extra.hidden=!extra.hidden;updateMore();});
    extra.addEventListener('input',updateMore);
    extra.addEventListener('invalid',()=>{extra.hidden=false;updateMore();},true);
    updateMore();
    card.querySelector('[data-person-remove]')?.addEventListener('click',()=>{if(person.id||persisted){if(!window.confirm(`确认删除联系人“${person.contact_name||'未填写联系人'}”吗？删除将在保存资料后生效，历史跟进保留。`))return;if(person.id){const deleted=form.elements.deleted_contacts;deleted.value=JSON.stringify([...JSON.parse(deleted.value||'[]'),person.id]);}}const primary=card.querySelector('[data-person-primary]').checked;card.remove();if(primary&&list.querySelector('[data-person-primary]'))list.querySelector('[data-person-primary]').checked=true;syncPersonChoices();});
    card.querySelector('[data-person-primary]').addEventListener('change',syncPersonChoices);syncPersonChoices();return card;
  }
  function syncPersonChoices(){
    const form=$('[data-workflow-form]'),cards=form.querySelectorAll('[data-person-card]');
    cards.forEach((card,index)=>{
      const name=`联系人 ${index+1}`;
      card.setAttribute('aria-label',name);
      card.querySelector('[data-person-number]').textContent=String(index+1);
      card.querySelector('[data-person-primary]').setAttribute('aria-label',`将${name}设为主联系人`);
      card.querySelector('[data-person-remove]').setAttribute('aria-label',`删除${name}`);
    });
    form.querySelector('[data-person-add-next]').hidden=cards.length<2;
  }
  function collectPeople(form){return [...form.querySelectorAll('[data-person-card]')].map(card=>({...Object.fromEntries([...card.querySelectorAll('[data-person-field]')].map(el=>[el.dataset.personField,el.value])),...(card.dataset.personId?{id:Number(card.dataset.personId)}:{}),is_primary:card.querySelector('[data-person-primary]').checked}));}
  function companyNotesEditor(view){
    if(!['leads','contacts'].includes(view))return '<label class="wide">公司备注<textarea name="notes" maxlength="20000" rows="6" placeholder="业务、采购需求或待核实事项"></textarea></label>';
    return `<div class="wide company-notes-field">
      <div class="company-notes-toolbar">
        <div class="company-notes-title"><label for="workflow-company-notes">公司备注</label><small>Markdown</small></div>
        <div class="company-notes-actions">
          <button type="button" data-notes-table><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="3" width="11" height="10" rx="1.5"/><path d="M2.5 6.5h11M8 6.5V13"/></svg>插入表格</button>
          <button type="button" data-notes-toggle aria-controls="workflow-notes-preview" aria-expanded="false">预览</button>
        </div>
      </div>
      <textarea id="workflow-company-notes" name="notes" maxlength="20000" rows="6" placeholder="业务、采购需求或待核实事项"></textarea>
      <div id="workflow-notes-preview" class="company-notes-render" aria-label="公司备注预览" hidden></div>
    </div>`;
  }
  function renderCompanyNotes(value){
    return window.TophooMarkdown?.render(value) ?? `<p>${esc(value)}</p>`;
  }
  function bindCompanyNotesEditor(form){
    const input=form.elements.notes, preview=form.querySelector('#workflow-notes-preview');
    if(!preview)return;
    const toggle=form.querySelector('[data-notes-toggle]'), insert=form.querySelector('[data-notes-table]');
    toggle.onclick=()=>{
      const show=preview.hidden;
      if(show)preview.innerHTML=renderCompanyNotes(input.value);
      preview.hidden=!show;
      input.hidden=show;
      insert.hidden=show;
      toggle.textContent=show?'返回编辑':'预览';
      toggle.setAttribute('aria-expanded',String(show));
      if(!show)input.focus();
    };
    insert.onclick=()=>{
      const {selectionStart:start,selectionEnd:end,value}=input;
      const before=value.slice(0,start), after=value.slice(end);
      const prefix=before ? (before.endsWith('\n\n')?'':before.endsWith('\n')?'\n':'\n\n') : '';
      const suffix=after ? (after.startsWith('\n\n')?'':after.startsWith('\n')?'\n':'\n\n') : '\n';
      const table=prefix+'| 项目 | 内容 |\n| --- | --- |\n| 示例 | 在这里填写 |'+suffix;
      if(value.length-end+start+table.length>input.maxLength)return toast('公司备注已接近字数上限，无法插入表格。','error');
      input.focus();
      input.setRangeText(table,start,end,'end');
      const cell=start+prefix.length+2;
      input.setSelectionRange(cell,cell+2);
    };
  }
  function openForm(item={},c=context()){personEdit=null;
    if((state.loading&&!c.verification)||state.busy)return;previousFocus=document.activeElement;editContext=c;state.editing=item.id||null;const form=$('[data-workflow-form]');
    const entity=c.view==='leads'?'线索':c.view==='contacts'?'客户':c.view==='prospecting'?'搜客':'客户';
    $('[data-form-title]').textContent=(state.editing?'编辑':'新增')+entity;$('[data-form-kicker]').textContent=c.verification?'客户查证':'公司与联系人资料';
    const grades='<option value="">未分级 · 待评估</option>'+Object.keys(gradeNames).map(x=>`<option value="${x}">${gradeLabel(x)}</option>`).join('');
    const owner=c.verification?(item.owner_user_id?`<input type="hidden" name="owner_user_id" value="${Number(item.owner_user_id)}">`:''):state.admin?`<label class="form-owner">归属<select name="owner_user_id"><option value="">当前用户（默认）</option>${state.owners.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}${item.owner_user_id&&!state.owners.some(x=>x.id===item.owner_user_id)?`<option value="${Number(item.owner_user_id)}">${esc(item.owner_name||'原负责人')}</option>`:''}</select></label>`:'';
    const source=`<label class="form-source-method">来源方式<input name="source_type" list="crm-source-methods" maxlength="40" placeholder="选择或输入来源"><datalist id="crm-source-methods">${sourceTypeChoices().map(value=>`<option value="${esc(value)}"></option>`).join('')}</datalist></label><input type="hidden" name="customer_source" value="${esc(item.customer_source||item.source||'')}">`;
    const followupTransfer=!c.verification&&state.admin&&c.view==='contacts'&&item.id?'<label class="followup-transfer"><input type="checkbox" name="transfer_followups" checked><span>归属变更时转交待完成跟进；不勾选则取消原计划</span></label>':'';
    const keyFields=(c.view==='contacts'?`<label>产品类别<input name="product_category" maxlength="160" placeholder="例如：换热器、制冷配件"></label>`:'')+(['leads','contacts'].includes(c.view)?`<label class="form-grade">分级<select name="grade" aria-describedby="customer-grade-help">${grades}</select></label>`:'')+owner;
    const gradeGuidance=['leads','contacts'].includes(c.view)?'<div class="customer-grade-guidance wide" id="customer-grade-help"><p data-grade-hint></p><small>分级按订单、样单及潜力评估。</small></div>':'';
    const sectionHead=(number,title,hint)=>`<div class="workflow-form-section-head"><span aria-hidden="true">${number}</span><div><h3>${title}</h3></div></div>`;
    $('[data-workflow-form-fields]').innerHTML=`<p class="workflow-form-intro">仅公司名称必填，其他信息可后续补充。</p>
      <section class="form-group workflow-form-company">${sectionHead('01','公司资料','记录企业基本信息，线索转为客户时保留。')}<div class="form-grid">${field('company_name','公司名称','text',false,'填写公司名称')}${field('company_website','公司官网','url',false,'https://')}${field('country','国家')}<datalist id="workflow-country-editor-options">${countryOptions.map(row=>`<option value="${esc(row.name)}"></option>`).join('')}</datalist><label>企业类型<input name="company_type" list="crm-company-types" maxlength="80" placeholder="例如：制造商、贸易商、工程承包商"><datalist id="crm-company-types">${companyTypes.suggestions()}</datalist></label>${field('company_address','公司地址','text',true)}${socialDisclosure(socialFields('company_'),item,'company_')}${companyNotesEditor(c.view)}</div></section>
      ${['leads','contacts'].includes(c.view)?`<section class="workflow-form-time" aria-label="当前时间"><span>客户当地时间</span><div class="workflow-local-clock" data-form-clock>${localClockContent(item.local_clock||{hint:'保存地区后可查看当地时间'})}</div></section>`:''}
      <section class="form-group workflow-form-management">${sectionHead('02',c.view==='contacts'?'客户管理':c.view==='leads'?'线索管理':'来源','记录来源方式、分类和归属。')}<div class="form-grid">${source}${c.view==='leads'?'<label>开发时间<input type="date" name="development_date"></label>':''}${keyFields}${['leads','contacts'].includes(c.view)?`<div class="workflow-research-form-field"><span>是否人工背调</span><input type="hidden" name="is_manually_researched" value="${!!item.is_manually_researched}">${manualResearchButton(item.is_manually_researched,'data-form-manual-research')}</div>`:''}</div>${gradeGuidance}${followupTransfer}</section>
      <section class="form-group workflow-form-people"><div class="person-section-heading">${sectionHead('03','联系人信息','每位联系人的联系方式和备注单独保存。')}<button type="button" data-person-add>＋ 新增联系人</button></div><input type="hidden" name="deleted_contacts" value="[]"><div data-person-list></div><div class="person-list-footer"><button type="button" data-person-add-next hidden>＋ 继续添加联系人</button></div></section>`;
    const formClock=$('[data-workflow-form-fields]').querySelector('[data-form-clock]');
    if(formClock){const countryInput=form.elements.country;countryInput?.addEventListener('input',()=>{formClock.innerHTML=localClockContent(countryInput.value===(item.country||'')?item.local_clock:{hint:'保存地区后可查看当地时间'});});}
    form.reset();Object.entries(item).forEach(([k,v])=>{if(form.elements[k])form.elements[k].value=v??''});if(c.view==='prospecting'&&!state.editing)form.elements.source_type.value='自主开发';$('[data-workflow-dialog]').hidden=false;form.dataset.mode=state.editing?'edit':'new';{(item.id?contactPeople(item):[{}]).forEach(person=>appendPerson(person,!!item.id));form.querySelector('[data-person-add]').onclick=form.querySelector('[data-person-add-next]').onclick=()=>{if(form.querySelectorAll('[data-person-card]').length>=100)return toast('每个客户最多支持 100 位联系人。','error');const card=appendPerson();card.querySelector('input[data-person-field]').focus();};}formSnapshot=formValue();form.elements.company_name?.focus();form.scrollTop=0;
    bindCompanyNotesEditor(form);
    const researchButton=form.querySelector('[data-form-manual-research]');if(researchButton)researchButton.onclick=()=>{const reviewed=form.elements.is_manually_researched.value!=='true';form.elements.is_manually_researched.value=String(reviewed);researchButton.setAttribute('aria-pressed',String(reviewed));researchButton.title=reviewed?'已人工背调，点击取消标记':'未人工背调，点击点亮标记';researchButton.lastElementChild.textContent=reviewed?'已背调':'未背调';};
    if(form.elements.grade){const select=form.elements.grade,hint=form.querySelector('[data-grade-hint]');const update=()=>{hint.textContent=gradeHint(select.value);};select.addEventListener('change',update);update();}
  }

  async function save(e){e.preventDefault();if(personEdit)return savePerson(e);if(state.busy||!editContext)return;const detailId=state.detailId,c={...editContext},f=e.currentTarget,data=Object.fromEntries(new FormData(f)),editing=state.editing;if(c.verification?!c.verification.current()||c.project!==pid():!sameContext(c))return toast('项目或列表已切换，请重新打开编辑。','error');if(c.view!=='customer-pool'){data.contacts=collectPeople(f);data.deleted_contact_ids=JSON.parse(data.deleted_contacts||'[]');delete data.deleted_contacts;for(const key of Object.keys(data))if(key.startsWith('person_')||key==='primary_contact')delete data[key];}if('development_date' in data)data.development_date=data.development_date||null;if('is_manually_researched' in data)data.is_manually_researched=data.is_manually_researched==='true';if(data.owner_user_id)data.owner_user_id=+data.owner_user_id;else delete data.owner_user_id;if(c.view==='contacts'&&f.elements.transfer_followups)data.transfer_followups=f.elements.transfer_followups.checked;setBusy(true);
    try{const saved=await api(baseFor(c)+(editing?`/${editing}`:''),{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});close(true);if(c.verification){c.verification.saved(saved);return;}toast(editing?'资料已更新':'资料已新增');if(sameContext(c)){if(!editing){state.page=1;state.customerQuickFilter='';for(const selector of ['[data-workflow-owner]','[data-filter-country]','[data-filter-manual-research]','[data-filter-company-type]','[data-filter-source-type]','[data-filter-product-category]','[data-filter-grade]','[data-filter-followup]','[data-filter-contacted]','[data-filter-completeness]','[data-workflow-search]','[data-filter-date-from]','[data-filter-date-to]','[data-filter-development-from]','[data-filter-development-to]'])$(selector).value='';$('[data-workflow-sort]').value=defaultSort();state.sortDirection=defaultDirection();}await load();}}catch(err){toast(err.message,'error');}finally{setBusy(false);if(!c.verification){render();if(detailId&&sameContext(c)&&$('[data-workflow-dialog]').hidden)openDetail(detailId);}}}
  async function mainAction(id){return runMain([id]);}
  async function runMain(ids){if(state.busy||state.loading)return;const c=context(),v=c.view;
    const names=ids.map(id=>state.items.find(x=>x.id===id)?.company_name||'').slice(0,3).map(esc).join('、'),summary=`<p>将处理已选择的 ${ids.length} 条资料：${names}${ids.length>3?'…':''}。</p>`;
    let content=summary,confirmText=meta[v].main;
    if(v==='contacts')content+='<label>释放原因<textarea name="reason" required maxlength="5000" placeholder="本次选中的客户统一使用此原因"></textarea></label>';
    if(v==='customer-pool')content+=state.admin?`<label>恢复后归属<select name="owner_user_id"><option value="">各自原负责人</option>${state.owners.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></label>`:'<p>恢复后将归属给你。</p>';
    if(v==='leads'){
      setBusy(true);
      try{const preview=await api(`${baseFor(c)}/batch/conversion-preview`,{method:'POST',body:JSON.stringify({ids})});if(!sameContext(c))return;
        content+=`<div class="lead-conversion-preview">${preview.items.map(item=>`<p><strong>${esc(item.company_name)}</strong><br>${item.mode==='blocked'?`无法转换：${esc(item.message)}`:item.mode==='merged'?`合并到：${esc(item.customer_name)}`:'新建客户'}</p>`).join('')}</div><p>原线索资料保存到转换历史；联系记录的原文、翻译和时间完整迁移。分级随线索转入；合并时已有的客户分级优先。提交时会重新核实匹配结果。</p>`;
        if(!preview.can_convert){toast('存在转换冲突，请查看提示后处理。','error');await actionDialog({title:'转换前检查',content,confirm:'知道了'});return;}
      }catch(error){toast(error.message,'error');return;}finally{setBusy(false);render();}
    }
    const data=await actionDialog({title:confirmText,content:content+(v==='contacts'?'<p>释放后将取消此客户在当前项目的待完成跟进计划，历史记录保留。</p>':''),confirm:confirmText,danger:v==='contacts'});if(!data||!sameContext(c))return;if(v==='contacts'&&!data.reason?.trim())return;
    setBusy(true);let completed=[];
    try{if(v==='contacts'||v==='customer-pool'){
      for(const id of ids){const url=v==='contacts'?`/api/contacts/projects/${c.project}/${id}/release`:`/api/customer-workflow/projects/${c.project}/pool/${id}/restore`;const body=v==='contacts'?{reason:data.reason.trim()}:{owner_user_id:data.owner_user_id?+data.owner_user_id:null};await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});completed.push(id);}
    }else{await api(`${baseFor(c)}/batch/${v==='prospecting'?'to-leads':'to-customers'}`,{method:'POST',body:JSON.stringify({ids})});completed=ids;}
    closeDetail();toast(`已${v==='contacts'?'放入公池':v==='customer-pool'?'恢复客户':v==='leads'?'转为客户':'放入线索'} ${completed.length} 条资料`);
    }catch(e){toast(`${completed.length?`已完成 ${completed.length} 条；剩余 ${ids.length-completed.length} 条未完成。`:''}${e.message}`,'error');}
    finally{if(sameContext(c)){await load();state.selected=new Set(ids.filter(id=>!completed.includes(id)&&shown().some(x=>x.id===id)));}setBusy(false);render();}
  }
  async function remove(id){return deleteItems([id]);}
  async function deleteItems(ids){if(state.busy||state.loading||state.view==='contacts')return;const c=context();const yes=await actionDialog({title:ids.length>1?'批量删除':'删除资料',content:`<p>确定删除 ${ids.length} 条资料吗？删除后无法恢复。</p>`,confirm:'确认删除',danger:true});if(!yes||!sameContext(c))return;setBusy(true);try{await api(`${baseFor(c)}/batch/delete`,{method:'POST',body:JSON.stringify({ids})});closeDetail();toast(`已删除 ${ids.length} 条资料`);if(sameContext(c))await load();}catch(e){toast(e.message,'error');}finally{setBusy(false);render();}}
  async function batch(main){const ids=[...state.selected];if(ids.length)return main?runMain(ids):deleteItems(ids);}
  function closeDetail(restoreFocus=false){++detailVersion;$('[data-workflow-detail]').hidden=true;state.detailId=null;if(restoreFocus&&detailFocus?.isConnected)detailFocus.focus();}
  window.tophooLeadWrite=async(url,options,id)=>{
    if(state.busy||state.loading)throw Error('正在处理，请稍候。');const c=context();setBusy(true);
    try{const result=await api(url,options);if(sameContext(c))await load();return result;}
    finally{setBusy(false);render();if(sameContext(c)&&state.detailId===id)openDetail(id,false);}
  };
  function safeLink(value,kind,label=value){if(!value)return '—';const raw=String(value).trim(),href=kind==='web'?(/^https?:\/\//i.test(raw)?raw:`https://${raw}`):`${kind==='mail'?'mailto':'tel'}:${raw}`;return `<a href="${esc(href)}" ${kind==='web'?'target="_blank" rel="noopener noreferrer"':''}>${esc(label)}</a>`;}
  const detailValue = value => value != null && String(value).trim() !== '';
  function detailFacts(fields){return `<dl class="customer-detail-facts">${fields.filter(([,value])=>detailValue(value)).map(([label,value,kind])=>`<div${['公司名称','公司地址','公司官网'].includes(label)?' class="is-wide"':''}><dt>${label}</dt><dd>${kind==='grade'?`<span class="grade grade-${esc((value||'x').slice(0,1).toLowerCase())}">${esc(value)}</span>`:kind?safeLink(value,kind):esc(value)}</dd></div>`).join('')}</dl>`;}
  function customerOverview(item){
    const fields=[['国家',item.country],['企业类型',item.company_type?companyTypes.label(item.company_type):''],['人工背调',item.is_manually_researched?'已人工背调':'未人工背调'],['公司官网',item.company_website,'web'],['公司地址',item.company_address]];
    const socials=socialValues(item,'company_').filter(([,value])=>detailValue(value));
    return `<section class="workflow-company-section customer-detail-section customer-detail-company" data-detail-company aria-label="公司资料"><header class="customer-detail-section-head"><h3>公司资料</h3></header>${detailFacts(fields)}${socials.length?`<div class="customer-detail-socials"><span>公司社交主页</span>${socials.map(([label,value,kind])=>safeLink(value,kind,label+' ↗')).join('')}</div>`:''}${customerNotes(item)}</section>`;
  }
  function customerManagement(item,lead=false){
    const heading=lead?'线索管理':'客户管理';
    const fields=[
      ['来源方式',sourceTypeOf(item)||'未填写'],
      ...(!lead?[['产品类别',item.product_category||'未填写']]:[]),
      [lead?'分级':'客户分级',gradeLabel(item.grade),'grade'],
      ...(state.admin?[['归属',item.owner_name||'未分配']]:[]),
      ...(lead?[['联系状态',leadStatuses[leadStatus(item)]],['开发时间',item.development_date||'未填写']]:[]),
    ];
    return `<section class="customer-detail-section customer-detail-management" data-detail-management aria-label="${heading}"><header class="customer-detail-section-head"><h3>${heading}</h3></header>${detailFacts(fields)}<div class="customer-detail-audit">${lead?`<span>资料完整度 ${completeness(item).score}%</span>`:''}<span>添加 ${esc(date(addedAt(item)))}</span>${item.updated_at?`<span>更新 ${esc(String(item.updated_at).slice(0,16).replace('T',' '))}</span>`:''}</div></section>`;
  }
  function customerNotes(item){return detailValue(item.notes)?`<div class="customer-company-notes" data-detail-notes><h4>公司备注</h4><div class="company-notes-render">${renderCompanyNotes(item.notes)}</div></div>`:'';}
  function customerDetailActions(id){
    return `<div class="customer-detail-left-actions"><button type="button" class="customer-detail-primary" data-detail-edit="${id}">编辑</button><button type="button" class="danger" data-detail-main="${id}">放入公池</button></div>`;
  }
  function leadDetailActions(id){
    return `<div class="lead-detail-actions"><button type="button" class="lead-action-edit" data-detail-edit="${id}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 4 3.5 3.5M4 13l-.7 3.7L7 16l9.2-9.2a1.5 1.5 0 0 0 0-2.1l-.9-.9a1.5 1.5 0 0 0-2.1 0L4 13Z"/></svg>编辑</button><button type="button" class="lead-action-convert" data-detail-main="${id}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M11 4H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6M9 10h8m-3-3 3 3-3 3"/></svg>转为客户</button><button type="button" class="danger lead-action-delete" data-detail-delete="${id}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14M7 5V3h6v2M5 5l.7 11h8.6L15 5M8 8v5m4-5v5"/></svg>删除</button></div>`;
  }
  async function openDetail(id,focus=true){const item=state.items.find(x=>x.id===id);if(!item||state.loading||state.busy)return;const c=context(),version=++detailVersion,overlay=$('[data-workflow-detail]'),resetScroll=overlay.hidden||state.detailId!==id;state.detailId=id;remember();if(overlay.hidden)detailFocus=document.activeElement;overlay.dataset.detailView=c.view;overlay.hidden=false;$('[data-detail-title]').textContent=item.company_name;$('[data-detail-kicker]').textContent=c.view==='contacts'?'客户详情':c.view==='leads'?'线索详情':meta[state.view].title;
    const fields=[['公司名称',item.company_name],['国家',item.country],['企业类型',companyTypes.label(item.company_type)],['人工背调',item.is_manually_researched?'已人工背调':'未人工背调'],['公司官网',item.company_website,'web'],['公司地址',item.company_address],...socialValues(item,'company_').map(([label,value,kind])=>['公司 '+label,value,kind]),['来源方式',item.source_type],...(state.admin?[['归属',item.owner_name]]:[]),...(['contacts','customer-pool'].includes(state.view)?[['产品类别',item.product_category],['客户分级',gradeLabel(item.grade)]]:[]),['添加日期',date(addedAt(item))],['修改日期',String(item.updated_at||'').slice(0,16).replace('T',' ')],['公司备注',item.notes],...(state.view==='customer-pool'?[['释放原因',item.release_reason],['释放日期',date(item.released_at)],['释放人',item.released_by_name]]:[])];
    if(state.view==='leads')fields.unshift(['当前状态',leadStatuses[leadStatus(item)]]);
    $('[data-detail-content]').innerHTML=c.view==='contacts'?`${customerOverview(item)}${customerManagement(item)}${peoplePanel(item,true)}`:c.view==='leads'?`${customerOverview(item)}${customerManagement(item,true)}${peoplePanel(item,true,true)}`:`<section class="workflow-company-section" data-detail-company aria-labelledby="workflow-company-heading"><header class="workflow-section-heading"><h3 id="workflow-company-heading">客户信息</h3><span>公司资料</span></header><dl class="workflow-detail-fields">${fields.map(([label,value,kind])=>`<div><dt>${label}</dt><dd>${kind?safeLink(value,kind):esc(value)||'—'}</dd></div>`).join('')}</dl></section>${peoplePanel(item,true,true)}`;
    if(resetScroll)$('[data-detail-content]').scrollTop=0;
    $('[data-detail-customer-search]').hidden=!['leads','contacts'].includes(c.view);
    $('[data-detail-actions]').innerHTML=c.view==='contacts'?customerDetailActions(id):c.view==='leads'?leadDetailActions(id):`<button type="button" class="danger" data-detail-delete="${id}">删除资料</button><button type="button" data-detail-main="${id}">${meta[c.view].main}</button>`;if(focus)overlay.querySelector('button[data-detail-close]')?.focus();document.dispatchEvent(new CustomEvent('tophoo-workflow-detail-ready',{detail:{...c,id,item}}));

  }
  function openVerification(id){
    const c=context(),item=state.items.find(x=>x.id===id);
    if(!item||!['leads','contacts'].includes(c.view)||!document.querySelector('[data-customer-search]'))return;
    if(state.detailId!==null)closeDetail();
    document.dispatchEvent(new CustomEvent('tophoo-customer-search-import',{detail:{...c,item}}));
  }
  $('[data-detail-customer-search]').addEventListener('click',()=>openVerification(state.detailId));
  document.addEventListener('tophoo-verification-edit', async ({detail}) => {
    const {project, view, id, current, ready} = detail;
    if (project !== pid() || !['leads','contacts'].includes(view) || !Number.isInteger(id) || id < 1 || !current()) return;
    const dialog = $('[data-workflow-dialog]');
    if (state.busy || !dialog.hidden) {
      ready('请先完成当前编辑。');
      return;
    }
    const c = {project, view, verification: detail};
    try {
      const item = await api(`${baseFor(c)}/${id}${view === 'contacts' ? '/preview' : ''}`);
      if (!current() || project !== pid()) return;
      ready('');
      if (state.busy || !dialog.hidden) return;
      dialog.dataset.permissionModule = view === 'leads' ? 'leads' : 'customer_list';
      openForm(item, c);
    } catch (error) {
      ready(error.message);
    }
  });
  function syncLeadExport(){
    const button=$('[data-leads-export]'),count=state.view==='leads'?filtered().length:0;
    button.hidden=state.view!=='leads';
    button.disabled=state.loading||state.busy||exportingLeads||!count;
    button.title='导出当前检索结果：公司名称、公司官网、国家、公司备注、联系人信息、跟进';
    button.textContent=exportingLeads?'正在导出…':`导出 Excel · ${count} 条`;
  }
  function leadExportScope(){
    const parts=[];
    const search=$('[data-workflow-search]').value.trim();if(search)parts.push('搜索：'+search);
    for(const selector of ['[data-filter-country]','[data-filter-manual-research]','[data-filter-company-type]','[data-filter-source-type]','[data-filter-contacted]','[data-filter-completeness]',...(state.admin?['[data-workflow-owner]']:[])]){
      const field=$(selector);if(field.value)parts.push(field.closest('label').firstChild.textContent.trim()+'：'+(field.tagName==='SELECT'?field.selectedOptions[0].textContent:field.value));
    }
    const from=$('[data-filter-date-from]').value,to=$('[data-filter-date-to]').value;
    if(from||to)parts.push(`添加日期：${from||'不限'} 至 ${to||'不限'}`);
    const developmentFrom=$('[data-filter-development-from]').value,developmentTo=$('[data-filter-development-to]').value;
    if(developmentFrom||developmentTo)parts.push('开发时间：'+(developmentFrom||'不限')+' 至 '+(developmentTo||'不限'));
    const sort=$('[data-workflow-sort]');
    return (parts.length?parts.join('；'):'筛选：全部线索')+'；排序：'+sort.selectedOptions[0].textContent+' '+$('[data-sort-direction]').textContent;
  }
  async function exportLeadResults(){
    if(state.view!=='leads'||state.loading||state.busy||exportingLeads)return;
    const c=context(),items=filtered();if(!items.length)return;
    // Snapshot all matches in their displayed order, before pagination/selection.
    const payload={ids:items.map(item=>item.id),scope:leadExportScope()};
    exportingLeads=true;syncLeadExport();
    try{
      const response=await fetch(`${baseFor(c)}/export/xlsx`,{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw Error(typeof body.detail==='string'?body.detail:'导出 Excel 失败，请重试。');}
      const blob=await response.blob();if(!sameContext(c))return;
      const now=new Date(),stamp=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`线索列表_检索结果_${stamp}.xlsx`;
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
      toast(`已导出 ${items.length} 条线索`);
    }catch(error){if(sameContext(c))toast(error.message,'error');}
    finally{exportingLeads=false;syncLeadExport();}
  }

  function customerPeoplePanel(customer,readonly=false){
    const people=contactPeople(customer);
    return `<section class="drawer-people customer-detail-section" data-people-customer="${customer.id}" data-detail-people><div class="people-panel-heading"><h2>联系人信息 · ${people.length} 位</h2>${readonly?`<button type="button" ${state.view==='leads'?'data-detail-contacts':'data-detail-edit'}="${customer.id}">编辑联系人</button>`:'<button type="button" data-person-new>＋ 新增联系人</button>'}</div>${people.length?people.map(person=>{
      const facts=[['邮箱',person.email,'mail'],['电话',person.phone,'phone'],['WhatsApp',person.whatsapp]].filter(([,value])=>detailValue(value)),links=socialValues(person);
      return `<article class="profile-person"><h3>${esc(person.contact_name)||'未填写联系人'}${person.is_primary?'<span class="person-primary-badge">主联系人</span>':''}</h3>${state.view==='leads'?`<div class="lead-contact-outreach" data-detail-outreach-email="${esc((person.email||'').trim())}" role="status">${person.email?'开发信数量读取中…':'无邮箱 · 暂无法统计'}</div>`:''}${facts.length?`<div class="profile-fields">${facts.map(([label,value,kind])=>`<div><small>${label}</small><strong>${safeLink(value,kind)}</strong></div>`).join('')}</div>`:'<p class="customer-detail-empty">暂未填写联系方式</p>'}${links.length?`<div class="customer-detail-socials">${links.map(([label,value,kind])=>safeLink(value,kind,label+' ↗')).join('')}</div>`:''}${detailValue(person.notes)?`<p class="customer-person-note"><span>联系人备注</span>${esc(person.notes)}</p>`:''}<div class="person-card-actions">${!readonly&&person.id?`<button type="button" data-person-edit="${person.id}">编辑联系人</button>${person.is_primary?'':`<button type="button" data-person-set-primary="${person.id}">设为主联系人</button>`}<button type="button" class="danger" data-person-delete="${person.id}">删除</button>`:''}</div></article>`;
    }).join(''):`<div class="people-empty">${readonly?'暂无联系人，可通过编辑资料补充。':'暂无联系人，可点击右上角新增。'}</div>`}</section>`;
  }
  function peoplePanel(customer,compact=false,readonly=false){
    if(compact&&['contacts','leads'].includes(state.view))return customerPeoplePanel(customer,readonly);
    const people=contactPeople(customer),empty=readonly?'暂无联系人信息，可通过编辑资料补充。':'暂无联系人，可新增联系人。客户资料和历史跟进仍保留。';
    return `<section class="${compact?'drawer-people':'profile-group profile-people'}" data-people-customer="${customer.id}" ${compact?'data-detail-people':''}><div class="people-panel-heading"><h2>联系人信息 · ${people.length} 位</h2>${readonly?'':'<button type="button" data-person-new>＋ 新增联系人</button>'}</div>${people.length?people.map(person=>`<article class="profile-person"><h3>${esc(person.contact_name)||'未填写联系人'}${person.is_primary?'<span class="person-primary-badge">主联系人</span>':''}</h3><div class="profile-fields">${[['邮箱',person.email,'mail'],['电话',person.phone,'phone'],['WhatsApp',person.whatsapp],...socialValues(person),['联系人备注',person.notes]].map(([label,value,kind])=>`<div><small>${label}</small><strong>${kind?safeLink(value,kind):esc(value)||'—'}</strong></div>`).join('')}</div><div class="person-card-actions">${!readonly&&person.id?`<button type="button" data-person-edit="${person.id}">编辑</button>`:''}${!readonly&&!person.is_primary&&person.id?`<button type="button" data-person-set-primary="${person.id}">设为主联系人</button>`:''}${!readonly&&person.id?`<button type="button" class="danger" data-person-delete="${person.id}">删除</button>`:''}</div></article>`).join(''):`<div class="people-empty">${empty}</div>`}</section>`;
  }
  function activeCustomer(id){return state.items.find(item=>item.id===id);}
  function openPersonForm(customer,person={}){
    if(state.busy||state.loading||!customer)return;previousFocus=document.activeElement;editContext=context();state.editing=null;personEdit={customerId:customer.id,personId:person.id||null,wasPrimary:!!person.is_primary};
    const form=$('[data-workflow-form]');$('[data-form-title]').textContent=person.id?'编辑联系人':'新增联系人';$('[data-form-kicker]').textContent=customer.company_name;
    $('[data-workflow-form-fields]').innerHTML=`<section class="form-group workflow-form-people"><div class="form-grid">${field('contact_name','联系人')}${field('email','邮箱','email')}${field('phone','电话')}${field('whatsapp','WhatsApp')}${socialDisclosure(socialFields(),person)}<label class="wide">联系人备注<textarea name="notes" maxlength="5000" rows="5" placeholder="职务、沟通偏好等"></textarea></label></div><label class="person-primary-choice single-primary-choice"><input type="checkbox" name="is_primary">设为主联系人</label><p class="person-form-hint">只保存这位联系人的资料。${contactPeople(customer).length?'':'首位联系人将自动成为主联系人。'}</p></section>`;
    form.reset();for(const key of ['contact_name','email','phone','whatsapp','notes',...socials.map(([key])=>key)])form.elements[key].value=person[key]||'';form.elements.is_primary.checked=!!person.is_primary||!contactPeople(customer).length;form.elements.is_primary.disabled=!!person.is_primary;form.dataset.mode='person';formSnapshot=formValue();$('[data-workflow-dialog]').hidden=false;form.elements.contact_name.focus();
  }
  function applyPersonResult(customer,c){
    if(!sameContext(c))return;const index=state.items.findIndex(item=>item.id===customer.id);if(index>=0)state.items[index]=customer;clearSelection();render();

  }
  async function savePerson(e){
    if(state.busy||!editContext||!personEdit)return;const c={...editContext},target={...personEdit},form=e.currentTarget,data=Object.fromEntries(new FormData(form));data.is_primary=form.elements.is_primary.checked;
    if(!sameContext(c))return toast('项目已切换，请重新打开联系人。','error');setBusy(true);let updated=null;
    try{updated=await api(`/api/contacts/projects/${c.project}/${target.customerId}/people${target.personId?`/${target.personId}`:''}`,{method:target.personId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(sameContext(c)){close(true);applyPersonResult(updated,c);toast('联系人已保存');}}
    catch(error){toast(error.message,'error');}finally{setBusy(false);if(personEdit&&form.elements.is_primary)form.elements.is_primary.disabled=!!activeCustomer(target.customerId)?.contacts?.find(person=>person.id===target.personId)?.is_primary;render();if(updated&&sameContext(c)&&state.detailId===target.customerId)openDetail(target.customerId);}
  }
  async function personAction(customer,person,operation){
    if(state.busy||state.loading||!customer||!person)return;const c=context();let replacement='';
    if(operation==='delete'){
      const others=contactPeople(customer).filter(item=>item.id!==person.id);const choose=person.is_primary&&others.length;
      const answer=await actionDialog({title:'删除联系人',content:`<p>确认删除“${esc(person.contact_name)||'未填写联系人'}”吗？客户资料和历史跟进会保留。</p>${choose?`<label>接替的主联系人<select name="replacement_id" required>${others.map(item=>`<option value="${item.id}">${esc(item.contact_name)||'未填写联系人'}${item.email?` · ${esc(item.email)}`:''}</option>`).join('')}</select></label>`:!others.length?'<p>删除后此客户将暂无联系人，可随时新增。</p>':''}`,confirm:'删除联系人',danger:true});
      if(!answer||!sameContext(c))return;replacement=answer.replacement_id?`?replacement_id=${Number(answer.replacement_id)}`:'';
    }
    setBusy(true);let updated=null;
    try{updated=await api(`/api/contacts/projects/${c.project}/${customer.id}/people/${person.id}${operation==='primary'?'/primary':replacement}`,{method:operation==='primary'?'POST':'DELETE'});applyPersonResult(updated,c);if(sameContext(c))toast(operation==='primary'?'主联系人已更新':'联系人已删除');}
    catch(error){toast(error.message,'error');}finally{setBusy(false);render();if(updated&&sameContext(c)&&state.detailId===customer.id)openDetail(customer.id);}
  }
  function handlePersonClick(e){
    const button=e.target.closest('[data-person-new],[data-person-edit],[data-person-delete],[data-person-set-primary]');if(!button||state.busy||state.loading)return;const customer=activeCustomer(Number(button.closest('[data-people-customer]').dataset.peopleCustomer));if(!customer)return;
    if(button.hasAttribute('data-person-new'))return openPersonForm(customer);
    const id=Number(button.dataset.personEdit||button.dataset.personDelete||button.dataset.personSetPrimary),person=contactPeople(customer).find(item=>item.id===id);if(!person)return;
    if(button.hasAttribute('data-person-edit'))openPersonForm(customer,person);else personAction(customer,person,button.hasAttribute('data-person-delete')?'delete':'primary');
  }
  $('[data-workflow-detail]').addEventListener('click',handlePersonClick);
  function clearSelection(){state.selected.clear();root.querySelectorAll('[data-select]').forEach(x=>x.checked=false);syncSelection();}
  function changeFilter(){clearTimeout(searchTimer);if(state.loading||state.busy)return;for(const [fromSelector,toSelector,fromKey,toKey] of [['[data-filter-date-from]','[data-filter-date-to]','dateFrom','dateTo'],['[data-filter-development-from]','[data-filter-development-to]','developmentFrom','developmentTo']]){
      const from=$(fromSelector).value,to=$(toSelector).value;
      if(from&&to&&from>to){const m=listMemory(loadedContext);$(fromSelector).value=m[fromKey]||'';$(toSelector).value=m[toKey]||'';toast('开始日期不能晚于结束日期。','error');return;}
    }state.page=1;clearSelection();render();$('.workflow-table-wrap').scrollTop=0;remember();}
  root.addEventListener('change',e=>{if(state.loading||state.busy)return;const box=e.target;if(box.matches('[data-select]')){box.checked?state.selected.add(+box.dataset.select):state.selected.delete(+box.dataset.select);syncSelection();}if(box.matches('[data-select-all]')){shown().forEach(x=>box.checked?state.selected.add(x.id):state.selected.delete(x.id));root.querySelectorAll('[data-select]').forEach(x=>x.checked=state.selected.has(+x.dataset.select));syncSelection();}});
  function recordView(id,prefill=null){const company=state.items.find(item=>item.id===id)?.company_name;document.dispatchEvent(new CustomEvent('tophoo-open-contact-records',{detail:{contactId:id,view:state.view,company,prefill}}));}
  document.addEventListener('tophoo-outreach-to-record',e=>{if(state.view==='leads'&&e.detail.project===pid()&&e.detail.id===state.detailId)recordView(e.detail.id,e.detail.prefill);});
  root.addEventListener('change',e=>{const select=e.target.closest('[data-customer-grade]');if(select)changeCustomerGrade(+select.dataset.customerGrade,select.value);});
  root.addEventListener('change',e=>{const select=e.target.closest('[data-contact-status]');if(select)changeLeadStatus(+select.dataset.contactStatus,select.value);});
  root.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||state.loading||state.busy)return;if(b.hasAttribute('data-lead-development-date')){editLeadDevelopmentDate(+b.dataset.leadDevelopmentDate);return;}if(b.hasAttribute('data-country-shortcut')){const input=$('[data-filter-country]'),country=b.dataset.countryShortcut;input.value=input.value===country?'':country;changeFilter();return;}if(b.hasAttribute('data-customer-contacts-open')){openDetail(+b.dataset.customerContactsOpen);const people=$('[data-detail-people]');if(people){people.tabIndex=-1;people.scrollIntoView({block:'start'});people.focus({preventScroll:true});}return;}if(b.hasAttribute('data-list-verify')){openVerification(+b.dataset.listVerify);return;}if(b.hasAttribute('data-list-records')){recordView(+b.dataset.listRecords);return;}if(b.hasAttribute('data-lead-contacts-open')){const item=state.items.find(x=>x.id===+b.dataset.leadContactsOpen);if(state.view==='leads'&&item)document.dispatchEvent(new CustomEvent('tophoo-lead-contacts-open',{detail:{...context(),id:item.id,item,trigger:b}}));return;}if(b.hasAttribute('data-lead-outreach-open')){const item=state.items.find(x=>x.id===+b.dataset.leadOutreachOpen);if(state.view==='leads'&&item)document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-open',{detail:{...context(),id:item.id,item,trigger:b}}));return;}if(b.hasAttribute('data-manual-research')){const item=state.items.find(x=>x.id===+b.dataset.manualResearch);if(item)changeManualResearch(item.id,!item.is_manually_researched);return;}if(b.hasAttribute('data-completeness-detail'))showCompleteness(+b.dataset.completenessDetail);if(b.hasAttribute('data-detail'))openDetail(+b.dataset.detail);if(b.hasAttribute('data-retry-workflow'))load();});
  $('[data-workflow-detail]').addEventListener('click',e=>{const b=e.target.closest('[data-detail-close],button');if(!b)return;if(b.hasAttribute('data-detail-contacts')){const item=state.items.find(x=>x.id===+b.dataset.detailContacts);if(state.view==='leads'&&item)document.dispatchEvent(new CustomEvent('tophoo-lead-contacts-open',{detail:{...context(),id:item.id,item,trigger:b}}));return;}if(b.hasAttribute('data-detail-close'))closeDetail(true);if(b.hasAttribute('data-detail-edit'))openForm(state.items.find(x=>x.id===+b.dataset.detailEdit));if(b.hasAttribute('data-detail-main'))mainAction(+b.dataset.detailMain);if(b.hasAttribute('data-detail-delete'))remove(+b.dataset.detailDelete);});
  $('[data-customer-filters-toggle]')?.addEventListener('click',()=>{if(state.loading||state.busy)return;listFiltersOpen[state.view]=!listFiltersOpen[state.view];syncListToolbar();});
  $('[data-customer-list-summary]')?.addEventListener('click',event=>{
    const status=event.target.closest('[data-lead-summary-status]');
    if(status&&state.view==='leads'&&!state.loading&&!state.busy){
      const statusFilter=$('[data-filter-contacted]');
      const nextStatus=status.dataset.leadSummaryStatus==='all'?'':status.dataset.leadSummaryStatus;
      if(statusFilter.value===nextStatus)return;
      statusFilter.value=nextStatus;
      $('[data-filter-grade]').value='';
      changeFilter();
      return;
    }
    const button=event.target.closest('[data-customer-quick-filter]');if(!button||state.view!=='contacts'||state.loading||state.busy)return;
    const key=button.dataset.customerQuickFilter;state.customerQuickFilter=key==='all'?'':key;changeFilter();$(`[data-customer-quick-filter="${key}"]`)?.focus({preventScroll:true});
  });
  $('[data-lead-grade-summary]')?.addEventListener('click',event=>{
    const button=event.target.closest('[data-lead-summary-grade]');
    if(!button||state.view!=='leads'||state.loading||state.busy)return;
    const grade=button.dataset.leadSummaryGrade;
    $('[data-filter-grade]').value=grade;
    changeFilter();
  });
  $('[data-leads-export]').onclick=exportLeadResults;
  $('[data-workflow-add]').onclick=()=>openForm();$('[data-workflow-form]').onsubmit=save;
  document.querySelectorAll('[data-workflow-close]').forEach(x=>x.onclick=()=>close());
  $('[data-workflow-search]').oninput=()=>{clearTimeout(searchTimer);clearSelection();searchTimer=setTimeout(changeFilter,120);};
  root.addEventListener('keydown',event=>{
    if(event.key==='Enter'&&event.target.matches('[data-customer-category]')&&!event.isComposing){event.preventDefault();event.target.blur();}
  });
  for(const selector of ['[data-workflow-owner]','[data-filter-country]','[data-filter-manual-research]','[data-filter-company-type]','[data-filter-source-type]','[data-filter-product-category]','[data-filter-grade]','[data-filter-followup]','[data-filter-contacted]','[data-filter-completeness]','[data-filter-date-from]','[data-filter-date-to]','[data-filter-development-from]','[data-filter-development-to]'])$(selector).onchange=changeFilter;
  $('[data-filter-country]').oninput=event=>{if(!event.isComposing)changeFilter();};
  $('[data-filter-country]').addEventListener('compositionend',changeFilter);
  function resetSearch(){if(state.loading||state.busy)return;state.customerQuickFilter='';clearTimeout(searchTimer);for(const selector of ['[data-workflow-owner]','[data-filter-country]','[data-filter-manual-research]','[data-filter-company-type]','[data-filter-source-type]','[data-filter-product-category]','[data-filter-grade]','[data-filter-followup]','[data-filter-contacted]','[data-filter-completeness]','[data-workflow-search]','[data-filter-date-from]','[data-filter-date-to]','[data-filter-development-from]','[data-filter-development-to]'])$(selector).value='';$('[data-workflow-sort]').value=defaultSort();state.sortDirection=defaultDirection();changeFilter();}
  $('[data-reset-filters]').onclick=resetSearch;
  $('[data-workflow-reset]').onclick=resetSearch;
  $('[data-filter-source-type]').onchange=()=>{changeFilter();};
  $('[data-workflow-sort]').onchange=()=>{state.sortDirection=['recent','completeness','updated'].includes($('[data-workflow-sort]').value)?'desc':'asc';changeFilter();};
  $('[data-sort-direction]').onclick=()=>{if(state.loading||state.busy)return;state.sortDirection=state.sortDirection==='asc'?'desc':'asc';changeFilter();};
  const validPageSize=value=>Number.isInteger(value)&&value>=10&&value<=1000;
  function syncPageSize(){const preset=[10,25,50,100].includes(state.size);$('[data-page-size]').value=preset?String(state.size):'custom';$('[data-custom-page-size]').hidden=preset;$('[data-custom-size-input]').value=String(state.size);}
  $('[data-page-size]').onchange=e=>{if(state.loading||state.busy)return syncPageSize();if(e.target.value==='custom'){$('[data-custom-page-size]').hidden=false;$('[data-custom-size-input]').value=String(state.size);$('[data-custom-size-input]').focus();return;}state.size=Number(e.target.value);syncPageSize();changeFilter();};
  $('[data-custom-page-size]').onsubmit=e=>{e.preventDefault();if(state.loading||state.busy)return;const value=Number($('[data-custom-size-input]').value);if(!validPageSize(value))return toast('每页条数请输入 10–1000 的整数。','error');state.size=value;syncPageSize();changeFilter();};
  function turnPage(delta){clearSelection();state.page+=delta;render();$('.workflow-table-wrap').scrollTop=0;remember();}
  $('[data-page-jump]').onsubmit=e=>{e.preventDefault();if(state.loading||state.busy)return;const input=$('[data-page-jump-input]'),page=Number(input.value);if(!Number.isInteger(page)||page<1||page>Number(input.max))return;turnPage(page-state.page);};
  window.addEventListener('pagehide',remember);
  $('[data-page-prev]').onclick=()=>turnPage(-1);$('[data-page-next]').onclick=()=>turnPage(1);$('[data-clear-selection]').onclick=clearSelection;$('[data-workflow-batch-main]').onclick=()=>batch(true);$('[data-workflow-batch-delete]').onclick=()=>batch(false);
  // 在导航处理前拦截未保存修改；保存中不允许重复操作或切换数据上下文。
  document.addEventListener('click',e=>{if(!e.target.closest('.global-nav-item,.crm-primary-item,[data-project-id],#sidebar-current-project,[data-crm-go-home]'))return;if(state.busy){e.preventDefault();e.stopImmediatePropagation();toast('正在保存，请稍候。');return;}if(!$('[data-workflow-dialog]').hidden&&!close()){e.preventDefault();e.stopImmediatePropagation();return;}remember();cancelAction?.();closeDetail();},true);
  document.addEventListener('keydown',e=>{if(e.target.closest('[data-contact-records-page],[data-followup-dialog],[data-followup-queue],.lead-outreach-editor,.lead-contacts-dialog,.mail-send-dialog,.mail-html-dialog'))return;if((e.key==='Enter'||e.key===' ')&&e.target.closest('.global-nav-item,.crm-primary-item,[data-project-id]')){if(state.busy||(!$('[data-workflow-dialog]').hidden&&!close())){e.preventDefault();e.stopImmediatePropagation();return;}remember();cancelAction?.();closeDetail();}if(e.key==='Escape'){const menu=$('[data-detail-more]');if(menu?.open&&$('[data-workflow-dialog]').hidden&&$('[data-action-dialog]').hidden){e.preventDefault();e.stopImmediatePropagation();menu.open=false;menu.querySelector('summary').focus();return;}if(!$('[data-action-dialog]').hidden)return;if(!$('[data-workflow-dialog]').hidden)close();else if(!$('[data-workflow-detail]').hidden)closeDetail(true);}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&!$('[data-workflow-dialog]').hidden){e.preventDefault();$('[data-workflow-form]').requestSubmit();}if(e.key==='Tab'){const dialog=!$('[data-action-dialog]').hidden?$('[data-action-dialog]'):!$('[data-workflow-dialog]').hidden?$('[data-workflow-dialog]'):!$('[data-workflow-detail]').hidden?$('[data-workflow-detail]'):null;if(!dialog)return;const nodes=[...dialog.querySelectorAll('button,input,select,textarea,a[href],summary')].filter(x=>!x.disabled&&x.getClientRects().length);const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}},true);
  document.addEventListener('tophoo-return-workflow-detail',async e=>{const id=+e.detail?.contactId,project=+e.detail?.projectId,view=e.detail?.view==='leads'?'leads':'contacts';if(project!==pid())return;if(!id){if(e.detail.refresh&&view==='contacts'&&state.view==='contacts'&&!root.hidden)await load();return;}if(root.hidden||state.view!==view){pendingCustomerOpen=id;if(state.view!==view)switchView(view);window.tophooNavigateGlobal?.(view);return;}if(e.detail.refresh)await load();openDetail(id);});
  document.addEventListener('tophoo-lead-contacts-updated', e=>{
    const d=e.detail;if(state.view!=='leads'||d.project!==pid())return;
    const item=state.items.find(x=>x.id===d.id);if(!item)return;
    item.contacts=d.contacts;const primary=d.contacts.find(x=>x.is_primary)||d.contacts[0]||{};
    for(const key of ['contact_name','email','phone','whatsapp'])item[key]=primary[key]||'';
    item.other_channels=primary.notes||'';render();
    if(state.detailId===item.id&&!$('[data-workflow-detail]').hidden){const panel=$('[data-workflow-detail]').querySelector('[data-detail-people]');if(panel)panel.outerHTML=peoplePanel(item,true,true);}
  });
  document.addEventListener('tophoo-lead-outreach-sent',e=>{if(state.view==='leads'&&e.detail.projectId===pid())load();});
  window.addEventListener('beforeunload',e=>{if(dirty()){e.preventDefault();e.returnValue='';}});
  document.addEventListener('tophoo-followup-open-customer',e=>{if(e.detail.projectId!==pid())return;if(state.view==='contacts'&&!root.hidden&&!state.loading)openDetail(e.detail.customerId);else{pendingCustomerOpen=e.detail.customerId;window.tophooNavigateGlobal?.('contacts');}});

  document.addEventListener('tophoo-followup-notes-changed',async e=>{if(!['contacts','leads'].includes(state.view)||e.detail.projectId!==pid())return;const id=state.detailId,c=context();await load();if(id&&sameContext(c))openDetail(id,false);});
  document.addEventListener('tophoo-followups-changed',async e=>{if(state.view!=='contacts'||e.detail.projectId!==pid())return;const id=state.detailId;await load();if(id&&state.view==='contacts'&&e.detail.projectId===pid())openDetail(id,false);});
  const workflowViews=new Set(Object.keys(meta));
  function switchView(view){if(!workflowViews.has(view))return;clearTimeout(searchTimer);remember();cancelAction?.();closeDetail();if(!$('[data-workflow-dialog]').hidden)close(true);state.view=view;root.hidden=false;load();}
  document.addEventListener('tophoo-customer-workflow-view',e=>switchView(e.detail.view));
  window.addEventListener('tophoo-project-changed',()=>{pendingCustomerOpen=null;cancelAction?.();closeDetail();close(true);load();});
  document.addEventListener('tophoo-auth-changed',()=>{if(editContext?.verification)close(true);});
  function restoreActiveWorkflow(){const view=localStorage.getItem('tophoo-global-active-section')||localStorage.getItem('tophoo-crm-active-section');if(workflowViews.has(view)&&!root.hidden&&pid()&&loadedContext!==contextKey({project:pid(),view}))switchView(view);}
  window.addEventListener('tophoo-project-availability',()=>{
    restoreActiveWorkflow();
    if(state.view==='leads'&&!state.loading&&loadedContext===contextKey(context())){
      if(window.tophooProjectAccess?.canEdit('leads')===false&&$('[data-action-form]').elements.development_date)cancelAction?.();
      render();
    }
  });
  window.setTimeout(restoreActiveWorkflow,0);
  root.addEventListener('change',event=>{if(event.target.matches('[data-customer-category]'))changeCustomerCategory(Number(event.target.dataset.customerCategory),event.target.value);});
})();
