/* Per-recipient delivery totals in the lead detail contact cards. */
(() => {
  const overlay=document.querySelector('[data-workflow-detail]');if(!overlay)return;
  let active=null,sequence=0;
  const auth=()=>window.tophooAuth?.headers?.()||{};
  const identity=()=>JSON.stringify(auth());
  const current=(s,panel,token)=>active===s&&sequence===token&&!overlay.hidden&&overlay.dataset.detailView==='leads'&&panel.isConnected&&Number(localStorage.getItem('tophoo-global-selected-project'))===s.project&&identity()===s.identity;
  async function refresh(){
    const s=active,panel=overlay.querySelector('[data-detail-people]');if(!s||!panel||overlay.hidden||overlay.dataset.detailView!=='leads')return;
    const token=++sequence;
    panel.querySelectorAll('[data-detail-outreach-email]').forEach(node=>{node.textContent=node.dataset.detailOutreachEmail?'开发信数量读取中…':'无邮箱 · 暂无法统计';});
    try{
      const response=await fetch(`/api/customer-workflow/projects/${s.project}/leads/${s.id}/contacts`,{headers:auth(),cache:'no-store'});
      if(!response.ok)throw Error('读取失败');const data=await response.json();if(!current(s,panel,token))return;
      panel.querySelectorAll('[data-detail-outreach-email]').forEach(node=>{
        const email=node.dataset.detailOutreachEmail.trim();if(!email)return;
        const count=data.outreach_stats?.[email.toLowerCase()]?.sent_count||0;
        const button=document.createElement('button');button.type='button';button.textContent=`已发开发信 · ${count} 封`;button.classList.toggle('is-sent',count>0);
        button.dataset.contactOutreach='';button.dataset.outreachProject=s.project;button.dataset.outreachLead=s.id;button.dataset.outreachRecipient=email;
        button.title='按该邮箱统计发送成功的开发信，点击查看记录';node.replaceChildren(button);
      });
    }catch{
      if(!current(s,panel,token))return;
      panel.querySelectorAll('[data-detail-outreach-email]').forEach(node=>{
        if(!node.dataset.detailOutreachEmail)return;
        const button=document.createElement('button');button.type='button';button.dataset.detailOutreachRetry='';button.textContent='数量读取失败，点击重试';node.replaceChildren(button);
      });
    }
  }
  document.addEventListener('tophoo-workflow-detail-ready',event=>{
    ++sequence;active=null;const d=event.detail;if(d.view!=='leads')return;
    active={project:Number(d.project),id:Number(d.id),identity:identity()};refresh();
  });
  for(const name of ['tophoo-lead-contacts-updated','tophoo-lead-outreach-updated'])document.addEventListener(name,event=>{
    if(active&&Number(event.detail.project)===active.project&&Number(event.detail.id)===active.id)refresh();
  });
  overlay.addEventListener('click',event=>{if(event.target.closest('[data-detail-outreach-retry]'))refresh();});
  for(const name of ['tophoo-project-changed','tophoo-auth-changed'])window.addEventListener(name,()=>{active=null;++sequence;});
})();
