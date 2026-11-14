(() => {
  const root = document.querySelector('[data-crm-rfq]');
  if (!root) return;
  const q = selector => root.querySelector(selector);
  const rows = q('[data-rfq-rows]'), add = q('[data-rfq-add]'), records = q('[data-rfq-records]');
  const preview = q('[data-rfq-preview]'), previewContent = q('[data-rfq-preview-content]');
  const search = q('[data-rfq-search]'), status = q('[data-rfq-status]'), source = q('[data-rfq-source]');
  const statButtons = [...root.querySelectorAll('[data-rfq-stat]')];
  function syncStats() {
    statButtons.forEach(button => {
      button.disabled = !ready;
      button.setAttribute('aria-pressed', String(button.dataset.rfqStat === status.value));
    });
  }
  const editor = document.createElement('section');
  editor.className = 'rfq-editor'; editor.hidden = true;
  const editorLayer = document.createElement('section');
  editorLayer.className='rfq-editor-modal';editorLayer.hidden=true;
  editorLayer.setAttribute('role','dialog');editorLayer.setAttribute('aria-modal','true');editorLayer.setAttribute('aria-labelledby','rfq-editor-title');
  editorLayer.innerHTML='<div class="rfq-editor-backdrop" data-close-rfq-editor></div>';
  editorLayer.append(editor);root.append(editorLayer);
  let editorReturnFocus=null, editorOverflow='';
  editorLayer.querySelector('[data-close-rfq-editor]').onclick=()=>{if(canLeave())closeEditor(true);};
  const toast = document.createElement('div'); toast.className = 'rfq-toast'; toast.hidden = true;
  toast.setAttribute('role', 'status'); document.body.append(toast);
  const pid = () => Number(localStorage.getItem('tophoo-global-selected-project')) || 0;
  const auth = () => window.tophooAuth?.headers?.() || {};
  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const numberOrder = new Intl.Collator('en', {numeric:true,sensitivity:'base'});
  const compareNumbers = (a,b) => numberOrder.compare(String(b.number||'').trim(),String(a.number||'').trim()) || Number(b.id)-Number(a.id);
  const statuses = ['待处理', '推进中', '已报价', '已成交', '已关闭'];
  const statusLabel = value => value;
  let rfqs = [], contacts = [], ready = false, loadedProject = -1, loadVersion = 0, page = 1;
  let baseline = '', saving = false, returnFocus = null, oldOverflow = '', toastTimer;
  let editorGeneration = 0, isAdmin = false, owners = [], currentUserId=null, customerContext=null;
  const ownerFilter = q('[data-rfq-owner]');
  const searchIndex = new Map();
  const pendingDeletes = new Set();
  function say(message, error = false) {
    clearTimeout(toastTimer); toast.textContent = message; toast.classList.toggle('is-error', error);
    toast.hidden = false; toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 7000 : 3200);
  }
  const errorMessage = body => Array.isArray(body?.detail)
    ? body.detail.map(entry => `${entry.loc?.slice(1).join(' / ') || '字段'}：${entry.msg}`).join('；')
    : typeof body?.detail === 'string' ? body.detail : '请求失败，请重试。';
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, headers: {...auth(), ...(options.headers || {})}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(errorMessage(body));
    if(options.method&&!['GET','HEAD'].includes(options.method)&&url.startsWith('/api/rfqs/projects/')){const info={project:Number(url.split('/')[4]),nonce:Date.now()+Math.random()};document.dispatchEvent(new CustomEvent('tophoo-linked-data-updated',{detail:info}));try{localStorage.setItem('tophoo-linked-data-updated',JSON.stringify(info));}catch{}}
    return body;
  }
  const normalizedStatus = value => ['需求确认中', '报价准备中'].includes(value) ? '推进中' : value === '沟通失败' ? '已关闭' : statuses.includes(value) ? value : '待处理';
  const statusBadge = value => `<span class="rfq-status is-${statuses.indexOf(normalizedStatus(value))}">${esc(statusLabel(normalizedStatus(value)))}</span>`;
  const statusSaves = new Map();
  const canEditStatus = () => !window.tophooProjectAccess || window.tophooProjectAccess.canEdit('rfq');
  const statusControl = item => {
    const pending = statusSaves.get(`${pid()}:${item.id}`), value = pending?.next || normalizedStatus(item.status);
    return `<span class="rfq-status-control"><select class="rfq-status rfq-inline-status is-${statuses.indexOf(value)}" data-rfq-inline-status="${item.id}" aria-label="修改 ${esc(item.number)} 的状态" title="${pending?'正在保存…':canEditStatus()?'选择后自动保存':'当前只有查看权限'}" ${pending||!canEditStatus()?'disabled':''} ${pending?'aria-busy="true"':''}>${statuses.map(s=>`<option value="${s}" ${s===value?'selected':''}>${s}</option>`).join('')}</select></span>`;
  };
  // Project permissions can arrive after the enquiry list has rendered.
  // Update existing controls so an initial loading state cannot leave them disabled.
  function syncStatusAccess() {
    rows.querySelectorAll('[data-rfq-inline-status]').forEach(select => {
      const pending = statusSaves.has(`${pid()}:${select.dataset.rfqInlineStatus}`);
      select.disabled = pending || !canEditStatus();
      select.title = pending ? '正在保存…' : canEditStatus() ? '选择后自动保存' : '当前只有查看权限';
    });
  }
  window.addEventListener('tophoo-project-availability', () => queueMicrotask(syncStatusAccess));
  rows.addEventListener('change', async event => {
    const select = event.target.closest('[data-rfq-inline-status]');
    if(!select || !ready)return;
    const id=Number(select.dataset.rfqInlineStatus),item=rfqs.find(x=>x.id===id),next=select.value,key=`${pid()}:${id}`;
    if(!item || !canEditStatus() || statusSaves.has(key) || !statuses.includes(next)){renderRfqs();return;}
    if(next===normalizedStatus(item.status))return;
    const project=pid(),identity=JSON.stringify(auth()),version=loadVersion,run={next};statusSaves.set(key,run);select.disabled=true;select.setAttribute('aria-busy','true');
    const current=()=>project===pid() && identity===JSON.stringify(auth()) && statusSaves.get(key)===run;
    try{
      const result=await request(`/api/rfqs/projects/${project}/${id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:next})});
      if(!current())return;
      if(version!==loadVersion){await load();return;}
      item.status=result.status;
      const detailStatus=previewContent.querySelector('[data-rfq-field="status"]>div');
      if(!preview.hidden&&q(`[data-edit-rfq="${id}"]`)&&detailStatus)detailStatus.innerHTML=statusBadge(item.status);
      say('询价单状态已更新。');
    }catch(error){if(current())say(error.message,true);}
    finally{
      if(statusSaves.get(key)===run){const focused=document.activeElement===select;statusSaves.delete(key);if(project===pid()&&identity===JSON.stringify(auth())&&ready){renderRfqs();if(focused)q(`[data-rfq-inline-status="${id}"]`)?.focus({preventScroll:true});}}
    }
  });
  const websiteLink = value => {
    const raw = String(value || '').trim();
    if (!raw) return '—';
    try {
      if (/^[a-z][a-z\d+.-]*:/i.test(raw) && !/^https?:/i.test(raw)) return esc(raw);
      const url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
      return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(raw)}</a>`;
    } catch { return esc(raw); }
  };
  const pageSize = () => {
    const raw = q('[data-rfq-size]').value === 'custom' ? q('[data-rfq-custom-count]').value : q('[data-rfq-size]').value;
    return Math.min(1000, Math.max(1, Math.floor(Number(raw) || 20)));
  };
  function remember() {
    if (customerContext) return;
    try { sessionStorage.setItem(`rfq-list-${loadedProject}`, JSON.stringify({query:search.value,status:status.value,source:source.value,owner:ownerFilter.value,size:String(pageSize()),page})); } catch {}
  }
  const clockFormats = new Map();
  function clockContent(clock) {
    if (!clock?.timezone) return `<span class="rfq-clock-hint">${esc(clock?.hint || '待补充地区')}</span>`;
    try {
      let formats = clockFormats.get(clock.timezone);
      if (!formats) { formats = {time: new Intl.DateTimeFormat('zh-CN', {timeZone:clock.timezone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}),date: new Intl.DateTimeFormat('zh-CN', {timeZone:clock.timezone,month:'2-digit',day:'2-digit',weekday:'short'})}; clockFormats.set(clock.timezone, formats); }
      const now = new Date();
      return `<time title="${esc(clock.timezone)}"><strong>${esc(formats.time.format(now))}</strong><small>${esc(formats.date.format(now))} · ${esc(clock.city || clock.timezone)}</small></time>`;
    } catch { return '<span class="rfq-clock-hint">待确认时区</span>'; }
  }
  setInterval(() => {
    if (root.hidden || !ready || document.hidden) return;
    rows.querySelectorAll('[data-rfq-clock]').forEach(node => { const item = rfqs.find(x => x.id === Number(node.dataset.rfqClock)); if (item) node.innerHTML = clockContent(item.local_clock); });
  }, 15000);
  function filteredRfqs() {
    const query = search.value.trim().toLocaleLowerCase();
    return rfqs.filter(item => (!status.value || normalizedStatus(item.status) === status.value)
      && (!source.value || item.inquiry_source === source.value)
      && (!ownerFilter.value || String(item.owner_user_id) === ownerFilter.value)
      && (!query || (searchIndex.get(item.id) || '').includes(query)));
  }
  function renderRfqs() {
    if(customerContext&&ready&&!root.hidden)document.dispatchEvent(new CustomEvent('tophoo-customer-documents-loaded',{detail:{...customerContext,kind:'rfqs',count:rfqs.length}}));
    syncStats();
    const filtered=filteredRfqs();
    const size = pageSize(), pages = Math.max(1, Math.ceil(filtered.length / size));
    page = Math.min(Math.max(1, page), pages);
    rows.innerHTML = filtered.length ? filtered.slice((page - 1) * size, page * size).map(item => {
      return `<tr data-rfq-row="${item.id}"><td><button type="button" class="rfq-number" data-preview-rfq="${item.id}" title="${esc(item.number)}">${esc(item.number)}</button></td><td>${esc(item.inquiry_date) || '—'}</td><td>${esc(item.inquiry_source) || '—'}</td><td>${statusControl(item)}</td><td><strong class="rfq-company" title="${esc(item.company_name)}">${esc(item.company_name) || '未关联客户'}</strong><small title="${esc([item.contact_name,item.contact_country].filter(Boolean).join(' · '))}">${esc(item.contact_name) || '—'}${item.contact_country ? ` · ${esc(item.contact_country)}` : ''}</small></td><td class="rfq-local-clock" data-rfq-clock="${item.id}">${clockContent(item.local_clock)}</td></tr>`;
    }).join('') : `<tr><td colspan="6" class="rfq-empty">${rfqs.length ? '没有匹配的询价单，可调整搜索或筛选条件。' : '还没有询价单，点击“新建询价单”开始。'}</td></tr>`;
    q('[data-rfq-total]').textContent = rfqs.length;
    const counts = {pending:0, active:0, quoted:0, won:0, closed:0};
    rfqs.forEach(item => {
      const value = normalizedStatus(item.status);
      if (value === '待处理') counts.pending++;
      if (value === '推进中') counts.active++;
      if (value === '已报价') counts.quoted++;
      if (value === '已成交') counts.won++;
      if (value === '已关闭') counts.closed++;
    });
    Object.entries(counts).forEach(([key, value]) => { q(`[data-rfq-metric="${key}"]`).textContent = value; });
    q('[data-rfq-summary]').textContent = filtered.length ? `共 ${filtered.length} 条 · 显示 ${(page - 1) * size + 1}–${Math.min(page * size, filtered.length)}` : '共 0 条';
    q('[data-rfq-page]').textContent = `${page} / ${pages}`;
    q('[data-rfq-prev]').disabled = page === 1; q('[data-rfq-next]').disabled = page === pages;
    q('.rfq-pagination').hidden = !!customerContext && filtered.length <= size;
    renderFilterChips();
    remember();
  }
  function renderFilterChips() {
    const host = q('[data-rfq-filters]');
    const owner = owners.find(item => String(item.id) === ownerFilter.value);
    const entries = [['query',search.value.trim()],['status',status.value],['source',source.value],['owner',ownerFilter.value ? owner?.name || ownerFilter.value : '']].filter(([,value]) => value);
    q('.rfq-list-context').hidden = !!customerContext && !entries.length;
    host.innerHTML = entries.length ? entries.map(([key,value]) => `<button type="button" class="rfq-filter-chip" data-rfq-clear-filter="${key}" aria-label="移除${esc({query:'搜索',status:'状态',source:'来源',owner:'归属'}[key])}筛选：${esc(value)}"><span>${esc(value)}</span><i aria-hidden="true">×</i></button>`).join('') : '<span class="rfq-list-hint">按编号从大到小排序 · 点击记录查看详情</span>';
  }
  q('[data-rfq-filters]').addEventListener('click',event => {
    const button = event.target.closest('[data-rfq-clear-filter]');
    if (!button || !ready) return;
    const control = {query:search,status,source,owner:ownerFilter}[button.dataset.rfqClearFilter];
    if (control) {control.value='';filterChanged();}
  });
  function refreshSources(savedValue = source.value) {
    const selectedStatus = status.dataset.restore || status.value;
    status.innerHTML = '<option value="">全部状态</option>' + statuses.map(value => `<option value="${esc(value)}">${esc(statusLabel(value))}</option>`).join('');
    status.value = selectedStatus ? normalizedStatus(selectedStatus) : '';
    searchIndex.clear();
    rfqs.forEach(item => searchIndex.set(item.id, [item.number,item.company_name,item.contact_name,item.contact_country,item.contact_email,item.contact_phone,item.contact_whatsapp,item.owner_name,item.inquiry_source,item.product_number,...(item.generic_fields || []).flatMap(field => [field.title,field.content]),...(item.inquiry_items || []).flatMap(entry=>[entry.content,entry.translation,entry.price,entry.notes])].join(' ').toLocaleLowerCase()));
    source.innerHTML = '<option value="">全部来源</option>' + [...new Set(rfqs.map(item => item.inquiry_source).filter(Boolean))].sort().map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
    source.value = savedValue;
  }
  const editorValue = () => JSON.stringify([...editor.querySelectorAll('input:not([data-contact-search]), select, textarea')].map(control => control.value));
  const dirty = () => !editor.hidden && baseline !== editorValue();
  function canLeave() {
    if (saving) { say('正在保存，请稍候。'); return false; }
    return !dirty() || confirm('有未保存的询价单 修改，确定放弃并离开吗？');
  }
  function closeEditor(restoreFocus = false) {
    editorGeneration++;
    const wasOpen=!editor.hidden;
    baseline = ''; editor.hidden = true; editorLayer.hidden=true; editor.innerHTML = ''; records.inert=false;q('.rfq-page-head').inert=false;
    if(wasOpen)document.body.style.overflow=editorOverflow;
    if (restoreFocus) (editorReturnFocus?.isConnected ? editorReturnFocus : add).focus({preventScroll:true});
    editorReturnFocus=null;
  }
  function closePreview(restoreFocus = false) {
    if (preview.hidden) return;
    preview.hidden = true; previewContent.innerHTML = ''; q('[data-rfq-detail-actions]').innerHTML = ''; document.body.style.overflow = oldOverflow;
    if (restoreFocus && returnFocus?.isConnected) returnFocus.focus({preventScroll:true});
    returnFocus = null;
  }
  // Shared labels, order and section identity for create, edit and detail.
  const blocks = {
    inquiry: '询价信息', customer: '客户信息', contact: '对接联系人',
    requirements: '需求内容', product_number: '历史产品编号',
  };
  const fieldLabels = {
    number:'编号', status:'当前状态', inquiry_date:'询价日期', inquiry_source:'询盘来源',
    owner_name:'归属用户', company_name:'客户名称', contact_country:'国家 / 地区',
    company_type_label:'企业类型', company_website:'公司官网', company_address:'公司地址',
    contact_name:'联系人姓名', contact_email:'邮箱', contact_phone:'电话',
    contact_whatsapp:'WhatsApp', contact_job_title:'职位',
  };
  const companyOrder = ['contact_country','company_type_label','company_website'];
  const personOrder = ['contact_email','contact_phone','contact_whatsapp'];
  const block = (key, content, action = '', badge = '') => `<section class="rfq-block" data-rfq-block="${key}"><header class="rfq-block-head"><h4>${blocks[key]}</h4>${badge}${action}</header>${content}</section>`;
  const fact = (key, value, {link = false, keep = false} = {}) => {
    if (!keep && !String(value ?? '').trim()) return '';
    return `<div class="rfq-fact" data-rfq-field="${key}"><span>${fieldLabels[key] || key}</span><div>${link && value ? websiteLink(value) : esc(value) || '—'}</div></div>`;
  };
  const factGrid = content => `<div class="rfq-facts">${content}</div>`;
  const moreFacts = (label, content) => content ? `<details class="rfq-more-info"><summary>${label}</summary>${factGrid(content)}</details>` : '';
  const socialFacts = (item, prefix) => ['linkedin','facebook','instagram','youtube'].map(key => {
    const value = item[`${prefix}_${key}`];
    return value ? `<div class="rfq-fact" data-rfq-field="${prefix}_${key}"><span>${{linkedin:'LinkedIn',facebook:'Facebook',instagram:'Instagram',youtube:'YouTube'}[key]}</span><div>${websiteLink(value)}</div></div>` : '';
  }).join('');
  const companyFacts = item => factGrid(companyOrder.map(key => fact(key,item[key],{link:key==='company_website'})).join(''))
    + moreFacts('更多客户资料',fact('company_address',item.company_address) + socialFacts(item,'company'));
  const personFacts = item => factGrid(personOrder.map(key => fact(key,item[key])).join(''))
    + moreFacts('更多联系资料',fact('contact_job_title',item.contact_job_title) + socialFacts(item,'contact'));
  const contactBadge = saved => `<small class="rfq-block-badge" title="${saved ? '联系人资料已随此询价保存，客户档案变更不会覆盖。' : '保存询价时保留本次联系人的姓名及联系方式。'}">${saved ? '资料已保留' : '随询价保存'}</small>`;
  const parameterNote = value => value ? `<details class="rfq-parameter-note"><summary>参数备注</summary><div class="rfq-read-text">${esc(value)}</div></details>` : '';

  function requirementDetails(item) {
    const entries = (item.inquiry_items || []).map((entry, index) =>
      `<article class="rfq-requirement"><h5>明细 ${index+1}</h5>${[
        ['需求',entry.content],['规格/参数',entry.translation],['报价',entry.price],['备注',entry.notes],
      ].map(([label,value])=>`<div class="rfq-fact"><span>${label}</span><div class="rfq-read-text">${esc(value)||'—'}</div></div>`).join('')}</article>`);
    for (const field of item.generic_fields || []) {
      entries.push(`<article class="rfq-requirement"><div class="rfq-fact"><span>需求标题</span><h5>${esc(field.title)}</h5></div><div class="rfq-fact"><span>需求内容</span><div class="rfq-read-text">${esc(field.content) || '—'}</div></div>${parameterNote(item.parameter_notes?.[field.key])}</article>`);
    }
    return `<div class="rfq-requirement-list">${entries.join('')||'<p class="rfq-block-empty">暂无需求内容</p>'}</div>`;
  }

  function openPreview(item) {
    if (!item) return;
    returnFocus = document.activeElement; oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    q('[data-rfq-preview-title]').textContent = `${item.number || '询价单'} · 详情`;
    q('[data-rfq-detail-actions]').innerHTML = `<button type="button" class="rfq-danger" data-delete-rfq="${item.id}" aria-label="删除 ${esc(item.number)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/></svg>删除</button><div class="rfq-detail-primary-actions"><button type="button" data-edit-rfq="${item.id}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5M4 20l4-1 13-13a2 2 0 0 0-5-3L3 16l-1 5Z"/></svg>编辑询价单</button></div>`;
    previewContent.innerHTML = block('inquiry',factGrid(
      fact('number',item.number,{keep:true}) + `<div class="rfq-fact" data-rfq-field="status"><span>${fieldLabels.status}</span><div>${statusBadge(item.status)}</div></div>`
      + fact('inquiry_date',item.inquiry_date,{keep:true}) + fact('inquiry_source',item.inquiry_source,{keep:true}))
      + moreFacts('更多询价信息',fact('owner_name',item.owner_name) + fact('product_number',item.product_number)))
      + block('customer',factGrid(fact('company_name',item.company_name || '未关联客户',{keep:true})) + companyFacts(item), '', '<small class="rfq-block-badge">来自客户档案</small>')
      + block('contact',factGrid(fact('contact_name',item.contact_name || '未指定',{keep:true})) + personFacts(item),'',contactBadge(item.contact_snapshot_saved))
      + block('requirements',requirementDetails(item));
    preview.hidden = false; preview.querySelector('button').focus({preventScroll:true});
    document.dispatchEvent(new CustomEvent('tophoo-rfq-detail-ready',{detail:{project:pid(),customerId:item.contact_id,personId:item.contact_person_id}}));
  }
  const genericRow = (field = {}) => `<div class="rfq-generic-row" data-generic-key="${esc(field.key || '')}"><label>需求标题<input data-generic-title maxlength="180" value="${esc(field.title)}" placeholder="例如：工况参数、尺寸要求"></label><label>需求内容<textarea data-generic-content maxlength="20000" placeholder="粘贴客户需求、图纸说明或技术参数">${esc(field.content)}</textarea></label>${parameterNote(field.parameter_note)}<button type="button" data-remove-generic class="rfq-secondary" aria-label="删除该项内容">×</button></div>`;
  function openRfq(item = {}) {
    if(customerContext&&!item.id)item={...item,contact_id:customerContext.customer};
    if(item.id&&statusSaves.has(`${pid()}:${item.id}`))return say('正在保存状态，请稍候。');
    if (!ready || !canLeave()) return;
    editorReturnFocus=item.id ? q(`[data-preview-rfq="${item.id}"]`) : add;
    closePreview();
    if(editor.hidden)editorOverflow=document.body.style.overflow;
    const project = pid(), editorAuth = JSON.stringify(auth()), generation = ++editorGeneration;
    records.inert=true;q('.rfq-page-head').inert=true;
    const inputField = (key, control) => `<label class="rfq-field" data-rfq-field="${key}"><span>${fieldLabels[key]}</span>${control}</label>`;
    const inquiryFields = `<div class="rfq-form-grid">${inputField('number',`<input name="number" maxlength="40" value="${esc(item.number)}" placeholder="留空自动生成">`)}${inputField('status',`<select name="status">${statuses.map(value=>`<option value="${value}" ${value===normalizedStatus(item.status)?'selected':''}>${value}</option>`).join('')}</select>`)}${inputField('inquiry_date',`<input type="date" name="inquiry_date" value="${esc(item.inquiry_date)}">`)}${inputField('inquiry_source',`<input name="inquiry_source" maxlength="160" value="${esc(item.inquiry_source)}" placeholder="MIC、邮件、WhatsApp…">`)}</div>`;
    const ownerControl = isAdmin ? `<label class="rfq-field" data-rfq-field="owner_name"><span>${fieldLabels.owner_name}</span><select name="owner_user_id" aria-label="归属用户"><option value="">${item.id ? '保持当前归属' : '默认归客户负责人，未关联时归本人'}</option>${owners.map(owner=>`<option value="${owner.id}" ${owner.id===item.owner_user_id?'selected':''}>${esc(owner.name)}</option>`).join('')}${item.owner_user_id && !owners.some(owner=>owner.id===item.owner_user_id) ? `<option value="${item.owner_user_id}" selected>${esc(item.owner_name || '原归属用户')}（原归属）</option>` : ''}</select></label>` : fact('owner_name',item.owner_name || '当前用户');
    const customerPicker = `<div class="rfq-customer-picker" data-rfq-field="company_name"><label for="rfq-customer-search">${fieldLabels.company_name}</label><input id="rfq-customer-search" type="search" data-contact-search role="combobox" aria-label="查找关联客户" aria-autocomplete="list" aria-expanded="false" aria-controls="rfq-customer-options" autocomplete="off" placeholder="搜索公司、联系人、邮箱或国家"><select name="contact" aria-label="关联客户" hidden></select><div id="rfq-customer-options" class="rfq-customer-options" role="listbox" hidden></div><small data-customer-selected hidden></small></div>`;
    editor.innerHTML = `<form data-rfq-form><div class="rfq-editor-head"><div class="rfq-window-heading"><small>询价管理 · ${item.id ? '编辑' : '新增'}</small><h3 id="rfq-editor-title">${item.id ? '编辑询价单' : '新增询价单'}</h3><small data-rfq-draft-status>Ctrl / ⌘ + S 保存</small></div><div><button type="button" data-cancel class="rfq-secondary rfq-editor-close" aria-label="关闭编辑">×</button></div></div><div class="rfq-editor-body"><p class="rfq-form-error" data-rfq-error role="alert" hidden></p><div class="rfq-block-layout">`
      + block('inquiry',inquiryFields + moreFacts('更多询价信息',ownerControl))
      + block('customer',customerPicker + '<div data-customer-facts></div>','','<small class="rfq-block-badge">来自客户档案</small>')
      + block('contact',inputField('contact_name','<select name="contact_person" aria-label="本次对接联系人"></select>') + '<div data-associated-info></div>','','<span data-contact-badge></span>')
      + block('requirements',`<div data-generic-fields>${(item.generic_fields?.length ? item.generic_fields : [{}]).map(field=>genericRow({...field,parameter_note:item.parameter_notes?.[field.key]})).join('')}</div>`,'<button type="button" class="rfq-secondary" data-add-generic>＋ 增加内容</button>')
      + '</div></div><div class="rfq-editor-bottom"><button type="button" data-cancel class="rfq-secondary">取消</button><button type="submit" data-save>保存询价单</button></div></form>';
    editor.hidden = false;editorLayer.hidden=false;document.body.style.overflow='hidden';
    const eq = selector => editor.querySelector(selector), form = eq('[data-rfq-form]'), contactSelect = eq('[name="contact"]');
    const genericHost = eq('[data-generic-fields]');
    function contactOptions(selected) {
      const term = eq('[data-contact-search]').value.trim().toLocaleLowerCase();
      const matches = contacts.filter(contact => contact.id === Number(selected) || !term || [contact.name,contact.company,contact.email,contact.country,...(contact.people || []).flatMap(person=>[person.contact_name,person.email,person.phone,person.whatsapp])].join(' ').toLocaleLowerCase().includes(term));
      contactSelect.innerHTML = '<option value="">暂不关联客户</option>' + matches.map(contact => `<option value="${contact.id}">${esc(contact.name)}${contact.company ? ` · ${esc(contact.company)}` : ''}${contact.country ? ` · ${esc(contact.country)}` : ''}</option>`).join('');
      // Keep a historical link when the current selector cannot access that contact.
      if (selected && !matches.some(contact => contact.id === Number(selected))) contactSelect.insertAdjacentHTML('beforeend', `<option value="${Number(selected)}">${esc(item.contact_name || '原关联客户')}（当前不可选）</option>`);
      contactSelect.value = selected || '';
    }
    const personSelect = eq('[name="contact_person"]'), customerSearch = eq('[data-contact-search]'), optionsHost = eq('#rfq-customer-options');
    let activeOption = -1;
    function associatedInfo() {
      const contact = contacts.find(entry => entry.id === Number(contactSelect.value));
      const snapshot = Number(contactSelect.value) === item.contact_id && (Number(personSelect.value) || null) === (item.contact_person_id || null) && item.contact_snapshot_saved;
      const person = (snapshot || (!contact && Number(contactSelect.value) === item.contact_id)) ? {contact_name:item.contact_name,email:item.contact_email,phone:item.contact_phone,whatsapp:item.contact_whatsapp,job_title:item.contact_job_title,...Object.fromEntries(['linkedin','facebook','instagram','youtube'].map(key=>[key,item[`contact_${key}`]]))} : (contact?.people || []).find(entry => entry.id === Number(personSelect.value)) || contact;
      const customer = contact ? {contact_country:contact.country,...contact} : Number(contactSelect.value) === item.contact_id ? item : {};
      const personItem = Object.fromEntries(['email','phone','whatsapp','job_title','linkedin','facebook','instagram','youtube'].map(key=>[`contact_${key}`,person?.[key]]));
      // Keep the current customer's company facts and the selected person's snapshot separate.
      eq('[data-customer-facts]').innerHTML = companyFacts(customer);
      eq('[data-associated-info]').innerHTML = personFacts(personItem);
      eq('[data-contact-badge]').innerHTML = contactBadge(snapshot);
      const selectedName = contact?.company || contact?.name || (contactSelect.value ? item.company_name : '');
      customerSearch.placeholder = '搜索公司、联系人、邮箱或国家';
      if (document.activeElement !== customerSearch) customerSearch.value = selectedName || ''; 
      customerSearch.setAttribute('aria-description', selectedName ? `已关联客户：${selectedName}` : '未关联客户');
      eq('[data-customer-selected]').textContent = selectedName;
    }
    function personOptions(initial = false) {
      const contact = contacts.find(entry => entry.id === Number(contactSelect.value));
      const people = contact?.people || [];
      personSelect.innerHTML = people.map(person=>`<option value="${person.id}">${esc(person.contact_name || '未填写姓名')}${person.is_primary ? ' · 主联系人' : ''}${person.email ? ` · ${esc(person.email)}` : ''}</option>`).join('');
      if (initial && item.contact_snapshot_saved) {
        const value = item.contact_person_id || '';
        if (![...personSelect.options].some(option=>option.value===String(value))) personSelect.insertAdjacentHTML('beforeend',`<option value="${esc(value)}">${esc(item.contact_name || '原对接联系人')} · 历史资料</option>`);
        personSelect.value = value;
        if (personSelect.selectedOptions[0]) personSelect.selectedOptions[0].textContent = item.contact_name || '原对接联系人';
      } else if (people.length) personSelect.value = (people.find(person=>person.is_primary) || people[0]).id;
      else personSelect.innerHTML = `<option value="">${contact ? esc(contact.name || '未填写联系人') : contactSelect.value ? esc(item.contact_name || '原对接联系人') : '请先关联客户'}</option>`;
      personSelect.disabled = !contactSelect.value;
      associatedInfo();
    }
    function showCustomerOptions() {
      contactOptions(contactSelect.value);
      optionsHost.innerHTML = [...contactSelect.options].map((option,index)=>`<button type="button" role="option" id="rfq-customer-option-${index}" data-customer-value="${esc(option.value)}" aria-selected="${option.value === contactSelect.value}">${esc(option.textContent)}</button>`).join('');
      optionsHost.hidden = false; customerSearch.setAttribute('aria-expanded','true'); activeOption = -1;
      customerSearch.removeAttribute('aria-activedescendant');
    }
    function hideCustomerOptions() { optionsHost.hidden=true;customerSearch.setAttribute('aria-expanded','false');customerSearch.removeAttribute('aria-activedescendant'); }
    function chooseCustomer(value) {
      const changed = contactSelect.value !== value;
      if (changed && isAdmin) { eq('[name="owner_user_id"]').value=''; eq('[name="owner_user_id"] option[value=""]').textContent='默认归客户负责人，未关联时保留原归属'; }
      contactSelect.value=value;customerSearch.value='';contactOptions(value);personOptions(!changed && Number(value) === item.contact_id);
      customerSearch.value=eq('[data-customer-selected]').textContent;
      const contact=contacts.find(entry=>entry.id===Number(value));
      if (!item.id && !eq('[name="inquiry_source"]').value.trim() && contact?.source) eq('[name="inquiry_source"]').value=contact.source;
      hideCustomerOptions();updateDirty();
    }
    contactOptions(item.contact_id); personOptions(true);
    customerSearch.oninput=showCustomerOptions;customerSearch.onfocus=()=>{customerSearch.select();showCustomerOptions();};
    optionsHost.onclick=event=>{const option=event.target.closest('[data-customer-value]');if(option){chooseCustomer(option.dataset.customerValue);customerSearch.focus();hideCustomerOptions();}};
    customerSearch.onkeydown=event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();hideCustomerOptions();return;}
      if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return;
      if(event.key==='Enter' && optionsHost.hidden)return;
      event.preventDefault();if(optionsHost.hidden)showCustomerOptions();
      const options=[...optionsHost.querySelectorAll('[role="option"]')];
      if(event.key==='Enter'){if(activeOption>=0)chooseCustomer(options[activeOption].dataset.customerValue);return;}
      activeOption=(activeOption+(event.key==='ArrowDown'?1:-1)+options.length)%options.length;
      options.forEach((option,index)=>option.classList.toggle('is-active',index===activeOption));
      customerSearch.setAttribute('aria-activedescendant',options[activeOption].id);options[activeOption].scrollIntoView({block:'nearest'});
    };
    eq('.rfq-customer-picker').addEventListener('focusout',()=>setTimeout(()=>{if(!eq('.rfq-customer-picker')?.contains(document.activeElement)){hideCustomerOptions();if(form.isConnected)customerSearch.value=eq('[data-customer-selected]').textContent;}},0));
    contactSelect.onchange=()=>personOptions();personSelect.onchange=associatedInfo;
    eq('[data-add-generic]').onclick = () => {
      if (genericHost.children.length >= 100) return say('最多可添加 100 项需求内容。', true);
      genericHost.insertAdjacentHTML('beforeend', genericRow()); genericHost.lastElementChild.querySelector('input').focus(); updateDirty();
    };
    genericHost.onclick = event => {
      const button = event.target.closest('[data-remove-generic]'); if (!button || saving) return;
      const row = button.closest('.rfq-generic-row');
      if ([...row.querySelectorAll('input,textarea')].some(control => control.value.trim()) && !confirm('删除这项需求内容？保存后生效。')) return;
      row.remove(); updateDirty();
    };
    editor.querySelectorAll('[data-cancel]').forEach(button => button.onclick = () => { if (canLeave()) closeEditor(true); });
    function updateDirty() { eq('[data-rfq-draft-status]').textContent = dirty() ? '有未保存修改 · Ctrl / ⌘ + S 保存' : 'Ctrl / ⌘ + S 保存'; }
    if(customerContext){contactSelect.disabled=true;customerSearch.readOnly=true;customerSearch.onfocus=null;customerSearch.oninput=null;customerSearch.onkeydown=null;hideCustomerOptions();if(isAdmin)eq('[name=owner_user_id]').closest('label').hidden=true;}
    baseline = editorValue(); form.addEventListener('input', updateDirty); form.addEventListener('change', updateDirty);
    form.onsubmit = async event => {
      event.preventDefault(); if (saving) return;
      const error = eq('[data-rfq-error]'); error.hidden = true;
      const fail = message => { error.textContent = message; error.hidden = false; error.scrollIntoView({block:'nearest'}); };
      if (pid() !== project || JSON.stringify(auth()) !== editorAuth) return fail('项目或登录状态已切换，请重新打开编辑。');
      const fieldRows = [...genericHost.querySelectorAll('.rfq-generic-row')];
      const generic_fields = fieldRows.map((row, index) => ({key:row.dataset.genericKey || `field_${Date.now().toString(36)}_${index + 1}`,title:row.querySelector('[data-generic-title]').value.trim(),content:row.querySelector('[data-generic-content]').value})).filter(field => field.title || field.content.trim());
      if (generic_fields.some(field => !field.title)) {
        fail('请为每一项已填写的需求内容添加标题。');
        fieldRows.find(row => !row.querySelector('input').value.trim() && row.querySelector('textarea').value.trim())?.querySelector('input').focus(); return;
      }
      const payload = {number:eq('[name="number"]').value.trim() || null,inquiry_date:eq('[name="inquiry_date"]').value || null,inquiry_source:eq('[name="inquiry_source"]').value.trim() || null,product_number:item.product_number || null,contact_id:Number(contactSelect.value) || null,contact_person_id:Number(personSelect.value) || null,template_key:'general',status:eq('[name="status"]').value,priority:item.priority || 'normal',owner:item.owner || null,application:item.application || null,quantity:item.quantity || null,parameters:{},parameter_notes:item.parameter_notes || {},generic_fields};
      if (isAdmin && eq('[name="owner_user_id"]').value && Number(eq('[name="owner_user_id"]').value) !== item.owner_user_id) payload.owner_user_id=Number(eq('[name="owner_user_id"]').value);
      saving = true;
      const controls = [...form.querySelectorAll('input,textarea,select,button')];
      if(customerContext){payload.contact_id=customerContext.customer;if(!item.id&&currentUserId)payload.owner_user_id=currentUserId;}
      controls.forEach(control => { control.disabled = true; });
      editor.querySelectorAll('[data-save]').forEach(button => { button.textContent = '保存中…'; });
      try {
        const saved = await request(`/api/rfqs/projects/${project}${item.id ? `/${item.id}` : ''}`, {method:item.id ? 'PUT' : 'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if (project !== pid() || JSON.stringify(auth()) !== editorAuth || generation !== editorGeneration || !form.isConnected) return;
        rfqs = [saved,...rfqs.filter(entry => entry.id !== saved.id)];
        rfqs.sort(compareNumbers);
        baseline = ''; saving = false; closeEditor(); refreshSources(); renderRfqs(); (q(`[data-preview-rfq="${saved.id}"]`) || add).focus({preventScroll:true}); say('询价单 已保存。');
      } catch (error) { if (project === pid() && form.isConnected) fail(error.message); }
      finally {
        // An old request must not unlock an editor opened in a different project.
        if (project === pid() && generation === editorGeneration) saving = false;
        controls.forEach(control => { control.disabled = false; });
        form.querySelectorAll('[data-save]').forEach(button => { button.textContent = '保存询价单'; });
      }
    };
    eq('[name="number"]').focus({preventScroll:true});
  }
  async function removeRfq(id) {
    const item = rfqs.find(entry => entry.id === id), project = pid(), identity = JSON.stringify(auth());
    if (!item || pendingDeletes.has(id) || !confirm(`确认删除询价单「${item.number}」？此操作无法恢复。`)) return;
    pendingDeletes.add(id);
    const button = q(`[data-delete-rfq="${id}"]`); if (button) button.disabled = true;
    try {
      await request(`/api/rfqs/projects/${project}/${id}`, {method:'DELETE'});
      if (project !== pid() || identity !== JSON.stringify(auth())) return;
      rfqs = rfqs.filter(entry => entry.id !== id); closePreview(); refreshSources(); renderRfqs(); say('询价单 已删除。');
    } catch (error) { if (project === pid()) say(error.message, true); }
    finally { pendingDeletes.delete(id); if (button) button.disabled = false; }
  }
  root.addEventListener('click', event => {
    const row = event.target.closest('[data-rfq-row]');
    if (row && !event.target.closest('button,a,input,select,textarea,.rfq-status-control') && !window.getSelection()?.toString().trim() && ready) {
      // Keep a stable keyboard return target when opening from a non-focusable cell.
      row.querySelector('[data-preview-rfq]')?.focus({preventScroll:true});
      openPreview(rfqs.find(item => item.id === Number(row.dataset.rfqRow)));
      return;
    }
    const button = event.target.closest('[data-preview-rfq],[data-edit-rfq],[data-delete-rfq]');
    if (!button || !ready) return;
    if (button.dataset.previewRfq) openPreview(rfqs.find(item => item.id === Number(button.dataset.previewRfq)));
    if (button.dataset.editRfq) openRfq(rfqs.find(item => item.id === Number(button.dataset.editRfq)));
    if (button.dataset.deleteRfq) removeRfq(Number(button.dataset.deleteRfq));
  });
  async function load() {
    const project = pid(), identity = JSON.stringify(auth()), version = ++loadVersion;
    if (project !== loadedProject) {
      closePreview(); closeEditor(); saving = false; ready = false; rfqs = []; contacts = []; loadedProject = project;
      let restored = {}; try { if (!customerContext) restored = JSON.parse(sessionStorage.getItem(`rfq-list-${project}`) || '{}'); } catch {}
      if (customerContext) restored = {query:search.value,status:status.value};
      search.value = typeof restored.query === 'string' ? restored.query : ''; status.dataset.restore = restored.status || ''; status.value = restored.status || '';
      const restoredSize = Math.min(1000, Math.max(1, Math.floor(Number(restored.size) || 20)));
      q('[data-rfq-size]').value = [10,20,30].includes(restoredSize) ? String(restoredSize) : 'custom';
      q('[data-rfq-custom-count]').value = restoredSize;
      q('[data-rfq-custom-size]').hidden = q('[data-rfq-size]').value !== 'custom';
      page = Number(restored.page) || 1;
      refreshSources(); source.dataset.restore = restored.source || ''; ownerFilter.dataset.restore = restored.owner || '';
      ownerFilter.value='';ownerFilter.hidden=true;isAdmin=false;owners=[];
    } else if (!editor.hidden) return;
    ready = false; add.disabled = true; q('[data-rfq-refresh]').disabled = true;
    syncStats();
    rows.innerHTML = `<tr><td colspan="6" class="rfq-empty">${project ? '正在加载询价单…' : '请先选择项目。'}</td></tr>`;
    root.querySelectorAll('[data-rfq-total],[data-rfq-metric]').forEach(el => { el.textContent = '—'; });
    q('[data-rfq-summary]').textContent = ''; q('[data-rfq-page]').textContent = ''; q('[data-rfq-filters]').innerHTML = '';
    q('[data-rfq-prev]').disabled = true; q('[data-rfq-next]').disabled = true;
    if (!project) { q('[data-rfq-refresh]').disabled = false; return; }
    try {
      const [recordData, references] = await Promise.all([request(`/api/rfqs/projects/${project}${customerContext?`?customer_id=${customerContext.customer}&mine=true`:``}`), request(`/api/rfqs/projects/${project}/references`)]);
      if (version !== loadVersion || project !== pid() || identity !== JSON.stringify(auth())) return;
      rfqs = recordData.sort(compareNumbers); contacts = (references.contacts || []).filter(c=>!customerContext||c.id===customerContext.customer);currentUserId=references.current_user_id; isAdmin=!!references.is_top_admin; owners=references.owners || [];
      const selectedOwner=ownerFilter.dataset.restore || ownerFilter.value;
      ownerFilter.innerHTML='<option value="">全部归属</option>'+owners.map(owner=>`<option value="${owner.id}">${esc(owner.name)}</option>`).join('');
      ownerFilter.hidden=!isAdmin||!!customerContext;ownerFilter.value=isAdmin?selectedOwner:'';delete ownerFilter.dataset.restore;
      if(customerContext){ownerFilter.value='';document.dispatchEvent(new CustomEvent('tophoo-customer-documents-loaded',{detail:{...customerContext,kind:'rfqs',count:rfqs.length}}));}
      ready = true; add.disabled = false;
      refreshSources(source.dataset.restore || source.value); delete source.dataset.restore; delete status.dataset.restore; renderRfqs();
    } catch (error) {
      if (version !== loadVersion || project !== pid() || identity !== JSON.stringify(auth())) return;
      rows.innerHTML = `<tr><td colspan="6" class="rfq-empty">${esc(error.message)} <button type="button" class="rfq-secondary" data-rfq-retry>重新加载</button></td></tr>`;
      q('[data-rfq-retry]').onclick = load;
    } finally { if (version === loadVersion) q('[data-rfq-refresh]').disabled = false; }
  }
  function filterChanged() { if (!ready) return; page = 1; renderRfqs(); }
  statButtons.forEach(button => button.addEventListener('click', () => {
    if (!ready) return;
    search.value = ''; source.value = ''; ownerFilter.value = '';
    status.value = button.dataset.rfqStat;
    filterChanged();
  }));
  search.oninput = filterChanged; status.onchange = filterChanged; source.onchange = filterChanged; ownerFilter.onchange=filterChanged; q('[data-rfq-size]').onchange = () => {
    q('[data-rfq-custom-size]').hidden = q('[data-rfq-size]').value !== 'custom';
    if (q('[data-rfq-size]').value === 'custom') q('[data-rfq-custom-count]').focus();
    filterChanged();
  };
  q('[data-rfq-custom-count]').onchange = () => {
    q('[data-rfq-custom-count]').value = pageSize(); filterChanged();
  };
  q('[data-rfq-reset]').onclick = () => { search.value = ''; status.value = ''; source.value = ''; ownerFilter.value=''; filterChanged(); };
  q('[data-rfq-prev]').onclick = () => { if (ready) { page--; renderRfqs(); } };
  q('[data-rfq-next]').onclick = () => { if (ready) { page++; renderRfqs(); } };
  q('[data-rfq-refresh]').onclick = load; add.onclick = () => openRfq();
  root.querySelectorAll('[data-close-rfq-preview]').forEach(button => button.onclick = () => closePreview(true));
  document.addEventListener('keydown', event => {
    if (root.hidden) return;
    if (event.target.closest('dialog[open]')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && !editor.hidden) { event.preventDefault(); editor.querySelector('form').requestSubmit(); }
    if (event.key === 'Escape') { if (!preview.hidden) closePreview(true); else if (!editor.hidden && canLeave()) closeEditor(true); }
    const activeDialog=!editor.hidden ? editor : !preview.hidden ? preview : null;
    if (event.key === 'Tab' && activeDialog) {
      const focusables = [...activeDialog.querySelectorAll('button:not(:disabled),input:not(:disabled):not([type="hidden"]),textarea:not(:disabled),select:not(:disabled),a[href],summary')].filter(control => control.getClientRects().length && (control.tagName === 'SUMMARY' || !control.closest('details:not([open])')));
      const first = focusables[0], last = focusables.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  document.addEventListener('click', event => {
    if (root.hidden || !event.target.closest('.global-nav-item,.crm-primary-item,.pm-project-row')) return;
    if (!canLeave()) { event.preventDefault(); event.stopImmediatePropagation(); }
    else { closeEditor(); closePreview(); }
  }, true);

  window.addEventListener('beforeunload', event => { if (dirty() || saving) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('tophoo-customer-documents-view',event=>{
    const c=event.detail;if(c.kind!=='rfqs'||c.project!==pid())return;
    customerContext=c;root.dataset.customerScope=String(c.customer);search.value=c.search||'';status.value=c.status||'';source.value='';ownerFilter.value='';delete source.dataset.restore;delete status.dataset.restore;delete ownerFilter.dataset.restore;page=1;
    loadedProject=pid();load();
  });
  document.addEventListener('tophoo-customer-documents-leave',event=>{
    if(root.hidden||!customerContext)return;if(!canLeave()){event.preventDefault();return;}
    closeEditor();closePreview();++loadVersion;customerContext=null;delete root.dataset.customerScope;
  });
  document.querySelector('[data-crm-section="rfq"]')?.addEventListener('click', load);
  window.addEventListener('tophoo-project-changed',()=>{customerContext=null;delete root.dataset.customerScope;load();});
  document.addEventListener('tophoo-auth-changed',()=>{customerContext=null;delete root.dataset.customerScope;++loadVersion;closePreview();closeEditor();rfqs=[];ready=false;});
  document.addEventListener('tophoo-open-customer-document',async event=>{
    const c=event.detail;if(c.kind!=='rfqs'||c.project!==pid())return;
    await load();if(c.project!==pid()||root.hidden||!ready)return;
    openPreview(rfqs.find(item=>item.id===c.id&&item.contact_id===c.customer));
  });
  load();
})();
