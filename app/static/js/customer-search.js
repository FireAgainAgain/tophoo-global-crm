(() => {
  const root = document.querySelector('[data-customer-search]');
  if (!root) return;
  const form = root.querySelector('[data-cs-form]');
  const companyResults = root.querySelector('[data-cs-company-results]');
  const contactResults = root.querySelector('[data-cs-contact-results]');
  const advanced = root.querySelector('[data-cs-advanced]');
  const extraResults = root.querySelector('[data-cs-extra-results]');
  const previewControl = root.querySelector('[data-cs-preview-control]');
  const groupTemplate = root.querySelector('[data-cs-group]');
  const linkTemplate = root.querySelector('[data-cs-link]');
  const companyFields = ['website', 'company', 'country'];
  const contactFields = ['person', 'email'];
  const fieldNames = [...companyFields, ...contactFields];
  const importButton = root.querySelector('[data-cs-import]');
  const queue = root.querySelector('[data-cs-queue]');
  const clearQueueButton = root.querySelector('[data-cs-clear-queue]');
  const manualButton = root.querySelector('[data-cs-manual]');
  const contactSelect = root.querySelector('[data-cs-contact]');
  const editButton = root.querySelector('[data-cs-edit-record]');
  const editStatus = root.querySelector('[data-cs-edit-status]');
  const followupButton = root.querySelector('[data-cs-followup]');
  const outreachButton = root.querySelector('[data-cs-outreach]');
  const resetButton = form.querySelector('[type="reset"]');
  const picker = root.querySelector('[data-cs-picker]');
  const sourceButtons = [...picker.querySelectorAll('[data-cs-source]')];
  const pickerScroll = picker.querySelector('[data-cs-picker-scroll]');
  const filter = picker.querySelector('[data-cs-record-search]');
  const pickerStatus = picker.querySelector('[data-cs-picker-status]');
  const pickerResults = picker.querySelector('[data-cs-picker-results]');
  const more = picker.querySelector('[data-cs-more]');
  const selectionStatus = picker.querySelector('[data-cs-selection]');
  const addButton = picker.querySelector('[data-cs-add]');
  const pageSize = 40;
  const permissionsBySource = { leads: 'leads', contacts: 'customer_list' };
  let projectId = 0, grants = new Set(), request, records = [], limit = pageSize;
  let source = 'leads';
  const entries = new Map();
  const selected = new Map();
  let manual = lookupData({});
  let active = manual;
  const field = name => form.elements.namedItem(name);
  const value = name => field(name).value.trim();
  const exact = value => {
    const phrase = value.replace(/[“”"]/g, ' ').replace(/\s+/g, ' ').trim();
    return phrase ? `"${phrase}"` : '';
  };

  function domainFrom(value) {
    if (!value || /[\s\\]/.test(value)) return '';
    try {
      const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
      const domain = url.hostname.replace(/^www\./, '').replace(/\.$/, '');
      if (url.username || url.password || !/^(?:[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?\.)+(?:[a-z]{2,63}|xn--[a-z\d-]+)$/i.test(domain)) return '';
      return domain;
    } catch {
      return '';
    }
  }

  function update() {
    const website = value('website');
    const email = value('email');
    const domain = domainFrom(website);
    const companyName = value('company');
    const company = exact(companyName);
    const person = exact(value('person'));
    const address = /^[^\s@"<>]+@[^\s@"<>.]+(?:\.[^\s@"<>.]+)+$/.test(email) ? exact(email) : '';
    const site = domain ? `site:${domain}` : '';
    const organization = company || (domain ? exact(domain) : '');
    const personContext = [person, organization].filter(Boolean).join(' ');
    const yearAgo = new Date();
    yearAgo.setFullYear(yearAgo.getFullYear() - 1);
    const recent = [yearAgo.getFullYear(), yearAgo.getMonth() + 1, yearAgo.getDate()].map(part => String(part).padStart(2, '0')).join('-');
    const companyWords = companyName.replace(/[^\p{L}\p{M}\p{N}]+/gu, ' ').trim();
    const companyOptions = [
        ['按公司名找官网', company],
        ['放宽公司名匹配', companyWords && `${companyWords} official website`],
        ['核对公司与官网', company && site && `${site} ${company}`],
        ['查找第三方提及', domain && `${organization} -${site}`],
        ['查找联系页面', (site || company) && `${site || company} contact`],
        ['Google 地图查公司', (company || domain) && [companyName || domain, value('country')].filter(Boolean).join(', '), 'maps'],
        ['查找 LinkedIn 公司页', organization && `site:linkedin.com/company ${organization}`],
    ];
    const contactOptions = [
        ['查找联系人', person && personContext],
        ['查找邮箱公开出处', address],
        ['核对邮箱与公司', address && (site || company) && `${address} ${site || company}`],
        ['查找 LinkedIn 个人页', person && `site:linkedin.com/in ${personContext}`],
        ['按姓名单独搜索', person && organization && person],
    ];
    const moreGroups = [
      ['网站与公开来源', [
        ['查看官网收录页面', site],
        ['查找第三方引用的域名', company && domain && `${exact(domain)} -${site}`],
        ['查找公司登记资料', organization && `${organization} company registration`],
        ['查找展会参展记录', organization && `${organization} exhibitor`],
        ['查找近一年动态', organization && `${organization} after:${recent}`],
      ]],
      ['产品与资料', [
        ['查找产品页面', (site || company) && `${site || company} products`],
        ['查找产品目录 PDF', (site || company) && `${site || company} catalog filetype:pdf`],
        ['查找技术资料 PDF', (site || company) && `${site || company} datasheet filetype:pdf`],
      ]],
    ];
    for (const [name, invalid] of [['website', website && !domain], ['email', email && !address]]) {
      root.querySelector(`[data-cs-error="${name}"]`).hidden = !invalid;
      field(name).setAttribute('aria-invalid', String(Boolean(invalid)));
    }
    const hasCompany = renderGroups(companyResults, [['', companyOptions]]);
    const hasContact = renderGroups(contactResults, [['', contactOptions]]);
    const hasMore = renderGroups(extraResults, moreGroups);
    advanced.hidden = !hasMore;
    previewControl.hidden = !hasCompany && !hasContact && !hasMore;
    resetButton.disabled = !fieldNames.some(name => field(name).value);
  }

  function renderGroups(target, groups) {
    const content = document.createDocumentFragment();
    for (const [title, options] of groups) {
      const available = options.filter(([, query]) => query);
      if (!available.length) continue;
      const group = groupTemplate.content.cloneNode(true);
      const heading = group.querySelector('h3');
      if (title) heading.textContent = title;
      else heading.remove();
      for (const [label, query, engine] of available) {
        const item = linkTemplate.content.cloneNode(true);
        item.querySelector('strong').textContent = label;
        item.querySelector('small').textContent = query;
        const url = new URL(engine === 'maps' ? 'https://www.google.com/maps/search/' : 'https://www.google.com/search');
        if (engine === 'maps') url.searchParams.set('api', '1');
        url.searchParams.set(engine === 'maps' ? 'query' : 'q', query);
        const link = item.querySelector('a');
        link.href = url.href;
        link.title = query;
        group.querySelector('.cs-options').append(item);
      }
      content.append(group);
    }
    const hasGroups = content.childElementCount > 0;
    target.replaceChildren(content);
    return hasGroups;
  }

  function lookupData(row, kind) {
    const people = row.contacts?.filter(person => person.contact_name || person.email) || [];
    const contacts = (people.length ? people : [row]).map(person => ({
      person: person.contact_name || '', email: person.email || '', primary: Boolean(person.is_primary),
    }));
    const primary = contacts.findIndex(person => person.primary);
    return {
      key: kind ? `${kind}:${row.id}` : null, kind, id: row.id,
      record: kind ? row : null,
      website: row.company_website || '',
      company: row.company || row.company_name || '',
      country: row.country || '',
      contacts, contactIndex: Math.max(0, primary),
    };
  }

  function entryName(entry) {
    const contact = entry.contacts[entry.contactIndex];
    return entry.company || entry.website || contact.person || contact.email || '未命名记录';
  }

  function renderQueue() {
    clearQueueButton.disabled = !entries.size;
    const content = document.createDocumentFragment();
    for (const entry of entries.values()) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'cs-record';
      button.setAttribute('aria-pressed', String(entry === active));
      const name = document.createElement('strong');
      name.textContent = entryName(entry);
      const details = document.createElement('small');
      details.textContent = [entry.kind === 'leads' ? '线索' : '客户', entry.country].filter(Boolean).join(' · ');
      button.append(name, details);
      button.addEventListener('click', () => {
        showEntry(entry);
        queue.children[[...entries.keys()].indexOf(entry.key)]?.firstElementChild?.focus();
      });
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'cs-queue-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `移除 ${entryName(entry)}`);
      remove.title = '移出名单';
      remove.addEventListener('click', () => removeEntry(entry));
      item.append(button, remove);
      content.append(item);
    }
    queue.replaceChildren(content);
  }

  function removeEntry(entry) {
    const list = [...entries.values()];
    const index = list.indexOf(entry);
    entries.delete(entry.key);
    if (entry === active) showEntry(list[index + 1] || list[index - 1] || manual);
    else renderQueue();
    const next = queue.children[Math.min(index, queue.children.length - 1)];
    (next?.firstElementChild || manualButton).focus();
  }

  function renderContact() {
    const person = active.contacts[active.contactIndex];
    contactFields.forEach(name => { field(name).value = person[name]; });
    contactSelect.replaceChildren(...active.contacts.map((contact, index) => new Option(
      `${contact.person || contact.email || '未命名联系人'}${contact.primary ? '（主联系人）' : ''}`, String(index)
    )));
    contactSelect.value = String(active.contactIndex);
    contactSelect.hidden = active.contacts.length < 2;
  }

  function renderEntryHeading() {
    root.querySelector('[data-cs-title]').textContent = active.key ? entryName(active) : '手动查证';
  }

  function hasActiveRecord() {
    return Boolean(!root.hidden && projectId && active.key && grants.has(permissionsBySource[active.kind]));
  }

  function updateRecordActions() {
    const hasRecord = Boolean(projectId && active.key && grants.has(permissionsBySource[active.kind]));
    if (followupButton) followupButton.hidden = !hasRecord;
    if (outreachButton) outreachButton.hidden = !hasRecord || active.kind !== 'leads';
    if (!editButton) return;
    const module = permissionsBySource[active.kind];
    editButton.hidden = !hasRecord || !window.tophooProjectAccess?.canEdit(module);
    editButton.textContent = active.kind === 'leads' ? '编辑线索资料' : '编辑客户资料';
  }

  function setEditStatus(message = '') {
    if (!editStatus) return;
    editStatus.textContent = message;
    editStatus.hidden = !message;
  }

  function showEntry(entry) {
    active = entry;
    companyFields.forEach(name => { field(name).value = entry[name]; });
    renderContact();
    manualButton.setAttribute('aria-pressed', String(!entry.key));
    resetButton.hidden = Boolean(entry.key);
    renderEntryHeading();
    updateRecordActions();
    if (editButton) editButton.disabled = false;
    setEditStatus();
    renderQueue();
    update();
  }

  followupButton?.addEventListener('click', () => {
    if (!hasActiveRecord()) return;
    document.dispatchEvent(new CustomEvent('tophoo-open-contact-records', {detail: {
      contactId: active.id, view: active.kind, company: active.record.company_name || active.record.company,
    }}));
  });

  outreachButton?.addEventListener('click', () => {
    if (!hasActiveRecord() || active.kind !== 'leads') return;
    document.dispatchEvent(new CustomEvent('tophoo-lead-outreach-open', {detail: {
      project: projectId, view: active.kind, id: active.id, item: active.record, trigger: outreachButton,
    }}));
  });

  editButton?.addEventListener('click', () => {
    const entry = active;
    const project = projectId;
    const module = permissionsBySource[entry.kind];
    const current = () => !root.hidden && projectId === project && active === entry &&
      window.tophooProjectAccess?.canEdit(module);
    if (!entry.key || !current()) return;
    editButton.disabled = true;
    setEditStatus('正在读取最新资料…');
    document.dispatchEvent(new CustomEvent('tophoo-verification-edit', {detail: {
      project, view: entry.kind, id: entry.id, current,
      ready(message) {
        if (!current()) return;
        editButton.disabled = false;
        setEditStatus(message);
      },
      saved(item) {
        if (!current()) return;
        const updated = lookupData(item, entry.kind);
        entries.set(entry.key, updated);
        showEntry(updated);
        setEditStatus('资料已保存，可以继续查证。');
      },
    }}));
  });

  function renderRecords(append = false) {
    const query = filter.value.trim().toLowerCase();
    const matches = records.filter(({search}) => !query || search.includes(query));
    pickerStatus.textContent = matches.length ? '' : query ? '没有匹配记录' : '暂无记录';
    pickerStatus.hidden = Boolean(matches.length);
    const content = document.createDocumentFragment();
    const start = append ? pickerResults.childElementCount : 0;
    for (const {data} of matches.slice(start, limit)) {
      const label = document.createElement('label');
      label.className = 'cs-picker-record';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.disabled = entries.has(data.key);
      checkbox.checked = checkbox.disabled || selected.has(data.key);
      const copy = document.createElement('span');
      copy.className = 'cs-picker-company';
      const name = document.createElement('strong');
      name.textContent = entryName(data);
      name.title = name.textContent;
      const details = document.createElement('small');
      details.textContent = checkbox.disabled ? '已在名单' : domainFrom(data.website) || data.website;
      details.title = details.textContent;
      copy.append(name);
      if (details.textContent && details.textContent !== name.textContent) copy.append(details);
      const country = document.createElement('span');
      country.className = 'cs-picker-country';
      country.textContent = data.country || '—';
      country.title = data.country;
      label.append(checkbox, copy, country);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) selected.set(data.key, data);
        else selected.delete(data.key);
        syncSelection();
      });
      content.append(label);
    }
    if (append) pickerResults.append(content);
    else {
      pickerResults.replaceChildren(content);
      pickerScroll.scrollTop = 0;
    }
    more.hidden = limit >= matches.length;
  }

  function syncSelection() {
    selectionStatus.textContent = `已选 ${selected.size} 条`;
    addButton.disabled = !selected.size;
  }

  async function loadRecords() {
    request?.abort();
    const kind = source;
    records = [];
    limit = pageSize;
    filter.disabled = true;
    more.hidden = true;
    pickerResults.replaceChildren();
    pickerStatus.hidden = false;
    if (!projectId || !grants.has(permissionsBySource[kind])) {
      pickerStatus.textContent = '当前项目没有此来源的查看权限。';
      return;
    }
    pickerStatus.textContent = '正在读取资料…';
    const pending = new AbortController();
    request = pending;
    try {
      const endpoint = kind === 'leads' ? `/api/customer-workflow/projects/${projectId}/leads` : `/api/contacts/projects/${projectId}`;
      const response = await fetch(endpoint, { headers: window.tophooAuth?.headers?.() || {}, signal: pending.signal });
      if (!response.ok) throw new Error('Could not read records');
      const payload = await response.json();
      if (pending.signal.aborted || !picker.open) return;
      records = (kind === 'leads' ? payload.items : payload.customers).map(row => {
        const data = lookupData(row, kind);
        const people = data.contacts.flatMap(contact => [contact.person, contact.email]);
        return { data, search: [data.company, data.website, data.country, ...people].filter(Boolean).join(' ').toLowerCase() };
      }).filter(record => record.search);
      filter.disabled = false;
      renderRecords();
    } catch {
      if (!pending.signal.aborted && picker.open) pickerStatus.textContent = '读取失败，请关闭后重试。';
    }
  }

  function syncSources() {
    const available = sourceButtons.filter(button => grants.has(permissionsBySource[button.dataset.csSource]));
    if (!available.some(button => button.dataset.csSource === source)) source = available[0]?.dataset.csSource || '';
    for (const button of sourceButtons) {
      button.hidden = !available.includes(button);
      button.setAttribute('aria-pressed', String(button.dataset.csSource === source));
    }
    importButton.hidden = !projectId || !available.length;
  }

  importButton.addEventListener('click', () => {
    if (importButton.hidden || picker.open) return;
    filter.value = '';
    selected.clear();
    syncSelection();
    picker.showModal();
    loadRecords();
  });
  addButton.addEventListener('click', () => {
    const first = selected.values().next().value;
    if (!first) return;
    for (const entry of selected.values()) entries.set(entry.key, entry);
    picker.close();
    showEntry(first);
    form.focus();
  });
  picker.querySelector('[data-cs-picker-close]').addEventListener('click', () => picker.close());
  picker.addEventListener('close', () => {
    if (picker.open) return;
    request?.abort();
    records = [];
    selected.clear();
    pickerResults.replaceChildren();
  });
  for (const button of sourceButtons) {
    button.addEventListener('click', () => {
      if (source === button.dataset.csSource) return;
      source = button.dataset.csSource;
      syncSources();
      filter.value = '';
      loadRecords();
    });
  }
  filter.addEventListener('input', () => { limit = pageSize; renderRecords(); });
  function showMore() {
    limit += pageSize;
    renderRecords(true);
  }
  pickerScroll.addEventListener('scroll', () => {
    if (!more.hidden && pickerScroll.scrollHeight - pickerScroll.scrollTop - pickerScroll.clientHeight < 56) showMore();
  });
  more.addEventListener('click', () => {
    const firstNew = pickerResults.childElementCount;
    showMore();
    pickerResults.children[firstNew]?.querySelector('input')?.focus();
  });

  manualButton.addEventListener('click', () => showEntry(manual));
  contactSelect.addEventListener('change', () => {
    active.contactIndex = Number(contactSelect.value);
    renderContact();
    update();
  });
  clearQueueButton.addEventListener('click', () => {
    entries.clear();
    showEntry(manual);
    manualButton.focus();
  });

  form.addEventListener('input', event => {
    const {name, value} = event.target;
    if (companyFields.includes(name)) {
      active[name] = value;
      if (active.key) {
        renderEntryHeading();
        renderQueue();
      }
    } else if (contactFields.includes(name)) {
      active.contacts[active.contactIndex][name] = value;
    } else return;
    update();
  });
  form.addEventListener('reset', event => {
    event.preventDefault();
    if (active.key) return;
    manual = lookupData({});
    showEntry(manual);
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    form.querySelector('.cs-link')?.focus();
  });
  function clearContext() {
    request?.abort();
    if (picker.open) picker.close();
    projectId = 0;
    grants.clear();
    entries.clear();
    selected.clear();
    manual = lookupData({});
    advanced.open = false;
    syncSources();
    showEntry(manual);
  }
  document.addEventListener('tophoo-auth-changed', clearContext);
  window.addEventListener('tophoo-project-changed', clearContext);
  window.addEventListener('tophoo-project-availability', ({detail}) => {
    const nextProjectId = detail?.hasProject ? Number(detail.projectId) || 0 : 0;
    const nextGrants = new Set(detail?.permissions || []);
    if (nextProjectId !== projectId || Object.values(permissionsBySource).some(key => grants.has(key) && !nextGrants.has(key))) clearContext();
    projectId = nextProjectId;
    grants = nextGrants;
    syncSources();
    queueMicrotask(updateRecordActions);
  });
  document.addEventListener('tophoo-customer-search-import', ({detail}) => {
    if (detail?.project !== projectId || !grants.has(permissionsBySource[detail.view])) return;
    if (!detail.item) return;
    window.tophooNavigateGlobal?.('customer-search');
    if (root.hidden) return;
    const incoming = lookupData(detail.item, detail.view);
    if (!entries.has(incoming.key)) entries.set(incoming.key, incoming);
    showEntry(entries.get(incoming.key));
    form.focus();
  });
  showEntry(manual);
})();
