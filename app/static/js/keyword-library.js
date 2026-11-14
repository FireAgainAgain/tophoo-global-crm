(() => {
  const $ = selector => document.querySelector(selector);
  const tree = $("#keyword-tree"), list = $("#keyword-list"), panel = $("#keyword-tree-panel"), status = $("#keyword-status");
  if (!tree || !list || !panel || !status) return;
  const importFile = $("#keyword-import-file"), clearButton = $("#keyword-clear-library");
  const pendingTransfers = new Set();
  const esc = (value = "") => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const currentProject = () => Number(localStorage.getItem("tophoo-global-selected-project")) || null;
  const headers = () => window.tophooAuth?.headers?.() || {};
  const hasSession = () => Boolean(window.tophooAuth?.token?.() || window.tophooAuth?.currentUser?.());
  let categories = [], keywords = [], selectedId = null, expanded = new Set(), checkedIds = new Set(), editorDirty = () => false;
  let projectVersion = 0, keywordVersion = 0, searchTimer, closeConfirmation = null, initialized = false;
  const capture = () => ({ project: currentProject(), version: projectVersion, token: window.tophooAuth?.token?.(), userId: window.tophooAuth?.currentUser?.()?.id, authenticated: hasSession() });
  const isCurrent = context => context.project === currentProject() && context.version === projectVersion && context.token === window.tophooAuth?.token?.() && context.userId === window.tophooAuth?.currentUser?.()?.id;
  const children = parent => categories.filter(item => item.parent_id === parent);
  const find = id => categories.find(item => item.id === Number(id));
  function syncTransferControls() {
    const disabled = !currentProject() || !hasSession() || pendingTransfers.has(currentProject());
    importFile.disabled = disabled;
    clearButton.disabled = disabled;
  }
  function resetLibraryView() {
    clearTimeout(searchTimer);
    selectedId = null; expanded.clear(); checkedIds.clear();
    $("#keyword-search").value = ""; $("#keyword-category-search").value = "";
    rememberView();
  }
  let statusTimer;
  const say = (text = "", error = false, persistent = false) => {
    clearTimeout(statusTimer);
    status.textContent = text; status.hidden = !text; status.classList.toggle("is-error", error);
    if (text && !persistent) statusTimer = setTimeout(() => { status.hidden = true; }, error ? 7000 : 3200);
  };
  const api = (project, path) => `/api/keywords/projects/${project}${path}`;
  const json = (method, payload) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请检查填写内容后重试。");
    return data;
  }
  function categoryPath(id) {
    const names = [], seen = new Set();
    for (let item = find(id); item && !seen.has(item.id); item = find(item.parent_id)) { names.unshift(item.name); seen.add(item.id); }
    return names.join(" / ");
  }
  function descendants(id) {
    const ids = new Set([id]), pending = [id];
    while (pending.length) for (const child of children(pending.pop())) if (!ids.has(child.id)) { ids.add(child.id); pending.push(child.id); }
    return ids;
  }
  function orderedCategories(parent = null, seen = new Set()) {
    return children(parent).flatMap(item => { if (seen.has(item.id)) return []; seen.add(item.id); return [item, ...orderedCategories(item.id, seen)]; });
  }
  function revealCategory(id) {
    const seen = new Set();
    for (let item = find(id); item && !seen.has(item.id); item = find(item.parent_id)) { seen.add(item.id); if (item.parent_id !== null) expanded.add(item.parent_id); }
  }
  const viewKey = () => 'tophoo-global-keyword-view-' + currentProject();
  function rememberView() { sessionStorage.setItem(viewKey(), JSON.stringify({selectedId, expanded:Array.from(expanded), q:$("#keyword-search").value})); }
  async function copyText(value) {
    if (navigator.clipboard?.writeText) { try { await navigator.clipboard.writeText(value); return; } catch {} }
    const field = document.createElement('textarea'); field.value = value; field.style.cssText = 'position:fixed;left:-9999px'; document.body.append(field); field.select();
    const copied = document.execCommand('copy'); field.remove(); if (!copied) throw new Error('复制失败，请手动复制。');
  }
  function updateSelection() {
    const available = new Set(keywords.map(item => item.id)); checkedIds = new Set(Array.from(checkedIds).filter(id => available.has(id)));
    const all = $("#keyword-select-all"); all.checked = !!keywords.length && checkedIds.size === keywords.length; all.indeterminate = checkedIds.size > 0 && checkedIds.size < keywords.length; all.disabled = !keywords.length || list.getAttribute('aria-busy') === 'true';
    $("#keyword-selection-bar").hidden = !checkedIds.size; $("#keyword-selection-count").textContent = '已选 ' + checkedIds.size + ' 条（当前结果）';
    list.querySelectorAll('[data-check-keyword]').forEach(input => { input.checked = checkedIds.has(Number(input.dataset.checkKeyword)); input.closest('tr').classList.toggle('is-selected', input.checked); });
  }
  async function copySelection() {
    const entries = keywords.filter(item => checkedIds.has(item.id));
    if (!entries.length) return;
    try { await copyText(entries.map(item => item.keyword).join("\n")); say('已复制 ' + entries.length + ' 条关键词。'); }
    catch (error) { say(error.message, true); }
  }
  async function deleteSelectedKeywords() {
    const context = capture(), ids = Array.from(checkedIds);
    if (!ids.length || !context.project || !context.authenticated) return;
    if (!await dialog({ title: "批量删除关键词", description: "将从当前项目及其所有分类中删除所选的 " + ids.length + " 条关键词。此操作不可撤销。", confirmText: "确认删除", danger: true }) || !isCurrent(context)) return;
    try {
      const data = await request(api(context.project, "/keywords/bulk-delete"), json("POST", { keyword_ids: ids }));
      if (!isCurrent(context)) return;
      ids.forEach(id => checkedIds.delete(id));
      await refresh(context);
      if (isCurrent(context)) say("已删除 " + data.deleted + " 条关键词。");
    } catch (error) { if (isCurrent(context)) say(error.message, true); }
  }
  function renderTree() {
    const scroll = tree.scrollTop; closeCategoryMenu();
    const term = $("#keyword-category-search").value.trim().toLowerCase(), visible = new Set();
    if (term) for (const item of categories.filter(item => item.name.toLowerCase().includes(term))) {
      const seen = new Set();
      for (let ancestor = item; ancestor && !seen.has(ancestor.id); ancestor = find(ancestor.parent_id)) { visible.add(ancestor.id); seen.add(ancestor.id); }
    }
    function node(item) {
      if (term && !visible.has(item.id)) return "";
      const kids = children(item.id), open = term || expanded.has(item.id);
      const folder = item.parent_id === null || kids.length > 0;
      const icon = folder
        ? `<span class="keyword-tree-folder is-folder" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M2.5 5.5h5l2-2h8v13h-15z"/>${open && kids.length ? '<path class="keyword-folder-open" d="M2.5 8h15l-2 8.5h-13z"/>' : ''}</svg></span>`
        : '<span class="keyword-tree-folder is-tag" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M3 3.5h7l7 7-6.5 6.5-7.5-7.5z"/><circle cx="6.5" cy="7" r="1"/></svg></span>';
      return `<div class="keyword-tree-node ${item.id === selectedId ? "is-active" : ""}"><div class="keyword-tree-row">${kids.length ? `<button type="button" class="keyword-tree-arrow" data-toggle="${item.id}" aria-expanded="${Boolean(open)}" aria-label="展开或收起${esc(item.name)}">${open ? "▾" : "▸"}</button>` : '<span class="keyword-tree-leaf"></span>'}${icon}<button type="button" class="keyword-tree-name" data-select="${item.id}" ${item.id === selectedId ? 'aria-current="true"' : ""} title="${esc(categoryPath(item.id))}">${esc(item.name)}</button><span class="keyword-tree-count" title="直接关联的关键词数量">${item.keyword_count || 0}</span><span class="keyword-tree-controls"><button type="button" data-category-menu="${item.id}" aria-label="${esc(item.name)}：分类操作" aria-haspopup="true" aria-expanded="false" aria-controls="keyword-category-menu" title="分类操作">⋯</button></span></div>${open ? `<div class="keyword-tree-children">${kids.map(node).join("")}</div>` : ""}</div>`;
    }
    tree.innerHTML = categories.length ? children(null).map(node).join("") || '<p class="keyword-tree-empty">没有匹配的分类。</p>' : '<div class="keyword-tree-empty"><strong>建立你的关键词目录</strong><p>新建分类，或导入 Excel 自动生成分组。</p></div>';
    tree.scrollTop = scroll; $("#keyword-all").classList.toggle("is-active", selectedId === null); $("#keyword-all").setAttribute("aria-current", String(selectedId === null));
    $("#keyword-category-total").textContent = categories.length;
    $("#keyword-add-root").disabled = !currentProject() || !hasSession();
  }
  function renderKeywords(items) {
    const category = find(selectedId);
    $("#keyword-category-name").textContent = category?.name || "全部关键词";
    $("#keyword-category-path").textContent = category ? categoryPath(category.id) : "当前项目 / 全部关键词";
    $("#keyword-count").textContent = `${items.length} 个关键词`;
    $("#keyword-visible-count").textContent = `当前显示 ${items.length} 条`;
    $("#keyword-add").disabled = !categories.length || !currentProject() || !hasSession();
    if (!items.length) { list.innerHTML = `<tr><td colspan="4"><div class="keyword-empty-state"><span aria-hidden="true">⌕</span><strong>${currentProject() ? "没有匹配的关键词" : "请先选择项目"}</strong><p>${currentProject() ? "调整搜索条件，也可以新增关键词或导入 Excel。" : "在项目中整理关键词与分类。"}</p></div></td></tr>`; updateSelection(); return; }
    list.innerHTML = items.map(item => {
      return `<tr data-keyword-id="${item.id}"><td class="keyword-check-cell"><input type="checkbox" data-check-keyword="${item.id}" aria-label="选择${esc(item.keyword)}"></td><td><div class="keyword-text-cell"><span class="keyword-text">${esc(item.keyword)}</span><button type="button" class="keyword-copy-one" data-copy-keyword="${item.id}" title="复制关键词" aria-label="复制${esc(item.keyword)}">⧉</button></div></td><td>${esc(item.chinese_translation || "待补充")}</td><td><button type="button" data-edit-keyword="${item.id}">编辑</button><button type="button" class="is-delete" data-delete-keyword="${item.id}">删除</button></td></tr>`;
    }).join("");
    updateSelection();
  }
  async function loadCategories(context = capture()) {
    if (!context.project || !context.authenticated) return;
    const data = await request(api(context.project, "/categories")); if (!isCurrent(context)) return;
    categories = data.categories || []; if (selectedId !== null && !find(selectedId)) selectedId = null;
    revealCategory(selectedId); renderTree(); rememberView();
  }
  async function loadKeywords(context = capture()) {
    const version = ++keywordVersion, category = selectedId;
    if (!context.project || !context.authenticated || (category !== null && !find(category))) { keywords = []; renderKeywords([]); return; }
    const query = new URLSearchParams({ q: $("#keyword-search").value.trim() });
    list.setAttribute("aria-busy", "true"); $("#keyword-select-all").disabled = true; rememberView();
    try {
      const data = await request(api(context.project, category === null ? `/keywords?${query}` : `/categories/${category}/keywords?${query}`));
      if (!isCurrent(context) || version !== keywordVersion || category !== selectedId) return;
      keywords = data.keywords || []; renderKeywords(keywords);
    } catch (error) { if (isCurrent(context) && version === keywordVersion) { keywords = []; renderKeywords([]); say(error.message, true); } }
    finally { if (isCurrent(context) && version === keywordVersion) { list.setAttribute("aria-busy", "false"); updateSelection(); } }
  }
  async function refresh(context = capture()) { await loadCategories(context); if (isCurrent(context)) await loadKeywords(context); }
  async function refreshProject() {
    initialized = true;
    ++projectVersion; ++keywordVersion; clearTimeout(searchTimer); closeConfirmation?.(null);
    $("#keyword-editor").close();
    categories = []; keywords = []; selectedId = null; expanded.clear(); checkedIds.clear();
    let view = {}; try { view = JSON.parse(sessionStorage.getItem(viewKey()) || '{}'); } catch {}
    selectedId = Number(view.selectedId) || null; expanded = new Set((view.expanded || []).map(Number));
    $("#keyword-search").value = view.q || ""; $("#keyword-category-search").value = "";
    importFile.value = ""; syncTransferControls();
    renderTree(); renderKeywords([]); say();
    const context = capture(); if (!context.project || !context.authenticated) return say("请先登录并选择一个项目。");
    try { await refresh(context); } catch (error) { if (isCurrent(context)) say(error.message, true); }
  }
  function dialog({ title, description, confirmText = "确认", danger = false, input = false, placeholder = "", choices = null, requiredText = null }) {
    closeConfirmation?.(null);
    return new Promise(resolve => {
      const host = $("#keyword-dialog"), field = $("#keyword-dialog-input"), select = $("#keyword-dialog-select"), note = $("#keyword-dialog-note");
      const confirm = $("#keyword-dialog-confirm");
      $("#keyword-dialog-title").textContent = title; $("#keyword-dialog-description").textContent = description; confirm.textContent = confirmText;
      host.classList.toggle("is-danger", danger); field.hidden = !input; field.value = ""; field.placeholder = placeholder;
      select.hidden = !choices; select.innerHTML = choices ? choices.map(item => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join("") : "";
      const renderNote = () => { note.hidden = !choices; note.textContent = choices?.find(item => item.value === select.value)?.note || ""; }; select.onchange = renderNote; renderNote();
      const updateConfirm = () => { confirm.disabled = requiredText !== null && field.value.trim() !== requiredText; };
      field.oninput = updateConfirm; updateConfirm();
      const done = value => { closeConfirmation = null; host.close(); host.oncancel = host.onclick = null; confirm.onclick = $("#keyword-dialog-cancel").onclick = select.onchange = field.oninput = null; resolve(value); };
      closeConfirmation = done; confirm.onclick = () => done(input ? field.value.trim() : choices ? select.value : true); $("#keyword-dialog-cancel").onclick = () => done(null);
      host.oncancel = event => { event.preventDefault(); done(null); }; host.onclick = event => { if (event.target === host) done(null); };
      field.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); $("#keyword-dialog-confirm").click(); } }; host.showModal(); if (input) field.focus();
    });
  }
  function openEditor({ title, description = "", eyebrow = "", fields, save, continuous = false }) {
    const host = $("#keyword-editor"), form = $("#keyword-editor-form"), button = $("#keyword-editor-save"), error = $("#keyword-editor-error"), context = capture();
    if (!context.project || !context.authenticated) return say("请先登录并选择项目。", true);
    host.classList.toggle("is-keyword-form", !eyebrow && !description);
    $("#keyword-editor-title").textContent = title;
    for (const [id, text] of [["description", description], ["eyebrow", eyebrow]]) {
      const label = $("#keyword-editor-" + id);
      label.textContent = text;
      label.hidden = !text;
    }
    $("#keyword-editor-fields").innerHTML = fields; $("#keyword-editor-fields").inert = false; error.hidden = true; button.disabled = false; button.textContent = continuous ? "保存关键词" : "保存修改"; $("#keyword-editor-hint").textContent = "Ctrl / ⌘ + S 保存";
    let saving = false, baseline = JSON.stringify(Array.from(new FormData(form).entries()));
    $("#keyword-editor-continue-label").hidden = !continuous; $("#keyword-editor-continue").checked = false;
    const dirty = () => JSON.stringify(Array.from(new FormData(form).entries())) !== baseline;
    editorDirty = () => host.open && dirty();
    form.oninput = () => { $("#keyword-editor-hint").textContent = dirty() ? '有未保存修改 · Ctrl / ⌘ + S 保存' : 'Ctrl / ⌘ + S 保存'; };
    const close = async () => {
      if (saving) return;
      if (dirty() && !await dialog({title:'放弃未保存修改？',description:'关闭后，本次填写或分类勾选的修改不会保存。',confirmText:'放弃修改'})) return;
      if (isCurrent(context)) host.close();
    };
    host.querySelectorAll("[data-close-editor]").forEach(control => control.onclick = close);
    host.oncancel = event => { event.preventDefault(); close(); }; host.onclick = event => { if (event.target === host) close(); };
    form.onsubmit = async event => {
      event.preventDefault(); if (saving || !form.reportValidity() || !isCurrent(context)) return;
      saving = true; $("#keyword-editor-fields").inert = true; $("#keyword-editor-continue").disabled = true; button.disabled = true; button.textContent = "正在保存…"; error.hidden = true;
      try {
        await save(new FormData(form), context); if (!isCurrent(context)) return;
        const keepAdding = continuous && $("#keyword-editor-continue").checked;
        if (!keepAdding) host.close();
        await refresh(context); if (!isCurrent(context)) return;
        if (keepAdding) {
          ['keyword','chinese_translation'].forEach(name => { form.elements.namedItem(name).value = ''; });
          baseline = JSON.stringify(Array.from(new FormData(form).entries())); $("#keyword-editor-hint").textContent = '已保存上一条 · 可继续新增'; form.elements.namedItem('keyword').focus();
        }
        say(keepAdding ? '已保存，所属分类已保留，可以继续新增。' : '修改已保存。');
      }
      catch (failure) { if (isCurrent(context)) { if (host.open) { error.textContent = failure.message; error.hidden = false; } else say(failure.message, true); } }
      finally { if (isCurrent(context)) { saving = false; $("#keyword-editor-fields").inert = false; $("#keyword-editor-continue").disabled = false; button.disabled = false; button.textContent = continuous ? "保存关键词" : "保存修改"; if (continuous && host.open && !form.elements.namedItem("keyword").value) form.elements.namedItem("keyword").focus(); } }
    };
    host.showModal(); form.querySelector("input:not([type=checkbox])")?.focus();
  }
  function moveSelectedKeywords() {
    const keywordIds = [...checkedIds];
    const sourceId = selectedId;
    const targets = orderedCategories().filter(item => item.id !== sourceId);
    if (!keywordIds.length || !targets.length) return say("没有可移动的关键词或目标分类。", true);
    openEditor({
      title: "批量修改分类",
      eyebrow: "关键词设置",
      description: sourceId === null
        ? `将选中的 ${keywordIds.length} 条关键词统一归入目标分类，替换它们原有的分类。`
        : `将选中的 ${keywordIds.length} 条关键词从「${categoryPath(sourceId)}」移到目标分类，保留它们所属的其他分类。`,
      fields: `<label class="keyword-editor-field">目标分类<select name="target_category_id" required><option value="">请选择分类</option>${targets.map(item => `<option value="${item.id}">${esc(categoryPath(item.id))}</option>`).join("")}</select></label>`,
      save: async (data, context) => {
        await request(api(context.project, "/keywords/move"), json("POST", {
          keyword_ids: keywordIds,
          source_category_id: sourceId,
          target_category_id: Number(data.get("target_category_id")),
        }));
        if (isCurrent(context)) checkedIds.clear();
      },
    });
  }
  function editCategory(id = null, parentId = null) {
    const item = id === null ? null : find(id); if (id !== null && !item) return;
    const excluded = item ? descendants(item.id) : new Set(), currentParent = item ? item.parent_id : parentId;
    openEditor({ title: item ? "编辑分类" : "新建分类", eyebrow: "分类设置", description: "调整名称和父类。移动分类时，其子分类和关键词会一并保留。",
      fields: `<label class="keyword-editor-field">分类名称<input name="name" required maxlength="180" value="${esc(item?.name)}" placeholder="例如：产品关键词"></label><label class="keyword-editor-field">父分类<select name="parent_id"><option value="">无父类 · 作为一级分类</option>${orderedCategories().filter(category => !excluded.has(category.id)).map(category => `<option value="${category.id}" ${category.id === currentParent ? "selected" : ""}>${esc(categoryPath(category.id))}</option>`).join("")}</select><small>自身与子分类不会出现在父类选项中。</small></label>`,
      save: async (data, context) => {
        const name = data.get("name").trim(); if (!name) throw new Error("请输入分类名称。"); const parent = data.get("parent_id") ? Number(data.get("parent_id")) : null;
        const result = await request(api(context.project, item ? `/categories/${item.id}` : "/categories"), json(item ? "PUT" : "POST", { name, parent_id: parent }));
        if (isCurrent(context)) { if (parent) expanded.add(parent); if (!item) selectedId = result.id; }
      },
    });
  }
  function editKeyword(item = null) {
    if (!categories.length) return say("请先新建一个分类。", true);
    const selected = new Set(item?.category_ids || (selectedId ? [selectedId] : []));
    const options = orderedCategories().map(category => {
      const path = categoryPath(category.id);
      return `<label data-category-option="${esc(path.toLowerCase())}">
        <input type="checkbox" name="category_ids" value="${category.id}" ${selected.has(category.id) ? "checked" : ""}>
        <span>${esc(path)}</span>
      </label>`;
    }).join("");
    openEditor({
      continuous: !item,
      title: item ? "编辑关键词" : "新增关键词",
      fields: `<div class="keyword-editor-grid">
        <label class="keyword-editor-field">关键词<input name="keyword" required maxlength="191" value="${esc(item?.keyword)}"></label>
        <label class="keyword-editor-field">中文翻译<input name="chinese_translation" maxlength="500" value="${esc(item?.chinese_translation)}"></label>
      </div>
      <fieldset class="keyword-category-picker">
        <legend>所属分类</legend>
        <div id="keyword-selected-categories" aria-live="polite"></div>
        <details class="keyword-category-disclosure">
          <summary>选择分类</summary>
          <input type="search" id="keyword-picker-search" placeholder="搜索分类" aria-label="搜索分类">
          <div class="keyword-category-options">${options}</div>
          <p id="keyword-picker-empty" hidden>没有匹配的分类。</p>
        </details>
      </fieldset>`,
      save: async (data, context) => {
        const keyword = data.get("keyword").trim();
        const categoryIds = data.getAll("category_ids").map(Number);
        if (!keyword) throw new Error("请输入关键词。");
        if (!categoryIds.length) throw new Error("请至少选择一个分类。");
        await request(api(context.project, item ? `/keywords/${item.id}` : "/keywords"), json(item ? "PUT" : "POST", {
          keyword, chinese_translation: data.get("chinese_translation").trim(), category_ids: categoryIds,
        }));
      },
    });
    const picker = $(".keyword-category-picker");
    const disclosure = picker.querySelector("details");
    const search = $("#keyword-picker-search");
    const renderSelection = () => {
      const paths = Array.from(picker.querySelectorAll("input:checked"), input => categoryPath(input.value));
      $("#keyword-selected-categories").innerHTML = paths.length
        ? paths.map(path => `<span>${esc(path)}</span>`).join("")
        : '<small>尚未选择分类</small>';
      disclosure.querySelector("summary").textContent = paths.length ? "修改分类" : "选择分类";
    };
    picker.onchange = event => {
      if (event.target.type !== "checkbox") return;
      renderSelection();
      $("#keyword-editor-error").hidden = true;
    };
    search.oninput = () => {
      const term = search.value.trim().toLowerCase();
      let matches = 0;
      picker.querySelectorAll("[data-category-option]").forEach(label => {
        label.hidden = !label.dataset.categoryOption.includes(term);
        if (!label.hidden) matches++;
      });
      $("#keyword-picker-empty").hidden = matches > 0;
    };
    renderSelection();
  }
  async function removeRecord(kind, id) {
    const context = capture(), category = kind === "categories", item = category ? find(id) : null;
    if (!await dialog({ title: category ? "删除分类" : "删除关键词", description: category ? `将删除「${item?.name}」及其子分类。仅属于这些分类的关键词也会删除，其他分类中的关键词保留。` : "此关键词将从当前项目及其所有分类中移除。", confirmText: "确认删除", danger: true }) || !isCurrent(context)) return;
    try { await request(api(context.project, `/${kind}/${id}`), { method: "DELETE" }); if (isCurrent(context)) { await refresh(context); say("删除成功。"); } } catch (error) { if (isCurrent(context)) say(error.message, true); }
  }
  async function moveCategory(id, direction) {
    const context = capture(); try { await request(api(context.project, `/categories/${id}/move`), json("POST", { direction })); if (isCurrent(context)) await loadCategories(context); } catch (error) { if (isCurrent(context)) say(error.message, true); }
  }
  async function exportKeywords(type) {
    const context = capture(); if (!context.project || !context.authenticated) return say("请先登录并选择项目。", true);
    try { const response = await fetch(api(context.project, type === "template" ? "/template" : `/export/${type}`), { headers: headers() }); if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "导出失败。"); const blob = await response.blob(); if (!isCurrent(context)) return; const match = response.headers.get("Content-Disposition")?.match(/filename\*=UTF-8''([^;]+)/i), url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = match ? decodeURIComponent(match[1]) : `关键词库.${type}`; link.click(); URL.revokeObjectURL(url); say(type === "template" ? "导入模板已开始下载，填写后可直接导入。" : "关键词库已开始下载。"); }
    catch (error) { if (isCurrent(context)) say(error.message, true); }
  }
  $("#keyword-download-template").onclick = () => exportKeywords("template");
  clearButton.onclick = async () => {
    const context = capture();
    if (!context.project || !context.authenticated || pendingTransfers.has(context.project)) return;
    const confirmation = await dialog({
      title: "清空当前项目的关键词库？",
      description: "将永久删除当前项目的全部关键词、分类和导入记录，不受搜索或分类筛选限制。建议先导出 Excel。请输入「清空」确认。",
      confirmText: "清空数据", danger: true, input: true, placeholder: "输入「清空」", requiredText: "清空"
    });
    if (confirmation !== "清空" || !isCurrent(context) || pendingTransfers.has(context.project)) return;
    pendingTransfers.add(context.project); syncTransferControls();
    try {
      const result = await request(api(context.project, "/keywords/clear"), json("POST", { confirmation }));
      if (!isCurrent(context)) return;
      resetLibraryView();
      await refresh(context);
      if (isCurrent(context)) say(`已清空：删除 ${result.keywords} 条关键词、${result.categories} 个分类。`);
    } catch (error) { if (isCurrent(context)) say(error.message, true); }
    finally { pendingTransfers.delete(context.project); if (currentProject() === context.project) syncTransferControls(); }
  };
  importFile.addEventListener("change", async event => {
    const file = event.target.files[0], context = capture(); if (!file) return; if (!context.project || !context.authenticated) { importFile.value = ""; return say("请先登录并选择项目。", true); }
    if (pendingTransfers.has(context.project)) return;
    pendingTransfers.add(context.project); syncTransferControls();
    try {
      const body = new FormData(); body.append("file", file);
      say("正在检查 Excel…", false, true);
      const preview = await request(api(context.project, "/imports/preview"), { method: "POST", body });
      if (!isCurrent(context)) return;
      say();
      const mode = await dialog({ title: "确认导入关键词库", description: `${file.name} · ${preview.format}。识别到 ${preview.unique_keywords} 个关键词（${preview.existing_keywords} 个已存在）、${preview.category_count} 个分类。`, confirmText: "继续", choices: [{ value: "update", label: "智能更新（推荐）", note: "更新已有词的非空翻译并补充分组。" }, { value: "merge", label: "合并新增", note: "保留已有关键词信息，新增关键词与分类关联。" }, { value: "replace", label: "清空后重新导入", note: "以本次 Excel 替换当前项目的关键词库。" }] });
      if (!mode || !isCurrent(context)) return;
      if (mode === "replace" && (!await dialog({ title: "确认替换整个关键词库", description: "当前项目全部关键词、分类与导入记录将被替换。建议先导出 Excel。", danger: true, confirmText: "确认替换" }) || !isCurrent(context))) return;
      say("正在导入关键词库…", false, true);
      const result = await request(api(context.project, `/imports?mode=${mode}`), { method: "POST", body });
      if (!isCurrent(context)) return;
      resetLibraryView();
      await refresh(context);
      if (isCurrent(context)) say(`导入完成：新增 ${result.added} 条，更新 ${result.updated} 条，新增分类关联 ${result.mapped} 个。`);
    } catch (error) { if (isCurrent(context)) say(error.message, true); }
    finally {
      pendingTransfers.delete(context.project);
      if (currentProject() === context.project) { importFile.value = ""; syncTransferControls(); }
    }
  });
  const categoryMenu = document.createElement('div');
  categoryMenu.id = 'keyword-category-menu'; categoryMenu.className = 'keyword-category-menu'; categoryMenu.hidden = true; categoryMenu.setAttribute('role', 'group'); categoryMenu.setAttribute('aria-label', '分类操作'); document.body.append(categoryMenu);
  let menuAnchor = null;
  function closeCategoryMenu(restoreFocus = false) {
    categoryMenu.hidden = true; const anchor = menuAnchor; menuAnchor = null; anchor?.setAttribute('aria-expanded','false'); if (restoreFocus && anchor?.isConnected) anchor.focus({preventScroll:true});
  }
  function openCategoryMenu(id, button) {
    if (!categoryMenu.hidden && menuAnchor === button) return closeCategoryMenu(true);
    closeCategoryMenu(); const item = find(id); if (!item) return;
    const siblings = children(item.parent_id), index = siblings.findIndex(value => value.id === id);
    categoryMenu.innerHTML = `<button type="button" data-action="edit">✎ 编辑分类</button><button type="button" data-action="add">＋ 新增子分类</button><button type="button" data-action="up" ${index <= 0 ? 'disabled' : ''}>↑ 上移分类</button><button type="button" data-action="down" ${index === siblings.length - 1 ? 'disabled' : ''}>↓ 下移分类</button><button type="button" data-action="delete">× 删除分类</button>`;
    menuAnchor = button; button.setAttribute('aria-expanded','true'); categoryMenu.hidden = false;
    const rect = button.getBoundingClientRect(), height = categoryMenu.offsetHeight;
    categoryMenu.style.left = Math.max(8, Math.min(rect.right-categoryMenu.offsetWidth, innerWidth-categoryMenu.offsetWidth-8)) + 'px';
    categoryMenu.style.top = Math.max(8, rect.bottom+height+8<=innerHeight ? rect.bottom+4 : rect.top-height-4) + 'px';
    categoryMenu.querySelectorAll('button').forEach(action => action.onclick = () => { const type = action.dataset.action; closeCategoryMenu(); if(type === 'edit') editCategory(id); else if(type === 'add') editCategory(null,id); else if(type === 'delete') removeRecord('categories',id); else moveCategory(id,type); });
    categoryMenu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
  }
  document.addEventListener('click', event => { if (!categoryMenu.hidden && !categoryMenu.contains(event.target) && !event.target.closest('[data-category-menu]')) closeCategoryMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !categoryMenu.hidden) { event.preventDefault(); closeCategoryMenu(true); } });
  document.addEventListener('scroll', event => { if(!categoryMenu.contains(event.target)) closeCategoryMenu(); },true);
  window.addEventListener('resize', () => closeCategoryMenu());
  async function selectCategory(id) {
    selectedId = id; checkedIds.clear(); keywords = []; revealCategory(id);
    renderTree(); renderKeywords([]); rememberView(); await loadKeywords();
  }
  tree.addEventListener("click", async event => {
    const button = event.target.closest("button"); if (!button) return;
    if (button.dataset.toggle) { const id = Number(button.dataset.toggle); expanded.has(id) ? expanded.delete(id) : expanded.add(id); renderTree(); rememberView(); }
    else if (button.dataset.select) { await selectCategory(Number(button.dataset.select)); }
    else if (button.dataset.categoryMenu) openCategoryMenu(Number(button.dataset.categoryMenu), button);
    else if (button.dataset.addCategory) editCategory(null, Number(button.dataset.addCategory));
    else if (button.dataset.deleteCategory) await removeRecord("categories", Number(button.dataset.deleteCategory));
    else if (button.dataset.moveCategory) await moveCategory(Number(button.dataset.id), button.dataset.moveCategory);
  });
  list.addEventListener("click", event => { const button = event.target.closest("button"); if (!button) return; if (button.dataset.copyKeyword) { const item = keywords.find(value => value.id === Number(button.dataset.copyKeyword)); copyText(item.keyword).then(() => say("关键词已复制。")).catch(error => say(error.message,true)); } else if (button.dataset.editKeyword) editKeyword(keywords.find(item => item.id === Number(button.dataset.editKeyword))); else if (button.dataset.deleteKeyword) removeRecord("keywords", Number(button.dataset.deleteKeyword)); });
  list.addEventListener('change', event => { const input = event.target.closest('[data-check-keyword]'); if (!input) return; const id = Number(input.dataset.checkKeyword); input.checked ? checkedIds.add(id) : checkedIds.delete(id); updateSelection(); });
  list.addEventListener('dblclick', event => { if (event.target.closest('button,input,details')) return; const row = event.target.closest('[data-keyword-id]'); if (row) editKeyword(keywords.find(item => item.id === Number(row.dataset.keywordId))); });
  $("#keyword-select-all").onchange = event => { checkedIds = event.target.checked ? new Set(keywords.map(item => item.id)) : new Set(); updateSelection(); };
  $("#keyword-copy-selected").onclick = copySelection;
  $("#keyword-move-selected").onclick = moveSelectedKeywords;
  $("#keyword-delete-selected").onclick = deleteSelectedKeywords;
  window.addEventListener('beforeunload', event => { if (editorDirty()) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('keydown', event => { if ($("#keyword-editor").open && !$("#keyword-dialog").open && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); $("#keyword-editor-form").requestSubmit(); } });
  $("#keyword-all").onclick = () => { selectedId = null; checkedIds.clear(); keywords = []; clearTimeout(searchTimer); renderTree(); renderKeywords([]); rememberView(); loadKeywords(); };
  $("#keyword-add-root").onclick = () => editCategory();
  $("#keyword-category-search").oninput = renderTree; $("#keyword-add").onclick = () => editKeyword(); $("#keyword-export-xlsx").onclick = () => exportKeywords("xlsx");
  $("#keyword-search").oninput = () => { clearTimeout(searchTimer); rememberView(); searchTimer = setTimeout(() => loadKeywords(), 220); };
  const resizer = $("#keyword-tree-resizer"), library = $(".keyword-library");
  resizer?.addEventListener("pointerdown", event => { if (window.innerWidth <= 850) return; const start = event.clientX, initial = panel.getBoundingClientRect().width; resizer.setPointerCapture(event.pointerId); const move = next => library.style.setProperty("--keyword-tree-width", `${Math.max(240, Math.min(420, initial + next.clientX - start))}px`); const stop = () => { resizer.removeEventListener("pointermove", move); resizer.removeEventListener("pointerup", stop); resizer.removeEventListener("pointercancel", stop); }; resizer.addEventListener("pointermove", move); resizer.addEventListener("pointerup", stop); resizer.addEventListener("pointercancel", stop); });
  document.addEventListener("tophoo-auth-changed", refreshProject); window.addEventListener("tophoo-project-changed", refreshProject);
  window.addEventListener("storage", event => { if (["tophoo-global-selected-project", "tophoo-global-access-token", "tophoo-global-current-user", null].includes(event.key)) refreshProject(); });
  document.addEventListener('tophoo-project-library-view', event => {
    if (event.detail?.section !== 'keyword-system') return;
    if (!initialized) refreshProject();
    else refresh().catch(error => say(error.message, true));
  });
  setTimeout(() => { if (!initialized) refreshProject(); }, 450);
})();
