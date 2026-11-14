(() => {
  const items = [...document.querySelectorAll('.global-nav-item')];
  const sections = [...document.querySelectorAll('.crm-nav-section')];
  const categoryRail = document.querySelector('.crm-category-rail');
  const categories = [...categoryRail.querySelectorAll('.crm-category-button')];
  const primary = [...document.querySelectorAll('.crm-primary-item')];
  const names = { projects: '项目', seo: 'SEO', crm: 'CRM', system: '系统' };
  const crmHost = document.querySelector('#global-crm-content');
  const projectManagement = document.querySelector('[data-crm-project-management]');
  const views = {
    'communication-phrases': '[data-phrase-library]',
    competitors: '[data-crm-competitor-research]',
    'communication-assistant': '[data-communication-assistant]',
    'auto-prospecting': '[data-auto-prospecting]',
    'customer-search': '[data-customer-search]',
    'ai-config': '[data-ai-config]',
    'mail-config': '[data-mail-config]',
    'url-navigation': '[data-user-links]',
    'keyword-system': '[data-module="keyword-system"]',
    'mic-products': '[data-module="mic-products"]',
    contacts: '[data-crm-contact-list]',
    rfq: '[data-crm-rfq]',
    quotations: '[data-crm-quotations]',
    'communication-scripts': '[data-crm-communication-scripts]',
    'project-management': '[data-crm-project-management]'
  };
  const crmViews = [...new Set([...Object.values(views), '[data-customer-workflow]', '[data-customer-documents-workspace]'])].map(selector => document.querySelector(selector)).filter(Boolean);
  const sectionOf = item => item.closest('.crm-nav-section');
  const groupOf = item => sectionOf(item).dataset.crmNavGroup;
  const keyOf = item => item.dataset.crmSection;
  let hasProject = false, initialized = false, active = 'project-management';

  function showNavigation(item) {
    const domain = item ? groupOf(item) : '';
    const section = item ? sectionOf(item) : null;
    primary.forEach(item => { const on = item.dataset.crmNavGroup === domain; item.classList.toggle('active', on); item.setAttribute('aria-pressed', String(on)); });
    sections.forEach(panel => { panel.hidden = panel !== section; });
    categories.forEach(button => {
      const panel = document.getElementById(button.getAttribute('aria-controls'));
      const selected = panel === section;
      button.hidden = panel.dataset.crmNavGroup !== domain || !items.some(candidate => sectionOf(candidate) === panel && !candidate.hidden);
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    categoryRail.hidden = categories.every(button => button.hidden);
    document.querySelector('#crm-secondary-group-title').textContent = names[domain] || '';
  }

  function activate(key, { notify = true } = {}) {
    if(['quote-calculator','rfq','quotations'].includes(key)) key = 'contacts';
    if(key === 'prospecting') key = 'auto-prospecting';
    if (key === 'overview' || key === 'dashboard') key = 'project-management';
    const requested = items.find(item => keyOf(item) === key);
    const item = requested && !requested.hidden ? requested : items.find(item => !item.hidden);
    document.querySelector('[data-no-module-access]')?.remove();
    if (!item) {
      showNavigation(null);
      crmViews.forEach(view => { view.hidden = true; });
      crmHost.hidden = false;
      const empty = document.createElement('p'); empty.dataset.noModuleAccess = '';
      empty.className = 'pm-empty-state'; empty.textContent = '当前项目尚未分配可访问的功能，请联系管理员。';
      crmHost.append(empty); active = ''; return;
    }
    active = keyOf(item);
    const domain = groupOf(item);
    showNavigation(item);
    items.forEach(candidate => { candidate.classList.toggle('active', candidate === item); if (candidate === item) candidate.setAttribute('aria-current', 'page'); else candidate.removeAttribute('aria-current'); });
    document.querySelector('#crm-breadcrumb-group').textContent = names[domain];
    document.querySelector('#crm-breadcrumb-current').textContent = item.querySelector('.crm-nav-label').textContent.trim();
    crmViews.forEach(view => { view.hidden = true; });
    const library = active === 'keyword-system' || active === 'mic-products';
    document.querySelectorAll('.project-library-view').forEach(module => {
      module.classList.toggle('active', library && module.dataset.module === active);
    });
    const customerView = ['prospecting', 'leads', 'contacts', 'customer-pool'].includes(active);
    const view = document.querySelector(customerView ? '[data-customer-workflow]' : (views[active] || '[data-crm-project-management]'));
    if (view) view.hidden = false;
    const workflow = document.querySelector('[data-customer-workflow]');
    if (workflow) workflow.hidden = !customerView;
    if (customerView) document.dispatchEvent(new CustomEvent('tophoo-customer-workflow-view', { detail: { view: active } }));
    if (active === 'communication-phrases') document.dispatchEvent(new CustomEvent('tophoo-communication-phrases-view'));
    if (active === 'communication-assistant') document.dispatchEvent(new CustomEvent('tophoo-communication-assistant-view'));
    if (active === 'auto-prospecting') document.dispatchEvent(new CustomEvent('tophoo-auto-prospecting-view'));
    if (active === 'url-navigation') document.dispatchEvent(new CustomEvent('tophoo-user-links-view'));
    if (active === 'quotations') document.dispatchEvent(new CustomEvent('tophoo-quotations-view'));
    if (active === 'mail-config') document.dispatchEvent(new CustomEvent('tophoo-mail-config-view'));
    if (active === 'ai-config') document.dispatchEvent(new CustomEvent('tophoo-ai-config-view'));
    if (active === 'project-management' && notify) document.dispatchEvent(new CustomEvent('tophoo-project-management-view', { detail: { tool: 'permissions' } }));
    if (library) document.dispatchEvent(new CustomEvent('tophoo-project-library-view', {detail:{section:active}}));
    localStorage.setItem('tophoo-global-active-section', active);
  }

  items.forEach(item => item.addEventListener('click', () => activate(keyOf(item))));
  categories.forEach(button => button.addEventListener('click', () => {
    if (button.getAttribute('aria-pressed') === 'true') return;
    const item = items.find(candidate => sectionOf(candidate).id === button.getAttribute('aria-controls') && !candidate.hidden);
    if (item) activate(keyOf(item));
  }));
  primary.forEach(button => button.addEventListener('click', () => {
    const domain = button.dataset.crmNavGroup;
    const current = items.find(item => keyOf(item) === active);
    const item = current && !current.hidden && groupOf(current) === domain ? current : items.find(item => groupOf(item) === domain && !item.hidden);
    if (item) activate(keyOf(item));
  }));
  document.querySelectorAll('[data-crm-go-home]').forEach(button => button.addEventListener('click', () => activate('project-management')));
  window.tophooNavigateGlobal = activate;
  document.addEventListener('tophoo-crm-open-project-manager', () => activate('project-management'));
  document.addEventListener('tophoo-crm-close-project-manager', () => activate('project-management'));
  document.querySelector('#crm-project-manager-back')?.addEventListener('click', () => activate('project-management'));
  window.addEventListener('tophoo-project-availability', event => {
    hasProject = Boolean(event.detail?.hasProject);
    const permissions = new Set(event.detail?.permissions || []);
    items.forEach(item => {
      const anyModule = item.dataset.globalAnyModule;
      item.hidden = anyModule ? !hasProject || !anyModule.split(' ').some(module => permissions.has(module))
        : Boolean(item.dataset.globalModule) && (hasProject ? !permissions.has(item.dataset.globalModule) : !['project-management','url-navigation','mail-config'].includes(keyOf(item)));
    });
    primary.forEach(button => { button.hidden = !items.some(item => groupOf(item) === button.dataset.crmNavGroup && !item.hidden); });
    const params = new URLSearchParams(location.search);
    const requested = params.get('section') || (params.get('page') === 'seo' ? 'keyword-system' : null);
    const initial = requested || localStorage.getItem('tophoo-global-active-section') || 'project-management';
    if (!initialized) { initialized = true; activate(initial, { notify: false }); }
    else if (active === 'project-management' && !projectManagement.hidden && permissions.has('project_management')) {
      showNavigation(items.find(item => keyOf(item) === active));
    }
    else activate(active, { notify: false });
  });
  // Project context loads the management data; do not trigger another load here.
  const rememberedSection = localStorage.getItem('tophoo-global-active-section');
  activate('project-management', { notify: false });
  if (rememberedSection) localStorage.setItem('tophoo-global-active-section', rememberedSection);
})();
