(() => {
  const rows = document.querySelector('#admin-user-rows'), feedback = document.querySelector('#admin-user-message');
  const currentAdminId = Number(document.querySelector('.admin-layout').dataset.currentAdminId);
  const dialog = document.querySelector('#user-editor-dialog'), form = document.querySelector('#user-editor-form');
  const search = document.querySelector('#user-search'), status = document.querySelector('#user-status');
  const message = document.querySelector('#user-editor-message'), create = document.querySelector('#open-create-user');
  let users = [], plans = [], editing = null, saving = false, baseline = '', opener;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const field = name => form.elements.namedItem(name);
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, headers:{'Content-Type':'application/json',...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map(x => x.msg).join('；') : '请求失败，请稍后重试。');
    return data;
  }
  function notify(text, success = false) { feedback.textContent = text; feedback.dataset.success = String(success); }
  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    const shown = users.filter(user => (!query || [user.display_name,user.email,user.phone,user.wechat_id].some(x => String(x || '').toLocaleLowerCase().includes(query))) && (status.value === 'all' || user.is_active === (status.value === 'active')));
    document.querySelector('#user-total').textContent = `显示 ${shown.length} / ${users.length} 位用户`;
    rows.innerHTML = shown.length ? shown.map(user => `<tr>
      <td data-label="用户"><div class="admin-user-name"><strong>${esc(user.display_name)}</strong><small>${esc(user.email)}</small><span>${user.is_admin ? '<span class="admin-role">管理员</span>' : ''}${user.id === currentAdminId ? '<span class="admin-self-note">当前账号</span>' : ''}</span></div></td>
      <td data-label="联系方式"><div class="admin-contact"><span>${esc(user.phone || '未填写手机号')}</span><small>微信：${esc(user.wechat_id || '未填写')}</small></div></td>
      <td data-label="工作区授权">${esc(user.plan?.name || '无已配置授权')}</td><td data-label="已参与项目">${Number(user.project_count) || 0} 个</td>
      <td data-label="状态"><span class="admin-status ${user.is_active ? '' : 'off'}">${user.is_active ? '启用' : '已停用'}</span></td>
      <td data-label="操作"><div class="admin-actions"><button type="button" class="admin-action" data-edit="${user.id}">编辑</button><button type="button" class="admin-action" data-password="${user.id}">修改密码</button>${user.id === currentAdminId ? '' : `<button type="button" class="admin-action" data-toggle="${user.id}">${user.is_active ? '停用' : '启用'}</button><button type="button" class="admin-action admin-delete-action" data-delete="${user.id}">删除</button>`}</div></td></tr>`).join('') : '<tr><td colspan="6" class="admin-empty">没有符合条件的用户</td></tr>';
  }
  function snapshot() { return JSON.stringify(Object.fromEntries(new FormData(form))); }
  function closeEditor() {
    if (saving) return;
    if (snapshot() !== baseline && !confirm('修改尚未保存，确定放弃修改吗？')) return;
    dialog.close(); opener?.focus();
  }
  function openEditor(user, button) {
    editing = user; opener = button; form.reset(); message.textContent = '';
    document.querySelector('#user-editor-title').textContent = user ? '编辑用户' : '新增用户';
    document.querySelector('#user-editor-intro').textContent = user ? '更新基本资料和账号设置。' : '创建登录账号，并分配其工作区授权。';
    form.querySelector('[type=submit]').textContent = user ? '保存修改' : '创建用户';
    form.querySelectorAll('[data-create-only]').forEach(el => { el.hidden = !!user; });
    form.querySelectorAll('[data-edit-only]').forEach(el => { el.hidden = !user; });
    field('password').disabled = !!user; field('password').required = !user;
    for (const key of ['display_name','email','phone','wechat_id']) field(key).value = user?.[key] || '';
    const options = plans.filter(p => p.is_active);
    const current = user?.plan;
    if (current && !options.some(p => p.code === current.code)) options.unshift({...current,name:current.name + '（已停用）',is_active:false});
    field('plan_code').innerHTML = (user && !current ? '<option value="">无已配置授权</option>' : '') + options.map(p => `<option value="${esc(p.code)}" ${!p.is_active ? 'disabled' : ''}>${esc(p.name)}</option>`).join('');
    if (current) field('plan_code').value = current.code;
    field('plan_code').required = !user;
    field('is_active').value = String(user?.is_active ?? true); field('is_active').disabled = !user || user.id === currentAdminId;
    form.querySelector('[data-self-note]').hidden = user?.id !== currentAdminId;
    baseline = snapshot(); dialog.showModal(); field('display_name').focus();
  }
  rows.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    const id = Number(button.dataset.password || button.dataset.edit || button.dataset.toggle || button.dataset.delete), user = users.find(x => x.id === id);
    if (!user) return;
    if (button.hasAttribute('data-edit')) return openEditor(user, button);
    if (button.hasAttribute('data-password')) return openPassword(user, button);
    if (button.hasAttribute('data-delete') && !confirm(`确定要删除用户“${user.display_name}”吗？\n\n这会永久删除该用户拥有的工作区、项目及相关资料，无法恢复。`)) return;
    button.disabled = true;
    try {
      if (button.hasAttribute('data-delete')) {
        const result = await request(`/api/admin/users/${id}`, {method:'DELETE'});
        users = users.filter(x => x.id !== id); notify(result.message || '用户已删除。',true);
      } else {
        const result = await request(`/api/admin/users/${id}`, {method:'PATCH',body:JSON.stringify({is_active:!user.is_active})});
        users = users.map(x => x.id === id ? result : x); notify(result.is_active ? '用户已启用。' : '用户已停用。',true);
      }
      render();
    } catch (error) { notify(error.message); button.disabled = false; }
  });
  const passwordDialog = document.querySelector('#user-password-dialog'), passwordForm = document.querySelector('#user-password-form');
  const passwordMessage = document.querySelector('#user-password-message');
  let passwordUser = null, passwordSaving = false, passwordOpener;
  function openPassword(user, button) {
    passwordUser = user; passwordOpener = button; passwordForm.reset(); passwordMessage.textContent = '';
    document.querySelector('#user-password-account').textContent = `${user.display_name} · ${user.email}`;
    passwordDialog.showModal(); passwordForm.elements.new_password.focus();
  }
  function closePassword() {
    if (passwordSaving) return;
    passwordForm.reset(); passwordMessage.textContent = '';
    passwordDialog.close();
  }
  passwordDialog.addEventListener('close', () => {
    passwordForm.reset(); passwordMessage.textContent = ''; passwordUser = null; passwordOpener?.focus();
  });
  passwordDialog.addEventListener('cancel', event => { event.preventDefault(); closePassword(); });
  passwordForm.querySelectorAll('[data-close-password]').forEach(button => { button.onclick = closePassword; });
  passwordForm.addEventListener('submit', async event => {
    event.preventDefault(); if (passwordSaving || !passwordUser) return;
    const password = passwordForm.elements.new_password.value;
    if (!password.trim()) { passwordMessage.textContent = '密码不能全部为空格。'; return; }
    if (password !== passwordForm.elements.confirm_password.value) {
      passwordMessage.textContent = '两次输入的密码不一致，请重新确认。'; passwordForm.elements.confirm_password.focus(); return;
    }
    const controls = Array.from(passwordForm.querySelectorAll('input,button'));
    passwordSaving = true; controls.forEach(x => { x.disabled = true; }); passwordMessage.textContent = '正在保存…';
    try {
      const result = await request(`/api/admin/users/${passwordUser.id}/password`, {method:'PATCH',body:JSON.stringify({new_password:password})});
      passwordForm.reset(); passwordDialog.close(); notify(result.message, true);
    } catch (error) { passwordMessage.textContent = error.message; }
    finally { passwordSaving = false; controls.forEach(x => { x.disabled = false; }); }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (saving) return;
    if (!field('display_name').value.trim()) { message.textContent = '昵称不能为空。'; field('display_name').focus(); return; }
    const payload = {display_name:field('display_name').value.trim(),email:field('email').value.trim(),phone:field('phone').value.trim() || null,wechat_id:field('wechat_id').value.trim() || null};
    if (editing) {
      if (editing.id !== currentAdminId) payload.is_active = field('is_active').value === 'true';
      if (field('plan_code').value && field('plan_code').value !== editing.plan?.code) payload.plan_code = field('plan_code').value;
    } else { payload.password = field('password').value; payload.plan_code = field('plan_code').value; }
    const controls = Array.from(form.querySelectorAll('input,select,button')), disabled = controls.map(x => x.disabled);
    saving = true; message.textContent = '正在保存…'; controls.forEach(x => { x.disabled = true; });
    try {
      const result = await request(editing ? `/api/admin/users/${editing.id}` : '/api/admin/users', {method:editing ? 'PATCH' : 'POST',body:JSON.stringify(payload)});
      users = editing ? users.map(x => x.id === result.id ? result : x) : [result,...users];
      dialog.close(); render(); notify(editing ? '用户资料已更新。' : '用户已创建。',true); opener?.focus();
    } catch (error) { message.textContent = error.message; }
    finally { controls.forEach((x,i) => { x.disabled = disabled[i]; }); saving = false; }
  });
  form.querySelectorAll('[data-close-editor]').forEach(button => { button.onclick = closeEditor; });
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
  create.onclick = () => openEditor(null, create);
  search.addEventListener('input', render); status.addEventListener('change', render);
  Promise.all([request('/api/admin/users'), request('/api/admin/plans')]).then(([list,data]) => {
    users = list; plans = data.plans || []; render(); create.disabled = !plans.some(p => p.is_active);
  }).catch(error => { rows.innerHTML = `<tr><td colspan="6" class="admin-empty">${esc(error.message)}</td></tr>`; notify(error.message); });
})();
