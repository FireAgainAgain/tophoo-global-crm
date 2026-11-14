(() => {
  const root = document.querySelector("[data-crm-competitor-research]");
  if (!root) return;
  const list = root.querySelector("[data-competitor-list]");
  const detail = root.querySelector("[data-competitor-detail]");
  const count = root.querySelector("[data-competitor-count]");
  const search = root.querySelector("[data-competitor-search]");
  const add = root.querySelector("[data-add-competitor]");
  const exportAll = root.querySelector("[data-export-competitors]");
  const headers = () => window.tophooAuth?.headers?.() || {};
  const projectId = () => Number(localStorage.getItem("tophoo-global-selected-project")) || null;
  const esc = (value = "") => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  let items = [], selectedId = null, editing = false, noticeTimer = null, loadedProject = null, loadVersion = 0, pendingWrites = 0, editorTab = 'company';
  function notify(message, type = "success", duration = 2600) {
    let notice = root.querySelector("[data-competitor-notice]");
    if (!notice) {
      notice = document.createElement("div");
      notice.className = "competitor-notice";
      notice.dataset.competitorNotice = "";
      notice.setAttribute("role", "status");
      notice.setAttribute("aria-live", "polite");
      root.append(notice);
    }
    clearTimeout(noticeTimer);
    notice.textContent = message;
    notice.dataset.type = type;
    notice.hidden = false;
    requestAnimationFrame(() => notice.classList.add("is-visible"));
    if (duration) noticeTimer = setTimeout(() => { notice.classList.remove("is-visible"); setTimeout(() => { notice.hidden = true; }, 180); }, duration);
  }
  function setBusy(button, label) {
    if (!button) return () => {};
    const original = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return () => { button.disabled = false; button.textContent = original; };
  }

  async function request(url, options = {}) {
    const project = projectId(), auth = JSON.stringify(headers()), write = options.method && options.method !== 'GET';
    if (write && pendingWrites) throw new Error('上一项操作尚未完成，请稍候。');
    if (write) pendingWrites++;
    try {
      const response = await fetch(url, {...options, headers: {...headers(), ...(options.headers || {})}});
      const payload = await response.json().catch(() => ({}));
      if (project !== projectId() || auth !== JSON.stringify(headers())) throw new Error('项目或登录状态已切换，请在当前项目重新操作。');
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '请求失败，请稍后重试。');
      return payload;
    } finally { if (write) pendingWrites--; }
  }
  const selectionKey = () => 'tophoo-global-competitor-selection-' + projectId();
  const remember = () => sessionStorage.setItem(selectionKey(), String(selectedId || ''));
  const formKey = form => form.hasAttribute('data-website-edit-form') ? 'website-' + form.dataset.websiteId : form.hasAttribute('data-website-form') ? 'new-website' : form.hasAttribute('data-keyword-form') ? 'new-keyword' : 'company';
  const formValue = form => JSON.stringify(Object.fromEntries(new FormData(form)));
  const dirtyForms = () => Array.from(detail.querySelectorAll('form')).filter(form => form.dataset.baseline && formValue(form) !== form.dataset.baseline);
  function canLeave() {
    if (pendingWrites) { notify('正在保存，请稍候再切换。', 'info'); return false; }
    return !dirtyForms().length || confirm('有未保存的修改，确定放弃并离开吗？');
  }
  function renderPreserving(skip = '') {
    const scroll = detail.scrollTop, focusedForm = document.activeElement?.closest('form');
    const focusKey = focusedForm ? formKey(focusedForm) : '', focusName = document.activeElement?.name;
    const newWebsiteOpen = detail.querySelector('[data-website-form]')?.hidden === false;
    const drafts = dirtyForms().filter(form => formKey(form) !== skip).map(form => ({key:formKey(form), values:Object.fromEntries(new FormData(form)), baseline:form.dataset.baseline, hidden:form.hidden}));
    renderList(); renderDetail();
    detail.querySelectorAll('form').forEach(form => {
      const draft = drafts.find(value => value.key === formKey(form)); if (!draft) return;
      Object.entries(draft.values).forEach(([name,value]) => { const input = form.elements.namedItem(name); if (input) input.value = value; });
      form.dataset.baseline = draft.baseline;
      if (form.hasAttribute('data-website-edit-form') && !draft.hidden) showWebsiteEditor(form.dataset.websiteId);
    });
    if (newWebsiteOpen) { const newForm = detail.querySelector('[data-website-form]'); if (newForm) newForm.hidden = false; }
    updateEditStatus();
    detail.scrollTop = scroll;
    if (skip === 'new-website') detail.querySelector('[data-website-form] [name="url"]')?.focus({preventScroll:true});
    else if (skip === 'new-keyword') detail.querySelector('[data-keyword-form] [name="keyword"]')?.focus({preventScroll:true});
    else if (focusKey && focusName) { const form = Array.from(detail.querySelectorAll('form')).find(value => formKey(value) === focusKey); form?.elements.namedItem(focusName)?.focus({preventScroll:true}); }
  }
  function safeWebsite(url) { try { const value = new URL(url); return ['http:', 'https:'].includes(value.protocol) ? esc(value.href) : '#'; } catch { return '#'; } }
  const selected = () => items.find((item) => item.id === selectedId);
  const empty = () => { root.classList.remove('is-editing'); detail.innerHTML = '<div class="competitor-empty"><span>◈</span><strong>开始建立竞品情报库</strong><small>选择已有竞品，或新增第一家竞品公司。</small></div>'; };
  function filters() {
    const key = search.value.trim().toLowerCase();
    return key ? items.filter((item) => `${item.name} ${item.country} ${item.notes} ${(item.websites || []).map(value => value.name + " " + value.url).join(" ")} ${(item.keywords || []).map(value => value.keyword + " " + value.language + " " + value.category).join(" ")}`.toLowerCase().includes(key)) : items;
  }
  function renderList() {
    const scrollTop = list.scrollTop, visible = filters();
    count.textContent = `${visible.length} 家`;
    exportAll.disabled = items.length === 0;
    list.innerHTML = visible.length ? visible.map((item) => { const position = items.findIndex((value) => value.id === item.id); return `<div class="competitor-list-row"><button class="competitor-list-item ${item.id === selectedId ? "is-active" : ""}" type="button" data-select-competitor="${item.id}" aria-pressed="${item.id === selectedId}" title="${esc(item.name)}"><span class="competitor-list-avatar">${esc(item.name.trim().charAt(0).toUpperCase())}</span><span class="competitor-list-copy"><strong>${esc(item.name)}</strong><small>${esc(item.country || "国家/地区未填写")}</small><span class="competitor-list-tags"><i>${item.websites.length} 个网站</i><i>${item.keywords.length} 个关键词</i></span></span><span class="competitor-list-arrow">›</span></button><span class="competitor-order-tools"><button type="button" data-move-competitor="${item.id}" data-direction="up" ${position === 0 ? "disabled" : ""} title="上移竞品" aria-label="上移竞品">↑</button><button type="button" data-move-competitor="${item.id}" data-direction="down" ${position === items.length - 1 ? "disabled" : ""} title="下移竞品" aria-label="下移竞品">↓</button></span></div>`; }).join("") : '<div class="competitor-empty-list">还没有匹配的竞品资料。</div>';
    list.querySelectorAll("[data-select-competitor]").forEach((button) => button.onclick = () => { if (selectedId === Number(button.dataset.selectCompetitor)) return; if (!canLeave()) return; selectedId = Number(button.dataset.selectCompetitor); remember(); editing = false; renderList(); renderDetail(); detail.scrollTop = 0; list.querySelector(`[data-select-competitor="${selectedId}"]`)?.focus({preventScroll:true}); });
    list.scrollTop = scrollTop;
    list.querySelectorAll("[data-move-competitor]").forEach((button) => button.onclick = () => moveCompetitor(Number(button.dataset.moveCompetitor), button.dataset.direction, button));
  }
  async function moveCompetitor(id, direction, button) {
    const restore = setBusy(button, "…");
    notify("正在调整竞品顺序…", "loading", 0);
    try {
      items = await request(`/api/competitors/projects/${projectId()}/${id}/move`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({direction})});
      renderPreserving();
      notify("竞品顺序已更新。");
    } catch (error) { restore(); notify(error.message, "error"); }
  }
  async function exportCompetitors(button) {
    const exportProject = projectId(), exportAuth = JSON.stringify(headers());
    const restore = setBusy(button, "导出中…");
    notify("正在生成竞品档案 PDF…", "loading", 0);
    try {
      const response = await fetch(`/api/competitors/projects/${projectId()}/export/pdf`, {headers:headers()});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "PDF 导出失败，请稍后重试。"); }
      const blob = await response.blob();
      if (exportProject !== projectId() || exportAuth !== JSON.stringify(headers())) throw new Error("项目或登录状态已切换，已取消旧项目的下载。");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "竞品档案汇总.pdf";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("竞品档案汇总 PDF 已开始下载。");
    } catch (error) { notify(error.message, "error"); }
    finally { restore(); }
  }
  async function exportCompetitor(item, button) {
    const restore = setBusy(button, "导出中…");
    notify("正在生成竞品档案 PDF…", "loading", 0);
    try {
      const response = await fetch(`/api/competitors/projects/${projectId()}/${item.id}/export/pdf`, {headers:headers()});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "PDF 导出失败，请稍后重试。"); }
      const blob = await response.blob();
      if (exportProject !== projectId() || exportAuth !== JSON.stringify(headers())) throw new Error("项目或登录状态已切换，已取消旧项目的下载。");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${item.name.replace(/[\\/:*?"<>|]+/g, "_")}_竞品档案.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("竞品档案 PDF 已开始下载。");
    } catch (error) { notify(error.message, "error"); }
    finally { restore(); }
  }
  function baseForm(item = {}) {
    return `<form class="competitor-form" data-competitor-form data-id="${item.id || ""}"><label>公司名称<input name="name" required maxlength="220" value="${esc(item.name)}" placeholder="例如：Competitor Heat Inc."></label><label>国家 / 地区<input name="country" maxlength="100" value="${esc(item.country)}" placeholder="例如：United States"></label><label class="competitor-wide">调研备注<textarea name="notes" maxlength="12000" placeholder="记录竞争优势、价格策略或值得继续跟进的线索。">${esc(item.notes)}</textarea></label><div class="competitor-wide competitor-actions"><button type="submit">${item.id ? "保存公司资料" : "创建竞品"}</button><button type="button" class="competitor-secondary" data-cancel-competitor>取消</button>${item.id ? '<details class="competitor-danger-menu"><summary>更多操作</summary><button type="button" class="competitor-danger" data-delete-competitor>删除竞品</button></details>' : ""}</div></form>`;
  }
  function websites(item) {
    const rows = item.websites.map(value => `<article class="competitor-website-card" data-website-card="${value.id}">
      <div class="competitor-website-summary" data-website-summary><a href="${safeWebsite(value.url)}" target="_blank" rel="noopener noreferrer"><strong>${esc(value.name)}</strong><small>${esc(value.url)}</small></a><div><button type="button" class="competitor-secondary" data-open-website="${value.id}">编辑</button><button type="button" class="competitor-danger" data-delete-website="${value.id}" aria-label="删除${esc(value.name)}">删除</button></div></div>
      <form class="competitor-website-edit" data-website-edit-form data-website-id="${value.id}" hidden><label>网站名称<input name="name" required maxlength="160" value="${esc(value.name)}"></label><label>网址<input name="url" type="url" required maxlength="1000" value="${esc(value.url)}" placeholder="https://example.com"></label><div class="competitor-inline-actions"><button type="submit">保存这个网站</button><button type="button" class="competitor-secondary" data-cancel-website="${value.id}">取消</button></div></form>
    </article>`).join('');
    return `<section class="competitor-editor-section"><header class="competitor-editor-section-head"><div><h4>网站资料</h4><p>网站单独保存，不影响其他页签中的输入。</p></div><button type="button" data-open-new-website>＋ 添加网站</button></header>
    <form class="competitor-website-edit competitor-new-website" data-website-form hidden><label>网址<input name="url" type="url" required maxlength="1000" placeholder="输入域名或 https://example.com"></label><label>网站名称<input name="name" required maxlength="160" placeholder="例如：官方网站"></label><div class="competitor-inline-actions"><button type="submit">添加网站</button><button type="button" class="competitor-secondary" data-cancel-new-website>取消</button></div></form>
    <div class="competitor-website-list">${rows || '<div class="competitor-view-empty">还没有网站，点击上方“添加网站”开始整理。</div>'}</div></section>`;
  }
  function showWebsiteEditor(id) {
    const card = detail.querySelector(`[data-website-card="${id}"]`); if (!card) return;
    card.querySelector('[data-website-summary]').hidden = true; card.querySelector('form').hidden = false;
  }
  function updateEditStatus() {
    const status = detail.querySelector('[data-editor-save-status]'); if (!status) return;
    const count = dirtyForms().length;
    status.textContent = count ? count + ' 处待保存 · 各页签分别保存' : '暂无未保存修改';
    status.classList.toggle('is-dirty', !!count);
    detail.querySelectorAll('[data-editor-tab]').forEach(button => {
      const pane = detail.querySelector('[data-editor-pane="' + button.dataset.editorTab + '"]');
      button.classList.toggle('has-draft', Array.from(pane?.querySelectorAll('form') || []).some(form => form.dataset.baseline && formValue(form) !== form.dataset.baseline));
    });
  }
  function selectEditorTab(tab, focus = false) {
    editorTab = tab;
    detail.querySelectorAll('[data-editor-tab]').forEach(button => { const active = button.dataset.editorTab === tab; button.classList.toggle('is-active', active); button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
    detail.querySelectorAll('[data-editor-pane]').forEach(pane => pane.hidden = pane.dataset.editorPane !== tab);
    detail.scrollTop = 0;
    if (focus) detail.querySelector('[data-editor-tab="' + tab + '"]')?.focus({preventScroll:true});
  }
  function bindEditorTabs(item) {
    detail.querySelectorAll('[data-editor-tab]').forEach(button => {
      button.onclick = () => selectEditorTab(button.dataset.editorTab);
      button.onkeydown = event => {
        const tabs = ['company','websites','keywords'], index = tabs.indexOf(button.dataset.editorTab);
        let target; if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') target = (index + tabs.length - 1) % tabs.length;
        else if (event.key === 'Home') target = 0; else if (event.key === 'End') target = 2; else return;
        event.preventDefault(); selectEditorTab(tabs[target], true);
      };
    });
    detail.querySelectorAll('[data-open-website]').forEach(button => button.onclick = () => { showWebsiteEditor(button.dataset.openWebsite); detail.querySelector('[data-website-edit-form][data-website-id="' + button.dataset.openWebsite + '"] [name="name"]')?.focus(); });
    detail.querySelectorAll('[data-cancel-website]').forEach(button => button.onclick = () => {
      const card = button.closest('[data-website-card]'), form = card.querySelector('form');
      if (formValue(form) !== form.dataset.baseline && !confirm('放弃这个网站的未保存修改吗？')) return;
      form.reset(); form.hidden = true; card.querySelector('[data-website-summary]').hidden = false; updateEditStatus();
    });
    const newForm = detail.querySelector('[data-website-form]');
    detail.querySelector('[data-open-new-website]').onclick = () => { newForm.hidden = false; newForm.querySelector('[name="url"]').focus(); };
    detail.querySelector('[data-cancel-new-website]').onclick = () => { if (formValue(newForm) !== newForm.dataset.baseline && !confirm('放弃新增网站的输入吗？')) return; newForm.reset(); newForm.hidden = true; updateEditStatus(); };
    detail.querySelectorAll('[name="url"]').forEach(input => input.onblur = () => {
      const value = input.value.trim();
      if (value && !/^[a-z][a-z0-9+.-]*:/i.test(value)) input.value = 'https://' + value;
      const name = input.form.querySelector('[name="name"]'); if (name && !name.value.trim() && input.value) name.value = '官方网站';
      updateEditStatus();
    });
    selectEditorTab(editorTab); updateEditStatus();
  }
  function keywords(item) {
    const rows = item.keywords.length ? item.keywords.map((value) => `<div class="competitor-entry"><div><strong>${esc(value.keyword)}</strong><small>${esc(value.language || "未分类语言")}${value.category ? ` · ${esc(value.category)}` : ""}</small></div><button class="competitor-danger" type="button" data-delete-keyword="${value.id}">×</button></div>`).join("") : '<div class="competitor-empty-list">尚未添加关键词。</div>';
    return `<section class="competitor-section"><div class="competitor-section-head"><div><h4>竞品关键词</h4><p>添加后立即保存；语言和分类可选。Ctrl / ⌘ + S 添加。</p></div></div><form class="competitor-add-row competitor-keyword-add" data-keyword-form><label>关键词<input name="keyword" required maxlength="300" placeholder="industrial dry cooler"></label><label>语言<input name="language" maxlength="30" placeholder="English"></label><label>分类<input name="category" maxlength="80" placeholder="核心产品词"></label><button type="submit">添加关键词</button></form><div class="competitor-keyword-editor-list">${rows}</div></section>`;
  }
  function readonlySections(item) {
    const websiteRows = item.websites.length ? item.websites.map((value) => `<a class="competitor-view-website" href="${safeWebsite(value.url)}" target="_blank" rel="noopener noreferrer"><span>↗</span><div><strong>${esc(value.name)}</strong><small>${esc(value.url)}</small></div></a>`).join("") : '<div class="competitor-view-empty">暂无网站，点击编辑竞品后添加。</div>';
    const keywordRows = item.keywords.length ? item.keywords.map((value) => `<button type="button" class="competitor-view-keyword" data-copy-keyword="${value.id}" title="点击复制关键词"><strong>${esc(value.keyword)}</strong><small>${esc(value.language || "未标注语言")}${value.category ? ` · ${esc(value.category)}` : ""}</small></button>`).join("") : '<div class="competitor-view-empty">暂无关键词，点击编辑竞品后添加。</div>';
    return `${item.notes ? `<section class="competitor-profile-notes"><strong>调研备注</strong><p>${esc(item.notes)}</p></section>` : ''}<section class="competitor-view-section"><div class="competitor-section-head"><div><h4>竞品网站</h4><p>${item.websites.length} 个网站入口</p></div></div><div class="competitor-view-websites">${websiteRows}</div></section><section class="competitor-view-section"><div class="competitor-section-head"><div><h4>竞品关键词</h4><p>${item.keywords.length} 个关键词</p></div></div><div class="competitor-view-keywords">${keywordRows}</div></section>`;
  }
  function bindDetail(item) {
    root.classList.toggle('is-editing', editing);
    detail.querySelectorAll('form').forEach(form => { form.dataset.baseline = formValue(form); });
    detail.oninput = updateEditStatus;
    const form = detail.querySelector("[data-competitor-form]");
    form.onsubmit = async (event) => {
      event.preventDefault();
      const restore = setBusy(form.querySelector('[type="submit"]'), item.id ? "保存中…" : "创建中…");
      notify(item.id ? "正在保存竞品资料…" : "正在创建竞品…", "loading", 0);
      try {
        const result = await request(`/api/competitors/projects/${projectId()}${item.id ? `/${item.id}` : ""}`, {method: item.id ? "PUT" : "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(Object.fromEntries(new FormData(form)))});
        if (item.id) items = items.map((value) => value.id === item.id ? result : value); else { items.unshift(result); selectedId = result.id; }
        editing = true; search.value = ''; remember(); renderPreserving('company');
        notify(item.id ? "竞品资料已保存。" : "竞品已创建，可以继续补充网站和关键词。");
      } catch (error) { restore(); notify(error.message, "error"); }
    };
    detail.querySelector("[data-cancel-competitor]")?.addEventListener("click", () => { if (!canLeave()) return; editing = false; if (!item.id) selectedId = items[0]?.id || null; renderList(); selectedId ? renderDetail() : empty(); notify("已取消本次修改。", "info"); });
    detail.querySelector("[data-delete-competitor]")?.addEventListener("click", async (event) => {
      if (!confirm(`确认删除竞品「${item.name}」及其网站、关键词吗？`)) return;
      const restore = setBusy(event.currentTarget, "删除中…"); notify("正在删除竞品资料…", "loading", 0);
      try { await request(`/api/competitors/projects/${projectId()}/${item.id}`, {method:"DELETE"}); items = items.filter((value) => value.id !== item.id); selectedId = items[0]?.id || null; editing = false; renderList(); selectedId ? renderDetail() : empty(); notify("竞品资料已删除。"); } catch (error) { restore(); notify(error.message, "error"); }
    });
    detail.querySelector("[data-website-form]")?.addEventListener("submit", async (event) => {
      event.preventDefault(); const formValue = event.currentTarget; const restore = setBusy(formValue.querySelector('[type="submit"]'), "添加中…"); notify("正在添加竞品网站…", "loading", 0);
      try { const result = await request(`/api/competitors/projects/${projectId()}/${item.id}/websites`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(new FormData(formValue)))}); items = items.map((value) => value.id === item.id ? result : value); renderPreserving('new-website'); notify("竞品网站已添加。"); } catch (error) { restore(); notify(error.message, "error"); }
    });
    detail.querySelectorAll("[data-website-edit-form]").forEach((formValue) => formValue.addEventListener("submit", async (event) => {
      event.preventDefault(); const restore = setBusy(formValue.querySelector('[type="submit"]'), "保存中…"); notify("正在保存竞品网站…", "loading", 0);
      try { const result = await request(`/api/competitors/projects/${projectId()}/${item.id}/websites/${formValue.dataset.websiteId}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(new FormData(formValue)))}); items = items.map((value) => value.id === item.id ? result : value); renderPreserving('website-' + formValue.dataset.websiteId); notify("竞品网站已保存。"); } catch (error) { restore(); notify(error.message, "error"); }
    }));
    detail.querySelector("[data-keyword-form]")?.addEventListener("submit", async (event) => {
      event.preventDefault(); const formValue = event.currentTarget; const restore = setBusy(formValue.querySelector('[type="submit"]'), "添加中…"); notify("正在添加竞品关键词…", "loading", 0);
      try { const result = await request(`/api/competitors/projects/${projectId()}/${item.id}/keywords`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(new FormData(formValue)))}); items = items.map((value) => value.id === item.id ? result : value); renderPreserving('new-keyword'); notify("竞品关键词已添加。"); } catch (error) { restore(); notify(error.message, "error"); }
    });
    detail.querySelectorAll("[data-delete-website]").forEach((button) => button.onclick = async () => {
      if (!confirm("确认删除这个网站吗？")) return;
      const restore = setBusy(button, "…"); notify("正在删除竞品网站…", "loading", 0);
      try { await request(`/api/competitors/projects/${projectId()}/${item.id}/websites/${button.dataset.deleteWebsite}`, {method:"DELETE"}); item.websites = item.websites.filter(value => value.id !== Number(button.dataset.deleteWebsite)); renderPreserving(); notify("竞品网站已删除。"); } catch (error) { restore(); notify(error.message, "error"); }
    });
    detail.querySelectorAll("[data-delete-keyword]").forEach((button) => button.onclick = async () => {
      if (!confirm("确认删除这个关键词吗？")) return;
      const restore = setBusy(button, "…"); notify("正在删除竞品关键词…", "loading", 0);
      try { await request(`/api/competitors/projects/${projectId()}/${item.id}/keywords/${button.dataset.deleteKeyword}`, {method:"DELETE"}); item.keywords = item.keywords.filter(value => value.id !== Number(button.dataset.deleteKeyword)); renderPreserving(); notify("竞品关键词已删除。"); } catch (error) { restore(); notify(error.message, "error"); }
    });
  }
  function renderDetail() {
    root.classList.toggle('is-editing', editing);
    const item = selected();
    if (!item) return empty();
    const action = editing ? '<div class="competitor-detail-actions"><span class="competitor-edit-state">编辑中</span><button type="button" class="competitor-secondary" data-finish-edit>完成编辑</button></div>' : '<div class="competitor-detail-actions"><button type="button" class="competitor-secondary" data-export-competitor>导出此档案</button><button type="button" data-edit-competitor>编辑竞品</button></div>';
    const hero = `<div class="competitor-detail-hero"><div class="competitor-detail-mark">${esc(item.name.trim().charAt(0).toUpperCase())}</div><div class="competitor-detail-head"><div><small>COMPETITOR PROFILE</small><h3>${esc(item.name)}</h3><p>${esc(item.country || "国家/地区未填写")}</p></div>${action}</div></div>`;
    if (editing) {
      const tabs = [['company','公司资料'],['websites','网站'],['keywords','关键词']];
      detail.innerHTML = `<div class="competitor-editor-top">${hero}<nav class="competitor-editor-tabs" role="tablist" aria-label="编辑竞品资料">${tabs.map(([key,label]) => `<button type="button" role="tab" id="competitor-tab-${key}" aria-controls="competitor-pane-${key}" data-editor-tab="${key}">${label}</button>`).join('')}</nav><div class="competitor-editor-status" data-editor-save-status role="status"></div></div>
      <section role="tabpanel" id="competitor-pane-company" aria-labelledby="competitor-tab-company" data-editor-pane="company"><header class="competitor-editor-section-head"><div><h4>公司资料</h4><p>只保存公司名称、国家和调研备注。Ctrl / ⌘ + S 保存。</p></div></header>${baseForm(item)}</section>
      <section role="tabpanel" id="competitor-pane-websites" aria-labelledby="competitor-tab-websites" data-editor-pane="websites" hidden>${websites(item)}</section>
      <section role="tabpanel" id="competitor-pane-keywords" aria-labelledby="competitor-tab-keywords" data-editor-pane="keywords" hidden>${keywords(item)}</section>`;
      bindDetail(item); bindEditorTabs(item);
      detail.querySelector('[data-finish-edit]').onclick = () => { if (!canLeave()) return; editing = false; renderDetail(); detail.scrollTop = 0; };
      return;
    }
    detail.innerHTML = `${hero}${readonlySections(item)}`;
    detail.querySelectorAll('[data-copy-keyword]').forEach(button => button.onclick = async () => {
      const value = item.keywords.find(value => value.id === Number(button.dataset.copyKeyword));
      try { await navigator.clipboard.writeText(value.keyword); notify('关键词已复制。'); } catch { notify('复制失败，请手动复制关键词。', 'error'); }
    });
    detail.querySelector("[data-edit-competitor]")?.addEventListener("click", () => { loadVersion++; editorTab = 'company'; editing = true; renderDetail(); detail.scrollTop = 0; detail.querySelector('[name="name"]')?.focus({preventScroll:true}); });
    detail.querySelector("[data-export-competitor]")?.addEventListener("click", (event) => exportCompetitor(item, event.currentTarget));
  }
  async function load() {
    const id = projectId();
    if (id !== loadedProject) {
      loadedProject = id; items = []; editing = false; editorTab = 'company'; search.value = '';
      selectedId = Number(sessionStorage.getItem(selectionKey())) || null;
      list.scrollTop = 0; detail.scrollTop = 0; renderList(); empty();
      root.querySelector('[data-competitor-notice]')?.setAttribute('hidden', '');
    } else if (editing) return;
    const version = ++loadVersion;
    add.disabled = !id;
    if (!id) { exportAll.disabled = true; return; }
    list.innerHTML = '<div class="competitor-empty-list" role="status">正在加载竞争对手…</div>';
    try {
      const data = await request('/api/competitors/projects/' + id);
      if (version !== loadVersion || id !== projectId()) return;
      items = data;
      if (!items.some(item => item.id === selectedId)) selectedId = items[0]?.id || null;
      remember(); renderList(); selectedId ? renderDetail() : empty();
    } catch (error) {
      if (version !== loadVersion || id !== projectId()) return;
      exportAll.disabled = true; list.innerHTML = `<div class="competitor-empty-list">${esc(error.message)}<button type="button" data-competitor-retry>重新加载</button></div>`; empty();
      list.querySelector('[data-competitor-retry]').onclick = load;
    }
  }
  add.onclick = () => { if (!canLeave()) return; loadVersion++; selectedId = null; editorTab = 'company'; editing = true; renderList(); detail.innerHTML = `<div class="competitor-create-head"><div><small>NEW COMPETITOR</small><h3>新增竞品</h3><p>先创建公司资料，创建后再补充网站和关键词。</p></div></div>${baseForm()}`; bindDetail({}); detail.scrollTop = 0; detail.querySelector('[name="name"]')?.focus({preventScroll:true}); };
  exportAll.onclick = () => exportCompetitors(exportAll);
  let appliedSearch = '';
  search.addEventListener('input', () => {
    const visible = filters();
    if (selectedId && !visible.some(item => item.id === selectedId)) {
      if (!canLeave()) { search.value = appliedSearch; return; }
      selectedId = visible[0]?.id || null; editing = false; renderDetail(); detail.scrollTop = 0;
    } else if (!selectedId && !editing) { selectedId = visible[0]?.id || null; renderDetail(); }
    appliedSearch = search.value; renderList(); remember();
  });
  window.addEventListener('beforeunload', event => { if (dirtyForms().length || pendingWrites) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('click', event => {
    if (root.hidden || !event.target.closest('.global-nav-item, .crm-primary-item, .pm-project-row')) return;
    if (!canLeave()) { event.preventDefault(); event.stopImmediatePropagation(); }
    else editing = false;
  }, true);
  document.addEventListener('keydown', event => {
    if (root.hidden || !editing) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      let form = document.activeElement?.closest('form');
      if (!form || form.closest('[data-editor-pane]')?.hidden) {
        const pane = detail.querySelector('[data-editor-pane="' + editorTab + '"]') || detail;
        form = Array.from(pane.querySelectorAll('form')).find(value => !value.hidden && formValue(value) !== value.dataset.baseline) || Array.from(pane.querySelectorAll('form')).find(value => !value.hidden);
      }
      if (form) form.requestSubmit(); else notify('请先打开网站编辑或添加表单。', 'info');
    }
  });
  window.addEventListener("tophoo-project-changed", () => { appliedSearch = ''; load(); });
  document.querySelector('[data-crm-section="competitors"]')?.addEventListener("click", load);
  window.setTimeout(load, 450);
})();
