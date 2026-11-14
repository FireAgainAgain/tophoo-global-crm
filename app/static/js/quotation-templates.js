/* Project template management. Quotes receive independent copies of settings. */
window.tophooQuotationTemplates=(root,{api,editable,changed,showPdf})=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const list=document.createElement('dialog'),edit=document.createElement('dialog'),picker=document.createElement('dialog');
  for(const node of [list,edit,picker]){node.className='quote-template-dialog';root.append(node);}
  edit.className='quote-editor quote-template-editor';
  list.dataset.quoteTemplateManager='';edit.dataset.quoteTemplateEditor='';picker.dataset.quoteTemplatePicker='';
  let records=[],current=null,settings={},baseSettings={},project=0,generation=0,pending=false,resolveChoice=null,initial='';
  const heading=(title,description)=>`<header><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div><button type="button" data-tpl-close aria-label="关闭">✕</button></header>`;
  const status=node=>node.querySelector('[data-tpl-status]');
  const dirty=()=>edit.open&&initial!==JSON.stringify(value());
  const canLeave=()=>!pending&&(!dirty()||confirm('模板尚未保存，确定放弃修改吗？'));
  const summary=tpl=>`<div class="quote-template-art">${tpl.settings.logo_data_url?`<img src="${esc(tpl.settings.logo_data_url)}" alt="">`:'<span class="quote-template-monogram">Q</span>'}<div><strong>${esc(tpl.settings.seller_company)}</strong><i></i><i></i></div><b>QUOTATION</b><div class="quote-template-paper-grid"></div></div><div class="quote-template-caption"><strong>${esc(tpl.name)}</strong><small>${esc(tpl.settings.currency||'USD')} · 版本 ${tpl.revision}</small></div>`;
  function closeEdit(force=false){if(pending&&!force)return false;if(!force&&edit.open&&initial!==JSON.stringify(value())&&!confirm('模板尚未保存，确定放弃修改吗？'))return false;edit.close();return true;}
  function close(){++generation;pending=false;resolveChoice?.(null);resolveChoice=null;picker.close();list.close();closeEdit(true);}
  function choose(templates,defaults){
    records=templates;project=pid();
    if(!records.length){alert('暂无可用模板，请先在模板管理中新增模板。');return Promise.resolve(null);}
    picker.style.width=records.length===1?'min(560px,94vw)':'';
    picker.innerHTML=heading('选择报价模板','每次新建都需选择模板。公司抬头、付款设置和条款会带入本次报价。')+`<div class="quote-template-body"><div class="quote-template-cards">${records.map(t=>`<button type="button" class="quote-template-card" data-tpl-select="${t.id}">${summary(t)}<span class="quote-template-use">使用此模板 →</span></button>`).join('')}</div></div><footer><span>历史报价保留创建时的模板内容</span><button type="button" data-tpl-cancel>取消</button></footer>`;
    picker.querySelector('[data-tpl-close]').onclick=picker.querySelector('[data-tpl-cancel]').onclick=()=>{picker.close();resolveChoice?.(null);resolveChoice=null;};
    picker.querySelectorAll('[data-tpl-select]').forEach(button=>button.onclick=()=>{
      const tpl=records.find(t=>t.id===Number(button.dataset.tplSelect));
      const selected={...structuredClone(defaults),...structuredClone(tpl.settings),template_id:tpl.id,template_name:tpl.name,template_revision:tpl.revision};
      picker.close();resolveChoice?.(pid()===project?selected:null);resolveChoice=null;
    });
    picker.showModal();return new Promise(resolve=>resolveChoice=resolve);
  }
  picker.addEventListener('cancel',event=>{event.preventDefault();picker.close();resolveChoice?.(null);resolveChoice=null;});
  async function refresh(){
    const run=++generation,selectedProject=project;
    const result=await api('/templates',{},selectedProject);
    if(run!==generation||selectedProject!==pid()||!list.open)return;
    records=result;renderList();
  }
  function renderList(){
    list.innerHTML=heading('报价模板','模板保存常用资料和报价设置。下载的 Excel 留空客户与产品明细，可直接填写。')+`<div class="quote-template-body"><div class="quote-template-toolbar"><span>${records.length} 个可用模板</span><button type="button" class="quote-primary" data-tpl-new>＋ 新增模板</button></div><p role="status" data-tpl-status hidden></p><div class="quote-template-cards">${records.map(t=>`<article class="quote-template-card">${summary(t)}<div class="quote-template-actions"><button type="button" data-tpl-edit="${t.id}">编辑</button><button type="button" data-tpl-preview="${t.id}">预览 PDF</button><button type="button" data-tpl-excel="${t.id}">下载 Excel</button></div></article>`).join('')}</div></div>`;
    list.querySelector('[data-tpl-close]').onclick=()=>{if(!pending)list.close();};
    list.querySelector('[data-tpl-new]').onclick=()=>openEdit(null);
    for(const action of ['edit','preview','excel'])list.querySelectorAll(`[data-tpl-${action}]`).forEach(button=>button.onclick=()=>{
      if(pending||!editable())return;const row=records.find(t=>t.id===Number(button.getAttribute(`data-tpl-${action}`)));
      if(action==='edit')openEdit(row);else if(action==='preview')preview(row);else downloadExcel(row,button);
    });
  }
  async function manage(defaults){
    baseSettings=defaults;
    if(!editable())return;project=pid();list.innerHTML=heading('报价模板','正在加载…');list.querySelector('[data-tpl-close]').onclick=close;list.showModal();
    try{await refresh();}catch(error){if(list.open){list.innerHTML=heading('报价模板',error.message);list.querySelector('[data-tpl-close]').onclick=close;}}
  }
  async function downloadExcel(row,button){
    pending=true;button.disabled=true;const activeProject=project,run=generation;
    try{
      const blob=await api(`/templates/${row.id}/xlsx`,{},activeProject);
      if(activeProject!==pid()||run!==generation||!list.open)return;
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download=row.name.replace(/[\\/:*?"<>|]/g,'-')+'.xlsx';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),30000);
    }catch(error){if(list.open&&run===generation){const node=status(list);node.hidden=false;node.textContent=error.message;}}
    finally{if(run===generation)pending=false;button.disabled=false;}
  }
  const shared=window.tophooQuotationForm;
  const {field,section}=shared;
  function openEdit(row){
    if(!editable()||pending)return;
    current=row;settings=structuredClone(row?.settings||Object.fromEntries(Object.keys(records[0].settings).map(key=>[key,baseSettings[key]])));
    const d=settings;
    const management=`<div class="quote-grid">${field('template_name','模板名称',row?.name||'','text','required')}${field('pdf_logo_width','Logo 显示宽度',d.pdf_logo_width||112,'number','min="60" max="120" step="1"')}</div>`;
    const buyerLeft=['buyer_company','attention','buyer_phone','buyer_email','buyer_address'].map((key,i)=>field(key,['买方公司 / TO','联系人 / ATTN','电话 / TEL','邮箱 / EMAIL','地址 / ADD'][i],'','text','disabled placeholder="新建报价单时填写"')).join('');
    const buyerRight=field('quote_date','报价日期 / DATE','','text','disabled placeholder="新建报价单时填写"')+field('salesperson','报价人 / FROM',d.salesperson)+field('salesperson_phone','报价人电话 / TEL',d.salesperson_phone)+field('salesperson_email','报价人邮箱 / EMAIL',d.salesperson_email,'email');
    const product=field('commodity','产品名称 / COMMODITY',d.commodity)+`<div class="quote-inline-fields">${field('currency','币种',d.currency,'text','pattern="[A-Z]{3}" maxlength="3" required')}${field('quantity_unit','数量单位',d.quantity_unit,'text','required')}</div><div class="quote-template-placeholder">具体产品规格、数量和价格在新建报价单时填写。</div>`;
    edit.innerHTML=heading(current?.id?'编辑报价模板':'新增报价模板','与报价单使用相同的编辑布局；默认信息会带入新报价单。')+`<form><div class="quote-form-content">`+section('模板管理 · 不导出',management,'quote-base')+section('卖方抬头与联系信息',`<div class="quote-letterhead">${shared.logo(d,'tpl')}<div class="quote-grid">${shared.seller(d)}</div></div>`,'quote-seller')+'<div class="quote-document-title">QUOTATION <span>报价单</span></div>'+section('买方与报价信息',`<div class="quote-buyer-columns"><div class="quote-grid">${buyerLeft}</div><div class="quote-grid quote-from-contact">${buyerRight}</div></div>`,'quote-buyer')+section('产品明细',product,'quote-product')+section('金额汇总',shared.amounts(d,{template:true}),'quote-amounts')+section('贸易条款',`<div class="quote-grid">${shared.terms(d)}</div>`,'quote-terms')+shared.bankSection(d)+section('底部联系说明',`<div class="quote-grid">${field('contact_line','底部联系说明',d.contact_line)}</div><div class="quote-signatures"><span>Seller<b data-tpl-seller-footer>${esc(d.seller_company)}</b></span><span>Buyer<b>新建报价时带入客户公司</b></span></div>`,'quote-signoff')+`</div><footer><span role="status" data-tpl-status></span><button type="button" data-tpl-preview-edit>预览 PDF</button><button type="button" data-tpl-cancel>取消</button><button type="submit" class="quote-primary">保存模板</button></footer></form>`;
    const form=edit.querySelector('form');shared.bindAmounts(form);form.elements.seller_company.required=true;form.elements.currency.pattern='[A-Z]{3}';form.elements.currency.maxLength=3;
    edit.querySelector('[data-tpl-close]').onclick=edit.querySelector('[data-tpl-cancel]').onclick=()=>closeEdit();
    edit.querySelector('[data-tpl-preview-edit]').onclick=()=>{if(form.reportValidity())preview(value());};
    const renderLogo=()=>{const img=edit.querySelector('[data-tpl-logo-preview]'),empty=edit.querySelector('[data-tpl-logo-empty]');img.hidden=!settings.logo_data_url;empty.hidden=!!settings.logo_data_url;form.elements.logo_data_url.value=settings.logo_data_url||'';if(settings.logo_data_url)img.src=settings.logo_data_url;else img.removeAttribute('src');edit.querySelector('[data-tpl-logo-label]').textContent=settings.logo_data_url?'更换 Logo':'上传 Logo';};
    edit.querySelector('[data-tpl-logo-remove]').onclick=()=>{settings.logo_data_url='';renderLogo();};
    edit.querySelector('[data-tpl-logo-upload]').onchange=async event=>{
      const file=event.target.files[0],run=generation;if(!file)return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>1024*1024){status(edit).textContent='请上传不超过 1 MB 的 PNG、JPG 或 WebP 图片。';return;}
      pending=true;
      try{const raw=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('图片读取失败'));reader.readAsDataURL(file);});const image=new Image();image.src=raw;await image.decode();if(image.naturalWidth>8192||image.naturalHeight>8192||image.naturalWidth*image.naturalHeight>16000000)throw Error('Logo 尺寸过大');if(run!==generation||!edit.open)return;settings.logo_data_url=raw;renderLogo();status(edit).textContent='';}catch(error){status(edit).textContent=error.message;}finally{pending=false;}
    };
    form.onsubmit=async event=>{
      event.preventDefault();if(pending||!editable()||project!==pid())return;const body=value(),run=generation;pending=true;const controls=[...form.querySelectorAll('button,input,select')].filter(n=>!n.disabled);controls.forEach(n=>n.disabled=true);status(edit).textContent='正在保存…';
      try{await api(current?.id?`/templates/${current.id}`:'/templates',{method:current?.id?'PUT':'POST',body:JSON.stringify(body)},project);if(project!==pid()||run!==generation)return;edit.close();await refresh();changed();}
      catch(error){if(edit.open)status(edit).textContent=error.message;}
      finally{pending=false;controls.forEach(n=>n.disabled=false);}
    };
    form.addEventListener('input',()=>{edit.querySelector('[data-tpl-seller-footer]').textContent=form.elements.seller_company.value;});
    edit.showModal();initial=JSON.stringify(value());
  }
  function value(){
    const form=edit.querySelector('form'),entries=Object.fromEntries(new FormData(form)),next={...settings};
    for(const key of Object.keys(settings))if(key in entries)next[key]=entries[key];
    next.pdf_logo_width=Number(entries.pdf_logo_width)||112;next.payment_mode=entries.payment_mode||null;next.deposit_percent=form.elements.deposit_percent.value||'0';for(const key of ['quantity_label','subtotal_label','total_label','balance_label','deposit_label'])next[key]=form.elements[key].value.trim();next.local_charge_label=form.elements.local_charge_label.value.trim()||'FOB FOSHAN CHARGE :';next.local_charge_amount=form.elements.local_charge_amount.value||'0';
    next.include_balance=entries.payment_mode==='deposit';
    for(const key of ['include_bank','include_local_charge'])next[key]=form.elements[key].checked;
    return {name:entries.template_name.trim(),revision:current?.id?current.revision:null,settings:next};
  }
  async function preview(row){
    if(pending)return;pending=true;const activeProject=project,run=generation;
    try{const blob=await api('/templates/preview-pdf',{method:'POST',body:JSON.stringify({name:row.name,settings:row.settings})},activeProject);if(activeProject===pid()&&run===generation)showPdf(blob,'Quotation-template-preview.pdf');}
    catch(error){const node=status(edit.open?edit:list);if(node){node.hidden=false;node.textContent=error.message;}}
    finally{pending=false;}
  }
  list.addEventListener('cancel',event=>{if(pending)event.preventDefault();});edit.addEventListener('cancel',event=>{event.preventDefault();closeEdit();});
  for(const event of ['tophoo-auth-changed','tophoo-project-changed'])document.addEventListener(event,close);
  window.addEventListener('tophoo-project-changed',close);
  return {choose,manage,close,dirty,canLeave,isBusy:()=>pending};
};
