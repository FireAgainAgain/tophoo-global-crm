/* Scoped contact outreach history; this window is read-only. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let active=null;
  function close(){const previous=active;active=null;if(previous){previous.dialog.close();previous.dialog.remove();if(previous.trigger?.isConnected)previous.trigger.focus();}}
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-contact-outreach]');if(!button||button.disabled)return;close();
    const dialog=document.createElement('dialog');dialog.className='contact-outreach-history';dialog.setAttribute('aria-labelledby','contact-outreach-title');
    const state={dialog,trigger:button,project:Number(button.dataset.outreachProject),lead:Number(button.dataset.outreachLead),email:button.dataset.outreachRecipient,before:null,busy:false};active=state;
    dialog.innerHTML=`<header><div><h2 id="contact-outreach-title">开发信发送记录</h2><p>${esc(state.email)}</p></div><button type="button" data-history-close aria-label="关闭发送记录">×</button></header><p class="outreach-history-basis">按该线索、当前邮箱统计服务器已接受的邮件，不代表对方已收到或阅读。</p><p data-history-status role="status"></p><div data-history-items></div><footer><button type="button" data-history-more hidden>加载更多</button></footer>`;
    document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-history-close]').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
    async function load(){if(state.busy||active!==state)return;state.busy=true;const status=dialog.querySelector('[data-history-status]'),more=dialog.querySelector('[data-history-more]');more.disabled=true;status.textContent='正在读取发送记录…';
      try{const params=new URLSearchParams({recipient:state.email});if(state.before)params.set('before_id',state.before);const response=await fetch(`/api/mail/projects/${state.project}/leads/${state.lead}/outreach-history?${params}`,{headers:window.tophooAuth?.headers?.()||{},cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'读取失败，请重试。');if(active!==state)return;
        const container=dialog.querySelector('[data-history-items]');for(const row of data.items||[]){const card=document.createElement('article');card.className='outreach-history-card';card.innerHTML=`<details><summary><strong>${esc(row.subject||'无标题')}</strong><time>${esc((row.accepted_at||row.created_at||'').slice(0,16).replace('T',' '))}</time></summary><p class="outreach-history-sender">发件人：${esc(row.sender)}</p><div data-history-body></div>${row.attachments?.length?`<p class="outreach-history-attachments">附件：${row.attachments.map(file=>esc(file.name)).join('、')}</p>`:''}</details>`;const body=card.querySelector('[data-history-body]');if(row.content_html&&window.TophooRichMail)body.innerHTML=window.TophooRichMail.clean(row.content_html);else body.textContent=row.content||'';container.append(card);}
        state.before=data.next_before_id;more.hidden=!state.before;more.textContent='加载更多';status.textContent=data.total?`共发送 ${data.total} 封开发信`:'尚未向该邮箱发送开发信';
      }catch(error){if(active===state){status.textContent=error.message;more.hidden=false;more.textContent='重新读取';}}finally{state.busy=false;if(active===state)more.disabled=false;}
    }
    dialog.querySelector('[data-history-more]').onclick=load;load();
  });
  window.addEventListener('tophoo-project-changed',close);document.addEventListener('tophoo-auth-changed',close);document.addEventListener('tophoo-customer-workflow-view',close);
})();
