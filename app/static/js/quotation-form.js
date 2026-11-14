/* Shared form components for quotation documents and their default templates. */
window.tophooQuotationForm=(()=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const limits={number:80,template_name:120,quantity_label:120,subtotal_label:120,total_label:120,balance_label:120,deposit_label:120,local_charge_label:120,buyer_company:260,attention:160,buyer_phone:120,buyer_email:260,buyer_address:1000,commodity:260,seller_company:260,seller_address:1000,seller_email:260,seller_phone:120,seller_fax:120,seller_website:260,salesperson:160,salesperson_phone:120,salesperson_email:260,contact_line:1000,quantity_unit:20,origin:260,price_validity:260,bank_account:120,swift_code:80,beneficiary_name:260,beneficiary_bank:500};
  const field=(key,label,value='',type='text',extra='')=>`<label>${esc(label)}<input name="${key}" type="${type}" ${['text','email'].includes(type)?`maxlength="${limits[key]||1000}"`:''} value="${esc(value)}" ${extra}></label>`;
  const section=(title,content,extra='')=>`<section class="quote-form-section ${extra}"><h3>${esc(title)}</h3>${content}</section>`;
  const seller=d=>['seller_company','seller_address','seller_email','seller_website','seller_phone','seller_fax'].map((key,i)=>field(key,['公司名称','公司地址','公司邮箱','公司网站','电话','传真'][i],d[key],key==='seller_email'?'email':'text',key==='seller_company'?'required':'')).join('');
  const terms=d=>['price_term','payment_term','delivery_time','packing','origin','price_validity'].map((key,i)=>field(key,['价格条款','付款条款','交货期','包装','原产地','报价有效期'][i],d[key])).join('');
  const bank=d=>['beneficiary_name','beneficiary_address','beneficiary_bank','bank_address','bank_account','swift_code'].map((key,i)=>field(key,['收款人名称','收款人地址','收款银行','银行地址','收款账号','SWIFT'][i],d[key])).join('');
  const logo=(d,prefix='quote')=>`<input type="hidden" name="logo_data_url" value="${esc(d.logo_data_url||'')}"><div class="quote-logo-editor"><div class="quote-logo-preview"><img data-${prefix}-logo-preview alt="报价 Logo 预览" ${d.logo_data_url?`src="${esc(d.logo_data_url)}"`:'hidden'}><span data-${prefix}-logo-empty ${d.logo_data_url?'hidden':''}>未设置 Logo</span></div><div class="quote-logo-controls"><div><label class="quote-logo-upload"><span data-${prefix}-logo-label>${d.logo_data_url?'更换 Logo':'上传 Logo'}</span><input type="file" accept="image/png,image/jpeg,image/webp" data-${prefix}-logo-upload hidden></label><button type="button" data-${prefix}-logo-remove>移除</button></div><small>支持 PNG、JPG、WebP，大小不超过 1 MB；按原比例显示。</small></div></div>`;
  const summaryFields=[
    ['quantity','quantity_label','数量合计','QUANTITY'],
    ['subtotal','subtotal_label','产品金额','TOTAL'],
    ['local','local_charge_label','FOB 费用','FOB FOSHAN CHARGE :'],
    ['total','total_label','总金额','TOTAL'],
    ['deposit','deposit_label','定金','留空自动命名'],
    ['balance','balance_label','尾款','BALANCE PAYMENT']
  ];
  function amounts(d,{template=false}={}){
    const rows=summaryFields.map(([key,,label])=>`<span class="${key==='total'?'quote-grand-total':''}" data-quote-${key}-wrap><span><span ${key==='deposit'?'data-payment-label':''}>${label}</span><small data-amount-caption="${key}" hidden></small></span><b data-quote-live-${key}>—</b></span>`).join('');
    const labels=summaryFields.map(([key,name,label,hint])=>`<div data-amount-label-field="${key}">${field(name,label,d[name]||'','text',`placeholder="${esc(hint)}"`)}</div>`).join('');
    return `<div class="quote-amount-layout"><div class="quote-amount-settings"><h4>${template?'默认付款设置':'付款设置'}</h4>
      <div class="quote-payment-options"><label>付款模式<select name="payment_mode">
        ${!d.payment_mode&&!d.include_balance?'<option value="">历史模式（仅显示定金）</option>':''}
        <option value="deposit" ${d.payment_mode==='deposit'||(!d.payment_mode&&d.include_balance)?'selected':''}>定金 + 尾款</option>
        <option value="full" ${d.payment_mode==='full'?'selected':''}>全款</option>
      </select></label><div data-deposit-percent>${field('deposit_percent','定金比例（%）',d.deposit_percent,'number','min="0" max="100" step="0.01" required')}</div></div>
      <div class="quote-payment-options quote-fee-options"><label class="quote-check"><input type="checkbox" name="include_local_charge" ${d.include_local_charge?'checked':''}>计入 FOB 费用</label><div data-local-charge-fields ${d.include_local_charge?'':'hidden'}>${field('local_charge_amount','FOB 金额',d.local_charge_amount??'0','number','min="0" max="1000000000" step="0.01"')}</div></div>
      </div>${template?'':`<div class="quote-amount-preview"><h4>实时汇总</h4><div class="quote-live-totals">${rows}</div></div>`}</div>
      <details class="quote-amount-labels"><summary>自定义导出名称</summary><p>这些名称用于 PDF 和 Excel，留空沿用默认名称。数量名称用于产品表头。</p><div class="quote-amount-label-grid">${labels}</div></details>`;
  }
  function bindAmounts(form){
    const mode=form.elements.payment_mode,percent=form.elements.deposit_percent,term=form.elements.payment_term;
    const depositTerm=()=>`${Number(percent.value)}% deposit, ${Number((100-Number(percent.value)).toFixed(2))}% balance before shipment`;
    const termsByMode=new Map();
    let previousMode=mode.value;
    mode.addEventListener('change',()=>{
      termsByMode.set(previousMode,term.value);
      term.value=termsByMode.get(mode.value)??(mode.value==='full'?'100% payment before shipment':depositTerm());
      previousMode=mode.value;
    });
    const sync=()=>{
      const charge=form.elements.include_local_charge.checked,full=mode.value==='full';
      form.querySelector('[data-deposit-percent]').hidden=full;
      percent.disabled=full;
      form.querySelector('[data-local-charge-fields]').hidden=!charge;
      form.elements.local_charge_amount.required=charge;
      form.elements.local_charge_amount.disabled=!charge;
      for(const [key,name,label] of summaryFields){
        const hidden=(['subtotal','local'].includes(key)&&!charge)||(key==='balance'&&mode.value!=='deposit');
        form.querySelector(`[data-amount-label-field="${key}"]`).hidden=hidden||(key==='deposit'&&full);
        const row=form.querySelector(`[data-quote-${key}-wrap]`);
        if(!row)continue;
        row.hidden=hidden;
        if(key==='deposit')row.querySelector('[data-payment-label]').textContent=full?'应付全款':'定金';
        const caption=row.querySelector('[data-amount-caption]'),custom=key==='deposit'&&full?'':form.elements[name].value.trim()||(key==='local'?'FOB FOSHAN CHARGE :':'');
        caption.textContent=custom;caption.hidden=!custom||custom===label;
      }
    };
    form.elements.deposit_percent.addEventListener('input',()=>{
      const input=form.elements.deposit_percent,term=form.elements.payment_term;
      if(!input.validity.valid||!/^\d+(?:\.\d+)?% deposit,\s*\d+(?:\.\d+)?% balance before shipment$/i.test(term.value))return;
      const percent=Number(input.value);
      term.value=percent+'% deposit, '+Number((100-percent).toFixed(2))+'% balance before shipment';
    });
    const section=form.querySelector('.quote-amounts');
    section.addEventListener('input',sync);section.addEventListener('change',sync);sync();
  }
  const bankSection=d=>`<details class="quote-form-section quote-bank" ${d.include_bank?'open':''}><summary>收款资料</summary><label class="quote-check"><input type="checkbox" name="include_bank" ${d.include_bank?'checked':''}>在导出的 PDF 和 Excel 中显示收款资料</label><div class="quote-grid">${bank(d)}</div></details>`;
  return {esc,field,section,seller,terms,bank,logo,amounts,bindAmounts,bankSection};
})();
