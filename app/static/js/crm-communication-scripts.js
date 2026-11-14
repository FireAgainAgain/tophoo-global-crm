(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function inlineMarkdown(value) {
    return esc(value)
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
      .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  }
  function markdownCells(line) { return line.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim()); }
  function markdownToHtml(source) {
    const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n'), html = [];
    let paragraph = [], listType = '', code = [], inCode = false;
    const flushParagraph = () => { if (paragraph.length) { html.push(`<p>${inlineMarkdown(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`); paragraph = []; } };
    const closeList = () => { if (listType) { html.push(`</${listType}>`); listType = ''; } };
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^```/.test(line.trim())) { flushParagraph(); closeList(); if (inCode) { html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`); code = []; inCode = false; } else inCode = true; continue; }
      if (inCode) { code.push(line); continue; }
      const next = lines[index + 1] || '', separator = markdownCells(next);
      if (line.includes('|') && separator.length > 1 && separator.every(cell => /^:?-{3,}:?$/.test(cell))) {
        flushParagraph(); closeList(); const headers = markdownCells(line); const rows = []; index += 2;
        while (index < lines.length && lines[index].includes('|') && lines[index].trim()) { rows.push(markdownCells(lines[index])); index += 1; }
        index -= 1; html.push(`<div class="script-markdown-table"><table><thead><tr>${headers.map(cell => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
      }
      if (!line.trim()) { flushParagraph(); closeList(); continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/); if (heading) { flushParagraph(); closeList(); const level = heading[1].length; html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
      if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { flushParagraph(); closeList(); html.push('<hr>'); continue; }
      const unordered = line.match(/^\s*[-+*]\s+(.+)$/), ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (unordered || ordered) { flushParagraph(); const nextType = unordered ? 'ul' : 'ol'; if (listType !== nextType) { closeList(); listType = nextType; html.push(`<${listType}>`); } html.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`); continue; }
      const quote = line.match(/^\s*>\s?(.*)$/); if (quote) { flushParagraph(); closeList(); html.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
      paragraph.push(line);
    }
    if (inCode) html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
    flushParagraph(); closeList(); return html.join('') || '<p class="script-markdown-empty">暂无内容</p>';
  }
  window.TophooMarkdown = {render: markdownToHtml};
  const root = document.querySelector('[data-crm-communication-scripts]');
  if (!root) return;
  const tree = root.querySelector('[data-script-tree]'), detail = root.querySelector('[data-script-detail]'), search = root.querySelector('[data-script-search]');
  const directoryButton=root.querySelector('[data-script-toggle-directory]');
  const directoryMedia=matchMedia('(max-width:1100px)');
  let directoryTouched=false;
  function setDirectory(collapsed){root.classList.toggle('is-directory-collapsed',collapsed);directoryButton.setAttribute('aria-expanded',String(!collapsed));directoryButton.textContent=collapsed?'展开目录':'收起目录';}
  setDirectory(directoryMedia.matches);
  directoryButton.onclick=()=>{directoryTouched=true;setDirectory(!root.classList.contains('is-directory-collapsed'));};
  directoryMedia.addEventListener('change',event=>{if(!directoryTouched)setDirectory(event.matches);});
  document.addEventListener('click',event=>{const more=detail.querySelector('.script-reader-more[open]');if(more&&!more.contains(event.target))more.open=false;});
  const pid = () => Number(localStorage.getItem('tophoo-global-selected-project')) || 0, headers = () => window.tophooAuth?.headers?.() || {};
  let state = {categories: [], scripts: []}, selectedCategory = null, expanded = new Set(), editingCategory = null, selectedScript = null, loadedProject = 0, loadVersion = 0, editorBaseline = '', saving = false;
  const children = parentId => state.categories.filter(item => (item.parent_id || null) === (parentId || null));
  const category = id => state.categories.find(item => item.id === Number(id));
  async function request(url, options = {}) {
    const project = pid(), auth = JSON.stringify(headers());
    const response = await fetch(url, {...options, headers: {...headers(), ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (project !== pid() || auth !== JSON.stringify(headers())) throw new Error('项目或登录状态已切换，请在当前项目重新操作。');
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请稍后再试。');
    return data;
  }
  const selectionKey = () => 'tophoo-global-knowledge-selection-' + pid();
  function remember() { sessionStorage.setItem(selectionKey(), JSON.stringify({category: selectedCategory, script: selectedScript, query: search.value, expanded: Array.from(expanded)})); }
  function editorValue() { const form = detail.querySelector('[data-script-editor]'); return form ? JSON.stringify(Array.from(new FormData(form).entries())) : ''; }
  function dirty() { return !!editorBaseline && editorValue() !== '' && editorValue() !== editorBaseline; }
  function canLeave() { if (saving) return false; if (dirty() && !confirm('有未保存的修改，确定放弃并离开吗？')) return false; editorBaseline = ''; return true; }
  function pathOf(id) { const names = [], seen = new Set(); let item = category(id); while (item && !seen.has(item.id)) { seen.add(item.id); names.unshift(item.name); item = category(item.parent_id); } return names.join(' / '); }
  function matches(entry, key) { return !key || (entry.title + '\n' + entry.content + '\n' + pathOf(entry.category_id)).toLowerCase().includes(key); }
  const categoryMatch = (item, key) => !key || item.name.toLowerCase().includes(key) || state.scripts.some(entry => entry.category_id === item.id && matches(entry, key)) || children(item.id).some(child => categoryMatch(child, key));
  function node(item, key) { const nested = children(item.id).filter(child => categoryMatch(child, key)); if (!categoryMatch(item, key)) return ''; const open = expanded.has(item.id) || Boolean(key && nested.length); return `<section><div class="script-tree-row ${selectedCategory === item.id ? 'is-active' : ''}"><button type="button" class="script-tree-toggle" data-script-toggle="${item.id}" aria-label="${open ? '收起' : '展开'}${esc(item.name)}" ${nested.length ? `aria-expanded="${open}"` : 'disabled'}>${nested.length ? (open ? '▾' : '▸') : '·'}</button><span class="script-tree-icon">${nested.length ? (open ? '📂' : '📁') : '◇'}</span><button type="button" class="script-tree-label" title="${esc(item.name)}" data-script-category="${item.id}" aria-current="${selectedCategory === item.id ? 'true' : 'false'}"><strong>${esc(item.name)}</strong></button><span class="script-tree-count">${state.scripts.filter(entry => entry.category_id === item.id).length}</span><span class="script-tree-tools"><button type="button" data-script-category-menu-toggle="${item.id}" aria-label="${esc(item.name)}：分类操作" aria-expanded="false" aria-controls="knowledge-category-menu" title="分类操作">⋯</button></span></div>${open && nested.length ? `<div class="script-tree-children">${nested.map(child => node(child, key)).join('')}</div>` : ''}</section>`; }
  function renderTree() { const scrollTop = tree.scrollTop; closeCategoryMenu(); const key = search.value.trim().toLowerCase(), roots = children(null).filter(item => categoryMatch(item, key)); tree.innerHTML = roots.length ? roots.map(item => node(item, key)).join('') : `<p class="script-tree-empty">${key ? '没有匹配的分类。' : '还没有分类。点击“＋ 分类”建立目录。'}</p>`; tree.querySelectorAll('[data-script-toggle]').forEach(button => button.onclick = () => { const id = Number(button.dataset.scriptToggle); if (!children(id).length) return; expanded.has(id) ? expanded.delete(id) : expanded.add(id); renderTree(); remember(); }); tree.querySelectorAll('[data-script-category]').forEach(button => button.onclick = () => selectCategory(Number(button.dataset.scriptCategory))); tree.querySelectorAll('[data-script-category-menu-toggle]').forEach(button => button.onclick = () => openCategoryMenu(Number(button.dataset.scriptCategoryMenuToggle), button)); tree.scrollTop = scrollTop; }
  function clearDetail() { selectedCategory = null; selectedScript = null; renderLibrary(); }
  function selectCategory(id) {
    if (!canLeave()) return;
    if (id != null && !category(id)) return;
    selectedCategory = id == null ? null : Number(id); selectedScript = null;
    let parent = category(id); const seen = new Set();
    while (parent && !seen.has(parent.id)) { seen.add(parent.id); expanded.add(parent.id); parent = category(parent.parent_id); }
    search.value = ''; remember(); renderLibrary(true);
  }
  function renderLibrary(resetList = false) {
    detail.classList.remove('is-editing'); root.classList.remove('is-editing');
    search.dataset.appliedQuery = search.value;
    const previousList = resetList ? null : detail.querySelector('.script-entry-list');
    const listScrollTop = previousList?.scrollTop || 0, listScrollLeft = previousList?.scrollLeft || 0;
    const item = category(selectedCategory), key = search.value.trim().toLowerCase();
    const entries = state.scripts.filter(entry => (!item || entry.category_id === item.id) && matches(entry, key));
    if (!entries.some(entry => entry.id === selectedScript)) selectedScript = entries[0]?.id || null;
    if (!selectedScript) toggleReading(false);
    root.querySelector('[data-script-path]').textContent = item ? pathOf(item.id) : '当前项目 / 全部知识';
    root.querySelector('[data-script-detail-title]').textContent = item?.name || '全部知识';
    root.querySelector('[data-script-add]').hidden = !state.categories.length;
    const exportButton = root.querySelector('[data-script-export-category]');
    exportButton.hidden = !item; exportButton.disabled = !state.scripts.some(entry => entry.category_id === item?.id);
    const summary = root.querySelector('[data-script-library-summary]');
    summary.textContent = state.categories.length; summary.title = state.categories.length + ' 个分类 · ' + state.scripts.length + ' 条知识';
    root.querySelector('[data-script-clear-search]').hidden = !key;
    root.querySelector('[data-script-all]').classList.toggle('is-active', !item);
    detail.innerHTML = `<div class="script-library-grid"><section class="script-entry-panel" aria-label="知识条目列表"><header><strong>${key ? '搜索结果' : '知识条目'}</strong><span>${entries.length} 条</span></header><div class="script-entry-list">${entries.length ? entries.map(entry => `<button type="button" class="script-entry ${entry.id === selectedScript ? 'is-active' : ''}" data-script-read="${entry.id}" aria-pressed="${entry.id === selectedScript}"><strong>${esc(entry.title)}</strong></button>`).join('') : '<div class="script-empty"><h2>' + (key ? '没有找到相关知识' : '暂无知识条目') + '</h2><p>' + (key ? '试试其他关键词，或切换到全部知识搜索。' : '先创建分类，再点击“＋ 条目”添加内容。') + '</p></div>'}</div></section><section class="script-reader" data-script-reader aria-label="知识正文"></section></div>`;
    const nextList = detail.querySelector('.script-entry-list'); nextList.scrollTop = listScrollTop; nextList.scrollLeft = listScrollLeft;
    detail.querySelectorAll('[data-script-read]').forEach(button => button.onclick = () => selectEntry(Number(button.dataset.scriptRead)));
    nextList.onkeydown = event => {
      const buttons = Array.from(nextList.querySelectorAll('[data-script-read]'));
      const index = buttons.indexOf(event.target); if (index < 0) return;
      let next;
      if (event.key === 'ArrowDown') next = Math.min(index + 1, buttons.length - 1);
      else if (event.key === 'ArrowUp') next = Math.max(index - 1, 0);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = buttons.length - 1;
      else return;
      event.preventDefault(); selectEntry(Number(buttons[next].dataset.scriptRead)); buttons[next].focus();
    };
    renderReader(); renderTree(); remember();
  }
  function selectEntry(id) {
    const button = detail.querySelector(`[data-script-read="${id}"]`);
    if (!button || id === selectedScript) return;
    selectedScript = id;
    detail.querySelectorAll('[data-script-read]').forEach(item => {
      const active = Number(item.dataset.scriptRead) === id;
      item.classList.toggle('is-active', active); item.setAttribute('aria-pressed', String(active));
    });
    renderReader();
    remember(); button.focus({preventScroll:true});
  }
  function readerFindMarkup() {
    return `<div class="script-reader-find" role="search" aria-label="查找当前条目正文">
      <div class="script-reader-find-input"><input type="search" data-reader-find placeholder="查找本条目内容…" aria-label="查找本条目内容" autocomplete="off" spellcheck="false" maxlength="200" title="Ctrl / ⌘ + F 查找正文；Enter 下一处，Shift + Enter 上一处"><button type="button" data-reader-find-clear aria-label="清除正文查找" title="清除查找" disabled>×</button></div>
      <output data-reader-find-status aria-live="polite" aria-atomic="true">输入关键词定位正文</output>
      <div class="script-reader-find-nav"><button type="button" data-reader-find-prev aria-label="上一个匹配" title="上一个（Shift + Enter）" disabled>↑</button><button type="button" data-reader-find-next aria-label="下一个匹配" title="下一个（Enter）" disabled>↓</button></div>
    </div>`;
  }
  function mountReaderFind(reader, initialQuery = '') {
    const body = reader.querySelector(':scope > .script-markdown-render'), input = reader.querySelector('[data-reader-find]');
    const status = reader.querySelector('[data-reader-find-status]'), previous = reader.querySelector('[data-reader-find-prev]'), next = reader.querySelector('[data-reader-find-next]'), clear = reader.querySelector('[data-reader-find-clear]');
    let hits = [], active = -1, applied = '', timer, composing = false;
    function jump(index) {
      if (!hits.length) return;
      if (active >= 0) hits[active].forEach(mark => mark.classList.remove('is-current'));
      active = (index + hits.length) % hits.length;
      hits[active].forEach(mark => mark.classList.add('is-current'));
      status.textContent = `${active + 1} / ${hits.length} 处`;
      const mark = hits[active][0], table = mark.closest('.script-markdown-table');
      if (table) {
        const rect = mark.getBoundingClientRect(), bounds = table.getBoundingClientRect();
        if (rect.left < bounds.left || rect.right > bounds.right) table.scrollLeft += rect.left - bounds.left - (table.clientWidth - rect.width) / 2;
      }
      const rect = mark.getBoundingClientRect(), bounds = body.getBoundingClientRect();
      body.scrollTop += rect.top - bounds.top - (body.clientHeight - rect.height) / 2;
    }
    function find() {
      clearTimeout(timer);
      if (!body.isConnected) return;
      body.querySelectorAll('mark[data-reader-hit]').forEach(mark => mark.replaceWith(...mark.childNodes));
      body.normalize(); hits = []; active = -1;
      const query = input.value.trim(); applied = input.value;
      clear.disabled = !input.value;
      if (query) {
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT), segments = [];
        let text = '', lastBlock = null, node;
        while ((node = walker.nextNode())) {
          const block = node.parentElement.closest('p,h1,h2,h3,h4,h5,h6,li,td,th,pre,blockquote') || body;
          if (lastBlock && block !== lastBlock) text += '\n';
          segments.push({node, start:text.length, end:text.length + node.length});
          text += node.data; lastBlock = block;
        }
        // Search literal text, including phrases split by bold, links or other inline markup.
        const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu');
        const matches = Array.from(text.matchAll(pattern));
        hits = matches.map(() => []);
        let firstMatch = 0;
        for (const segment of segments) {
          while (firstMatch < matches.length && matches[firstMatch].index + matches[firstMatch][0].length <= segment.start) firstMatch++;
          const ranges = [];
          for (let index = firstMatch; index < matches.length && matches[index].index < segment.end; index++) {
            const match = matches[index];
            ranges.push({start:Math.max(0, match.index - segment.start), end:Math.min(segment.node.length, match.index + match[0].length - segment.start), hit:index});
          }
          if (!ranges.length) continue;
          const fragment = document.createDocumentFragment(); let offset = 0;
          for (const range of ranges) {
            fragment.append(document.createTextNode(segment.node.data.slice(offset, range.start)));
            const mark = document.createElement('mark'); mark.dataset.readerHit = String(range.hit);
            mark.textContent = segment.node.data.slice(range.start, range.end); hits[range.hit].push(mark);
            fragment.append(mark); offset = range.end;
          }
          fragment.append(document.createTextNode(segment.node.data.slice(offset)));
          segment.node.replaceWith(fragment);
        }
      }
      previous.disabled = next.disabled = !hits.length;
      status.textContent = query ? (hits.length ? `1 / ${hits.length} 处` : '未找到匹配内容') : '输入关键词定位正文';
      if (hits.length) jump(0);
    }
    function step(direction) {
      if (applied !== input.value) { find(); if (direction < 0) jump(hits.length - 1); }
      else jump(active + direction);
    }
    input.addEventListener('input', () => { clearTimeout(timer); if (!composing) timer = setTimeout(find, 120); });
    input.addEventListener('compositionstart', () => { composing = true; clearTimeout(timer); });
    input.addEventListener('compositionend', () => { composing = false; find(); });
    input.addEventListener('keydown', event => {
      if (event.isComposing || composing) return;
      if (event.key === 'Enter') { event.preventDefault(); step(event.shiftKey ? -1 : 1); }
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); input.value = ''; find(); input.blur(); }
    });
    clear.onclick = () => { input.value = ''; find(); input.focus({preventScroll:true}); };
    previous.onclick = () => step(-1); next.onclick = () => step(1);
    input.value = initialQuery.slice(0, 200); if (input.value) find();
  }
  const entryMarkup=entry=>entry.content_format==='email'?window.TophooRichMail.clean(entry.content_html||window.TophooRichMail.escape(entry.content).replace(/\n/g,'<br>')):markdownToHtml(entry.content);
  function renderReader() {
    const reader = detail.querySelector('[data-script-reader]'), entry = state.scripts.find(item => item.id === selectedScript);
    if (!entry) { reader.innerHTML = '<div class="script-empty"><span>◇</span><h2>让知识随手可用</h2><p>在左侧选择条目，即可直接阅读、复制和编辑。</p></div>'; return; }
    const siblings = state.scripts.filter(item => item.category_id === entry.category_id), index = siblings.findIndex(item => item.id === entry.id);
    reader.innerHTML = `<header class="script-reader-head"><small>${esc(pathOf(entry.category_id))}</small><h2>${esc(entry.title)}</h2><div class="script-reader-actions"><button type="button" data-reader-copy>复制</button><button type="button" data-reader-edit>编辑</button><button type="button" class="script-reader-open" data-reader-preview aria-haspopup="dialog">↗ 放大阅读</button><details class="script-reader-more"><summary>更多 ⋯</summary><div class="script-reader-more-menu"><button type="button" data-reader-export>导出条目 PDF</button><button type="button" data-reader-up title="在所属分类内上移" ${index <= 0 ? 'disabled' : ''}>↑ 上移</button><button type="button" data-reader-down title="在所属分类内下移" ${index === siblings.length - 1 ? 'disabled' : ''}>↓ 下移</button><button type="button" class="script-reader-delete" data-reader-delete>删除</button></div></details></div>${readerFindMarkup()}</header><div class="script-markdown-render">${entryMarkup(entry)}</div>`;
    reader.querySelector('[data-reader-copy]').onclick = event => copyScript(entry.id, event.currentTarget);
    reader.querySelector('[data-reader-edit]').onclick = () => openScript(entry);
    reader.querySelector('[data-reader-preview]').onclick = () => toggleReading();
    reader.querySelector('[data-reader-export]').onclick = event => exportScriptPdf(entry, event.currentTarget);
    reader.querySelector('[data-reader-delete]').onclick = () => deleteScript(entry.id);
    reader.querySelector('[data-reader-up]').onclick = () => moveScript(entry.id, 'up');
    reader.querySelector('[data-reader-down]').onclick = () => moveScript(entry.id, 'down');
    mountReaderFind(reader, search.value.trim());
  }
  const contentPreview=root.querySelector('[data-script-content-preview]'),previewBody=root.querySelector('[data-script-preview-body]');
  function closeContentPreview(){if(contentPreview.open)contentPreview.close();previewBody.replaceChildren();}
  function toggleReading(force){
    if(force===false||contentPreview.open){closeContentPreview();return;}
    const entry=state.scripts.find(item=>item.id===selectedScript);if(!entry)return;
    closeCategoryMenu();
    const more=detail.querySelector('.script-reader-more[open]');if(more)more.open=false;
    previewBody.innerHTML=entryMarkup(entry);
    contentPreview.setAttribute('aria-label',entry.title+' · 正文预览');contentPreview.showModal();previewBody.scrollTop=0;
  }
  root.querySelector('[data-script-preview-close]').onclick=closeContentPreview;
  contentPreview.addEventListener('cancel',event=>{event.preventDefault();closeContentPreview();});
  async function copyText(value) { if (navigator.clipboard?.writeText) { try { await navigator.clipboard.writeText(value); return; } catch {} } const field = document.createElement('textarea'); field.value = value; field.setAttribute('readonly', ''); field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'; document.body.append(field); field.select(); field.setSelectionRange(0, field.value.length); const copied = document.execCommand('copy'); field.remove(); if (!copied) throw new Error('copy_failed'); }
  function markCopied(button) { const original = button.innerHTML; button.classList.add('is-copied'); button.innerHTML = '<span>✓</span>已复制'; setTimeout(() => { button.classList.remove('is-copied'); button.innerHTML = original; }, 1500); }
  async function copyScript(id, button) { const item = state.scripts.find(entry => entry.id === id); if (!item) return; try { if(item.content_format==='email'&&item.content_html){const html=window.TophooRichMail.clean(item.content_html);if(!navigator.clipboard?.write||!window.ClipboardItem)throw Error('rich_clipboard_unavailable');await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),'text/plain':new Blob([item.content],{type:'text/plain'})})]);}else await copyText(item.content); markCopied(button); } catch { alert('复制失败，请选中正文复制；富文本也可在开发信中通过“知识库”直接插入。'); } }
  async function exportScriptPdf(entry, button) {
    if (button.disabled) return;
    const project = pid(), auth = JSON.stringify(headers());
    button.disabled = true; button.textContent = '导出中…';
    let blobUrl;
    try {
      const response = await fetch(`/api/communication-scripts/projects/${project}/scripts/${entry.id}/export/pdf`, {headers: headers()});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '导出失败，请稍后重试。');
      }
      const blob = await response.blob();
      if (project !== pid() || auth !== JSON.stringify(headers())) throw new Error('项目或登录状态已切换，请在当前项目重新导出。');
      const disposition = response.headers.get('Content-Disposition') || '';
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      if (!encodedName || !response.headers.get('Content-Type')?.includes('application/pdf')) throw new Error('导出文件异常，请重试。');
      const link = document.createElement('a');
      blobUrl = URL.createObjectURL(blob); link.href = blobUrl;
      link.download = decodeURIComponent(encodedName); document.body.append(link); link.click(); link.remove();
    } catch (error) { alert(error.message); }
    finally {
      if (blobUrl) setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      button.disabled = false; button.textContent = '导出条目 PDF';
    }
  }
  function categoryOptions(item = null) { const blocked = new Set(); const collect = id => children(id).forEach(child => { blocked.add(child.id); collect(child.id); }); if (item) { blocked.add(item.id); collect(item.id); } const options = (parentId, depth = 0) => children(parentId).filter(candidate => !blocked.has(candidate.id)).map(candidate => `<option value="${candidate.id}" ${item?.parent_id === candidate.id ? 'selected' : ''}>${'　'.repeat(depth)}${esc(candidate.name)}</option>${options(candidate.id, depth + 1)}`).join(''); return '<option value="">作为顶级分类</option>' + options(null); }
  function openCategory(item = null) { if (!canLeave()) return; if (detail.querySelector('[data-script-editor]')) renderLibrary(); editingCategory = item; const dialog = root.querySelector('[data-script-category-dialog]'), form = root.querySelector('[data-script-category-form]'); form.querySelector('[name="name"]').value = item?.name || ''; form.querySelector('[name="parent_id"]').innerHTML = categoryOptions(item); dialog.hidden = false; form.querySelector('[name="name"]').focus(); }
  function closeCategory() { root.querySelector('[data-script-category-dialog]').hidden = true; editingCategory = null; }
  function scriptCategoryOptions(selectedId) { const build = (parentId, depth = 0) => children(parentId).map(item => `<option value="${item.id}" ${item.id === Number(selectedId) ? 'selected' : ''}>${'　'.repeat(depth)}${esc(item.name)}</option>${build(item.id, depth + 1)}`).join(''); return build(null); }
  function mountEditorFind(form, textarea, setMode) {
    const input = form.querySelector('[data-editor-find]'), status = form.querySelector('[data-editor-find-status]');
    const previous = form.querySelector('[data-editor-find-prev]'), next = form.querySelector('[data-editor-find-next]'), clear = form.querySelector('[data-editor-find-clear]');
    let hits = [], active = -1, timer = null, composing = false;
    function jump(index, focus = false) {
      if (!hits.length || textarea.disabled) return;
      active = (index + hits.length) % hits.length;
      const hit = hits[active];
      if (form.dataset.editorMode === 'preview') { setMode('edit'); if (!focus) input.focus({preventScroll:true}); }
      // Measure wrapped source text instead of estimating by line count.
      const style = getComputedStyle(textarea), mirror = document.createElement('div');
      for (const property of ['fontFamily','fontSize','fontWeight','fontStyle','lineHeight','letterSpacing','wordSpacing','textIndent','tabSize','paddingTop','paddingRight','paddingBottom','paddingLeft']) mirror.style[property] = style[property];
      Object.assign(mirror.style, {position:'fixed',left:'-100000px',top:'0',visibility:'hidden',boxSizing:'border-box',width:`${textarea.clientWidth}px`,whiteSpace:'pre-wrap',overflowWrap:'break-word'});
      mirror.textContent = textarea.value.slice(0, hit.start);
      const marker = document.createElement('span'); marker.textContent = textarea.value.slice(hit.start, hit.end); mirror.append(marker);
      document.body.append(mirror);
      const y = marker.getBoundingClientRect().top - mirror.getBoundingClientRect().top;
      mirror.remove();
      textarea.setSelectionRange(hit.start, hit.end);
      if (focus) textarea.focus({preventScroll:true});
      textarea.scrollTop = Math.max(0, y - textarea.clientHeight / 2 + parseFloat(style.lineHeight) / 2);
      status.textContent = `${active + 1} / ${hits.length} 处`;
    }
    function find(locate = true) {
      clearTimeout(timer); timer = null; hits = []; active = -1;
      const query = input.value;
      if (query) {
        const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu');
        hits = Array.from(textarea.value.matchAll(pattern), match => ({start:match.index,end:match.index + match[0].length}));
      }
      previous.disabled = next.disabled = !hits.length; clear.disabled = !query;
      status.textContent = query ? (hits.length ? `${hits.length} 处` : '未找到匹配内容') : '输入关键词定位内容';
      if (locate && hits.length) jump(0);
      else if (hits.length) {
        active = hits.findIndex(hit => hit.start >= textarea.selectionStart);
        if (active < 0) active = hits.length - 1;
        status.textContent = `${active + 1} / ${hits.length} 处`;
      }
    }
    function step(direction, focus = false) {
      if (timer) { find(); jump(direction < 0 ? hits.length - 1 : 0, focus); }
      else jump(active + direction, focus);
    }
    input.addEventListener('input', event => { event.stopPropagation(); clearTimeout(timer); timer = null; if (!composing) timer = setTimeout(() => find(), 120); });
    input.addEventListener('compositionstart', () => { composing = true; clearTimeout(timer); timer = null; });
    input.addEventListener('compositionend', () => { composing = false; find(); });
    input.addEventListener('keydown', event => {
      if (event.isComposing || composing) return;
      if (event.key === 'Enter') { event.preventDefault(); step(event.shiftKey ? -1 : 1); }
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); input.value = ''; find(false); textarea.focus({preventScroll:true}); }
    });
    previous.onclick = () => step(-1, true); next.onclick = () => step(1, true);
    clear.onclick = () => { input.value = ''; find(false); input.focus({preventScroll:true}); };
    textarea.addEventListener('input', () => find(false));
    form.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'f') {
        event.preventDefault(); event.stopPropagation();
        const selected = textarea.value.slice(textarea.selectionStart, textarea.selectionEnd);
        if (document.activeElement === textarea && selected && selected.length <= input.maxLength && !selected.includes('\n')) input.value = selected;
        input.focus({preventScroll:true}); input.select(); if (input.value) find();
      }
    });
  }
  function mountMarkdownEditor(form) {
    const textarea = form.querySelector('[name="content"]'), live = form.querySelector('[data-md-live]');
    const limit = textarea.maxLength, undo = form.querySelector('[data-md-action="undo"]'), redo = form.querySelector('[data-md-action="redo"]');
    const snapshot = () => ({value: textarea.value, start: textarea.selectionStart, end: textarea.selectionEnd, scroll: textarea.scrollTop});
    let history = [snapshot()], position = 0, restoring = false, composing = false;
    const rememberSelection = () => { if (history[position].value === textarea.value) history[position] = snapshot(); };
    const refresh = () => {
      const previewScroll = live.scrollTop;
      live.innerHTML = markdownToHtml(textarea.value); live.scrollTop = previewScroll;
      undo.disabled = position === 0; redo.disabled = position === history.length - 1;
      form.querySelector('[data-editor-count]').textContent = `${textarea.value.length.toLocaleString()} / ${limit.toLocaleString()} 字符`;
    };
    const change = () => {
      if (!restoring && !composing && history[position].value !== textarea.value) {
        history = history.slice(0, position + 1); history.push(snapshot());
        if (history.length > 100) history.shift();
        position = history.length - 1;
      }
      refresh();
    };
    function restore(next) {
      if (next < 0 || next >= history.length) return;
      rememberSelection(); position = next;
      const item = history[position]; restoring = true;
      textarea.value = item.value; textarea.focus({preventScroll:true});
      textarea.setSelectionRange(item.start, item.end); textarea.scrollTop = item.scroll;
      textarea.dispatchEvent(new Event('input', {bubbles:true})); restoring = false;
    }
    function replace(start, end, value, selectionStart, selectionEnd = selectionStart) {
      if (textarea.value.length - (end - start) + value.length > limit) {
        form.querySelector('[data-editor-status]').textContent = `内容最多 ${limit.toLocaleString()} 字符，请精简后重试`; return;
      }
      rememberSelection(); const scroll = textarea.scrollTop;
      textarea.setRangeText(value, start, end, 'preserve'); textarea.focus({preventScroll:true});
      textarea.setSelectionRange(selectionStart, selectionEnd); textarea.scrollTop = scroll;
      textarea.dispatchEvent(new Event('input', {bubbles:true}));
    }
    function inline(marker, fallback) {
      const start = textarea.selectionStart, end = textarea.selectionEnd, value = textarea.value, selected = value.slice(start, end);
      if (selected.includes('\n') && selected.trim()) {
        const parts = selected.split('\n');
        const wrapped = line => line.length >= marker.length * 2 && line.startsWith(marker) && line.endsWith(marker);
        const remove = parts.every(line => !line.trim() || wrapped(line));
        const content = parts.map(line => !line.trim() ? line : remove ? line.slice(marker.length, -marker.length) : wrapped(line) ? line : marker + line + marker).join('\n');
        replace(start, end, content, start, start + content.length); return;
      }
      if (value.slice(Math.max(0, start - marker.length), start) === marker && value.slice(end, end + marker.length) === marker) {
        replace(start - marker.length, end + marker.length, selected, start - marker.length, end - marker.length);
      } else if (selected.length >= marker.length * 2 && selected.startsWith(marker) && selected.endsWith(marker)) {
        const content = selected.slice(marker.length, -marker.length);
        replace(start, end, content, start, start + content.length);
      } else {
        const content = selected || fallback;
        replace(start, end, marker + content + marker, start + marker.length, start + marker.length + content.length);
      }
    }
    function lines(kind) {
      const value = textarea.value, from = textarea.selectionStart, to = textarea.selectionEnd;
      const start = from === 0 ? 0 : value.lastIndexOf('\n', from - 1) + 1;
      const last = to > from && value[to - 1] === '\n' ? to - 1 : to;
      const found = value.indexOf('\n', last), end = found < 0 ? value.length : found;
      const selected = value.slice(start, end).split('\n');
      const pattern = kind === 'quote' ? /^>\s?/ : kind === 'list' ? /^[-+*]\s+/ : kind === 'ordered' ? /^\d+[.)]\s+/ : new RegExp(`^#{${kind}}\\s+`);
      const remove = selected.some(line => pattern.test(line)) && selected.every(line => !line.trim() || pattern.test(line));
      let index = 0;
      const content = selected.map(line => {
        if (remove) return line.replace(pattern, '');
        if (!line.trim() && selected.length > 1) return line;
        const plain = line.replace(kind === 'quote' ? /^>\s?/ : /^(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+)/, '');
        const prefix = kind === 'quote' ? '> ' : kind === 'list' ? '- ' : kind === 'ordered' ? `${++index}. ` : '#'.repeat(kind) + ' ';
        return prefix + (plain || (kind === 'quote' ? '引用内容' : Number.isInteger(kind) ? '标题' : '列表项'));
      }).join('\n');
      replace(start, end, content, start, start + content.length);
    }
    function block(content, selectOffset = 0, selectLength = content.length) {
      const start = textarea.selectionStart, end = textarea.selectionEnd, value = textarea.value;
      const before = start && !value.slice(0, start).endsWith('\n\n') ? (value[start - 1] === '\n' ? '\n' : '\n\n') : '';
      const after = end < value.length && !value.slice(end).startsWith('\n\n') ? (value[end] === '\n' ? '\n' : '\n\n') : '';
      replace(start, end, before + content + after, start + before.length + selectOffset, start + before.length + selectOffset + selectLength);
    }
    const actions = {
      undo: () => restore(position - 1), redo: () => restore(position + 1),
      heading1: () => lines(1), heading: () => lines(2), heading3: () => lines(3),
      bold: () => inline('**', '粗体文字'), italic: () => inline('*', '斜体文字'), strike: () => inline('~~', '删除线文字'),
      list: () => lines('list'), ordered: () => lines('ordered'), quote: () => lines('quote'),
      inline: () => inline('`', '代码'),
      code: () => { const selected = textarea.value.slice(textarea.selectionStart, textarea.selectionEnd) || '代码内容'; block('```\n' + selected + '\n```', 4, selected.length); },
      link: () => { const start = textarea.selectionStart, end = textarea.selectionEnd; const label = textarea.value.slice(start, end) || '链接文字', url = 'https://example.com'; replace(start, end, `[${label}](${url})`, start + label.length + 3, start + label.length + 3 + url.length); },
      table: () => block('| 项目 | 内容 |\n| --- | --- |\n| 示例 | 说明 |', 2, 2),
      divider: () => block('---', 3, 0)
    };
    form.querySelectorAll('[data-md-action]').forEach(button => {
      // Keep the textarea selection when a mouse user clicks the toolbar.
      button.onmousedown = event => event.preventDefault();
      button.onclick = () => {
        if (composing) return;
        if (form.dataset.editorMode === 'preview') setMode('edit');
        actions[button.dataset.mdAction]?.();
      };
    });
    const setMode = mode => {
      form.dataset.editorMode = mode;
      form.querySelectorAll('[data-editor-mode-button]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.editorModeButton === mode)));
      if (mode !== 'preview') textarea.focus({preventScroll:true});
    };
    form.querySelectorAll('[data-editor-mode-button]').forEach(button => button.onclick = () => setMode(button.dataset.editorModeButton));
    textarea.addEventListener('invalid', () => { if (form.dataset.editorMode === 'preview') setMode('edit'); });
    form.dataset.editorMode = window.matchMedia('(max-width:900px)').matches ? 'edit' : 'split';
    form.querySelectorAll('[data-editor-mode-button]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.editorModeButton === form.dataset.editorMode)));
    textarea.addEventListener('input', change);
    textarea.addEventListener('beforeinput', event => {
      if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') { event.preventDefault(); restore(position + (event.inputType === 'historyUndo' ? -1 : 1)); }
      else rememberSelection();
    });
    ['select', 'click', 'keyup', 'blur'].forEach(name => textarea.addEventListener(name, rememberSelection));
    textarea.addEventListener('compositionstart', () => { rememberSelection(); composing = true; });
    textarea.addEventListener('compositionend', () => { composing = false; change(); });
    textarea.addEventListener('keydown', event => {
      if (event.isComposing || composing || !(event.ctrlKey || event.metaKey) || event.altKey) return;
      const key = event.key.toLowerCase();
      const action = key === 'z' ? (event.shiftKey ? 'redo' : 'undo') : key === 'y' ? 'redo' : ({b:'bold', i:'italic', k:'link'})[key];
      if (action) { event.preventDefault(); actions[action](); }
    });
    mountEditorFind(form, textarea, setMode);
    refresh();
  }

  function openScript(item = null) {
    if (!canLeave()) return;
    const editorProject = pid(), editorAuth = JSON.stringify(headers());
    if (!selectedCategory) selectedCategory = item?.category_id || state.categories[0]?.id;
    if (!selectedCategory) return;
    detail.classList.add('is-editing'); root.classList.add('is-editing'); detail.scrollTop = 0;
    const button = (action, label, title) => `<button type="button" data-md-action="${action}" aria-label="${title}" title="${title}">${label}</button>`;
    detail.innerHTML = `<form class="script-editor" data-script-editor>
      <div class="script-editor-actions script-editor-actions-top"><span data-editor-status role="status">Ctrl / ⌘ + S 保存</span><div><button type="button" data-script-editor-cancel>取消</button><button type="submit">保存</button></div></div>
      <div class="script-editor-meta"><label>标题<input name="title" required maxlength="260" value="${esc(item?.title || '')}" placeholder="例如：首次回复询盘"></label><label>所属分类<select name="category_id">${scriptCategoryOptions(item?.category_id || selectedCategory)}</select></label></div>
      <section class="script-markdown-field" aria-label="知识内容编辑器">
        <div class="script-markdown-label"><label class="knowledge-format-choice">内容格式<select name="content_format"><option value="markdown">Markdown</option><option value="email">富文本</option></select></label><label for="knowledge-content">内容 <small>支持 Markdown</small></label><div class="script-editor-modes" role="group" aria-label="编辑视图"><button type="button" data-editor-mode-button="edit">编辑</button><button type="button" data-editor-mode-button="split">对照</button><button type="button" data-editor-mode-button="preview">预览</button></div></div>
        <div class="script-markdown-toolbar" role="group" aria-label="Markdown 格式工具">
          <span class="script-format-group">${button('undo','↶','撤销（Ctrl / ⌘ + Z）')}${button('redo','↷','重做（Ctrl / ⌘ + Shift + Z）')}</span>
          <span class="script-format-group">${button('heading1','H1','一级标题')}${button('heading','H2','二级标题')}${button('heading3','H3','三级标题')}</span>
          <span class="script-format-group">${button('bold','<strong>B</strong>','加粗（Ctrl / ⌘ + B）')}${button('italic','<em>I</em>','斜体（Ctrl / ⌘ + I）')}${button('strike','<s>S</s>','删除线')}</span>
          <span class="script-format-group">${button('list','• 列表','无序列表')}${button('ordered','1. 列表','编号列表')}${button('quote','❯ 引用','引用')}</span>
          <span class="script-format-group">${button('link','↗ 链接','链接（Ctrl / ⌘ + K）')}${button('table','▦ 表格','插入表格')}${button('inline','&#96;代码','行内代码')}${button('code','&lt;/&gt;','代码块')}${button('divider','—','分隔线')}</span>
        </div>
        ${readerFindMarkup().replaceAll("data-reader-find", "data-editor-find").replace('class="script-reader-find"', 'class="script-reader-find script-editor-find"').replaceAll("查找本条目内容", "查找编辑内容").replaceAll("正文", "编辑内容")}
        <div class="script-markdown-editor-grid"><textarea id="knowledge-content" name="content" required maxlength="50000" rows="18" spellcheck="false" placeholder="在这里输入内容，可选中文字后点击上方按钮设置格式。">${esc(item?.content || '')}</textarea><section class="script-live-preview" aria-label="内容预览"><header><span>实时预览</span><small>MARKDOWN</small></header><div class="script-markdown-render" data-md-live></div></section></div>
        <footer class="script-editor-footer"><span>选中文字设置格式 · 再次点击可取消</span><span data-editor-count></span></footer>
      </section>
    </form>`;
    const form = detail.querySelector('[data-script-editor]'), textarea = form.querySelector('[name="content"]');
    const emailMode=item?.content_format==='email';let rich=null;
    form.querySelector('[name="content_format"]').value=emailMode?'email':'markdown';
    if(emailMode){
      const section=form.querySelector('.script-markdown-field'),formatChoice=form.querySelector('.knowledge-format-choice');
      section.innerHTML='<div class="knowledge-mail-heading">富文本 <small>支持图片、表格及带格式签名，可在开发信中直接引用</small></div><textarea name="content" hidden></textarea><textarea name="content_html" hidden></textarea><div data-knowledge-mail-body></div>';
      section.prepend(formatChoice);
      rich=window.TophooRichMail.mount(section.querySelector('[data-knowledge-mail-body]'));rich.set(item?.content_html,item?.content);
      const sync=()=>{const data=rich.get();form.elements.content.value=data.content;form.elements.content_html.value=data.content_html;};
      section.querySelector('[data-knowledge-mail-body]').addEventListener('input',sync);sync();
    }else mountMarkdownEditor(form);
    editorBaseline = editorValue();
    form.querySelector('[name="content_format"]').onchange=event=>{
      const target=event.target.value;
      if(emailMode&&target==='markdown'&&!confirm('切换为文档格式后，将只保留文字，图片与邮件排版会移除。是否继续？')){event.target.value='email';return;}
      const content=rich?rich.get().content:form.elements.content.value;
      const draft={...item,title:form.elements.title.value,category_id:Number(form.elements.category_id.value),content,content_format:target,content_html:target==='email'?markdownToHtml(content):''};
      editorBaseline='';openScript(draft);editorBaseline='format-changed';
    };
    form.addEventListener('input', () => { form.querySelector('[data-editor-status]').textContent = dirty() ? '有未保存修改 · Ctrl / ⌘ + S 保存' : 'Ctrl / ⌘ + S 保存'; });
    form.querySelector('[name="title"]').focus({preventScroll:true});
    form.querySelector('[data-script-editor-cancel]').onclick = () => { if (canLeave()) renderLibrary(); };
    form.onsubmit = async event => {
      event.preventDefault(); if (saving) return;
      if (pid() !== editorProject || JSON.stringify(headers()) !== editorAuth) return alert('项目或登录状态已切换，请重新打开编辑。');
      const targetCategory = Number(form.querySelector('[name="category_id"]').value);
      const payload = {title: form.querySelector('[name="title"]').value.trim(), category_id: targetCategory, content: form.elements.content.value.trim(),content_format:emailMode?'email':'markdown',content_html:rich?rich.get().content_html:''};
      if (!payload.title || !payload.content) return alert('标题和内容不能只包含空格。');
      const saveButton = form.querySelector('[type="submit"]');
      saving = true; saveButton.disabled = true; saveButton.textContent = '保存中…';
      // Freeze fields while saving so successful navigation cannot discard edits made mid-request.
      const controls = Array.from(form.querySelectorAll('input,select,textarea,button')).map(control => [control, control.disabled]);
      controls.forEach(([control]) => { control.disabled = true; });rich?.lock(true);
      try {
        const saved = await request(`/api/communication-scripts/projects/${pid()}/scripts${item?.id ? `/${item.id}` : ''}`, {method:item?.id ? 'PUT' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        editorBaseline = ''; selectedCategory = targetCategory; selectedScript = saved.id; remember();
        localStorage.setItem('tophoo-knowledge-updated-' + pid(), String(Date.now()) + Math.random());
        await load();
      } catch (error) { alert(error.message); }
      finally {
        saving = false;rich?.lock(false); controls.forEach(([control, disabled]) => { control.disabled = disabled; });
        saveButton.disabled = false; saveButton.textContent = '保存';
      }
    };
  }

  async function deleteCategory(id) {
    if (!canLeave()) return;
    const item=category(id);if(!item)return;
    const ids=new Set([id]);let changed=true;
    while(changed){changed=false;state.categories.forEach(child=>{if(ids.has(child.parent_id)&&!ids.has(child.id)){ids.add(child.id);changed=true;}});}
    const count=state.scripts.filter(entry=>ids.has(entry.category_id)).length;
    if(!confirm(`确认删除分类“${item.name}”？\n将同时删除其下全部内容：${ids.size-1} 个子分类、${count} 条知识条目。\n此操作无法恢复。`))return;
    if(detail.querySelector('[data-script-editor]'))renderLibrary();
    saving=true;
    try{
      await request(`/api/communication-scripts/projects/${pid()}/categories/${id}?confirmed=true`,{method:'DELETE'});
      ids.forEach(deleted=>expanded.delete(deleted));
      localStorage.setItem('tophoo-knowledge-updated-'+pid(),String(Date.now())+Math.random());
      await load();
    }catch(error){alert(error.message);}finally{saving=false;}
  }
  async function moveCategory(id, direction) { if (!canLeave()) return; if (detail.querySelector('[data-script-editor]')) renderLibrary(); try { await request(`/api/communication-scripts/projects/${pid()}/categories/${id}/move`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({direction})}); await load(); } catch (error) { alert(error.message); } }
  async function exportCategoryPdf() {
    const item = category(selectedCategory), button = root.querySelector('[data-script-export-category]');
    if (!item || button.disabled) return;
    const project = pid(), auth = JSON.stringify(headers()); let blobUrl;
    button.disabled = true;
    try {
      const response = await fetch(`/api/communication-scripts/projects/${project}/categories/${item.id}/export/pdf`, {headers: headers()});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '导出失败，请稍后重试。'); }
      const disposition = response.headers.get('Content-Disposition') || '';
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      if (!encodedName || !response.headers.get('Content-Type')?.includes('application/pdf')) throw new Error('导出文件异常，请重试。');
      const blob = await response.blob();
      if (project !== pid() || auth !== JSON.stringify(headers())) throw new Error('项目或登录状态已切换，请在当前项目重新导出。');
      const link = document.createElement('a'); blobUrl = URL.createObjectURL(blob); link.href = blobUrl;
      link.download = decodeURIComponent(encodedName); document.body.append(link); link.click(); link.remove();
    } catch (error) { alert(error.message); }
    finally { if (blobUrl) setTimeout(() => URL.revokeObjectURL(blobUrl), 1000); button.disabled = !state.scripts.some(entry => entry.category_id === selectedCategory); }
  }
  async function deleteScript(id) { const item = state.scripts.find(entry => entry.id === id); if (!item || !confirm(`确认删除知识条目“${item.title}”吗？`)) return; try { await request(`/api/communication-scripts/projects/${pid()}/scripts/${id}`, {method: 'DELETE'}); localStorage.setItem('tophoo-knowledge-updated-' + pid(), String(Date.now()) + Math.random()); await load(); } catch (error) { alert(error.message); } }
  async function moveScript(id, direction) { try { await request(`/api/communication-scripts/projects/${pid()}/scripts/${id}/move`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({direction})}); localStorage.setItem('tophoo-knowledge-updated-' + pid(), String(Date.now()) + Math.random()); await load(); } catch (error) { alert(error.message); } }
  async function load() {
    closeContentPreview();
    const project = pid(), version = ++loadVersion;
    if (project !== loadedProject) {
      toggleReading(false); loadedProject = project; state = {categories: [], scripts: []}; expanded = new Set();
      editorBaseline = ''; saving = false; closeCategory(); search.value = '';
      let remembered = {}; try { remembered = JSON.parse(sessionStorage.getItem(selectionKey()) || '{}'); } catch {}
      selectedCategory = remembered.category || null; selectedScript = remembered.script || null;
      search.value = typeof remembered.query === 'string' ? remembered.query : '';
      expanded = new Set(Array.isArray(remembered.expanded) ? remembered.expanded : []);
      tree.innerHTML = ''; detail.classList.remove('is-editing'); root.classList.remove('is-editing'); detail.innerHTML = ''; root.querySelector('[data-script-add]').hidden = true; root.querySelector('[data-script-export-category]').hidden = true;
    } else if (editorBaseline && detail.querySelector('[data-script-editor]')) return;
    if (!project) { clearDetail(); return; }
    detail.innerHTML = '<div class="script-empty" role="status"><h2>正在加载知识库…</h2></div>';
    try {
      const data = await request('/api/communication-scripts/projects/' + project);
      if (version !== loadVersion || project !== pid()) return;
      state = data; if (!category(selectedCategory)) selectedCategory = null;
      renderLibrary();
    } catch (error) {
      if (version !== loadVersion || project !== pid()) return;
      detail.innerHTML = `<div class="script-empty"><h2>加载失败</h2><p>${esc(error.message)}</p><button type="button" data-script-retry>重新加载</button></div>`;
      detail.querySelector('[data-script-retry]').onclick = load;
    }
  }
  const categoryForm = root.querySelector('[data-script-category-form]'); categoryForm.onsubmit = async event => { event.preventDefault(); const payload = {name: categoryForm.querySelector('[name="name"]').value.trim(), parent_id: Number(categoryForm.querySelector('[name="parent_id"]').value) || null}; try { await request(`/api/communication-scripts/projects/${pid()}/categories${editingCategory ? `/${editingCategory.id}` : ''}`, {method: editingCategory ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); closeCategory(); await load(); } catch (error) { alert(error.message); } };
  const categoryMenu = document.createElement('div');
  categoryMenu.id = 'knowledge-category-menu'; categoryMenu.className = 'script-category-menu'; categoryMenu.hidden = true; categoryMenu.setAttribute('role', 'group'); categoryMenu.setAttribute('aria-label', '分类操作');
  document.body.append(categoryMenu);
  let categoryMenuAnchor = null;
  function closeCategoryMenu(restoreFocus = false) {
    categoryMenu.hidden = true;
    const anchor = categoryMenuAnchor; categoryMenuAnchor = null;
    anchor?.setAttribute('aria-expanded', 'false');
    if (restoreFocus && anchor?.isConnected) anchor.focus({preventScroll:true});
  }
  function openCategoryMenu(id, button) {
    if (!categoryMenu.hidden && categoryMenuAnchor === button) return closeCategoryMenu(true);
    closeCategoryMenu(); const item = category(id); if (!item) return;
    const siblings = children(item.parent_id), index = siblings.findIndex(candidate => candidate.id === id);
    categoryMenu.innerHTML = `<button type="button" data-category-action="edit">✎ 编辑分类</button><button type="button" data-category-action="up" ${index <= 0 ? 'disabled' : ''}>↑ 上移分类</button><button type="button" data-category-action="down" ${index === siblings.length - 1 ? 'disabled' : ''}>↓ 下移分类</button><button type="button" data-category-action="delete">× 删除分类</button>`;
    categoryMenuAnchor = button; button.setAttribute('aria-expanded', 'true'); categoryMenu.hidden = false;
    const rect = button.getBoundingClientRect();
    categoryMenu.style.left = Math.max(8, Math.min(rect.right - categoryMenu.offsetWidth, window.innerWidth - categoryMenu.offsetWidth - 8)) + 'px';
    const menuHeight = categoryMenu.offsetHeight;
    categoryMenu.style.top = Math.max(8, rect.bottom + menuHeight + 8 <= window.innerHeight ? rect.bottom + 4 : rect.top - menuHeight - 4) + 'px';
    categoryMenu.querySelectorAll('button').forEach(action => action.onclick = () => {
      const name = action.dataset.categoryAction; closeCategoryMenu();
      if (name === 'edit') openCategory(item);
      else if (name === 'delete') deleteCategory(id);
      else moveCategory(id, name);
    });
    categoryMenu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
  }
  document.addEventListener('click', event => { if (!categoryMenu.hidden && !categoryMenu.contains(event.target) && !event.target.closest('[data-script-category-menu-toggle]')) closeCategoryMenu(); });
  document.addEventListener('scroll', event => { if (!categoryMenu.contains(event.target)) closeCategoryMenu(); }, true);
  window.addEventListener('resize', () => closeCategoryMenu());
  window.addEventListener('beforeunload', event => { if (dirty() || saving) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('click', event => {
    if (root.hidden || !event.target.closest('.global-nav-item, .crm-primary-item, .pm-project-row, [data-script-add-category]')) return;
    if (!canLeave()) { event.preventDefault(); event.stopImmediatePropagation(); }
    else if (detail.querySelector('[data-script-editor]')) renderLibrary();
  }, true);
  document.addEventListener('keydown', event => {
    if (root.hidden||contentPreview.open) return;
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'f') {
      const finder = detail.querySelector('[data-reader-find]');
      if (finder) { event.preventDefault(); finder.focus({preventScroll:true}); finder.select(); return; }
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && detail.querySelector('[data-script-editor]')) { event.preventDefault(); detail.querySelector('[data-script-editor]').requestSubmit(); }
    if (event.key === 'Escape') { const more=detail.querySelector('.script-reader-more[open]');if(more){more.open=false;more.querySelector('summary').focus();return;} if (!categoryMenu.hidden) { closeCategoryMenu(true); return; } closeCategory(); if (detail.querySelector('[data-script-editor]')) { if (canLeave()) renderLibrary(); } }
  });
  window.addEventListener('storage', event => { if (event.key === 'tophoo-knowledge-updated-' + pid() && !dirty() && !saving) load(); });
  root.querySelector('[data-script-clear-search]').onclick = () => { if (!canLeave()) return; search.value = ''; renderLibrary(true); search.focus({preventScroll:true}); };
  root.querySelector('[data-script-add-category]').onclick = () => openCategory(); root.querySelector('[data-script-add]').onclick = () => openScript(); root.querySelector('[data-script-export-category]').onclick = exportCategoryPdf; root.querySelector('[data-script-category-cancel]').onclick = closeCategory; root.querySelector('[data-script-category-dialog]').onclick = event => { if (event.target === event.currentTarget) closeCategory(); }; search.oninput = () => { if (!canLeave()) { search.value = search.dataset.appliedQuery || ''; return; } renderLibrary(true); }; root.querySelector('[data-script-all]').onclick = () => selectCategory(null); document.querySelector('[data-crm-section="communication-scripts"]')?.addEventListener('click', load); window.addEventListener('tophoo-project-changed', load); load();
})();
