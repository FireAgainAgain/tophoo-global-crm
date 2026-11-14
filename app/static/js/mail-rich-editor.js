/* Small, self-contained email editor; persisted markup is also sanitized on the server. */
(() => {
  const tags=new Set('P DIV SPAN BR HR STRONG B EM I U S STRIKE A IMG TABLE THEAD TBODY TFOOT TR TD TH UL OL LI BLOCKQUOTE H1 H2 H3 H4 FONT'.split(' '));
  const styles=new Set('color background-color font-family font-size font-weight font-style text-decoration text-align vertical-align width height max-width min-width border border-top border-bottom border-left border-right border-radius border-collapse border-spacing padding padding-left padding-right padding-top padding-bottom margin margin-left margin-right margin-top margin-bottom line-height white-space'.split(' '));
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function clean(html){
    const template=document.createElement('template');template.innerHTML=html;
    [...template.content.querySelectorAll('*')].forEach(node=>{
      if(['SCRIPT','STYLE','IFRAME','OBJECT','SVG','MATH','TEMPLATE'].includes(node.tagName)){node.remove();return;}
      if(!tags.has(node.tagName)){node.replaceWith(...node.childNodes);return;}
      [...node.attributes].forEach(({name,value})=>{
        if(name==='style'){
          node.setAttribute('style',value.split(';').filter(item=>styles.has(item.split(':')[0].trim().toLowerCase())&&!/url|expression|@|[<>\\]/i.test(item)).join(';'));
        }else if(name==='href'&&node.tagName==='A'&&/^(https?:\/\/|mailto:|tel:)/i.test(value)){}
        else if(name==='src'&&node.tagName==='IMG'&&(/^(https:\/\/)/.test(value)||/^data:image\/(png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$/i.test(value))){}
        else if(!['alt','title','width','height','colspan','rowspan','cellpadding','cellspacing','border','align','valign','color','face','size'].includes(name))node.removeAttribute(name);
      });
    });
    return template.innerHTML;
  }
  const plain=html=>{const node=document.createElement('div');node.innerHTML=clean(html);node.querySelectorAll('br').forEach(br=>br.replaceWith('\n'));node.querySelectorAll('p,div,tr').forEach(block=>block.append('\n'));return (node.textContent||'').trim();};
  function mount(body){
    const toolbar=document.createElement('div');toolbar.className='mail-rich-toolbar';toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','邮件正文格式');
    const buttons=[['bold','加粗','B'],['italic','斜体','I'],['underline','下划线','U'],['insertUnorderedList','项目列表','• 列表'],['justifyLeft','左对齐','左对齐'],['justifyCenter','居中','居中'],['link','插入链接','链接'],['image','插入图片','图片'],['table','插入签名表格','表格'],['html','导入 HTML 签名','HTML 签名'],['knowledge','从知识库插入邮件模板或签名','知识库'],['removeFormat','清除文字格式','清除格式']];
    toolbar.innerHTML=buttons.map(([cmd,title,text])=>`<button type="button" data-rich-command="${cmd}" title="${title}" aria-label="${title}">${text}</button>`).join('')+'<label class="mail-rich-color" title="文字颜色">颜色<input type="color" value="#263248" aria-label="文字颜色"></label><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-rich-image hidden>';
    body.before(toolbar);body.classList.add('mail-rich-body');body.contentEditable='true';body.setAttribute('role','textbox');body.setAttribute('aria-label','邮件正文');body.setAttribute('aria-multiline','true');body.dataset.placeholder='编写邮件正文，或直接粘贴带图片与排版的签名…';
    let range=null,revision=0;
    const remember=()=>{const selection=getSelection();if(selection.rangeCount&&body.contains(selection.anchorNode))range=selection.getRangeAt(0).cloneRange();};
    body.addEventListener('keyup',remember);body.addEventListener('mouseup',remember);body.addEventListener('input',remember);
    const restore=()=>{body.focus();const selection=getSelection();if(range&&body.contains(range.commonAncestorContainer)){selection.removeAllRanges();selection.addRange(range);}else if(!body.contains(selection.anchorNode)){const end=document.createRange();end.selectNodeContents(body);end.collapse(false);selection.removeAllRanges();selection.addRange(end);}};
    const changed=()=>{body.dispatchEvent(new Event('input',{bubbles:true}));remember();};
    const insert=html=>{if(!body.isConnected||body.contentEditable!=='true')return;restore();document.execCommand('insertHTML',false,clean(html));changed();};
    const imageFile=async file=>{
      const expected=revision;
      if(body.contentEditable!=='true')return;
      if(!/^image\/(png|jpeg|gif|webp)$/.test(file.type)||file.size>1024*1024){alert('请选择不超过 1 MB 的 PNG、JPG、GIF 或 WebP 图片。');return;}
      if(body.innerHTML.length+file.size*1.4>2800000){alert('正文图片总量过大，请压缩图片后添加。');return;}
      const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
      if(expected===revision&&body.isConnected&&body.contentEditable==='true')insert(`<img src="${data}" alt="${escape(file.name||'图片')}" style="max-width:100%;height:auto" width="${Math.min(480,body.clientWidth-30)}">`);
    };
    toolbar.addEventListener('mousedown',event=>{if(event.target.closest('button'))event.preventDefault();});
    toolbar.addEventListener('click',event=>{
      const cmd=event.target.closest('[data-rich-command]')?.dataset.richCommand;if(!cmd||body.contentEditable!=='true')return;
      if(cmd==='image'){toolbar.querySelector('[data-rich-image]').click();return;}
      if(cmd==='knowledge'){
        const project=Number(localStorage.getItem('tophoo-global-selected-project'));
        if(!project)return alert('请先选择项目。');
        const dialog=document.createElement('dialog');dialog.className='mail-html-dialog knowledge-mail-picker';dialog.innerHTML='<h3>从知识库插入</h3><input type="search" placeholder="搜索邮件模板或签名" aria-label="搜索知识库邮件内容"><p role="status" data-picker-status>正在读取知识库…</p><select size="5" aria-label="选择知识条目" data-picker-list></select><div class="mail-rich-preview" data-picker-preview></div><footer><button type="button" data-picker-cancel>取消</button><button type="button" data-picker-insert disabled>插入正文</button></footer>';
        document.body.append(dialog);dialog.showModal();dialog.addEventListener('keydown',event=>event.stopPropagation());dialog.addEventListener('close',()=>dialog.remove());dialog.querySelector('[data-picker-cancel]').onclick=()=>dialog.close();
        const list=dialog.querySelector('[data-picker-list]'),preview=dialog.querySelector('[data-picker-preview]'),submit=dialog.querySelector('[data-picker-insert]'),status=dialog.querySelector('[data-picker-status]');let entries=[];
        const markup=item=>item.content_format==='email'&&item.content_html?clean(item.content_html):'<p>'+escape(item.content||'').replace(/\n/g,'<br>')+'</p>';
        const show=()=>{const item=entries.find(item=>String(item.id)===list.value);preview.innerHTML=item?markup(item):'';submit.disabled=!item;};
        const render=()=>{const key=dialog.querySelector('input').value.trim().toLowerCase();const matches=entries.filter(item=>(item.title+' '+item.content).toLowerCase().includes(key));list.innerHTML=matches.map(item=>`<option value="${item.id}">${escape(item.title)}${item.content_format==='email'?' · 富文本':' · Markdown'}</option>`).join('');if(matches.length)list.value=String(matches[0].id);status.textContent=matches.length+' 条内容；图文签名请在知识库选择“富文本”格式保存。';show();};
        dialog.querySelector('input').oninput=render;list.onchange=show;
        submit.onclick=()=>{if(project!==Number(localStorage.getItem('tophoo-global-selected-project')))return alert('项目已切换，请重新选择。');const item=entries.find(item=>String(item.id)===list.value);if(item){dialog.close();insert(markup(item));}};
        fetch(`/api/communication-scripts/projects/${project}`,{headers:window.tophooAuth?.headers?.()||{}}).then(async response=>{const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'无法读取知识库。');if(!dialog.isConnected)return;entries=data.scripts||[];render();}).catch(error=>{status.textContent=error.message;});return;
      }
      if(cmd==='html'){
        const dialog=document.createElement('dialog');dialog.className='mail-html-dialog';dialog.innerHTML='<h3>导入 HTML 签名</h3><p>粘贴签名的 HTML 代码，插入到正文光标处。也可直接从邮件中复制签名并粘贴到正文。</p><textarea aria-label="签名 HTML 代码" placeholder="<table>…</table>"></textarea><footer><button type="button" data-cancel>取消</button><button type="button" data-insert>插入签名</button></footer>';document.body.append(dialog);dialog.showModal();dialog.addEventListener('keydown',event=>event.stopPropagation());
        dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>dialog.remove());dialog.querySelector('[data-insert]').onclick=()=>{const value=dialog.querySelector('textarea').value;if(value.length>2800000)return alert('签名内容过大，请压缩图片。');dialog.close();insert(value);};return;
      }
      if(cmd==='link'){const url=prompt('请输入链接地址（https://、mailto: 或 tel:）');if(!url)return;if(!/^(https?:\/\/|mailto:|tel:)/i.test(url))return alert('请输入有效链接。');restore();if(getSelection().isCollapsed)insert(`<a href="${escape(url)}">${escape(url)}</a>`);else{document.execCommand('createLink',false,url);changed();}return;}
      if(cmd==='table'){insert('<table cellpadding="8" cellspacing="0" style="border-collapse:collapse"><tbody><tr><td style="vertical-align:top;border-right:1px solid #dce2eb">公司标识</td><td style="vertical-align:top"><strong>您的姓名 / 职位</strong><br>公司名称<br>电话 · 邮箱 · 网站</td></tr></tbody></table><p><br></p>');return;}
      restore();document.execCommand(cmd,false,null);changed();
    });
    toolbar.querySelector('[data-rich-image]').onchange=async event=>{for(const file of event.target.files)await imageFile(file);event.target.value='';};
    toolbar.querySelector('input[type=color]').oninput=event=>{restore();document.execCommand('foreColor',false,event.target.value);changed();};
    body.addEventListener('paste',event=>{
      if(body.contentEditable!=='true')return;event.preventDefault();const data=event.clipboardData;
      const html=data.getData('text/html');if(html){insert(html);return;}
      const files=[...data.files].filter(file=>file.type.startsWith('image/'));if(files.length){files.forEach(imageFile);return;}
      insert(escape(data.getData('text/plain')).replace(/\r?\n/g,'<br>'));
    });
    body.addEventListener('dragover',event=>event.preventDefault());
    body.addEventListener('drop',event=>{event.preventDefault();if(body.contentEditable==='true')[...event.dataTransfer.files].forEach(imageFile);});
    body.addEventListener('click',event=>{if(event.target.closest('a'))event.preventDefault();});
    return {insert, set:(html,text)=>{revision++;body.innerHTML=html?clean(html):escape(text||'').replace(/\n/g,'<br>');range=null;},get:()=>({content:body.innerText.trim()||(body.querySelector('img')?'[图片]':''),content_html:clean(body.innerHTML)}),lock:locked=>{body.contentEditable=String(!locked);body.setAttribute('aria-readonly',String(locked));toolbar.querySelectorAll('button,input').forEach(node=>node.disabled=locked);}};
  }
  window.TophooRichMail={mount,clean,plain,escape};
})();
