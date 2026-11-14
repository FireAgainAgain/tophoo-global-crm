(() => {
  const page = document.querySelector('[data-ai-config]');
  if (!page) return;
  const q = selector => page.querySelector(selector), dialog = q('[data-ai-editor]'), form = q('[data-ai-form]');
  const field = name => form.elements.namedItem(name);
  const projectId = () => Number(localStorage.getItem('tophoo-global-selected-project')) || 0;
  const headers = () => window.tophooAuth?.headers?.() || {};
  const endpoint = id => `/api/ai-config/projects/${id}`;
  const state = {models:[],features:[],providers:[],editingId:null,canManage:false,busy:false,generation:0,loadVersion:0,loadedProject:0,editorProject:0,editorIdentity:'',verificationToken:null,testedConnection:null,baseline:''};
  const toast = document.createElement('div'); toast.className = 'ai-notice'; toast.hidden = true; toast.setAttribute('role','status'); document.body.append(toast);
  let toastTimer;
  function notice(message, failed = false) { clearTimeout(toastTimer); toast.textContent=message; toast.classList.toggle('failed',failed); toast.hidden=!message; toastTimer=setTimeout(()=>{toast.hidden=true;},failed?7000:3200); }
  const node = (tag,className,text) => { const element=document.createElement(tag); element.className=className || ''; if(text!==undefined)element.textContent=text; return element; };
  async function request(path,options={}) {
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{...headers(),'Content-Type':'application/json',...(options.headers || {})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(Array.isArray(data.detail)?data.detail.map(item=>item.msg).join('；'):typeof data.detail==='string'?data.detail:'请求失败，请重试。');
    return data;
  }
  function projectName() { return document.querySelector('#sidebar-current-project-name')?.textContent?.trim() || `项目 ${projectId()}`; }
  function status(kind,message) { const badge=q('[data-ai-test-badge]'); badge.className='ai-badge '+kind; badge.textContent=kind==='success'?'连接测试通过':kind==='failed'?'连接测试失败':'待测试'; q('[data-ai-test-message]').textContent=message; }
  const payload = () => ({name:field('name').value.trim(),provider:field('provider').value,protocol:'openai-compatible',model:field('model').value.trim(),base_url:field('base_url').value.trim(),api_key:field('api_key').value.trim() || null,notes:field('notes').value.trim(),temperature:Number(field('temperature').value),max_tokens:Number(field('max_tokens').value),request_timeout_seconds:Number(field('request_timeout_seconds').value),verification_token:state.verificationToken});
  const connectionValue = () => JSON.stringify(['model','base_url','api_key','temperature','max_tokens','request_timeout_seconds'].map(name=>field(name).value.trim()));
  const editorValue = () => JSON.stringify(payload());
  const dirty = () => dialog.open && state.baseline!==editorValue();
  function canLeave() { if(state.busy){notice('正在处理，请稍候。');return false;} return !dirty() || confirm('有未保存的 AI 连接修改，确定放弃吗？'); }
  function close(force=false) { if(!force&&!canLeave())return; state.generation++; dialog.close(); state.editingId=null;state.baseline='';state.busy=false;state.verificationToken=null;state.testedConnection=null; }
  function updateActions() { q('[data-ai-save]').textContent=state.testedConnection===connectionValue()?'保存连接':'测试并保存'; }
  function busy(value) { state.busy=value;form.querySelectorAll('input,textarea,select,button').forEach(control=>{control.disabled=value;}); if(!value){q('[data-ai-test]').textContent='仅测试';updateActions();} }
  function error(message) { const element=q('[data-ai-editor-error]');element.textContent=message; element.hidden=!message; if(message)element.scrollIntoView({block:'nearest'}); }
  function validate() {
    field('api_key').setCustomValidity('');
    if(!field('api_key').value.trim()&&!state.models.find(item=>item.id===state.editingId)?.api_key_masked)field('api_key').setCustomValidity('请填写 API Key。');
    if([...form.querySelectorAll('[data-ai-advanced] input')].some(input=>!input.checkValidity()))q('[data-ai-advanced]').open=true;
    if(!field('name').value.trim())field('name').setCustomValidity('请填写连接名称。');else field('name').setCustomValidity('');
    if(!field('model').value.trim())field('model').setCustomValidity('请填写模型 ID。');else field('model').setCustomValidity('');
    return form.reportValidity();
  }
  function refreshEndpoint() { q('[data-ai-endpoint-summary]').textContent=field('base_url').value || '请在高级设置中填写'; }
  function inferProvider(model) {
    if(!model)return 'qwen';
    try { const host=new URL(model.base_url).hostname; const preset=state.providers.find(item=>item.base_url&&new URL(item.base_url).hostname===host); return preset?.id || (model.provider==='custom'?'custom':state.providers.some(item=>item.id===model.provider)?model.provider:'custom'); }catch{return 'custom';}
  }
  function providerChanged() {
    const preset=state.providers.find(item=>item.id===field('provider').value);
    field('base_url').value=preset?.base_url || '';field('model').placeholder=preset?.model?`例如：${preset.model}（以控制台为准）`:'填写实际模型 ID';
    if(!field('name').value.trim())field('name').value=`${preset?.name || '自定义'}连接`;
    if(field('provider').value==='custom')q('[data-ai-advanced]').open=true;
    refreshEndpoint(); invalidateTest();
  }
  function invalidateTest() { state.verificationToken=null;state.testedConnection=null;status('','连接参数已修改，请重新测试。');updateActions(); }
  function open(id=null) {
    if(!state.canManage || state.loadedProject!==projectId())return;
    state.editingId=id;state.generation++;state.editorProject=projectId();state.editorIdentity=JSON.stringify(headers());state.verificationToken=null;state.testedConnection=null;
    const model=state.models.find(item=>item.id===id);
    form.reset();busy(false);error('');form.querySelectorAll('input').forEach(input=>input.setCustomValidity(''));q('[data-ai-advanced]').open=false;
    field('provider').replaceChildren(...state.providers.map(item=>{const option=node('option','',item.name);option.value=item.id;return option;}));
    field('provider').value=inferProvider(model);
    ['name','model','base_url','temperature','max_tokens','request_timeout_seconds','notes'].forEach(key=>{if(model)field(key).value=model[key]??'';});
    field('api_key').type='password';field('api_key').value='';field('api_key').placeholder=model?.api_key_masked || '填写服务商生成的 API Key';
    q('[data-ai-reveal]').textContent='显示';q('[data-ai-key-hint]').textContent=model?.api_key_masked?`已保存 ${model.api_key_masked}，留空保留原密钥。`:'密钥保存后不回显。';
    q('[data-ai-editor-title]').textContent=model?'编辑连接':'添加连接';q('[data-ai-editor-project]').textContent=`当前项目：${projectName()}`;
    if(!model)providerChanged();else refreshEndpoint();
    if(model?.last_test_status==='success')state.testedConnection=connectionValue();
    status(model?.last_test_status || '',model?.last_test_message || '仅测试不保存。测试并保存将完成连接检查后保存为可用连接。');
    updateActions();state.baseline=editorValue();dialog.showModal();field('name').focus();
  }
  function render() {
    q('[data-ai-new]').disabled=!state.canManage;
    const used=state.features.filter(item=>item.model_configuration_id).length;
    q('[data-ai-usage-summary]').textContent=`已保存 ${state.models.length} 个连接 · 连接测试通过 ${state.models.filter(item=>item.last_test_status==='success').length} 个 · 已绑定 ${used} 个业务功能`;
    q('[data-ai-integration-note]').hidden=state.features.length>0;q('[data-ai-binding-section]').hidden=!state.features.length;
    const list=q('[data-ai-model-list]');list.replaceChildren();
    if(!state.models.length)list.append(node('div','ai-empty','暂无个人连接，点击“添加连接”保存你自己的 Key。旧项目共享连接不再使用。'));
    state.models.forEach(model=>{
      const card=node('article','ai-model'),top=node('div','ai-model-top');
      const title=node('div');title.append(node('h3','',model.name),node('p','ai-model-id',`${state.providers.find(item=>item.id===inferProvider(model))?.name || '自定义'} · ${model.model}`));
      top.append(title,node('span','ai-badge '+(model.enabled&&model.last_test_status==='success'?'success':''),!model.enabled?'草稿 / 已停用':model.last_test_status==='success'?'允许功能使用':'需测试后使用'));
      const meta=node('div','ai-model-meta');meta.append(node('span','ai-badge '+model.last_test_status,model.last_test_status==='success'?'连接测试通过':model.last_test_status==='failed'?'连接测试失败':'连接待测试'));
      const bound=(model.features || []).map(key=>state.features.find(item=>item.key===key)?.name || key);
      meta.append(node('span','ai-usage-label',bound.length?'用于：'+bound.join('、'):'尚未用于业务功能'));
      const footer=node('div','ai-model-footer');footer.append(node('small','',model.last_tested_at?'最近测试 '+new Date(model.last_tested_at).toLocaleString():model.last_test_status==='success'?'连接已通过测试':'尚未测试连接'));
      const actions=node('div','ai-model-actions'),edit=node('button','','编辑 / 测试'),remove=node('button','danger','删除');
      edit.type=remove.type='button';edit.disabled=!state.canManage;remove.disabled=!state.canManage||Boolean(bound.length);edit.onclick=()=>open(model.id);
      remove.title=bound.length?'先解除功能绑定再删除':'删除连接';
      remove.onclick=async()=>{
        if(!confirm(`删除连接“${model.name}”？`))return;
        const id=projectId(),identity=JSON.stringify(headers());remove.disabled=true;
        try { await request(endpoint(id)+'/models/'+model.id,{method:'DELETE'});if(id!==projectId()||identity!==JSON.stringify(headers()))return;state.models=state.models.filter(item=>item.id!==model.id);render();notice('连接已删除。'); }
        catch(err){if(id===projectId())notice(err.message,true);}finally{if(remove.isConnected)remove.disabled=!state.canManage||Boolean(bound.length);}
      };
      actions.append(edit,remove);footer.append(actions);card.append(top,node('div','ai-model-url',model.base_url),meta,footer);
      if(model.notes)card.append(node('p','ai-model-notes',model.notes));list.append(card);
    });
    const features=q('[data-ai-features]');features.replaceChildren();
    state.features.forEach(feature=>{
      const row=node('div','ai-feature-row'),info=node('div');info.append(node('b','',feature.name),node('p','',feature.description));
      const select=node('select');select.setAttribute('aria-label',feature.name+'使用的连接');select.disabled=!state.canManage;
      const empty=node('option','','暂不绑定');empty.value='';select.append(empty);
      state.models.forEach(model=>{const usable=model.enabled&&model.last_test_status==='success';if(!usable&&model.id!==feature.model_configuration_id)return;const option=node('option','',model.name+(usable?'':'（需测试或启用）'));option.value=model.id;option.selected=model.id===feature.model_configuration_id;select.append(option);});
      const button=node('button','ai-button','保存绑定');button.type='button';button.disabled=!state.canManage;
      button.onclick=async()=>{const id=projectId(),identity=JSON.stringify(headers());button.disabled=select.disabled=true;try{await request(endpoint(id)+'/features/'+feature.key,{method:'PUT',body:JSON.stringify({model_configuration_id:select.value?Number(select.value):null})});if(id!==projectId()||identity!==JSON.stringify(headers()))return;await load();notice('功能绑定已保存。');}catch(err){if(id===projectId())notice(err.message,true);}finally{if(button.isConnected)button.disabled=select.disabled=!state.canManage;}};
      row.append(info,select,button);features.append(row);
    });
  }
  async function load() {
    if(dialog.open)return;
    const id=projectId(),version=++state.loadVersion,identity=JSON.stringify(headers());state.canManage=false;state.loadedProject=0;q('[data-ai-new]').disabled=true;q('[data-ai-refresh]').disabled=true;
    q('[data-ai-project-name]').textContent=id?projectName():'请先选择项目';q('[data-ai-usage-summary]').textContent=id?'正在加载我的个人连接…':'请先选择项目。';q('[data-ai-binding-section]').hidden=true;q('[data-ai-integration-note]').hidden=true;
    q('[data-ai-model-list]').replaceChildren(node('div','ai-empty',id?'正在加载…':'请先选择项目。'));state.models=[];state.features=[];
    if(!id){q('[data-ai-refresh]').disabled=false;return;}
    try {
      const [data,providers]=await Promise.all([request(endpoint(id)),state.providers.length?Promise.resolve({items:state.providers}):request('/api/ai-config/providers')]);
      if(id!==projectId()||version!==state.loadVersion||identity!==JSON.stringify(headers()))return;
      state.models=data.models || [];state.features=data.features || [];state.providers=providers.items || [];state.canManage=Boolean(data.can_manage);state.loadedProject=id;render();
    }catch(err){if(id!==projectId()||version!==state.loadVersion||identity!==JSON.stringify(headers()))return;q('[data-ai-usage-summary]').textContent='连接加载失败';const empty=node('div','ai-empty',err.message+' '),retry=node('button','ai-button','重新加载');retry.type='button';retry.onclick=load;empty.append(retry);q('[data-ai-model-list]').replaceChildren(empty);}
    finally{if(version===state.loadVersion)q('[data-ai-refresh]').disabled=false;}
  }
  const currentEditor = generation => generation===state.generation&&state.editorProject===projectId()&&state.editorIdentity===JSON.stringify(headers())&&dialog.open;
  async function operate(mode) {
    if(state.busy||!validate())return;
    const generation=state.generation,id=state.editingId,project=state.editorProject;
    if(!currentEditor(generation))return error('项目或登录状态已切换，请重新打开连接。');
    if(mode==='draft'&&state.models.find(item=>item.id===id)?.features?.length&&!confirm('保存草稿将停用此连接，已绑定功能将暂时无法使用。继续吗？'))return;
    error('');busy(true);
    try {
      if(mode==='test'||(mode==='save'&&state.testedConnection!==connectionValue())) {
        state.verificationToken=null;state.testedConnection=null;status('','正在检查连接…');q('[data-ai-test]').textContent='测试中…';
        const result=await request(endpoint(project)+'/test-draft',{method:'POST',body:JSON.stringify({...payload(),enabled:false,model_configuration_id:id})});
        if(!currentEditor(generation))return;
        state.verificationToken=result.verification_token;state.testedConnection=connectionValue();status('success',result.message);
      }
      if(mode==='test')return;
      if(!currentEditor(generation))return;
      const data={...payload(),enabled:mode==='save'};
      const saved=await request(endpoint(project)+'/models'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(data)});
      if(!currentEditor(generation))return;
      state.models=[saved,...state.models.filter(item=>item.id!==saved.id)];close(true);render();notice(mode==='draft'?'草稿已保存，连接已停用。':'连接已保存；业务使用情况见列表。');
    }catch(err){if(currentEditor(generation)){error(err.message);if(!state.testedConnection)status('failed',err.message);}}
    finally{if(currentEditor(generation))busy(false);}
  }
  q('[data-ai-new]').onclick=()=>open();q('[data-ai-refresh]').onclick=load;
  q('[data-ai-test]').onclick=()=>operate('test');q('[data-ai-save-draft]').onclick=()=>operate('draft');form.onsubmit=event=>{event.preventDefault();operate('save');};
  q('[data-ai-reveal]').onclick=event=>{const input=field('api_key');input.type=input.type==='password'?'text':'password';event.target.textContent=input.type==='password'?'显示':'隐藏';};
  q('[data-ai-edit-endpoint]').onclick=()=>{q('[data-ai-advanced]').open=true;field('base_url').focus();};field('provider').onchange=providerChanged;
  form.addEventListener('input',event=>{error('');if(event.target.setCustomValidity)event.target.setCustomValidity('');if(['name','notes','provider'].includes(event.target.name))return;invalidateTest();if(event.target.name==='base_url')refreshEndpoint();});
  q('[data-ai-save]').addEventListener('click',()=>{if(!form.checkValidity())q('[data-ai-advanced]').open=true;});
  page.querySelectorAll('[data-ai-close]').forEach(button=>button.onclick=()=>close());dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  document.addEventListener('click',event=>{if(page.hidden||!event.target.closest('.global-nav-item,.crm-primary-item,.pm-project-row'))return;if(!canLeave()){event.preventDefault();event.stopImmediatePropagation();}else close(true);},true);
  document.addEventListener('keydown',event=>{if(!page.hidden&&dialog.open&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();operate('save');}});
  window.addEventListener('beforeunload',event=>{if(dirty()||state.busy){event.preventDefault();event.returnValue='';}});
  document.addEventListener('tophoo-ai-config-view',()=>{page.hidden=false;load();});window.addEventListener('tophoo-project-changed',()=>{close(true);state.loadVersion++;if(!page.hidden)load();});
})();
