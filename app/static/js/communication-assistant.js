/* Country clocks and customer-specific schedules are reference data, never CRM rows. */
(() => {
  const root=document.querySelector('[data-communication-assistant]'),panel=document.querySelector('[data-comm-panel]');
  if(!root||!panel)return;
  const q=s=>root.querySelector(s),p=s=>panel.querySelector(s),home=document.querySelector('[data-comm-home-dialog]');
  const settings=p('[data-comm-settings]'),homeForm=home.querySelector('form');
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stamp=v=>new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  const localStamp=v=>String(v||'').slice(0,16).replace('T',' ');
  const weekdays=['周一','周二','周三','周四','周五','周六','周日'];
  const clone=v=>JSON.parse(JSON.stringify(v));
  const state={project:0,catalog:null,prefs:null,tab:'favorites',limit:40,items:[],loading:false,prefBusy:false,panel:null,strip:null,conversion:null,compare:null};
  let bootPromise=null,listVersion=0,panelVersion=0,stripVersion=0,settingsBaseline='',homeBaseline='';
  const snapshot=form=>JSON.stringify([...new FormData(form)]);
  const editing=()=>!settings.hidden;
  const dirty=()=>editing()&&snapshot(settings)!==settingsBaseline;
  let clockAnchor=null;
  const clockFormats=new Map();
  function clockNow(){return new Date(clockAnchor?clockAnchor.epoch+performance.now()-clockAnchor.tick:Date.now());}
  function clockText(zone,date=clockNow()){
    if(!clockFormats.has(zone))clockFormats.set(zone,new Intl.DateTimeFormat('en-GB',{timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}));
    return clockFormats.get(zone).format(date);
  }
  function tickClocks(){
    if(document.hidden)return;
    if(!root.hidden){
      updateReferenceClock();
      if(!state.compare)root.querySelectorAll('[data-comm-clock-zone]').forEach(node=>{node.textContent=clockText(node.dataset.commClockZone);});
    }
    if(panel.open&&!editing()&&state.panel?.data){const node=p('[data-comm-live-time]');if(node)node.textContent=clockText(state.panel.data.config.timezone);}
    document.querySelectorAll('[data-comm-inline-zone]').forEach(node=>{node.textContent=clockText(node.dataset.commInlineZone);});
  }
  async function api(path,options={},project=pid()){
    const requestTick=performance.now();
    const response=await fetch(`/api/communication/projects/${project}${path}`,{...options,headers:{...(window.tophooAuth?.headers?.()||{}),...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const failure=Error(Array.isArray(data.detail)?data.detail.map(x=>x.msg.replace(/^Value error,\s*/, '')).join('；'):data.detail||'读取失败，请重试。');failure.status=response.status;throw failure;}
    if(!path.startsWith('/overview?')||!new URLSearchParams(path.split('?')[1]).has('at')){
      const generated=data.generated_at||data.items?.[0]?.generated_at;
      if(generated&&Number.isFinite(Date.parse(generated)))clockAnchor={epoch:Date.parse(generated)+(performance.now()-requestTick)/2,tick:performance.now()};
    }
    return data;
  }
  function error(node,message=''){node.textContent=message;node.hidden=!message;}
  async function boot(){
    const project=pid();if(!project)throw Error('请先选择项目。');
    if(state.project===project&&state.prefs&&state.catalog)return;
    if(bootPromise&&state.project===project)return bootPromise;
    state.project=project;
    const pending=Promise.all([state.catalog?Promise.resolve(state.catalog):api('/catalog',{},project),api('/preferences',{},project)]).then(([catalog,prefs])=>{if(project!==pid())throw Error('项目已切换。');state.catalog=catalog;state.prefs=prefs;});
    bootPromise=pending;try{await pending;}finally{if(bootPromise===pending)bootPromise=null;}
  }
  const place=key=>state.catalog?.places.find(x=>x.key===key);
  const defaultConfig=key=>{const row=place(key);return {country:row?.country||'',timezone:row?.timezone||'',city:'',subdivision:null,schedule:{weekdays:[0,1,2,3,4],periods:[{start:'09:00',end:'12:00'},{start:'13:00',end:'17:00'}]},closures:[],confirmed:false,respect_public_holidays:true};};
  const configFor=key=>clone(state.prefs?.overrides[key]||defaultConfig(key));
  const offsetText=minutes=>minutes===0?'与北京同时间':`比北京${minutes>0?'快':'慢'} ${Math.floor(Math.abs(minutes)/60)} 小时${Math.abs(minutes)%60?' '+Math.abs(minutes)%60+' 分钟':''}`;
  function statusHtml(data){return `<span class="comm-status is-${esc(data.state.key)}"><i></i>${esc(data.state.label)}</span>`;}
  function keysForList(){
    const term=q('[data-comm-search]').value.trim().toLowerCase();
    const pool=term||state.tab==='all'?state.catalog.places:state.prefs.favorites.map(key=>place(key)).filter(Boolean);
    return pool.filter(x=>!term||[x.country_name,x.country_en,x.country,...(x.search_aliases||[]),x.city,x.city_en,x.timezone,state.prefs.overrides[x.key]?.city].join(' ').toLowerCase().includes(term)).map(x=>x.key);
  }
  async function loadList(){
    if(root.hidden)return;const project=pid(),version=++listVersion;state.loading=true;root.setAttribute('aria-busy','true');error(q('[data-comm-error]'));
    try{
      await boot();if(version!==listVersion||project!==pid())return;
      const keys=keysForList(),selected=keys.slice(0,state.limit),items=[];
      for(let i=0;i<selected.length;i+=80){const response=await api('/overview?'+new URLSearchParams({keys:selected.slice(i,i+80).join(','),days:'7',...(state.compare?{at:state.compare+':00+08:00'}:{})}),{},project);if(version!==listVersion||project!==pid())return;items.push(...response.items);}
      state.items=items;renderList();q('[data-comm-count]').textContent=`已加载 ${items.length} / ${keys.length} 个地区${q('[data-comm-status]').value!=='all'?' · 状态筛选作用于已加载地区':''}`;
      q('[data-comm-more]').hidden=selected.length>=keys.length;q('[data-comm-favorite-count]').textContent=state.prefs.favorites.length;
      q('[data-comm-source]').textContent=state.catalog.sources.timezone+' · '+state.catalog.sources.holidays;
      updateReferenceClock();
    }catch(e){if(version===listVersion){error(q('[data-comm-error]'),e.message);q('[data-comm-rows]').innerHTML='<p class="comm-empty">地区资料暂不可用，请点击刷新重试。</p>';q('[data-comm-count]').textContent='';}}
    finally{if(version===listVersion){state.loading=false;root.setAttribute('aria-busy','false');}}
  }
  function renderList(){
    const focused=document.activeElement,focusPlace=focused?.dataset.commPlace,focusStar=focused?.dataset.commStar;
    const filter=q('[data-comm-status]').value,items=state.items.filter(x=>filter==='all'||(filter==='working'?x.state.key==='working':!['working','unverified'].includes(x.state.key)));
    q('[data-comm-rows]').innerHTML=items.length?items.map(x=>{
      const hour=Number(x.now.time.slice(0,2)),day=hour>=6&&hour<18,favorite=state.prefs.favorites.includes(x.key);
      const rail=Array.from({length:24},(_,h)=>`<span class="${h>=6&&h<18?'is-day':'is-night'}${h===hour?' is-current':''}" title="当地 ${String(h).padStart(2,'0')}:00"></span>`).join('');
      return `<article class="comm-city-card"><header><button class="comm-place-name" type="button" data-comm-place="${esc(x.key)}"><strong>${esc(x.city)} <i>↗</i></strong><span>${esc(x.country_name)} · ${esc(x.now.offset_label)}</span></button><button type="button" class="comm-star" data-comm-star="${esc(x.key)}" aria-pressed="${favorite}" aria-label="${favorite?'取消关注':'关注'}${esc(x.country_name+' '+x.city)}">${favorite?'★':'☆'}</button></header><div class="comm-city-time"><strong class="comm-row-clock" data-comm-clock-zone="${esc(x.config.timezone)}">${esc(clockText(x.config.timezone,new Date(x.now.iso)))}</strong><span class="comm-day-icon" title="${day?'当地白天（示意）':'当地夜间（示意）'}" aria-label="${day?'当地白天':'当地夜间'}">${day?'☀':'☾'}</span></div><div class="comm-city-date"><span>${esc(x.now.date.slice(5))} ${esc(x.now.weekday)}</span><span>${esc(offsetText(x.difference_minutes))}</span></div><div class="comm-hour-rail" aria-label="24 小时日夜示意，当前当地 ${esc(x.now.time)}">${rail}</div><div class="comm-axis-labels"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div><footer>${statusHtml(x)}<span>${x.state.key==='working'?'按'+(x.config.confirmed?'已确认':'参考')+'作息':x.next_working?'下次工作 '+esc(stamp(x.next_working.start.beijing))+' 北京':'暂无工作安排'}</span></footer>${x.holidays[0]&&x.holidays[0].days_away<=3?`<div class="comm-card-holiday" title="${esc(x.holidays[0].name)}">假日 · ${esc(x.holidays[0].date.slice(5)+' '+x.holidays[0].name)}</div>`:''}</article>`;
    }).join(''):'<p class="comm-empty">'+(q('[data-comm-search]').value?'没有匹配的地区，试试国家名或英文城市名。':state.tab==='favorites'?'暂无常用城市，在上方搜索并点击星标添加。':'当前筛选下没有地区。')+'</p>';

    tickClocks();
    const restore=focusPlace?root.querySelector(`[data-comm-place="${CSS.escape(focusPlace)}"]`):focusStar?root.querySelector(`[data-comm-star="${CSS.escape(focusStar)}"]`):null;restore?.focus({preventScroll:true});
  }
  function beijingValue(date=clockNow()){
    const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
    const part=type=>parts.find(p=>p.type===type).value;
    return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
  }
  function updateReferenceClock(){
    const value=state.compare||beijingValue();q('[data-comm-beijing]').textContent=state.compare?value.slice(11,16)+':00':clockText('Asia/Shanghai');q('[data-comm-beijing-date]').textContent=value.slice(0,10).replaceAll('-',' / ');
    if(document.activeElement!==q('[data-comm-compare]'))q('[data-comm-compare]').value=value;
    q('[data-comm-slider]').value=Number(value.slice(11,13))*60+Number(value.slice(14,16));
    q('[data-comm-mode]').textContent=state.compare?'时间对照':'实时';q('[data-comm-now]').hidden=!state.compare;root.classList.toggle('is-comparing',!!state.compare);
  }
  function compareAt(value){
    if(!value){state.compare=null;updateReferenceClock();loadList();return;}
    const field=q('[data-comm-compare]');if(!field.checkValidity()){field.reportValidity();return;}
    state.compare=value;updateReferenceClock();loadList();
  }
  async function savePrefs(next){
    if(state.prefBusy)throw Error('正在保存，请稍候。');const project=pid();state.prefBusy=true;
    try{const saved=await api('/preferences',{method:'PUT',body:JSON.stringify(next)},project);if(project===pid())state.prefs=saved;return saved;}finally{state.prefBusy=false;}
  }
  async function toggleStar(key){
    try{await boot();const next=clone(state.prefs),index=next.favorites.indexOf(key);if(index>=0)next.favorites.splice(index,1);else{if(next.favorites.length>=30)throw Error('最多关注 30 个地区，请先移除不常用地区。');next.favorites.push(key);}await savePrefs(next);await loadList();}catch(e){error(q('[data-comm-error]'),e.message);}
  }
  const endpoint=context=>`/entities/${context.kind}/${context.id}?person=${encodeURIComponent(context.person||'')}`;
  async function getEntity(context){return api(endpoint(context),{},context.project);}
  function stripVisible(context){const node=context.node,container=node?.closest('[data-workflow-detail],[data-rfq-preview]');return node?.isConnected&&container&&!container.hidden&&context.project===pid()&&String(context.id)===node.dataset.entity;}
  async function loadStrip(context){
    const version=++stripVersion,node=context.node;if(!node)return;
    try{
      await boot();const info=await getEntity(context);if(version!==stripVersion||!stripVisible(context))return;
      state.strip={...context,info};renderStrip(node,info);
    }catch(e){if(version===stripVersion&&context.person&&e.status===422){loadStrip({...context,person:''});return;}if(version===stripVersion&&stripVisible(context))node.innerHTML=`<span class="comm-inline-icon" aria-hidden="true">◷</span><div><strong>沟通参考暂不可用</strong><small>${esc(e.message)}</small></div><button type="button" data-comm-open-entity>重试</button>`;}
  }
  function renderStrip(node,info){
    const data=info.overview,person=info.people.find(x=>x.key===info.person),name=person?person.name+' · ':'';
    node.innerHTML=`<span class="comm-inline-icon" aria-hidden="true">◷</span><div>${data?`<strong>${esc(name+data.city)} <span data-comm-inline-zone="${esc(data.config.timezone)}">${esc(clockText(data.config.timezone,new Date(data.now.iso)))}</span> <span>· ${esc(data.now.weekday)}</span></strong><div class="comm-inline-meta">${statusHtml(data)}<span>${esc(offsetText(data.difference_minutes))}</span>${data.state.key!=='working'&&data.next_working?'<small>下次工作：北京 '+esc(stamp(data.next_working.start.beijing))+'</small>':''}</div>${data.holidays[0]&&data.holidays[0].days_away<=3?`<small class="comm-holiday-hint">近期假日：${esc(data.holidays[0].date+' '+data.holidays[0].name)}</small>`:''}`:`<strong>客户当地时间</strong><small>${info.country_code?'该国家有多个时区，现有地址不足以确定，请补选城市':'缺少可识别的国家信息，请补充地区'}</small>`}<small class="comm-inline-source">${data?(data.config.confirmed?'客户已确认作息':info.origin==='auto_address'?'已根据公司地址自动识别 · 参考作息':info.origin==='auto_country'?'已根据国家自动识别 · 参考作息':'按参考作息判断'):'不会修改客户的国家或其他资料'}</small></div><button type="button" data-comm-open-entity>${data?'查看安排':info.country_code?'补选城市':'补充地区'} ↗</button>`;
  }
  function closePanel(force=false){if(!force&&state.settingsBusy){error(p('[data-comm-settings-error]'),'正在保存或计算，请稍候。');return false;}if(!force&&dirty()&&!confirm('作息设置尚未保存，是否放弃修改？'))return false;++panelVersion;panel.close();state.panel=null;settings.hidden=true;return true;}
  async function openPanel(context){
    if(panel.open&&!closePanel())return;const version=++panelVersion,project=pid();state.panel={...context,project,previewOnly:false};state.conversion=null;settings.hidden=true;error(p('[data-comm-panel-error]'));p('[data-comm-panel-content]').hidden=false;p('[data-comm-panel-content]').innerHTML='<p class="comm-empty">正在读取沟通安排…</p>';p('[data-comm-person-label]').hidden=true;
    if(!panel.open)panel.showModal();
    try{
      await boot();if(version!==panelVersion||project!==pid())return;
      if(context.kind){state.panel.info=await getEntity(state.panel);if(version!==panelVersion||project!==pid())return;state.panel.data=state.panel.info.overview;}
      else{state.panel.config=configFor(context.key);state.panel.data=await api('/preview',{method:'POST',body:JSON.stringify({config:state.panel.config,days:30})},project);}
      if(version!==panelVersion||project!==pid())return;renderPanel();
    }catch(e){if(version===panelVersion)error(p('[data-comm-panel-error]'),e.message);}
  }
  function renderPanel(){
    const context=state.panel;if(!context)return;const data=context.data,info=context.info;
    p('[data-comm-panel-kicker]').textContent=info?'客户沟通安排':'城市详情 · 实时';p('#comm-panel-title').textContent=info?info.company_name:data?data.country_name+' · '+data.city:'沟通安排';p('[data-comm-panel-subtitle]').textContent=info?(info.person?'联系人可独立设置，未设置时继承公司安排':'公司安排；联系人默认继承'): '这里显示当前实际时间；支持日期换算、假日和作息设置';
    p('[data-comm-person-label]').hidden=!info||!info.people.length;
    p('[data-comm-person]').innerHTML=info?'<option value="">公司安排</option>'+info.people.map(x=>`<option value="${esc(x.key)}" ${x.key===info.person?'selected':''}>${esc(x.name)}</option>`).join(''):'';
    if(!data){p('[data-comm-panel-content]').innerHTML=`<div class="comm-unconfigured"><span aria-hidden="true">◷</span><h3>补充客户所在地区</h3><p>${info?.country_code?'已尝试根据国家和公司地址识别；该国家有多个时区，请补选客户所在城市，保存后自动沿用。':'请选择国家／地区和城市，客户原有资料不会被修改。'}</p><button type="button" class="comm-primary" data-comm-edit-settings>选择沟通地区</button></div>`;return;}
    const selectedPerson=info?.people.find(x=>x.key===info.person),origin=context.previewOnly?'本次预览，尚未保存':info?.origin==='person'?'联系人独立安排':info?.origin==='company'?'公司安排':info?.origin==='auto_address'?'根据公司地址自动识别':info?.origin==='auto_country'?'根据国家自动识别':'地区参考安排';
    p('[data-comm-panel-content]').innerHTML=`<section class="comm-clock-card"><div class="comm-clock-top"><span>${esc(selectedPerson?selectedPerson.name+' · '+data.city:data.city)}</span>${statusHtml(data)}</div><strong class="comm-big-clock" data-comm-live-time>${esc(clockText(data.config.timezone,new Date(data.now.iso)))}</strong><p data-comm-live-date>${esc(data.now.date+' '+data.now.weekday)} · ${esc(data.now.offset_label)}${data.now.is_dst?' · 夏令时':''}</p><small>${esc(offsetText(data.difference_minutes))} · ${esc(origin)} · ${data.config.confirmed?'客户已确认':'通用／自定义参考作息'}</small><div class="comm-clock-actions"><button type="button" data-comm-edit-settings>${info?'地区与作息设置':'调整参考作息'}</button>${info?.has_override&&info.can_edit?'<button type="button" data-comm-reset-settings>恢复继承／默认</button>':''}</div></section>
      <section class="comm-panel-section"><h3>下一工作时段</h3>${data.next_working?`<div class="comm-next-window"><strong>当地 ${esc(localStamp(data.next_working.start.iso))} — ${esc(data.next_working.end.time)}</strong><span>北京 ${esc(stamp(data.next_working.start.beijing))} — ${esc(stamp(data.next_working.end.beijing))}</span></div>`:'<p class="comm-muted">近期暂无工作时段，请核对作息和休假安排。</p>'}${!data.holiday_supported?'<p class="comm-warning">该地区假日资料暂缺，不能据此确认正常上班。</p>':''}</section>
      <section class="comm-panel-section"><header><h3>时间换算</h3><small>支持约电话或视频会议</small></header><form data-comm-convert-form><div class="comm-convert-inputs"><select name="source" aria-label="输入时间的时区"><option value="local">${info?'客户当地时间':'当地时间'}</option><option value="beijing">北京时间</option></select><input name="value" type="datetime-local" required value="${esc((data.next_working?.start.iso||data.now.iso).slice(0,16))}" aria-label="待换算的日期和时间"></div><div class="comm-convert-fold"><select name="fold" aria-label="夏令时重复时间选择"><option value="">自动识别夏令时</option><option value="0">回拨时第一次出现</option><option value="1">回拨时第二次出现</option></select><button type="submit">换算时间</button></div></form><div data-comm-conversion role="status"></div></section>
      <section class="comm-panel-section"><header><h3>共同工作时段</h3><small>按双方配置及公共假日计算</small></header>${data.common_windows.length?data.common_windows.map(x=>`<div class="comm-overlap"><strong>当地 ${esc(localStamp(x.start.iso))} — ${esc(x.end.time)}</strong>${data.home_timezone!=='Asia/Shanghai'?`<small>我的时区 ${esc(localStamp(x.home_start))} — ${esc(localStamp(x.home_end))}</small>`:''}<span>北京 ${esc(stamp(x.start.beijing))} — ${esc(stamp(x.end.beijing))}</span></div>`).join(''):'<p class="comm-muted">未来两周没有重叠的工作时段，可通过“我的作息”调整参考安排。</p>'}</section>
      <section class="comm-panel-section"><header><h3>近期假日与休假</h3><select data-comm-holiday-days aria-label="假日查看范围"><option value="7">未来 7 天</option><option value="30" selected>未来 30 天</option></select></header><p class="comm-muted">${data.config.subdivision?'全国及 '+esc(data.config.subdivision)+' 地方公共假日':'仅全国公共假日；可在设置中选择地方假日'} · 客户休假单独登记</p><div data-comm-holidays>${holidaysHtml(data.holidays)}</div></section>
      ${!info?'<section class="comm-panel-section"><h3>适用客户</h3><p class="comm-muted">当前项目中已明确此时区的在跟客户</p><div data-comm-related>正在读取…</div></section>':''}
      <footer class="comm-panel-footer"><a href="${esc(data.sources.timezone_url)}" target="_blank" rel="noopener">${esc(data.sources.timezone)}</a><a href="${esc(data.sources.holiday_url)}" target="_blank" rel="noopener">${esc(data.sources.holidays)}</a><p>${esc(data.sources.note)}</p><p>计算于北京时间 ${esc(stamp(data.generated_at))}</p></footer>`;
    context.config=clone(data.config);state.conversion=null;bindConverter();
    if(!info&&state.compare){const form=p('[data-comm-convert-form]');form.elements.source.value='beijing';form.elements.value.value=state.compare;form.requestSubmit();}
    if(!info)loadRelated(data.key);
  }
  function holidaysHtml(items){return items.length?items.map(x=>`<article class="comm-holiday"><time datetime="${esc(x.date)}">${esc(x.date.slice(5))}${x.end_date?' — '+esc(x.end_date.slice(5)):''}</time><div><strong>${esc(x.name)}</strong><small>${x.type==='closure'?'客户休假':esc(x.scope)} · ${x.days_away===0?'今天':x.days_away+' 天后'}</small></div></article>`).join(''):'<p class="comm-muted">所选期间暂无已记录假日或休假；临时公告仍需核对。</p>';}
  async function loadRelated(key){const version=panelVersion;try{const data=await api('/related-customers?'+new URLSearchParams({key}));if(version!==panelVersion)return;const node=p('[data-comm-related]');if(node)node.innerHTML=data.items.length?data.items.map(x=>`<button type="button" class="comm-related" data-comm-customer="${x.id}">${esc(x.company_name)} <span>↗</span></button>`).join('')+(data.total>20?'<small>显示前 20 家，可前往客户列表浏览。</small>':''):'<p class="comm-muted">暂无已明确此时区的客户。</p>';}catch(e){if(version===panelVersion&&p('[data-comm-related]'))p('[data-comm-related]').textContent=e.message;}}
  function bindConverter(){const form=p('[data-comm-convert-form]');if(!form)return;form.addEventListener('input',()=>{state.conversion=null;p('[data-comm-conversion]').innerHTML='';});form.onsubmit=async event=>{event.preventDefault();const context=state.panel,version=panelVersion,button=form.querySelector('[type="submit"]'),values=Object.fromEntries(new FormData(form));button.disabled=true;try{const result=await api('/convert',{method:'POST',body:JSON.stringify({config:context.config,value:values.value,source:values.source,fold:values.fold===''?null:Number(values.fold)})},context.project);if(version!==panelVersion)return;state.conversion=result;p('[data-comm-conversion]').innerHTML=`<div class="comm-conversion-result"><strong>客户当地 ${esc(localStamp(result.iso))}</strong><span>北京时间 ${esc(stamp(result.beijing))}</span><small>${esc(result.state.label)}${result.state.reason?' · '+esc(result.state.reason):''}</small><div><button type="button" data-comm-copy-time>复制时间</button>${context.kind==='customers'&&context.info.can_edit?'<button type="button" class="comm-primary" data-comm-create-plan>添加跟进计划</button>':''}</div></div>`;}catch(e){if(version===panelVersion)p('[data-comm-conversion]').innerHTML=`<p class="comm-error">${esc(e.message)}</p>`;}finally{button.disabled=false;}};}
  async function refreshPanelClock(){
    const context=state.panel,version=panelVersion;if(!panel.open||editing()||!context?.config)return;
    try{const data=await api('/preview',{method:'POST',body:JSON.stringify({config:context.config,days:Number(p('[data-comm-holiday-days]')?.value||30)})},context.project);
      if(version!==panelVersion||editing())return;context.data=data;
      if(p('[data-comm-live-time]'))p('[data-comm-live-time]').textContent=clockText(data.config.timezone);
      if(p('[data-comm-live-date]'))p('[data-comm-live-date]').textContent=data.now.date+' '+data.now.weekday+' · '+data.now.offset_label+(data.now.is_dst?' · 夏令时':'');
      const status=p('.comm-clock-top .comm-status');if(status)status.outerHTML=statusHtml(data);
      const next=p('.comm-next-window');if(next&&data.next_working)next.innerHTML=`<strong>当地 ${esc(localStamp(data.next_working.start.iso))} — ${esc(data.next_working.end.time)}</strong><span>北京 ${esc(stamp(data.next_working.start.beijing))} — ${esc(stamp(data.next_working.end.beijing))}</span>`;
      if(p('[data-comm-holidays]'))p('[data-comm-holidays]').innerHTML=holidaysHtml(data.holidays);
    }catch(_){}
  }
  const periodHtml=(item={start:'09:00',end:'17:00'})=>`<div class="comm-period"><input type="time" name="period_start" required value="${esc(item.start)}" aria-label="工作开始时间"><span>—</span><input type="time" name="period_end" required value="${esc(item.end)}" aria-label="工作结束时间"><button type="button" data-comm-remove-period aria-label="移除此工作时段">×</button></div>`;
  const weekdayHtml=values=>weekdays.map((label,index)=>`<label><input type="checkbox" name="weekdays" value="${index}" ${values.includes(index)?'checked':''}><span>${label}</span></label>`).join('');
  const closureHtml=(item={})=>`<div class="comm-closure"><input type="date" name="closure_start" required value="${esc(item.start)}" aria-label="休假开始日期"><input type="date" name="closure_end" required value="${esc(item.end)}" aria-label="休假结束日期"><input name="closure_name" required maxlength="120" value="${esc(item.name)}" placeholder="例如客户年度休假" aria-label="休假说明"><button type="button" data-comm-remove-closure aria-label="移除此休假">×</button></div>`;
  function scheduleValues(form,selector){return {weekdays:[...form.querySelectorAll('[name="weekdays"]:checked')].map(x=>Number(x.value)),periods:[...form.querySelectorAll(selector+' .comm-period')].map(row=>({start:row.querySelector('[name="period_start"]').value,end:row.querySelector('[name="period_end"]').value}))};}
  function collectConfig(){return {country:settings.elements.country.value,timezone:settings.elements.timezone.value,city:settings.elements.city.value.trim(),subdivision:settings.elements.subdivision.value||null,schedule:scheduleValues(settings,'[data-comm-periods]'),confirmed:settings.elements.confirmed.checked,respect_public_holidays:settings.elements.respect_public_holidays.checked,closures:[...settings.querySelectorAll('.comm-closure')].map(row=>({start:row.querySelector('[name="closure_start"]').value,end:row.querySelector('[name="closure_end"]').value,name:row.querySelector('[name="closure_name"]').value.trim()}))};}
  function zoneOptions(country,selected=''){const items=state.catalog.places.filter(x=>x.country===country);settings.elements.timezone.innerHTML='<option value="">请选择城市／时区</option>'+items.map(x=>`<option value="${esc(x.timezone)}">${esc(x.city+' · '+x.timezone)}</option>`).join('');settings.elements.timezone.value=selected|| (items.length===1?items[0].timezone:'');}
  async function subdivisionOptions(country,selected=''){const version=panelVersion;settings.elements.subdivision.innerHTML='<option value="">仅全国公共假日</option>';if(!country)return;try{const rows=await api('/subdivisions/'+country);if(version!==panelVersion||country!==settings.elements.country.value)return;settings.elements.subdivision.innerHTML='<option value="">仅全国公共假日</option>'+rows.map(x=>`<option value="${esc(x.code)}">${esc(x.name+' ('+x.code+')')}</option>`).join('');settings.elements.subdivision.value=selected||'';}catch(e){if(version===panelVersion)error(p('[data-comm-settings-error]'),e.message);}}
  async function openSettings(){
    const context=state.panel;if(!context)return;const config=context.config||{...defaultConfig(''),country:context.info?.country_code||''};
    p('[data-comm-panel-content]').hidden=true;settings.hidden=false;error(p('[data-comm-settings-error]'));
    p('[data-comm-settings-title]').textContent=context.kind?'客户地区与作息':'我的地区参考作息';p('[data-comm-settings-hint]').textContent=context.kind?(context.info.can_edit?'联系人设置优先于公司；未单独设置时继承公司安排。':'当前为只读，可选择地区预览，不能保存客户设置。'):'仅保存为本人的地区参考，不代表所有客户都按此作息上班。';
    settings.elements.country.innerHTML='<option value="">请选择国家／地区</option>'+state.catalog.countries.map(x=>`<option value="${x.code}">${esc(x.name+' · '+x.name_en)}</option>`).join('');settings.elements.country.value=config.country;
    zoneOptions(config.country,config.timezone);settings.elements.city.value=config.city||'';settings.elements.confirmed.checked=!!config.confirmed&&(!context.kind||context.info.has_override);settings.elements.respect_public_holidays.checked=config.respect_public_holidays!==false;p('[data-comm-confirmed-label]').hidden=!context.kind;
    p('[data-comm-weekdays]').innerHTML=weekdayHtml(config.schedule.weekdays);p('[data-comm-periods]').innerHTML=config.schedule.periods.map(periodHtml).join('');p('[data-comm-closures]').innerHTML=config.closures.map(closureHtml).join('');p('[data-comm-save-settings]').hidden=!!context.kind&&!context.info.can_edit;
    await subdivisionOptions(config.country,config.subdivision);settingsBaseline=snapshot(settings);settings.elements.country.focus();
  }
  settings.elements.country.onchange=()=>{zoneOptions(settings.elements.country.value);subdivisionOptions(settings.elements.country.value);};
  settings.addEventListener('input',event=>{if(event.target.name!=='confirmed'&&event.target.name!=='city')settings.elements.confirmed.checked=false;});
  settings.onsubmit=async event=>{event.preventDefault();await applySettings(!state.panel?.kind||state.panel.info.can_edit);};
  async function applySettings(save){
    if(!settings.reportValidity())return;const context=state.panel,version=panelVersion,config=collectConfig();state.settingsBusy=true;settings.querySelectorAll('button,input,select').forEach(x=>x.disabled=true);error(p('[data-comm-settings-error]'));
    try{
      const data=await api('/preview',{method:'POST',body:JSON.stringify({config,days:30})},context.project);if(version!==panelVersion)return;
      if(save&&context.kind){context.info=await api(endpoint(context),{method:'PUT',body:JSON.stringify(config)},context.project);context.data=context.info.overview;context.person=context.info.person;context.previewOnly=false;if(state.strip&&state.strip.id===context.id&&state.strip.kind===context.kind)loadStrip({...state.strip,person:context.person});}
      else if(save){const next=clone(state.prefs),key=config.country+':'+config.timezone;config.confirmed=false;next.overrides[key]=config;await savePrefs(next);context.key=key;context.data=data;context.previewOnly=false;}
      else{context.data=data;context.previewOnly=true;}
      if(version!==panelVersion)return;settings.hidden=true;p('[data-comm-panel-content]').hidden=false;renderPanel();if(save&&!root.hidden)loadList();
    }catch(e){if(version===panelVersion)error(p('[data-comm-settings-error]'),e.message);}
    finally{state.settingsBusy=false;settings.querySelectorAll('button,input,select').forEach(x=>x.disabled=false);}
  }
  async function resetSettings(){const context=state.panel;if(!context?.kind||!confirm('清除此对象的独立安排，恢复继承公司或地区参考作息？'))return;try{context.info=await api(endpoint(context),{method:'DELETE'},context.project);context.data=context.info.overview;context.previewOnly=false;renderPanel();if(state.strip)loadStrip({...state.strip,person:context.person});}catch(e){error(p('[data-comm-panel-error]'),e.message);}}
  function closeHome(force=false){if(!force&&snapshot(homeForm)!==homeBaseline&&!confirm('我的作息尚未保存，是否放弃修改？'))return false;home.close();return true;}
  async function openHome(){try{await boot();homeForm.elements.home_timezone.innerHTML=state.catalog.places.map(x=>`<option value="${esc(x.timezone)}">${esc(x.country_name+' · '+x.city+' ('+x.timezone+')')}</option>`).join('');homeForm.elements.home_timezone.value=state.prefs.home_timezone;home.querySelector('[data-comm-home-weekdays]').innerHTML=weekdayHtml(state.prefs.home_schedule.weekdays);home.querySelector('[data-comm-home-periods]').innerHTML=state.prefs.home_schedule.periods.map(periodHtml).join('');error(home.querySelector('[data-comm-home-error]'));homeBaseline=snapshot(homeForm);home.showModal();}catch(e){error(q('[data-comm-error]'),e.message);}}
  homeForm.onsubmit=async event=>{event.preventDefault();const project=pid(),next=clone(state.prefs);next.home_timezone=homeForm.elements.home_timezone.value;next.home_schedule=scheduleValues(homeForm,'[data-comm-home-periods]');const button=homeForm.querySelector('[type="submit"]');button.disabled=true;try{await savePrefs(next);if(project===pid())closeHome(true);}catch(e){error(home.querySelector('[data-comm-home-error]'),e.message);}finally{button.disabled=false;}};
  function addPeriod(container){if(container.children.length<4)container.insertAdjacentHTML('beforeend',periodHtml());}
  panel.addEventListener('click',async event=>{
    const b=event.target.closest('button');if(!b)return;
    if(b.hasAttribute('data-comm-close'))closePanel();else if(b.hasAttribute('data-comm-edit-settings'))openSettings();else if(b.hasAttribute('data-comm-settings-cancel')){if(!dirty()||confirm('是否放弃尚未保存的作息修改？')){settings.hidden=true;p('[data-comm-panel-content]').hidden=false;}}else if(b.hasAttribute('data-comm-preview-settings'))applySettings(false);else if(b.hasAttribute('data-comm-reset-settings'))resetSettings();else if(b.hasAttribute('data-comm-add-period'))addPeriod(p('[data-comm-periods]'));else if(b.hasAttribute('data-comm-remove-period'))b.closest('.comm-period').remove();else if(b.hasAttribute('data-comm-add-closure')){if(p('[data-comm-closures]').children.length<20)p('[data-comm-closures]').insertAdjacentHTML('beforeend',closureHtml());}else if(b.hasAttribute('data-comm-remove-closure'))b.closest('.comm-closure').remove();
    else if(b.hasAttribute('data-comm-copy-time')&&state.conversion){try{await navigator.clipboard.writeText(`客户当地时间：${localStamp(state.conversion.iso)} (${state.panel.config.timezone})；北京时间：${stamp(state.conversion.beijing)}`);b.textContent='已复制';}catch{error(p('[data-comm-panel-error]'),'复制失败，可选中换算结果手动复制。');}}
    else if(b.hasAttribute('data-comm-create-plan')&&state.conversion){const context=state.panel,result=state.conversion;if(closePanel())document.dispatchEvent(new CustomEvent('tophoo-communication-followup',{detail:{projectId:context.project,customerId:context.id,personId:Number(context.person)||null,dueAt:result.utc,hint:`客户当地 ${localStamp(result.iso)} (${context.config.timezone}) · 北京 ${stamp(result.beijing)}`}}));}
    else if(b.dataset.commCustomer){const customerId=Number(b.dataset.commCustomer),project=pid();if(closePanel()){document.dispatchEvent(new CustomEvent('tophoo-followup-open-customer',{detail:{projectId:project,customerId}}));}}
  });
  p('[data-comm-person]').onchange=event=>{const context=state.panel;if(context)openPanel({...context,person:event.target.value});};
  panel.addEventListener('change',async event=>{if(!event.target.matches('[data-comm-holiday-days]'))return;const context=state.panel,version=panelVersion;try{const data=await api('/preview',{method:'POST',body:JSON.stringify({config:context.config,days:Number(event.target.value)})},context.project);if(version===panelVersion)p('[data-comm-holidays]').innerHTML=holidaysHtml(data.holidays);}catch(e){if(version===panelVersion)error(p('[data-comm-panel-error]'),e.message);}});
  panel.addEventListener('cancel',event=>{event.preventDefault();closePanel();});home.addEventListener('cancel',event=>{event.preventDefault();closeHome();});
  home.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.hasAttribute('data-comm-home-close'))closeHome();else if(b.hasAttribute('data-comm-home-add-period'))addPeriod(home.querySelector('[data-comm-home-periods]'));else if(b.hasAttribute('data-comm-remove-period'))b.closest('.comm-period').remove();});
  root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.commTab){state.tab=b.dataset.commTab;state.limit=40;root.querySelectorAll('[data-comm-tab]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));loadList();}else if(b.dataset.commPlace)openPanel({key:b.dataset.commPlace});else if(b.dataset.commStar)toggleStar(b.dataset.commStar);else if(b.hasAttribute('data-comm-more')){state.limit+=40;loadList();}else if(b.hasAttribute('data-comm-refresh'))loadList();else if(b.hasAttribute('data-comm-now'))compareAt(null);else if(b.hasAttribute('data-comm-home'))openHome();});
  q('[data-comm-compare]').onchange=event=>compareAt(event.target.value);
  q('[data-comm-slider]').oninput=event=>{const minutes=Number(event.target.value),value=(state.compare||beijingValue()).slice(0,10)+'T'+String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');q('[data-comm-compare]').value=value;q('[data-comm-beijing]').textContent=value.slice(11);};
  q('[data-comm-slider]').onchange=()=>compareAt(q('[data-comm-compare]').value);
  let searchTimer;q('[data-comm-search]').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.limit=40;loadList();},220);};q('[data-comm-status]').onchange=loadList;
  document.addEventListener('click',event=>{if(event.target.closest('[data-comm-open-entity]')?.closest('[data-comm-inline]')===state.strip?.node&&state.strip)openPanel({...state.strip});});
  function mountStrip(anchor,context){
    const node=document.createElement('section');node.className='comm-inline';node.dataset.commInline='';node.dataset.entity=String(context.id||'');node.setAttribute('aria-label','客户当地时间和沟通参考');anchor.after(node);
    if(!context.id){++stripVersion;state.strip=null;node.innerHTML='<span class="comm-inline-icon" aria-hidden="true">◷</span><div><strong>客户当地时间</strong><small>请先在询价单中关联客户，以显示当地时间和沟通安排。</small></div>';return;}
    node.innerHTML='<span class="comm-inline-icon" aria-hidden="true">◷</span><div><strong>客户当地时间</strong><small>正在读取沟通参考…</small></div>';
    const previous=state.strip;state.strip={...context,node,person:context.person??(previous?.id===context.id&&previous?.project===context.project&&previous?.kind===context.kind?previous.person:'')};loadStrip(state.strip);
  }
  document.addEventListener('tophoo-workflow-detail-ready',event=>{
    const context=event.detail;if(!['leads','contacts'].includes(context.view))return;const company=document.querySelector('[data-workflow-detail] [data-detail-company]');if(!company)return;
    mountStrip(company,{id:context.id,kind:context.view==='leads'?'leads':'customers',project:context.project});
  });
  document.addEventListener('tophoo-rfq-detail-ready',event=>{
    const anchor=document.querySelector('[data-rfq-preview-content] [data-rfq-block="contact"]')||document.querySelector('[data-rfq-preview-content] [data-rfq-block="customer"]');if(anchor)mountStrip(anchor,{id:event.detail.customerId,kind:'customers',person:String(event.detail.personId||''),project:event.detail.project});
  });
  document.addEventListener('tophoo-communication-assistant-view',loadList);
  document.addEventListener('click',event=>{if(!event.target.closest('.global-nav-item,.crm-primary-item,[data-project-id]'))return;if(panel.open&&!closePanel()){event.preventDefault();event.stopImmediatePropagation();}if(home.open&&!closeHome()){event.preventDefault();event.stopImmediatePropagation();}},true);
  function reset(){++listVersion;++panelVersion;++stripVersion;bootPromise=null;state.project=0;state.prefs=null;state.items=[];state.compare=null;state.strip=null;state.conversion=null;closePanel(true);closeHome(true);clearTimeout(searchTimer);if(!root.hidden)loadList();}
  window.addEventListener('tophoo-project-changed',reset);document.addEventListener('tophoo-auth-changed',reset);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshPanelClock();if(!root.hidden)loadList();if(state.strip&&stripVisible(state.strip))loadStrip(state.strip);}});
  window.setInterval(tickClocks,1000);
  window.setInterval(()=>{if(document.hidden)return;refreshPanelClock();if(!root.hidden&&!state.loading&&!state.compare)loadList();if(state.strip&&stripVisible(state.strip))loadStrip(state.strip);},60000);
})();
