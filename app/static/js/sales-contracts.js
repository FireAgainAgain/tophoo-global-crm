(() => {
  const root = document.querySelector('[data-crm-contracts]');
  if (!root) return;
  const q = selector => root.querySelector(selector);
  const form = q('[data-contract-form]');
  const fields = q('[data-contract-fields]');
  const editor = q('[data-contract-editor]');
  const picker = q('[data-contract-template-picker]');
  const pdf = q('[data-contract-pdf]');
  const rowsNode = q('[data-contract-rows]');
  const fileInput = q('[data-contract-signed-input]');
  const pid = () => Number(localStorage.getItem('tophoo-global-selected-project'));
  const editable = () => !context?.archive && (window.tophooProjectAccess?.canEdit('customer_list') ?? true);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const today = () => new Date().toLocaleDateString('sv-SE', {timeZone: 'Asia/Shanghai'});
  const money = (value, currency) => {
    const [whole, fraction = ''] = String(value).split('.');
    return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0')}`;
  };
  function centsText(cents) {
    const absolute = cents < 0n ? -cents : cents;
    return `${cents < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`;
  }
  const templateNames = {domestic: '内销中文合同', export: '外销英文合同'};
  let context, rows = [], draft, baseline, pdfUrl, busy = false, uploading, creation;

  function feedback(message = '', error = false) {
    const node = q('[data-contract-feedback]');
    node.textContent = message;
    node.hidden = !message;
    node.classList.toggle('is-error', error);
  }

  function formFeedback(message = '', error = false) {
    const node = q('[data-contract-form-status]');
    node.textContent = message;
    node.classList.toggle('is-error', error);
  }

  function active(target) {
    return target && target === context && target.project === pid() && !root.hidden;
  }

  async function api(target, path = '', {method = 'GET', data} = {}) {
    const headers = {...window.tophooAuth?.headers?.()};
    let body = data;
    if (data && !(data instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(data);
    }
    const response = await fetch(`/api/contracts/projects/${target.project}/customers/${target.customer}${path}`, {method, headers, body});
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      const issues = Array.isArray(error.detail) ? error.detail.map(item => item.msg.replace('Value error, ', '')) : [];
      throw Error(typeof error.detail === 'string' ? error.detail : issues.join('；') || '操作失败，请稍后重试。');
    }
    return response.headers.get('content-type')?.includes('application/json') ? response.json() : response.blob();
  }

  function renderRows() {
    q('[data-contract-count]').textContent = `${rows.length} 份合同`;
    q('[data-contract-add]').hidden = !editable();
    rowsNode.innerHTML = rows.length ? rows.map(row => {
      const writable = editable();
      const canUpload = writable && ['草稿', '已发出'].includes(row.status);
      return `<tr><td><button type="button" class="quote-number" data-contract-action="view" data-id="${row.id}">${esc(row.number)}</button>
        <small>${row.layout === 'domestic' ? '内销合同' : '外销合同'}${row.source_quote_number ? ' · ' + esc(row.source_quote_number) : ''}</small></td>
        <td>${esc(row.date)}</td><td class="contract-money">${esc(money(row.total, row.currency))}</td>
        <td><span class="contract-state" data-state="${esc(row.status)}">${esc(row.status)}</span></td>
        <td><div class="quote-row-actions">
          ${row.status === '草稿' && writable ? `<button type="button" data-contract-action="edit" data-id="${row.id}">编辑</button>` : ''}
          <button type="button" data-contract-action="view" data-id="${row.id}">预览</button>
          <button type="button" class="quote-more-action" popovertarget="contract-menu-${row.id}" aria-label="合同 ${esc(row.number)} 的更多操作">⋯</button>
          <div class="quote-row-menu" id="contract-menu-${row.id}" popover>
            ${menuButton(row, 'pdf', '导出 PDF')}${menuButton(row, 'xlsx', '导出 Excel')}
            ${row.status === '草稿' && writable ? menuButton(row, 'send', '标记已发出') : ''}
            ${canUpload ? menuButton(row, 'upload', '上传签回 PDF') : ''}
            ${row.has_signed ? menuButton(row, 'signed', '下载签回件') : ''}
            ${writable && row.status !== '已作废' ? menuButton(row, 'void', '作废合同', true) : ''}
          </div>
        </div></td></tr>`;
    }).join('') : '<tr><td class="quote-empty" colspan="5">该客户暂无合同</td></tr>';
  }

  function menuButton(row, action, label, danger = false) {
    return `<button type="button" ${danger ? 'class="quote-danger"' : ''} data-contract-action="${action}" data-id="${row.id}">${label}</button>`;
  }

  async function load(target) {
    const result = await api(target);
    if (!active(target)) return;
    rows = result;
    renderRows();
    document.dispatchEvent(new CustomEvent('tophoo-customer-documents-loaded', {
      detail: {...target, count: rows.length}
    }));
  }

  function field(name, label, value, options = {}) {
    const {type = 'text', required = false, wide = false, max, step, min, choices, rows = 2} = options;
    const attr = `name="${name}" ${required ? 'required' : ''} ${max ? `maxlength="${max}"` : ''}`;
    let control;
    if (choices) {
      control = `<select ${attr}>${choices.map(([key, title]) =>
        `<option value="${key}" ${key === value ? 'selected' : ''}>${title}</option>`).join('')}</select>`;
    } else if (type === 'textarea') {
      control = `<textarea ${attr} rows="${rows}">${esc(value)}</textarea>`;
    } else {
      control = `<input ${attr} type="${type}" value="${esc(value)}" ${step ? `step="${step}"` : ''} ${min != null ? `min="${min}"` : ''}>`;
    }
    return `<label class="${wide ? 'contract-wide' : ''}"><span>${label}</span>${control}</label>`;
  }

  function card(id, title, content) {
    return `<section class="contract-card" data-contract-section="${id}"><h3>${title}</h3>${content}</section>`;
  }

  const terms = [
    ['price_term','价格 / 交货条件'], ['delivery_time','交货时间'], ['packing','包装方式'],
    ['transport','运输及费用'], ['origin','原产地'], ['price_validity','价格有效期']
  ];
  const domesticTerms = [
    ['invoice','税费及发票'], ['acceptance','验收标准'], ['quality','质量要求'], ['breach','违约责任']
  ];
  const bank = [
    ['beneficiary_name','户名'], ['beneficiary_address','收款人地址'], ['beneficiary_bank','开户行'],
    ['bank_address','银行地址'], ['bank_account','账号'], ['swift_code','SWIFT']
  ];

  function party(title, prefix, doc, person) {
    const entry = (key, label, options) => field(key, label, doc[key] ?? '', options);
    return `<div class="contract-party"><h4>${title}</h4><div class="contract-grid">
      ${entry(prefix + '_company', '公司名称', {required: true, wide: true, max: 260})}
      ${entry(person, '联系人', {max: 160})}${entry(prefix + '_phone', '电话', {max: 120})}
      ${entry(prefix + '_email', '邮箱', {max: 260})}${entry(prefix + '_tax_id', '税号', {max: 120})}
      ${entry(prefix + '_address', '地址', {type:'textarea', wide:true, max:1000})}
    </div></div>`;
  }

  function fit(node) {
    node.style.height = 'auto';
    node.style.height = `${node.scrollHeight + 2}px`;
  }

  function addLine(line = {}) {
    const list = form.querySelector('[data-contract-lines]');
    if (list.children.length >= 100) return;
    const row = document.createElement('div');
    row.className = 'contract-line';
    const entry = (name, label, value, options) => field(name, label, value, options);
    row.innerHTML = `<div class="contract-line-top"><strong>产品</strong><button type="button" data-contract-remove-line>删除</button></div>
      <div class="contract-grid line-grid">
        ${entry('name','名称 / 型号',line.name,{max:160})}${entry('brand','商标',line.brand,{max:100})}
        ${entry('quantity','数量',line.quantity ?? '1',{type:'number',required:true,step:'0.001',min:'0.001'})}
        ${entry('unit','单位',line.unit,{max:20})}
        ${entry('unit_price','单价',line.unit_price ?? '0',{type:'number',required:true,step:'0.01',min:0})}
        <div class="contract-line-amount"><span>金额</span><output></output></div>
        ${entry('description','型号 / 规格',line.description,{type:'textarea',required:true,wide:true,max:2000})}
        ${entry('remark','备注',line.remark,{wide:true,max:300})}
      </div>`;
    list.append(row);
    fit(row.querySelector('textarea'));
    renumberLines();
  }

  function renumberLines() {
    const lines = form.querySelectorAll('.contract-line');
    lines.forEach((line, index) => {
      line.querySelector('strong').textContent = `产品 ${index + 1}`;
      line.querySelector('[data-contract-remove-line]').disabled = lines.length === 1;
    });
  }

  function renderEditor(row) {
    const doc = row.document;
    const entry = (name, label, options = {}) => field(name, label, doc[name] ?? '', options);
    const termField = ([name, label]) => entry(name, label, {type:'textarea', max:name === 'breach' ? 2000 : 1000});
    q('#contract-editor-title').textContent = row.id ? '编辑合同' : '新建合同';
    const source = q('[data-contract-source]');
    const layout = doc.layout || 'export';
    source.hidden = false;
    source.textContent = [templateNames[layout], row.source_quote_number && `来源报价 ${row.source_quote_number}`].filter(Boolean).join(' · ');
    fields.innerHTML =
      card('parties', '双方信息', `<div class="contract-grid contract-top">
        ${field('number','合同号',row.number,{required:true,max:80})}
        <input type="hidden" name="layout" value="${layout}">
        ${field('contract_date','签订日期',doc.contract_date || today(),{type:'date',required:true})}
        ${entry('signing_place','签订地点',{max:260})}
      </div><div class="contract-parties">${party('卖方 / 供方','seller',doc,'salesperson')}${party('买方 / 需方','buyer',doc,'attention')}</div>
      <div class="contract-grid contract-charges">
        <label><span>卖方 Logo</span><input type="file" name="logo_image" accept="image/png,image/jpeg,image/webp"></label>
        <div data-contract-logo></div>
      </div>`) +
      card('items', '产品明细', `<div class="contract-grid contract-top">
        ${entry('commodity','商品名称',{max:260})}
        ${entry('hs_code','HS 编码',{max:40})}
        ${field('currency','币种',doc.currency || 'CNY',{required:true,max:3})}
        ${layout === 'domestic' && doc.currency && !['CNY','RMB'].includes(doc.currency) ?
          '<p class="quote-feedback contract-wide">来源报价使用外币。请核对人民币单价和币种后再保存。</p>' : ''}
      </div><div data-contract-lines></div><button type="button" data-contract-add-line>＋ 添加产品</button>
      <div class="contract-grid contract-charges">
        ${entry('charge_label','附加费用名称',{max:120})}
        ${field('charge_amount','附加费用',doc.charge_amount || '0',{type:'number',step:'0.01',min:0})}
      </div>`) +
      card('terms', '付款与交付', `<div class="contract-grid">
        ${field('payment_mode','付款方式',doc.payment_mode || 'full',{choices:[['full','全款'],['deposit','定金＋尾款']]})}
        ${field('deposit_percent','定金比例 %',doc.deposit_percent ?? '50',{type:'number',step:'0.01',min:0})}
        <output class="contract-wide contract-totals" data-contract-totals></output>
        ${terms.map(termField).join('')}
        <div class="contract-wide contract-grid" data-contract-domestic>${domesticTerms.map(termField).join('')}</div>
        ${entry('additional_terms','其他条款',{type:'textarea',wide:true,max:4000})}
      </div>`) +
      card('receipt', '收款与签署', `<div class="contract-grid">
        ${field('receipt_mode','收款资料',doc.receipt_mode || 'none',{choices:[['none','不展示'],['bank','公司银行账户'],['alipay','支付宝收款']]})}
        <div class="contract-wide contract-grid" data-contract-bank>${bank.map(([key,label])=>entry(key,label)).join('')}</div>
        <div class="contract-wide contract-grid" data-contract-alipay>
          ${entry('alipay_name','收款人',{max:260})}${entry('alipay_account','支付宝账号',{max:160})}
          <label><span>支付宝收款二维码</span><input type="file" name="alipay_image" accept="image/png,image/jpeg,image/webp"></label>
          <div data-contract-qr></div>
        </div>
      </div>`);
    editor.showModal();
    (doc.items?.length ? doc.items : [{}]).forEach(addLine);
    updateDisplay();
    fields.scrollTop = 0;
    baseline = JSON.stringify(payload());
    formFeedback();
    form.elements.number.focus();
  }

  // The preview uses the same integer cents and quantity scale as the server.
  function scaled(value, precision) {
    const match = /^(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(value);
    if (!match) return 0n;
    const [, whole, part = '', exponent = '0'] = match;
    const shift = Number(exponent) + precision - part.length;
    const digits = whole + part;
    if (!digits || Math.abs(shift) > 32) return 0n;
    const factor = 10n ** BigInt(Math.abs(shift));
    const amount = BigInt(digits);
    if (shift >= 0) return amount * factor;
    return amount % factor === 0n ? amount / factor : 0n;
  }

  function updateDisplay() {
    const mode = form.elements.payment_mode.value;
    const receipt = form.elements.receipt_mode.value;
    form.elements.deposit_percent.closest('label').hidden = mode !== 'deposit';
    form.querySelector('[data-contract-bank]').hidden = receipt !== 'bank';
    form.querySelector('[data-contract-alipay]').hidden = receipt !== 'alipay';
    form.querySelector('[data-contract-domestic]').hidden = form.elements.layout.value !== 'domestic';
    const currency = form.elements.currency.value.toUpperCase();
    let total = scaled(form.elements.charge_amount.value, 2);
    form.querySelectorAll('.contract-line').forEach(line => {
      const amount = (scaled(line.querySelector('[name="quantity"]').value, 3) *
        scaled(line.querySelector('[name="unit_price"]').value, 2) + 500n) / 1000n;
      total += amount;
      line.querySelector('output').textContent = money(centsText(amount), currency);
    });
    const deposit = (total * scaled(form.elements.deposit_percent.value, 2) + 5000n) / 10000n;
    const box = form.querySelector('[data-contract-totals]');
    const entries = mode === 'deposit' ? [['合计',total],['定金',deposit],['尾款',total - deposit]] : [['全款',total]];
    box.innerHTML = entries.map(([label, amount]) => `<span>${label} <strong>${esc(money(centsText(amount),currency))}</strong></span>`).join('');
    for (const [type, key, label] of [['qr','alipay_qr','二维码'], ['logo','logo_data_url','Logo']]) {
      const node = form.querySelector(`[data-contract-${type}]`);
      if (node.dataset.image === (draft.document[key] || '')) continue;
      node.dataset.image = draft.document[key] || '';
      node.innerHTML = draft.document[key]
        ? `<img alt="${label}" src="${esc(draft.document[key])}"><button type="button" data-contract-remove-image="${key}">移除${label}</button>` : '';
    }
  }

  function payload() {
    const doc = {...draft.document};
    for (const [key, value] of new FormData(form)) {
      if (typeof value === 'string' && !['number','name','brand','quantity','unit','unit_price','description','remark'].includes(key)) {
        doc[key] = value.trim();
      }
    }
    doc.currency = doc.currency.toUpperCase();
    doc.deposit_percent ||= '50';
    doc.charge_amount ||= '0';
    doc.items = [...form.querySelectorAll('.contract-line')].map(line =>
      Object.fromEntries([...line.querySelectorAll('[name]')].map(node=>[node.name,node.value.trim()])));
    return {number: form.elements.number.value.trim(), revision: draft.revision,
      source_quote_id: draft.source_quote_id, document: doc};
  }

  function allowClose() {
    if (!editor.open) return true;
    if (busy) return false;
    if (baseline !== JSON.stringify(payload()) && !window.confirm('放弃本次未保存的修改？')) return false;
    editor.close();
    return true;
  }

  async function openEditor(target, row) {
    if (!editable() || !active(target)) return;
    const value = await api(target, `/${row.id}`);
    if (!active(target) || editor.open) return;
    if (value.status !== '草稿') throw Error('只能编辑草稿，请刷新合同列表。');
    draft = value;
    renderEditor(value);
  }

  function pickerStatus(message = '', error = false) {
    const node = q('[data-contract-template-status]');
    node.textContent = message;
    node.hidden = !message;
    node.classList.toggle('is-error', error);
  }

  function closeTemplatePicker() {
    creation = null;
    picker.close();
  }

  function pickTemplate(target, quotationId) {
    if (!active(target) || !editable() || busy || picker.open || editor.open) return;
    creation = {target, quotationId, pending: false};
    pickerStatus();
    picker.querySelectorAll('[data-contract-template]').forEach(button => { button.disabled = false; });
    picker.showModal();
  }

  picker.oncancel = event => { event.preventDefault(); closeTemplatePicker(); };
  picker.onclick = async event => {
    if (event.target.closest('[data-contract-template-cancel]')) {
      closeTemplatePicker();
      return;
    }
    const choice = event.target.closest('[data-contract-template]');
    const current = creation;
    if (!choice || !current || current.pending || !active(current.target) || !editable()) return;
    current.pending = true;
    const buttons = picker.querySelectorAll('[data-contract-template]');
    buttons.forEach(button => { button.disabled = true; });
    pickerStatus('正在载入模板…');
    const query = new URLSearchParams({layout: choice.dataset.contractTemplate});
    if (current.quotationId) query.set('quotation_id', current.quotationId);
    try {
      const value = await api(current.target, `/defaults?${query}`);
      if (creation !== current || !active(current.target)) return;
      closeTemplatePicker();
      draft = value;
      renderEditor(value);
    } catch (error) {
      if (creation !== current || !active(current.target)) return;
      pickerStatus(error.message, true);
      current.pending = false;
      buttons.forEach(button => { button.disabled = false; });
    }
  };

  function closePdf() {
    pdf.close();
    pdf.querySelector('iframe').removeAttribute('src');
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    pdfUrl = null;
  }

  function showPdf(blob, number) {
    if (pdfUrl) closePdf();
    pdfUrl = URL.createObjectURL(blob);
    pdf.querySelector('iframe').src = pdfUrl;
    const link = q('[data-contract-pdf-download]');
    link.href = pdfUrl;
    link.download = `Sales-Contract-${number}.pdf`;
    pdf.showModal();
  }

  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function setBusy(value) {
    busy = value;
    q('[data-contract-save]').disabled = value;
    q('[data-contract-preview]').disabled = value;
    q('[data-contract-add]').disabled = value;
  }

  async function saveOrPreview(preview) {
    if (busy || !editable() || !form.reportValidity()) return;
    const target = context;
    const data = payload();
    const id = draft.id;
    setBusy(true);
    formFeedback();
    try {
      const path = preview ? '/preview/pdf' : id ? `/${id}` : '';
      const result = await api(target, path, {method: id && !preview ? 'PUT' : 'POST', data});
      if (!active(target)) return;
      if (preview) showPdf(result, data.number);
      else {
        editor.close();
        feedback('合同已保存。');
        await load(target);
      }
    } catch (error) {
      if (active(target)) {
        if (editor.open) formFeedback(error.message, true);
        else feedback(error.message, true);
      }
    } finally { setBusy(false); }
  }

  form.onsubmit = event => { event.preventDefault(); saveOrPreview(false); };
  q('[data-contract-preview]').onclick = () => saveOrPreview(true);
  q('[data-contract-close]').onclick = allowClose;
  q('[data-contract-pdf-close]').onclick = closePdf;
  editor.oncancel = event => { event.preventDefault(); allowClose(); };
  pdf.oncancel = event => { event.preventDefault(); closePdf(); };
  editor.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && !pdf.open) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  editor.querySelector('nav').onclick = event => {
    const section = event.target.closest('[data-contract-jump]')?.dataset.contractJump;
    if (section) form.querySelector(`[data-contract-section="${section}"]`)?.scrollIntoView({block:'start',behavior:'smooth'});
  };
  form.oninput = event => {
    if (event.target.matches('.contract-line textarea')) fit(event.target);
    if (event.target.type !== 'file') updateDisplay();
  };
  form.onclick = event => {
    if (event.target.closest('[data-contract-add-line]')) {
      addLine();
      updateDisplay();
    }
    if (event.target.closest('[data-contract-remove-line]')) {
      event.target.closest('.contract-line').remove();
      renumberLines();
      updateDisplay();
    }
    const image = event.target.closest('[data-contract-remove-image]')?.dataset.contractRemoveImage;
    if (image) {
      draft.document[image] = '';
      form.elements[image === 'alipay_qr' ? 'alipay_image' : 'logo_image'].value = '';
      updateDisplay();
    }
  };
  form.onchange = event => {
    if (!['alipay_image','logo_image'].includes(event.target.name)) return;
    const key = event.target.name === 'alipay_image' ? 'alipay_qr' : 'logo_data_url';
    const image = event.target.files[0], current = draft;
    if (!image) return;
    if (!['image/png','image/jpeg','image/webp'].includes(image.type) || image.size > 1024 * 1024) {
      event.target.value = '';
      formFeedback('图片请使用 1 MB 以内的 PNG、JPG 或 WebP。', true);
      return;
    }
    setBusy(true);
    const reader = new FileReader();
    reader.onload = () => {
      if (draft !== current || !editor.open) return;
      draft.document[key] = reader.result;
      formFeedback();
      updateDisplay();
    };
    reader.onerror = () => formFeedback('无法读取图片。', true);
    reader.onloadend = () => setBusy(false);
    reader.readAsDataURL(image);
  };

  q('[data-contract-add]').onclick = () => pickTemplate(context);
  rowsNode.addEventListener('toggle', event => {
    const menu = event.target;
    if (!menu.matches('.quote-row-menu') || event.newState !== 'open') return;
    const rect = menu.previousElementSibling.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(rect.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.top = `${rect.bottom + menu.offsetHeight < innerHeight ? rect.bottom + 4 : Math.max(8, rect.top - menu.offsetHeight - 4)}px`;
  }, true);
  rowsNode.onclick = async event => {
    const button = event.target.closest('[data-contract-action]');
    const row = rows.find(item => item.id === Number(button?.dataset.id));
    const target = context;
    if (!row || !active(target) || busy) return;
    button.closest('[popover]')?.hidePopover();
    const action = button.dataset.contractAction;
    if (action === 'upload') {
      uploading = {target, row};
      fileInput.value = '';
      fileInput.click();
      return;
    }
    setBusy(true);
    feedback();
    try {
      if (action === 'edit') await openEditor(target, row);
      else if (action === 'send' || action === 'void') {
        const status = action === 'send' ? '已发出' : '已作废';
        if (!window.confirm(action === 'send' ? '标记为已发出后，合同正文将锁定。继续？' : '确认作废这份合同？')) return;
        await api(target, `/${row.id}/status`, {method:'PATCH',data:{status,revision:row.revision}});
        if (active(target)) await load(target);
      } else {
        const extension = action === 'xlsx' ? 'xlsx' : 'pdf';
        const path = action === 'signed' ? `/${row.id}/signed` : `/${row.id}/document/${extension}`;
        const blob = await api(target, path);
        if (!active(target)) return;
        if (action === 'view') showPdf(blob, row.number);
        else download(blob, `Sales-Contract-${row.number}${action === 'signed' ? '-signed' : ''}.${extension}`);
      }
    } catch (error) { if (active(target)) feedback(error.message, true); }
    finally { setBusy(false); }
  };
  fileInput.onchange = async () => {
    const file = fileInput.files[0], pending = uploading;
    uploading = null;
    if (!file || !pending || !active(pending.target) || busy) return;
    if (!window.confirm('归档这份签回 PDF 并标记合同为已签署？')) return;
    const data = new FormData();
    data.append('file', file);
    setBusy(true);
    try {
      const {target, row} = pending;
      await api(target, `/${row.id}/signed?revision=${row.revision}`, {method:'POST',data});
      if (active(target)) {
        feedback('签回件已归档。');
        await load(target);
      }
    } catch (error) { if (active(pending.target)) feedback(error.message, true); }
    finally { setBusy(false); }
  };

  function reset() {
    context = null;
    rows = [];
    draft = null;
    uploading = null;
    closeTemplatePicker();
    editor.close();
    closePdf();
  }
  document.addEventListener('tophoo-customer-documents-view', async event => {
    const target = event.detail;
    if (target.kind !== 'contracts' || target.project !== pid()) return;
    context = target;
    root.dataset.permissionModule = target.archive ? 'customer_pool' : 'customer_list';
    rows = [];
    renderRows();
    feedback();
    try {
      await load(target);
      if (target.quotationId) pickTemplate(target, target.quotationId);
    } catch (error) { if (active(target)) feedback(error.message, true); }
  });
  document.addEventListener('tophoo-customer-documents-leave', event => {
    if (event.defaultPrevented || !context || root.hidden) return;
    if (!allowClose()) { event.preventDefault(); return; }
    reset();
  });
  document.addEventListener('click', event => {
    if (!context || root.hidden || !event.target.closest('.global-nav-item,.crm-primary-item,.pm-project-row,[data-project-id]')) return;
    if (!allowClose()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    reset();
  }, true);
  window.addEventListener('beforeunload', event => {
    if (editor.open && (busy || baseline !== JSON.stringify(payload()))) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  window.addEventListener('tophoo-project-changed', reset);
  document.addEventListener('tophoo-auth-changed', reset);
})();
