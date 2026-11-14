/* A customer-scoped workspace hosts the existing inquiry and quotation tools. */
(() => {
  const workflow=document.querySelector('[data-customer-workflow]'),workspace=document.querySelector('[data-customer-documents-workspace]');
  if(!workflow||!workspace)return;
  const body=workspace.querySelector('[data-customer-document-body]'),heading=workspace.querySelector('[data-customer-document-heading]');
  const roots={rfqs:document.querySelector('[data-crm-rfq]'),quotations:document.querySelector('[data-crm-quotations]'),contracts:document.querySelector('[data-crm-contracts]')};
  const tabs=[['rfqs','询价单'],['quotations','报价单'],['contracts','合同']];
  Object.values(roots).filter(Boolean).forEach(root=>body.append(root));
  const pid=()=>Number(localStorage.getItem('tophoo-global-selected-project'))||0;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let context=null,trigger=null;
  const dialog=document.querySelector('[data-customer-inquiry]');
  const inquiryForm=dialog.querySelector('[data-inquiry-form]');
  const inquiryPicker=dialog.querySelector('[data-inquiry-picker]');
  const inquiryRecord=dialog.querySelector('[data-inquiry-record]');
  const inquiryStatus=dialog.querySelector('[data-inquiry-status]');
  const contentKey='customer_inquiry_content';
  const itemList=dialog.querySelector('[data-inquiry-items]');
  const addItemButton=dialog.querySelector('[data-inquiry-add-item]');
  const maxItems=25;
  const fields=[
    ['content','需求','填写产品和需求',3],
    ['translation','规格/参数','填写规格、尺寸及工况',3],
    ['price','报价','填写币种、单价或总价',3],
    ['notes','备注','填写交期、条件或其他说明',2],
  ];
  let inquiry=null, inquiryRows=[], activeInquiry=null, original='', saving=false;

  const formValues=()=>({
    number:inquiryForm.elements.number.value,
    inquiry_items:[...itemList.children].map(row=>Object.fromEntries(
      fields.map(([key])=>[key,row.querySelector(`[name="${key}"]`).value])
    )),
  });
  const dirty=()=>!inquiryForm.hidden && JSON.stringify(formValues())!==original;
  const confirmDiscard=()=>!dirty()||window.confirm('询价尚未保存，确定放弃修改吗？');
  const editable=()=>window.tophooProjectAccess?.canEdit('rfq')===true;
  const inquiryUrl=c=>`/api/rfqs/projects/${c.project}`;
  async function inquiryRequest(url, options={}){
    const response=await fetch(url,{...options,headers:{...window.tophooAuth?.headers?.(),...options.headers}});
    const result=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(typeof result?.detail==='string'?result.detail:'操作失败，请重试。');
    return result;
  }
  function inquiryContent(item){
    if(!item)return '';
    if(item.parameters?.[contentKey]!==undefined)return item.parameters[contentKey];
    return (item.generic_fields||[]).map(field=>field.content?.trim()?`${field.title}：${field.content}`:'')
      .filter(Boolean).join('\n\n');
  }
  function syncItemControls(){
    const rows=[...itemList.children], canEdit=editable()&&!saving;
    dialog.querySelector('[data-inquiry-item-count]').textContent=`${rows.length} 条`;
    addItemButton.hidden=!editable();
    addItemButton.disabled=!canEdit||rows.length>=maxItems;
    rows.forEach((row,index)=>{
      const title=`明细 ${index+1}`;
      row.querySelector('h4').textContent=title;
      const remove=row.querySelector('[data-inquiry-remove-item]');
      remove.hidden=!editable();
      remove.disabled=!canEdit||rows.length===1;
      remove.setAttribute('aria-label',`移除${title}`);
      row.querySelectorAll('textarea').forEach(field=>{
        field.readOnly=!canEdit;
        field.setAttribute('aria-label',`${title} · ${field.dataset.label}`);
      });
    });
  }
  function fitItem(row){
    const inputs=[...row.querySelectorAll('textarea')];
    if(!row.getClientRects().length)return;
    inputs.forEach(input=>input.style.height='auto');
    const height=Math.max(...inputs.map(input=>{
      const style=getComputedStyle(input);
      return input.scrollHeight+parseFloat(style.borderTopWidth)+parseFloat(style.borderBottomWidth);
    }));
    inputs.forEach(input=>input.style.height=`${height}px`);
  }
  let listWidth=0;
  new ResizeObserver(([entry])=>{
    if(entry.contentRect.width===listWidth)return;
    listWidth=entry.contentRect.width;
    [...itemList.children].forEach(fitItem);
  }).observe(itemList);
  itemList.addEventListener('input',event=>{
    if(event.target.matches('textarea'))fitItem(event.target.closest('li'));
  });
  function appendItem(item={}){
    const row=document.createElement('li');
    row.className='customer-inquiry-item';
    row.innerHTML=`<div class="customer-inquiry-item-head"><h4></h4><button type="button" data-inquiry-remove-item>移除</button></div>
      <div class="customer-inquiry-item-fields">${fields.map(([key,label,placeholder,rows])=>
        `<label>${label}<textarea name="${key}" data-label="${label}" rows="${rows}" maxlength="20000" placeholder="${placeholder}" ${key==='content'?'required':''}></textarea></label>`).join('')}</div>`;
    fields.forEach(([key])=>row.querySelector(`[name="${key}"]`).value=item[key]??'');
    itemList.append(row);
    requestAnimationFrame(()=>fitItem(row));
    return row;
  }
  addItemButton.onclick=()=>{
    if(saving||!editable()||itemList.children.length>=maxItems)return;
    const row=appendItem();
    syncItemControls();
    row.querySelector('textarea').focus();
  };
  itemList.addEventListener('click',event=>{
    const remove=event.target.closest('[data-inquiry-remove-item]');
    if(!remove||saving||!editable()||itemList.children.length<=1)return;
    const row=remove.closest('li');
    const next=row.nextElementSibling||row.previousElementSibling;
    row.remove();
    syncItemControls();
    next.querySelector('textarea').focus();
  });
  function selectInquiry(item){
    activeInquiry=item;
    dialog.querySelector('h2').textContent=editable()?(item?'编辑询价':'新增询价'):'查看询价';
    inquiryRecord.value=item?.id??'';
    inquiryForm.hidden=!item&&!editable();
    inquiryForm.elements.number.value=item?.number||'';
    itemList.replaceChildren();
    const items=item?.inquiry_items?.length?item.inquiry_items:[{content:inquiryContent(item),notes:item?.notes||''}];
    items.forEach(appendItem);
    syncItemControls();
    inquiryForm.elements.number.readOnly=!editable();
    inquiryForm.querySelector('[type="submit"]').hidden=!editable();
    dialog.querySelector('[data-inquiry-shortcut]').hidden=!editable();
    original=JSON.stringify(formValues());
    inquiryStatus.textContent=inquiryForm.hidden?'暂无询价。':'';
  }
  async function openInquiry(customer, company, number=''){
    if(!dialog.open)dialog.showModal();
    const c={project:pid(),customer};
    inquiry=c;
    inquiryForm.hidden=true;
    inquiryPicker.hidden=true;
    dialog.querySelector('h2').textContent='询价';
    inquiryStatus.textContent='正在读取…';
    dialog.querySelector('[data-inquiry-customer]').textContent=company||'';
    try{
      const rows=await inquiryRequest(`${inquiryUrl(c)}?customer_id=${customer}`);
      if(inquiry!==c)return;
      inquiryRows=rows;
      inquiryPicker.hidden=!rows.length||(!editable()&&rows.length===1);
      inquiryRecord.replaceChildren(new Option('选择询价…',''),...rows.map(item=>new Option(item.number,item.id)));
      inquiryRecord.options[0].disabled=true;
      inquiryRecord.hidden=rows.length===1&&!editable();
      dialog.querySelector('[data-inquiry-new]').hidden=!editable();
      selectInquiry(rows.find(item=>item.number===number)||rows[0]||null);
      if(editable())(activeInquiry?itemList.querySelector('textarea'):inquiryForm.elements.number).focus();
    }catch(error){if(inquiry===c)inquiryStatus.textContent=error.message;}
  }
  inquiryRecord.onchange=()=>{
    if(!confirmDiscard()){inquiryRecord.value=activeInquiry?.id??'';return;}
    selectInquiry(inquiryRows.find(item=>String(item.id)===inquiryRecord.value)||null);
  };
  dialog.querySelector('[data-inquiry-new]').onclick=()=>{
    if(!saving&&confirmDiscard()){selectInquiry(null);inquiryForm.elements.number.focus();}
  };
  function closeInquiry(){
    if(!saving&&confirmDiscard()){inquiry=null;dialog.close();}
  }
  dialog.querySelectorAll('[data-inquiry-close]').forEach(button=>button.onclick=closeInquiry);
  dialog.oncancel=event=>{event.preventDefault();closeInquiry();};
  dialog.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&!inquiryForm.hidden&&editable()){
      event.preventDefault();
      if(!saving)inquiryForm.requestSubmit();
    }
  });
  inquiryForm.onsubmit=async event=>{
    event.preventDefault();
    if(saving||!inquiry||!editable())return;
    const c=inquiry,item=activeInquiry,values=formValues();
    const number=values.number.trim(), inquiry_items=values.inquiry_items;
    if(!number||inquiry_items.some(entry=>!entry.content.trim())){
      inquiryStatus.textContent='请填写编号和每条明细的需求。';
      return;
    }
    saving=true;
    const submit=inquiryForm.querySelector('[type="submit"]');
    submit.disabled=true;
    inquiryForm.elements.number.readOnly=true;
    syncItemControls();
    inquiryRecord.disabled=true;
    inquiryStatus.textContent='正在保存…';
    try{
      const url=`${inquiryUrl(c)}/customers/${c.customer}`;
      await inquiryRequest(item?`${url}/${item.id}`:url,{
        method:item?'PATCH':'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({number,inquiry_items})
      });
      if(inquiry!==c)return;
      inquiry=null;
      dialog.close();
      if(context?.customer===c.customer&&!item){context.counts.rfqs++;renderHeading();}
      document.dispatchEvent(new CustomEvent('tophoo-return-workflow-detail',{detail:{projectId:c.project,view:'contacts',refresh:true}}));
    }catch(error){if(inquiry===c)inquiryStatus.textContent=error.message;}
    finally{
      saving=false;submit.disabled=false;inquiryRecord.disabled=false;
      inquiryForm.elements.number.readOnly=!editable();
      syncItemControls();
    }
  };
  function mayLeave(){return document.dispatchEvent(new CustomEvent('tophoo-customer-documents-leave',{cancelable:true}));}
  function renderHeading(){
    if(!context)return;
    heading.innerHTML=`<div class="customer-document-heading-row"><button type="button" class="subpage-back-button" data-documents-back aria-label="返回列表" title="返回列表"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m11.5 5-5 5 5 5M7 10h9"/></svg></button><h1>${esc(context.company)}</h1><nav class="customer-document-tabs" aria-label="客户单据切换">${tabs.filter(([kind])=>!context.archive||kind==='contracts').map(([kind,label])=>`<button type="button" data-document-tab="${kind}" class="${context.kind===kind?'is-active':''}" aria-pressed="${context.kind===kind}" ${!context.allowed[kind]?'disabled':''}>${label}<span>${context.counts[kind]??'—'}</span></button>`).join('')}</nav></div>`;
  }
  function show(kind, extra={}){
    if(!context||!context.allowed[kind]||!roots[kind])return;
    context.kind=kind;workflow.hidden=true;workspace.hidden=false;
    Object.entries(roots).forEach(([key,root])=>{if(root)root.hidden=key!==kind;});
    renderHeading();
    const crumb=document.querySelector('#crm-breadcrumb-current');if(crumb)crumb.textContent=context.archive?'客户公池 › 合同归档':'客户列表 › '+tabs.find(tab=>tab[0]===kind)[1];
    document.dispatchEvent(new CustomEvent('tophoo-customer-documents-view',{detail:{...context,status:context.filters[kind]||'',search:context.searches[kind]||'',...extra}}));
    workspace.scrollIntoView({block:'start'});
  }
  workflow.addEventListener('click',event=>{
    const button=event.target.closest('[data-customer-documents]');if(!button||button.disabled||workflow.getAttribute('aria-busy')==='true')return;
    if(!mayLeave())return;
    if(button.dataset.customerDocuments==='rfqs'){
      openInquiry(Number(button.dataset.customerId),button.dataset.customerName,button.dataset.documentNumber);
      return;
    }
    const row=button.closest('[data-workflow-row]'),allowed={},counts={};
    for(const [kind] of tabs){const entry=row.querySelector(`[data-customer-documents="${kind}"]`);allowed[kind]=!!entry&&!entry.disabled;counts[kind]=Number(entry?.querySelector('.workflow-activity-count')?.textContent)||0;}
    trigger=button;context={archive:button.hasAttribute('data-contract-archive'),project:pid(),customer:Number(button.dataset.customerId),company:button.dataset.customerName,allowed,counts,filters:{rfqs:'',quotations:''},searches:{rfqs:'',quotations:''}};context.filters[button.dataset.customerDocuments]=button.dataset.documentStatus||'';
    context.searches[button.dataset.customerDocuments]=button.dataset.documentNumber||'';
    show(button.dataset.customerDocuments);
  });
  document.addEventListener('tophoo-contract-from-quote',event=>{
    const {customer, quotationId}=event.detail;
    if(context?.kind==='quotations'&&context.customer===customer&&mayLeave())show('contracts',{quotationId});
  });
  heading.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||!context)return;
    if(button.hasAttribute('data-documents-back')){
      if(!mayLeave())return;const returnView=context.archive?'customer-pool':'contacts';workspace.hidden=true;context=null;
      if(window.tophooNavigateGlobal)window.tophooNavigateGlobal(returnView);
      else{workflow.hidden=false;document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view',{detail:{view:returnView}}));}
      if(trigger?.isConnected)trigger.focus();return;
    }
    if(button.dataset.documentTab==='rfqs'&&mayLeave())openInquiry(context.customer,context.company);
    else if(button.dataset.documentTab&&button.dataset.documentTab!==context.kind&&mayLeave())show(button.dataset.documentTab);
  });
  document.addEventListener('tophoo-customer-documents-loaded',event=>{
    const c=event.detail;if(!context||c.project!==context.project||c.customer!==context.customer)return;
    context.counts[c.kind]=c.count;renderHeading();
  });
  const reset=()=>{workspace.hidden=true;context=null;inquiry=null;dialog.close();};
  window.addEventListener('tophoo-project-changed',reset);document.addEventListener('tophoo-auth-changed',reset);
})();
