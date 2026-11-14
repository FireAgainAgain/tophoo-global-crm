/* Sales quotations use current linked customer facts and server-calculated amounts. */
(() => {
  const root=document.querySelector('[data-crm-quotations]');if(!root)return;
  const q=selector=>root.querySelector(selector),editor=q('[data-quote-editor]'),form=q('[data-quote-form]'),detail=q('[data-quote-detail]'),pdf=q('[data-quote-pdf]');
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const today=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
  const editable=()=>!window.tophooProjectAccess||window.tophooProjectAccess.canEdit('quotations');
  let rows=[],refs={customers:[],defaults:{}},page=1,pageSize=10,version=0,loadedProject=0,editing=null,editProject=0,baseline='',busy=false,pdfUrl=null,linkVersion=0,linkRefreshing=false,detailRowId=null,templateSnapshot={};
  let customerContext=null;
  const templateTools=window.tophooQuotationTemplates?.(root,{api,editable,changed:refreshLinkedData,showPdf});
  async function api(path='',options={},project=pid()){
    const response=await fetch(`/api/quotations/projects/${project}${path}`,{...options,headers:{...(window.tophooAuth?.headers?.()||{}),...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{})}});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(typeof data.detail==='string'?data.detail:'请检查填写内容或稍后重试。');}
    return (/application\/(pdf|vnd\.openxmlformats-officedocument\.spreadsheetml\.sheet)/.test(response.headers.get('content-type')||''))?response.blob():response.json();
  }
  function feedback(message='',error=false){const node=q('[data-quote-feedback]');node.hidden=!message;node.textContent=message;node.classList.toggle('is-error',error);const status=q('[data-quote-detail-status]');if(status){status.textContent=message;status.hidden=!message;status.classList.toggle('is-error',error);}}
  const money=(value,currency)=>`${currency} ${String(value).replace(/\B(?=(\d{3})+(?!\d))/g,',')}`;
  function rowActions(row){
    const canEdit=editable(),menuId=`quote-row-menu-${row.id}`;
    return `
      <button type="button" class="quote-preview-action" data-quote-preview-saved="${row.id}" title="预览报价 PDF">预览</button>
      ${canEdit?`<button type="button" data-quote-edit="${row.id}">编辑</button>`:''}
      <button type="button" class="quote-more-action" popovertarget="${menuId}" aria-label="报价单 ${esc(row.number)} 的更多操作" title="更多操作">⋯</button>
      <div id="${menuId}" class="quote-row-menu" popover>
        <button type="button" data-quote-export="${row.id}">导出 PDF</button>
        <button type="button" data-quote-export-excel="${row.id}">导出 Excel</button>
        ${customerContext&&row.customer_id===customerContext.customer&&window.tophooProjectAccess?.canEdit('customer_list')?`<button type="button" data-quote-contract="${row.id}">生成合同</button>`:''}
        ${canEdit?`<button type="button" class="quote-danger" data-quote-delete="${row.id}">删除报价单</button>`:''}
      </div>`;
  }
  const rowActionsByName={view:showDetail,edit:openEditor,'preview-saved':previewSaved,export:download,
    'export-excel':row=>download(row,'xlsx'),delete:remove,
    contract:row=>document.dispatchEvent(new CustomEvent('tophoo-contract-from-quote',{detail:{customer:row.customer_id,quotationId:row.id}}))};
  const rowList=q('[data-quote-rows]');
  rowList.addEventListener('toggle',event=>{
    const menu=event.target;
    if(!menu.matches('.quote-row-menu')||event.newState!=='open')return;
    const trigger=menu.previousElementSibling.getBoundingClientRect();
    const {offsetWidth:width,offsetHeight:height}=menu;
    const viewport=document.documentElement;
    const below=trigger.bottom+6;
    menu.style.left=`${Math.max(8,Math.min(trigger.right-width,viewport.clientWidth-width-8))}px`;
    menu.style.top=`${below+height<=viewport.clientHeight-8?below:Math.max(8,trigger.top-height-6)}px`;
  },true);
  function closeRowMenu(event){
    const menu=q('.quote-row-menu:popover-open');
    if(menu&&!(event?.target instanceof Node&&menu.contains(event.target)))menu.hidePopover();
  }
  window.addEventListener('scroll',closeRowMenu,{capture:true,passive:true});
  window.addEventListener('resize',closeRowMenu);
  rowList.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(!button)return;
    if(busy){event.preventDefault();return;}
    for(const [name,action] of Object.entries(rowActionsByName)){
      const id=Number(button.getAttribute('data-quote-'+name));
      if(!id)continue;
      const row=rows.find(row=>row.id===id);
      if(row){
        const menu=button.closest('.quote-row-menu');
        if(menu){
          menu.hidePopover();
          menu.previousElementSibling.focus({preventScroll:true});
        }
        action(row);
      }
      return;
    }
  });
  function render(){
    const search=q('[data-quote-search]').value.trim().toLowerCase();
    const matched=rows.filter(row=>!search||[row.number,row.document.buyer_company,row.document.attention,row.document.commodity,...row.document.items.map(i=>i.description)].join(' ').toLowerCase().includes(search));
    const pages=Math.max(1,Math.ceil(matched.length/pageSize));page=Math.min(page,pages);
    q('.quote-pagination').hidden=!!customerContext&&matched.length<=pageSize;
    q('[data-quote-applied-filter]').hidden=!customerContext||!search;
    q('[data-quote-filter-label]').textContent=[search?`编号：${q('[data-quote-search]').value.trim()}`:''].filter(Boolean).join(' · ');
    q('[data-quote-count]').textContent=`${rows.length} 份报价`;
    q('[data-quote-rows]').innerHTML=matched.length?matched.slice((page-1)*pageSize,page*pageSize).map(row=>`<tr><td><button type="button" class="quote-number" data-quote-view="${row.id}">${esc(row.number)}</button>${row.document.template_name?`<small class="quote-template-tag">${esc(row.document.template_name)}</small>`:''}${row.document.salesperson?`<small>报价人：${esc(row.document.salesperson)}</small>`:''}</td><td class="quote-customer-column"><strong>${esc(row.document.buyer_company)}</strong><small>${esc(row.document.attention||'未填写联系人')}</small></td><td class="quote-date-column">${esc(row.document.quote_date)}</td><td class="quote-action-column"><div class="quote-row-actions">${rowActions(row)}</div></td></tr>`).join(''):'<tr><td colspan="4" class="quote-empty">'+(rows.length?'没有符合条件的报价单':'暂无报价单，点击“新建报价”开始')+'</td></tr>';
    q('[data-quote-page-info]').textContent=`共 ${matched.length} 份 · 第 ${page} / ${pages} 页`;
    q('[data-quote-prev]').disabled=page<=1;q('[data-quote-next]').disabled=page>=pages;
  }

  async function load(){
    const project=pid(),expected=++version;if(root.hidden)return;
    if(!project){rows=[];render();return;}
    feedback('正在读取报价单…');
    try{const results=await Promise.all([api(customerContext?`?customer_id=${customerContext.customer}&mine=true`:'',{},project),api('/references',{},project)]);if(expected!==version||project!==pid())return;[rows,refs]=results;loadedProject=project;render();feedback();if(customerContext)document.dispatchEvent(new CustomEvent('tophoo-customer-documents-loaded',{detail:{...customerContext,kind:'quotations',count:rows.length}}));}
    catch(error){if(expected===version){rows=[];render();feedback(error.message,true);}}
  }
  const linkedFields=['buyer_company','buyer_address','attention','buyer_phone','buyer_email','contact_person_id'];
  function liveBuyer(document,customerId,preferred=null){
    const doc={...document},c=refs.customers.find(c=>c.id===customerId);if(!c)return doc;
    const people=c.people||[];let person=people.find(p=>p.id===(preferred||doc.contact_person_id));
    if(!person&&!doc.contact_person_id&&!preferred){const matches=people.filter(p=>(doc.buyer_email&&p.email?.toLowerCase()===doc.buyer_email.toLowerCase())||(doc.attention&&p.contact_name?.toLowerCase()===doc.attention.toLowerCase()));if(matches.length===1)person=matches[0];}
    person=person||people.find(p=>p.is_primary)||people[0];
    return {...doc,buyer_company:c.company||c.name,buyer_address:c.company_address||'',contact_person_id:person?.id||null,
      attention:person?person.contact_name||'':c.people_initialized?'':c.name||'',buyer_email:person?person.email||'':c.people_initialized?'':c.email||'',
      buyer_phone:person?person.phone||person.whatsapp||'':c.people_initialized?'':c.phone||c.whatsapp||''};
  }
  const liveRow=row=>({...row,document:liveBuyer(row.document,row.customer_id)});
  function syncEditorLinks(){
    if(!editor.open||busy||editProject!==pid())return;const wasDirty=dirty(),customerId=Number(form.elements.customer_id.value)||null;
    for(const [name,records,label]of [['customer_id',refs.customers,c=>c.company||c.name]]){
      const select=form.elements[name],value=select.value,oldLabel=select.selectedOptions[0]?.textContent;
      select.innerHTML=`<option value="">手动填写 / 不关联客户</option>`+records.map(r=>`<option value="${r.id}">${esc(label(r))}</option>`).join('');
      if(value&&!records.some(r=>String(r.id)===value))select.add(new Option(oldLabel||'原关联资料',value));select.value=value;
    }
    const doc=liveBuyer({...Object.fromEntries(linkedFields.filter(k=>form.elements[k]).map(k=>[k,form.elements[k].value])),contact_person_id:Number(q('[data-quote-person]').value)||null},customerId);
    updatePeople();q('[data-quote-person]').value=doc.contact_person_id||'';
    const linked=refs.customers.some(c=>c.id===customerId);
    for(const key of linkedFields){if(form.elements[key]){if(linked)form.elements[key].value=doc[key]||'';form.elements[key].readOnly=linked;}}
    if(!wasDirty)baseline=JSON.stringify(payload());recalculate();
  }
  async function refreshLinkedData(){
    if(root.hidden||document.hidden||busy||linkRefreshing||loadedProject!==pid())return;
    const project=pid(),identity=JSON.stringify(window.tophooAuth?.headers?.()||{}),expected=version;linkRefreshing=true;
    try{const fresh=await api('/references',{cache:'no-store'},project);if(project!==pid()||expected!==version||identity!==JSON.stringify(window.tophooAuth?.headers?.()||{})||root.hidden||busy)return;
      if(JSON.stringify(fresh)===JSON.stringify(refs))return;refs=fresh;rows=rows.map(liveRow);render();syncEditorLinks();
      if(detail.open){const scroll=q('[data-quote-detail-content]').scrollTop,row=rows.find(r=>r.id===detailRowId);if(row){renderDetail(row);q('[data-quote-detail-content]').scrollTop=scroll;}}
    }catch{ /* Keep the current document intact; opening again retries the read. */ }finally{linkRefreshing=false;}
  }
  async function prepareLinks(){const project=pid(),run=++linkVersion,identity=JSON.stringify(window.tophooAuth?.headers?.()||{}),fresh=await api('/references',{cache:'no-store'},project);if(run!==linkVersion||project!==pid()||root.hidden||identity!==JSON.stringify(window.tophooAuth?.headers?.()||{}))return false;refs=fresh;return true;}
  async function openEditor(item=null){
    let document=null;
    if(!editable()||busy)return;
    try{if(!await prepareLinks())return;const project=pid(),run=linkVersion;
      if(!item){document=await templateTools.choose(refs.templates||[],refs.defaults);if(!document||project!==pid()||run!==linkVersion)return;}
      renderEditor(item?liveRow(item):null,document);if(customerContext&&!item&&editor.open){form.elements.customer_id.value=customerContext.customer;fillCustomer();baseline=JSON.stringify(payload());}
    }catch(error){feedback(error.message,true);}
  }
  async function showDetail(row){if(!row)return;try{if(await prepareLinks())renderDetail(liveRow(row));}catch(error){feedback(error.message,true);}}
  const {field,section}=window.tophooQuotationForm;
  const number=()=>`QT-${today().replaceAll('-','')}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(16).toUpperCase().padStart(8,'0')}`;
  function fitDescription(field){
    if(!field.getClientRects().length)return;
    field.style.height='auto';
    field.style.height=`${field.scrollHeight+field.offsetHeight-field.clientHeight}px`;
  }
  function fitDescriptions(){
    q('[data-quote-lines]')?.querySelectorAll('[data-line-description]').forEach(fitDescription);
  }
  let editorWidth=0;
  new ResizeObserver(([entry])=>{
    if(entry.contentRect.width===editorWidth)return;
    editorWidth=entry.contentRect.width;
    fitDescriptions();
  }).observe(editor);
  function addLine(item={description:'',quantity:'1',unit_price:'0'}){
    const tr=document.createElement('tr');tr.innerHTML=`<td data-line-no></td><td><textarea data-line-description rows="2" maxlength="2000" required placeholder="例如：2 HP">${esc(item.description)}</textarea></td><td><input type="number" data-line-quantity min="0.001" max="100000000" step="0.001" required value="${esc(item.quantity)}" aria-label="数量"></td><td><input type="number" data-line-price min="0" max="1000000000" step="0.01" required value="${esc(item.unit_price)}" aria-label="单价"></td><td data-line-amount></td><td><button type="button" data-remove-line aria-label="删除产品行">✕</button></td>`;
    q('[data-quote-lines]').append(tr);const description=tr.querySelector('[data-line-description]');description.addEventListener('input',()=>fitDescription(description));fitDescription(description);tr.querySelector('[data-remove-line]').onclick=()=>{if(q('[data-quote-lines]').children.length===1)return;tr.remove();recalculate();};recalculate();
  }
  function payload(){
    const values=Object.fromEntries(new FormData(form)),document={...refs.defaults,...templateSnapshot};
    for(const key of Object.keys(document)){if(key in values)document[key]=values[key];}
    document.items=[...q('[data-quote-lines]').children].map(tr=>({description:tr.querySelector('[data-line-description]').value.trim(),quantity:tr.querySelector('[data-line-quantity]').value,unit_price:tr.querySelector('[data-line-price]').value}));
    document.deposit_label=form.elements.deposit_label.value.trim();for(const key of ['quantity_label','subtotal_label','total_label','balance_label'])document[key]=form.elements[key].value.trim();document.salesperson_phone=form.elements.salesperson_phone.value.trim();document.salesperson_email=form.elements.salesperson_email.value.trim();document.logo_data_url=form.elements.logo_data_url.value;document.include_bank=form.elements.include_bank.checked;document.payment_mode=values.payment_mode||null;document.include_balance=values.payment_mode==='deposit';document.deposit_percent=form.elements.deposit_percent.value||'0';document.include_local_charge=form.elements.include_local_charge.checked;document.local_charge_label=form.elements.local_charge_label.value.trim()||'FOB FOSHAN CHARGE :';document.local_charge_amount=form.elements.local_charge_amount.value||'0';document.estimated_volume=null;document.contact_person_id=Number(q('[data-quote-person]').value)||null;
    return {number:values.number.trim(),customer_id:Number(values.customer_id)||null,revision:editing?.revision??null,document};
  }
  const dirty=()=>!busy&&editor.open&&baseline&&JSON.stringify(payload())!==baseline;
  function canLeave(){return !busy&&templateTools.canLeave()&&(!dirty()||confirm('报价单尚未保存，确定放弃修改吗？'));}
  function closeEditor(force=false){if(!force&&!canLeave())return false;++linkVersion;editor.close();baseline='';editing=null;return true;}
  function scaled(value,places){if(!/^\d+(\.\d*)?$/.test(value))throw Error();const [a,b='']=value.split('.');if(b.length>places)throw Error();return BigInt(a)*10n**BigInt(places)+BigInt(b.padEnd(places,'0'));}
  const cents=value=>`${value/100n}.${String(value%100n).padStart(2,'0')}`;
  function recalculate(){
    const lines=[...q('[data-quote-lines]').children],currency=form.elements.currency.value||'USD';let total=0n,quantity=0n,valid=true;
    lines.forEach((tr,index)=>{tr.querySelector('[data-line-no]').textContent=index+1;try{const qty=scaled(tr.querySelector('[data-line-quantity]').value,3),price=scaled(tr.querySelector('[data-line-price]').value,2),amount=(qty*price+500n)/1000n;total+=amount;quantity+=qty;tr.querySelector('[data-line-amount]').textContent=cents(amount);}catch{valid=false;tr.querySelector('[data-line-amount]').textContent='—';}tr.querySelector('[data-remove-line]').disabled=busy||lines.length===1;});
    const subtotal=total;
    try{if(form.elements.include_local_charge.checked)total+=scaled(form.elements.local_charge_amount.value,2);}catch{valid=false;}
    q('[data-quote-live-subtotal]').textContent=valid?money(cents(subtotal),currency):'—';
    q('[data-quote-live-local]').textContent=valid?money(cents(total-subtotal),currency):'—';
    let deposit='—',balance='—';if(form.elements.payment_mode.value==='full'){deposit=cents(total);}else try{const depositCents=(total*scaled(form.elements.deposit_percent.value,2)+5000n)/10000n;deposit=cents(depositCents);balance=cents(total-depositCents);}catch{valid=false;}
    q('[data-quote-live-total]').textContent=valid?money(cents(total),currency):'—';q('[data-quote-live-deposit]').textContent=valid?money(deposit,currency):'—';q('[data-quote-live-balance]').textContent=valid?money(balance,currency):'—';q('[data-quote-live-quantity]').textContent=valid?`${Number(quantity)/1000} ${form.elements.quantity_unit.value}`:'—';
    form.elements.salesperson_phone.placeholder=form.elements.seller_phone.value;form.elements.salesperson_email.placeholder=form.elements.seller_email.value;
    q('[data-quote-letterhead-name]').textContent=form.elements.seller_company.value;
    q('[data-quote-seller-sign]').textContent=form.elements.seller_company.value;
    q('[data-quote-buyer-sign]').textContent=form.elements.buyer_company.value;
    q('[data-quote-form-status]').textContent=dirty()?'尚未保存':'';
  }
  function renderEditor(item=null,document=null){
    if(!editable()||busy||!canLeave())return;
    if(loadedProject!==pid())return feedback('请等待当前项目报价数据加载完成。',true);
    detail.close();editing=item;editProject=pid();baseline='';
    const d=structuredClone({...refs.defaults,...(document||item?.document||{})});
    if(!item&&!d.payment_mode)d.payment_mode='deposit';
    templateSnapshot=Object.fromEntries(['template_id','template_name','template_revision','pdf_layout','pdf_logo_width'].map(key=>[key,d[key]]).filter(([,value])=>value!==undefined));
    q('#quote-editor-title').textContent=editing?'编辑报价单':'新建报价单';
    const customers='<option value="">手动填写 / 不关联客户</option>'+refs.customers.map(c=>`<option value="${c.id}">${esc(c.company||c.name)}</option>`).join('');
    const basic=(d.template_name?`<p class="quote-template-current">模板：<strong>${esc(d.template_name)}</strong><span>版本 ${esc(d.template_revision||1)} · 本报价保留独立副本</span></p>`:'')+field('number','报价编号',editing?.number||number(),'text','required');
    const associations=`<p class="quote-link-hint">买方资料随所选客户同步，保存后报价归入该客户。</p><div class="quote-grid quote-fill-tools"><label>关联客户<select name="customer_id">${customers}</select></label><label>选择联系人<select data-quote-person><option value="">手动填写联系人</option></select></label></div>`;
    const logo=window.tophooQuotationForm.logo(d);
    const buyerLeft=field('buyer_company','买方公司 / TO',d.buyer_company,'text','required')+field('attention','联系人 / ATTN',d.attention)+field('buyer_phone','电话 / TEL',d.buyer_phone)+field('buyer_email','邮箱 / EMAIL',d.buyer_email,'email')+field('buyer_address','地址 / ADD',d.buyer_address);
    const buyerRight=field('quote_date','报价日期 / DATE',d.quote_date,'date','required')+field('salesperson','报价人 / FROM',d.salesperson)+field('salesperson_phone','报价人电话 / TEL',d.salesperson_phone||'','text',`placeholder="${esc(d.seller_phone)}"`)+field('salesperson_email','报价人邮箱 / EMAIL',d.salesperson_email||'','email',`placeholder="${esc(d.seller_email)}"`);
    const buyer=`<div class="quote-buyer-columns"><div class="quote-grid">${buyerLeft}</div><div class="quote-grid quote-from-contact">${buyerRight}<small>电话、邮箱留空时沿用卖方联系方式</small></div></div>`;
    const items=`<div class="quote-grid quote-product-fields">${field('commodity','产品名称 / COMMODITY',d.commodity)}${field('currency','币种',d.currency,'text','pattern="[A-Z]{3}" maxlength="3" required')}${field('quantity_unit','数量单位',d.quantity_unit,'text','required')}</div><div class="quote-items-wrap"><table class="quote-items"><thead><tr><th>#</th><th>型号 / 规格</th><th>数量</th><th>单价</th><th>金额</th><th></th></tr></thead><tbody data-quote-lines></tbody></table></div><button type="button" data-quote-add-line>＋ 添加产品</button>`;
    const terms=window.tophooQuotationForm.terms(d);
    const seller=window.tophooQuotationForm.seller(d);
    const amounts=window.tophooQuotationForm.amounts(d);
    q('[data-quote-fields]').innerHTML=
      `<details class="quote-form-section quote-seller quote-editor-letterhead" data-quote-step="seller"><summary><span>01 · 卖方抬头</span><strong data-quote-letterhead-name>${esc(d.seller_company)}</strong></summary><div class="quote-letterhead">${logo}<div class="quote-grid">${seller}</div></div></details>`+
      `<div data-quote-step="buyer">${section('02 · 买方与报价信息',`<div class="quote-grid quote-editor-basics">${basic}</div>${associations}${buyer}`,'quote-buyer')}</div>`+
      `<div data-quote-step="items">${section('03 · 产品明细',items,'quote-product')}</div>`+
      `<div data-quote-step="payment">${section('04 · 付款与贸易条款',amounts+`<div class="quote-grid quote-editor-terms">${terms}</div>`,'quote-amounts')}</div>`+
      `<div class="quote-editor-end" data-quote-step="footer">${section('05 · 底部联系与签署',`<div class="quote-grid">${field('contact_line','联系说明',d.contact_line)}</div><div class="quote-signatures"><span>Seller<b data-quote-seller-sign></b></span><span>Buyer<b data-quote-buyer-sign></b></span></div>`,'quote-signoff')}${window.tophooQuotationForm.bankSection(d)}<details class="quote-form-section quote-internal-notes"><summary>内部备注</summary><label class="quote-notes-label"><textarea name="internal_notes" aria-label="内部备注" maxlength="5000" rows="3" placeholder="仅供内部使用">${esc(d.internal_notes)}</textarea></label></details></div>`;
    if(item?.customer_id&&!refs.customers.some(c=>c.id===item.customer_id))form.elements.customer_id.add(new Option('历史关联客户（保留快照）',item.customer_id));
    form.elements.customer_id.value=String(item?.customer_id||'');
    window.tophooQuotationForm.bindAmounts(form);
    for(const line of d.items)addLine(line);
    renderLogo();q('[data-quote-logo-upload]').onchange=event=>uploadLogo(event.target.files[0]);q('[data-quote-logo-remove]').onclick=()=>{form.elements.logo_data_url.value='';renderLogo();recalculate();};
    updatePeople();q('[data-quote-person]').value=d.contact_person_id||'';
    for(const key of linkedFields)if(form.elements[key])form.elements[key].readOnly=!!item?.customer_id&&refs.customers.some(c=>c.id===item.customer_id);
    form.elements.customer_id.onchange=()=>fillCustomer();
    q('[data-quote-person]').onchange=()=>{const c=refs.customers.find(c=>c.id===Number(form.elements.customer_id.value)),person=c?.people?.find(p=>p.id===Number(q('[data-quote-person]').value));if(person){form.elements.attention.value=person.contact_name||'';form.elements.buyer_phone.value=person.phone||person.whatsapp||'';form.elements.buyer_email.value=person.email||'';}else if(c)fillCustomer();recalculate();};
    q('[data-quote-add-line]').onclick=()=>{if(q('[data-quote-lines]').children.length>=100)return alert('每份报价最多 100 项产品。');addLine();q('[data-quote-lines]').lastElementChild.querySelector('[data-line-description]').focus();};
    editor.showModal();fitDescriptions();q('[data-quote-fields]').scrollTop=0;form.elements.customer_id.focus({preventScroll:true});baseline=JSON.stringify(payload());recalculate();
  }
  function renderLogo(){
    const logo=form.elements.logo_data_url.value,img=q('[data-quote-logo-preview]');
    img.hidden=!logo;q('[data-quote-logo-empty]').hidden=!!logo;q('[data-quote-logo-remove]').disabled=!logo;
    if(logo)img.src=logo;else img.removeAttribute('src');q('[data-quote-logo-label]').textContent=logo?'更换 Logo':'上传 Logo';
  }
  async function uploadLogo(file){
    if(!file||busy||!editable())return;
    if(!['image/png','image/jpeg','image/webp'].includes(file.type))return q('[data-quote-form-status]').textContent='请上传 PNG、JPG 或 WebP 图片。';
    if(file.size>1024*1024)return q('[data-quote-form-status]').textContent='Logo 不能超过 1 MB。';
    const target=form.elements.logo_data_url,project=editProject;let errorMessage='';lock(true);q('[data-quote-form-status]').textContent='正在读取 Logo…';
    try{
      const value=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('图片读取失败，请重试。'));reader.readAsDataURL(file);});
      const image=new Image();image.src=value;await image.decode();
      if(Math.max(image.naturalWidth,image.naturalHeight)>8192||image.naturalWidth*image.naturalHeight>16000000)throw Error('Logo 尺寸过大，请缩小后上传。');
      if(!target.isConnected||project!==pid())return;target.value=value;renderLogo();
    }catch(error){errorMessage=error.message||'图片无法读取，请重新上传。';}
    finally{lock(false);if(target.isConnected){q('[data-quote-logo-upload]').value='';renderLogo();recalculate();if(errorMessage)q('[data-quote-form-status]').textContent=errorMessage;}}
  }
  function updatePeople(){
    const customer=refs.customers.find(c=>c.id===Number(form.elements.customer_id.value));
    q('[data-quote-person]').innerHTML='<option value="">'+(customer?'使用主联系人':'手动填写联系人')+'</option>'+(customer?.people||[]).map(p=>`<option value="${p.id}">${esc(p.contact_name||p.email||'未填写姓名')}</option>`).join('');
  }
  function fillCustomer(){
    const c=refs.customers.find(c=>c.id===Number(form.elements.customer_id.value));updatePeople();
    if(c){const doc=liveBuyer({},c.id);for(const key of linkedFields)if(form.elements[key])form.elements[key].value=doc[key]||'';q('[data-quote-person]').value=doc.contact_person_id||'';}
    for(const key of linkedFields)if(form.elements[key])form.elements[key].readOnly=!!c;
    recalculate();
  }
  function lock(value){busy=value;form.querySelectorAll('input,textarea,select,button').forEach(node=>node.disabled=value);q('[data-quote-close]').disabled=value;if(!value&&form.elements.include_local_charge){form.elements.local_charge_label.disabled=!form.elements.include_local_charge.checked;form.elements.local_charge_amount.disabled=!form.elements.include_local_charge.checked;form.elements.deposit_percent.disabled=form.elements.payment_mode.value==='full';const removeButtons=form.querySelectorAll('[data-remove-line]');if(removeButtons.length===1)removeButtons[0].disabled=true;}}
  q('[data-quote-section-nav]').addEventListener('click',event=>{
    const key=event.target.closest('[data-quote-jump]')?.dataset.quoteJump;
    if(!key)return;
    const target=q(`[data-quote-step="${key}"]`);
    if(target instanceof HTMLDetailsElement)target.open=true;
    target.scrollIntoView({block:'start'});
  });
  form.addEventListener('invalid',event=>{
    const section=event.target.closest('details');
    if(section)section.open=true;
  },true);
  form.addEventListener('input',recalculate);form.addEventListener('change',recalculate);
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!editable())return;if(editProject!==pid())return feedback('项目已切换，请重新打开报价单。',true);
    const submitted=payload(),project=editProject,item=editing;lock(true);q('[data-quote-form-status]').textContent='正在保存…';
    try{const saved=await api(item?`/${item.id}`:'',{method:item?'PUT':'POST',body:JSON.stringify(submitted)},project);if(project!==pid())return;closeEditor(true);await load();
      if(customerContext&&saved.customer_id!==customerContext.customer){
        const customer=refs.customers.find(c=>c.id===saved.customer_id);
        detail.close();
        feedback(customer?`报价单已保存到「${customer.company||customer.name}」的报价列表。`:'报价单已保存，并已从当前客户的报价列表移出。');
      }else feedback('报价单已保存');}
    catch(error){q('[data-quote-form-status]').textContent=error.message;}finally{lock(false);}
  };
  function renderDetail(row){
    detailRowId=row?.id;
    if(!row)return;
    const d=row.document,grid=pairs=>`<dl>${pairs.filter(([,v])=>v!==null&&v!==undefined&&v!=='').map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`;
    const block=(title,body,cls='')=>`<section class="quote-detail-section ${cls}"><h3>${title}</h3>${body}</section>`;
    const management=block('内部管理 · 不导出',grid([['报价编号',row.number],['模板',d.template_name?`${d.template_name} · 版本 ${d.template_revision||1}`:'历史报价'],['关联客户',refs.customers.find(c=>c.id===row.customer_id)?.company]])+(d.internal_notes?`<details class="quote-internal-notes"><summary>内部备注</summary><p class="quote-internal-note">${esc(d.internal_notes)}</p></details>`:''),'quote-base');
    const seller=block('卖方抬头与联系信息',`<div class="quote-detail-hero">${d.logo_data_url?`<img src="${esc(d.logo_data_url)}" alt="报价 Logo">`:''}<div><h3>${esc(d.seller_company)}</h3><p>${esc(d.seller_address)}</p></div></div>`+grid([['公司邮箱',d.seller_email],['公司网站',d.seller_website],['电话',d.seller_phone],['传真',d.seller_fax]]),'quote-seller');
    const buyer=block('买方与报价信息',`<div class="quote-buyer-columns">${grid([['联系人 / ATTN',d.attention],['买方公司 / TO',d.buyer_company],['电话 / TEL',d.buyer_phone],['邮箱 / EMAIL',d.buyer_email],['地址 / ADD',d.buyer_address]])}${grid([['报价日期 / DATE',d.quote_date],['报价人 / FROM',d.salesperson],['报价人电话 / TEL',d.salesperson_phone||d.seller_phone],['报价人邮箱 / EMAIL',d.salesperson_email||d.seller_email]])}</div>`,'quote-buyer');
    const product=block('产品明细',`<div class="quote-detail-product-title"><strong>${esc(d.commodity)}</strong><span>${esc(d.quantity_unit)} · ${esc(d.currency)}</span></div><div class="quote-items-wrap"><table class="quote-items"><thead><tr><th>#</th><th>型号 / 规格</th><th>数量</th><th>单价</th><th>金额</th></tr></thead><tbody>${d.items.map((item,i)=>`<tr><td>${i+1}</td><td>${esc(item.description)}</td><td>${esc(item.quantity)}</td><td>${esc(item.unit_price)}</td><td>${esc(row.totals.line_amounts[i])}</td></tr>`).join('')}</tbody></table></div>`,'quote-product');
    const amounts=block('金额汇总',`<div class="quote-live-totals"><span>${esc(d.quantity_label||'数量合计')} <b>${esc(row.totals.quantity_total)} ${esc(d.quantity_unit)}</b></span>${d.include_local_charge?`<span>${esc(d.subtotal_label||'产品金额')} <b>${esc(money(row.totals.items_subtotal,d.currency))}</b></span><span>${esc(d.local_charge_label)} <b>${esc(money(row.totals.local_charge,d.currency))}</b></span>`:''}<span class="quote-grand-total">${esc(d.total_label||'总金额')} <b>${esc(money(row.totals.total,d.currency))}</b></span><span>${esc(d.payment_mode==='full'?'应付全款':d.deposit_label||`定金 · ${d.deposit_percent}%`)} <b>${esc(money(d.payment_mode==='full'?row.totals.total:row.totals.deposit,d.currency))}</b></span>${d.payment_mode==='deposit'||(!d.payment_mode&&d.include_balance)?`<span>${esc(d.balance_label||'尾款')} <b>${esc(money(row.totals.balance,d.currency))}</b></span>`:''}</div>`,'quote-amounts');
    const terms=block('贸易条款',grid([['价格条款',d.price_term],['付款条款',d.payment_term],['交货期',d.delivery_time],['包装',d.packing],['原产地',d.origin],['报价有效期',d.price_validity]]),'quote-terms');
    const bank=`<details class="quote-detail-extra quote-bank" ${d.include_bank?'open':''}><summary>收款资料 · ${d.include_bank?'导出显示':'仅内部保存'}</summary>${grid([['收款人名称',d.beneficiary_name],['收款人地址',d.beneficiary_address],['收款银行',d.beneficiary_bank],['银行地址',d.bank_address],['收款账号',d.bank_account],['SWIFT',d.swift_code]])}</details>`;
    const signoff=block('底部联系说明',grid([['底部联系说明',d.contact_line]])+`<div class="quote-signatures"><span>Seller<b>${esc(d.seller_company)}</b></span><span>Buyer<b>${esc(d.buyer_company)}</b></span></div>`,'quote-signoff');
    q('#quote-detail-title').innerHTML=`<span>${esc(row.number)}</span>`;
    q('[data-quote-detail-content]').innerHTML=management+seller+'<div class="quote-document-title">QUOTATION <span>报价单</span></div>'+buyer+product+amounts+terms+bank+signoff;
    q('[data-quote-detail-status]').hidden=true;if(!detail.open)detail.showModal();q('[data-quote-detail-content]').scrollTop=0;
  }
  async function remove(row){if(busy||!editable()||!confirm(`确定删除报价单 ${row.number}？`))return;busy=true;try{await api(`/${row.id}?revision=${row.revision}`,{method:'DELETE'});detail.close();await load();feedback('报价单已删除');}catch(error){feedback(error.message,true);}finally{busy=false;}}
  function closePdf(){pdf.close();q('[data-quote-pdf-frame]').src='about:blank';if(pdfUrl)URL.revokeObjectURL(pdfUrl);pdfUrl=null;}
  function showPdf(blob,filename){if(pdfUrl)URL.revokeObjectURL(pdfUrl);pdfUrl=URL.createObjectURL(blob);q('[data-quote-pdf-frame]').src=pdfUrl;q('[data-quote-pdf-download]').href=pdfUrl;q('[data-quote-pdf-download]').download=filename;if(!pdf.open)pdf.showModal();}
  async function download(row,format='pdf'){try{const blob=await api(`/${row.id}/${format}`);const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`Quotation-${row.number.replace(/[\\/:*?"<>|]/g,'-')}.${format}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(error){feedback(error.message,true);}}
  async function previewSaved(row){
    if(busy)return;const project=pid(),button=q(`[data-quote-preview-saved="${row.id}"]`);busy=true;
    if(button){button.disabled=true;button.textContent='生成中…';}feedback('正在生成报价单预览…');
    try{const blob=await api(`/${row.id}/pdf`,{},project);if(project===pid()){showPdf(blob,`Quotation-${row.number.replace(/[\\/:*?"<>|]/g,'-')}.pdf`);feedback();}}
    catch(error){if(project===pid())feedback(error.message,true);}
    finally{busy=false;if(button?.isConnected){button.disabled=false;button.textContent='预览';}}
  }
  q('[data-quote-preview]').onclick=async()=>{if(busy||!form.reportValidity())return;const submitted=payload(),project=editProject;lock(true);try{const blob=await api('/preview-pdf',{method:'POST',body:JSON.stringify(submitted)},project);if(project===pid())showPdf(blob,`Quotation-${submitted.number}.pdf`);}catch(error){q('[data-quote-form-status]').textContent=error.message;}finally{lock(false);}};
  q('[data-quote-templates]').onclick=async()=>{if(busy||!editable())return;try{if(await prepareLinks())await templateTools.manage(refs.defaults);}catch(error){feedback(error.message,true);}};q('[data-quote-add]').onclick=()=>openEditor();q('[data-quote-refresh]').onclick=load;q('[data-quote-close]').onclick=()=>closeEditor();editor.addEventListener('cancel',event=>{event.preventDefault();closeEditor();});
  q('[data-quote-detail-close]').onclick=()=>{if(!busy){++linkVersion;detail.close();}};
  detail.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  let backdropDown=false;
  const outsideDetail=event=>{const r=detail.getBoundingClientRect();return event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom;};
  detail.addEventListener('pointerdown',event=>{backdropDown=event.target===detail&&outsideDetail(event);});
  detail.addEventListener('click',event=>{if(!busy&&backdropDown&&event.target===detail&&outsideDetail(event))detail.close();backdropDown=false;});
  q('[data-quote-pdf-close]').onclick=closePdf;pdf.addEventListener('cancel',event=>{event.preventDefault();closePdf();});
  q('[data-quote-search]').oninput=()=>{page=1;render();};q('[data-quote-prev]').onclick=()=>{page--;render();};q('[data-quote-next]').onclick=()=>{page++;render();};q('[data-quote-page-size]').onchange=event=>{pageSize=Math.max(1,Math.min(200,Math.floor(Number(event.target.value)||10)));event.target.value=pageSize;page=1;render();};
  q('[data-quote-clear-filter]').onclick=()=>{q('[data-quote-search]').value='';page=1;render();};
  editor.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();event.stopPropagation();form.requestSubmit();}});
  document.addEventListener('click',event=>{if(root.hidden||!event.target.closest('.global-nav-item,.crm-primary-item,.pm-project-row,[data-project-id]'))return;if(!canLeave()){event.preventDefault();event.stopImmediatePropagation();}else{templateTools.close();closeEditor(true);detail.close();closePdf();}},true);
  window.addEventListener('beforeunload',event=>{if(dirty()||busy||templateTools.dirty()||templateTools.isBusy()){event.preventDefault();event.returnValue='';}});

  window.setInterval(refreshLinkedData,15000);
  window.addEventListener('focus',refreshLinkedData);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLinkedData();});
  document.addEventListener('tophoo-linked-data-updated',event=>{if(event.detail?.project===pid())refreshLinkedData();});
  window.addEventListener('storage',event=>{if(event.key==='tophoo-linked-data-updated'){try{if(JSON.parse(event.newValue)?.project===pid())refreshLinkedData();}catch{}}});
  document.addEventListener('tophoo-customer-documents-view',event=>{
    const c=event.detail;if(c.kind!=='quotations'||c.project!==pid())return;
    customerContext=c;root.dataset.customerScope=String(c.customer);q('[data-quote-search]').value=c.search||'';page=1;load();
  });
  document.addEventListener('tophoo-customer-documents-leave',event=>{
    if(root.hidden||!customerContext)return;if(!canLeave()){event.preventDefault();return;}
    closeRowMenu();templateTools.close();closeEditor(true);detail.close();closePdf();++version;customerContext=null;delete root.dataset.customerScope;
  });
  document.addEventListener('tophoo-quotations-view',load);
  document.addEventListener('tophoo-open-customer-document',async event=>{
    const c=event.detail;if(c.kind!=='quotations'||c.project!==pid())return;
    await load();if(c.project!==pid()||root.hidden)return;
    await showDetail(rows.find(row=>row.id===c.id&&row.customer_id===c.customer));
  });
  if(!root.hidden)load();
  document.addEventListener('tophoo-auth-changed',()=>{customerContext=null;delete root.dataset.customerScope;++version;++linkVersion;closeEditor(true);detail.close();closePdf();rows=[];refs={customers:[],defaults:{}};loadedProject=0;render();});
  window.addEventListener('tophoo-project-changed',()=>{customerContext=null;delete root.dataset.customerScope;++version;++linkVersion;closeEditor(true);detail.close();closePdf();rows=[];loadedProject=0;if(!root.hidden)load();});
})();
