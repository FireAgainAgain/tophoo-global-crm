/* Shared-module read-only presentation. The server independently enforces every write. */
(() => {
  let reads = new Set(), writes = new Set(), ready = false;
  const roots = {
    project_management: '[data-crm-project-management],.pm-modal-overlay',
    url_navigation: '[data-user-links]',
    ai_configuration: '[data-ai-config]',
    mail_configuration: '[data-mail-config]',
    auto_prospecting: '[data-auto-prospecting]',
    customer_list: '[data-followup-dialog],[data-followup-queue]',
    quotations:'[data-crm-quotations]',
    rfq: '[data-crm-rfq]', knowledge_base: '[data-crm-communication-scripts],#knowledge-category-menu',
    competitor_research: '[data-crm-competitor-research]',
    keyword_library: '[data-module="keyword-system"],#keyword-category-menu,.keyword-editor-overlay',
    mic_products: '[data-module="mic-products"]'
  };
  const mutations = [
    '[data-ul-add]','[data-ul-category-add]','[data-ul-category-edit]','.ul-link-menu','[data-ul-form] button[type="submit"]','[data-ul-category-delete]',
    '[data-new]','[data-edit-project]','[data-move]','[data-delete]','[data-add-role]','[data-save-role]','[data-delete-role]','[data-add-project-member]','[data-save-member]','[data-remove-member]',
    '.pm-form button[type="submit"]',
    '[data-mail-account-add]','[data-mail-account-default]','[data-mail-account-delete]','[data-mail-edit]','[data-mail-test]','[data-mail-test-message]','[data-mail-form] button[type="submit"]',
    '[data-ai-new]','[data-ai-save]','[data-ai-test]',
    '[data-ul-form] input','[data-ul-form] select','[data-mail-form] input','[data-mail-form] select','[data-mail-form] textarea',

    '[data-scan-open]','[data-scan-start]','[data-scan-import]',
    '[data-workflow-add]','[data-workflow-batch-main]','[data-workflow-batch-delete]',
    '[data-detail-edit]','[data-detail-main]','[data-detail-delete]',
    '[data-person-new]','[data-person-edit]','[data-person-delete]','[data-person-set-primary]',
    '[data-contact-status]','[data-customer-grade]','[data-record-add]','[data-edit]','[data-delete]','[data-save]',
    '[data-fu-add]','[data-fu-edit]','[data-fu-complete]','[data-fu-cancel]',
    '[data-outreach-save]','[data-outreach-record]','[data-outreach-send]','[data-mail-send-confirm]',
    '[data-acq-submit]','[data-acq-import]','[data-acq-confirm]','[data-acq-ignore]',
    '[data-acq-cancel]','[data-acq-delete-record]','[data-acq-delete-results]',
    '[data-qc-save]',
    '[data-quote-templates]','[data-quote-add]','[data-quote-import]','[data-quote-edit]','[data-quote-delete]',
    '[data-rfq-add]','[data-edit-rfq]','[data-delete-rfq]',
    '[data-script-add-category]','[data-script-add]','[data-script-category-menu-toggle]',
    '[data-reader-edit]','[data-reader-delete]','[data-reader-up]','[data-reader-down]',
    '[data-add-competitor]','[data-edit-competitor]','[data-move-competitor]','[data-open-new-website]','[data-delete-competitor]','[data-open-website]',
    '[data-delete-website]','[data-delete-keyword]',
    '[data-edit-keyword]','[data-delete-keyword]','[data-set-layout]','[data-category-menu]',
    '.mr-edit-toggle','.mr-row-remove','.mr-add','[data-category-action]','#keyword-category-menu [data-action]',
    '#mic-form select','#mic-social-form input[type="checkbox"]','#mic-image-upload','#mic-add','#mic-save','#mic-social-save','#mic-add-name','#mic-remove-image','[data-remove-name]','[data-mic-remove-record]',
    '[data-task-id]',
    '#project-action-generate','#gsc-upload-file',
    '#product-tdk-add','#product-tdk-clear-trash','#product-tdk-clear-all','#product-tdk-file',
    '#article-tdk-add','#article-tdk-clear-draft','#article-tdk-clear-all','#article-tdk-file',
    '#keyword-add','#keyword-add-root','#keyword-clear-library','#keyword-move-selected','#keyword-delete-selected','#keyword-editor-save','#keyword-import-file'
  ].join(',');
  const fieldOriginal = new WeakMap();
  const readonlyOriginal = new WeakMap();
  const scopeFor = element => element.closest('[data-permission-module]')?.dataset.permissionModule || Object.entries(roots).find(([, selector]) => element.closest(selector))?.[0];
  function forbidden(element) {
    const module = scopeFor(element);
    const destination = element.matches('[data-acq-confirm]') ? 'leads' : element.matches('[data-workflow-batch-main],[data-detail-main]') ? ({leads:'customer_list',customer_list:'customer_pool',customer_pool:'customer_list',auto_prospecting:'leads'})[module] : null;
    return Boolean(ready && module && (!writes.has(module) || (destination && !writes.has(destination))) && !element.matches('.mic-thumbnail'));
  }
  function refresh() {
    document.querySelectorAll(mutations).forEach(control => {
      const denied = forbidden(control);
      const isField = ['SELECT','INPUT','TEXTAREA'].includes(control.tagName);
      const displayTarget=control.matches('input[type="file"]')?(control.closest('label')||control):control;
      const hide=Boolean(denied&&(!isField||control.type==='file'));
      if(displayTarget.classList.contains('module-write-hidden')!==hide)displayTarget.classList.toggle('module-write-hidden',hide);
      if (isField) {
        if (denied) {
          if (!fieldOriginal.has(control)) fieldOriginal.set(control, control.disabled);
          if (!control.disabled) control.disabled = true;
        } else if (fieldOriginal.has(control)) {
          control.disabled = fieldOriginal.get(control); fieldOriginal.delete(control);
        }
      }
    });
    document.querySelectorAll('[data-outreach-subject],[data-outreach-content],[data-outreach-translation],#mic-form textarea,#mic-form input:not([type="file"]),#mic-social-form textarea,#keyword-editor-form input[name]').forEach(field=>{
      if(forbidden(field)){if(!readonlyOriginal.has(field))readonlyOriginal.set(field,field.readOnly);if(!field.readOnly)field.readOnly=true;}
      else if(readonlyOriginal.has(field)){field.readOnly=readonlyOriginal.get(field);readonlyOriginal.delete(field);}
    });
    const item = document.querySelector('.global-nav-item[aria-current="page"]');
    const module = item?.dataset.globalModule;
    let badge = document.querySelector('#module-readonly-badge');
    if (!badge) {
      badge = document.createElement('span'); badge.id = 'module-readonly-badge'; badge.textContent = '只读';
      badge.title = '可查看、搜索、复制和导出；修改请联系项目管理员';
      document.querySelector('#crm-breadcrumb-current')?.after(badge);
    }
    badge.hidden = !ready || !module || !reads.has(module) || writes.has(module);
  }
  window.tophooProjectAccess = {canEdit: module => ready && writes.has(module)};
  window.addEventListener('tophoo-project-availability', event => {
    reads = new Set(event.detail?.permissions || []);
    writes = new Set(event.detail?.writePermissions ?? event.detail?.permissions ?? []);
    ready = true; refresh();
  });
  // Includes controls rendered later in drawers and menus; no polling or whole-page rerender.
  let scheduled = false;
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {scheduled = false; refresh();});
  }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'aria-current', 'data-permission-module']});
  document.addEventListener('submit',event=>{
    if(event.target.matches('[data-ul-form],[data-mail-form],[data-ai-form],.pm-form,[data-workflow-form],[data-action-form],[data-rfq-form],[data-script-category-form],[data-script-editor],.competitor-form,[data-website-form],[data-website-edit-form],[data-keyword-form],#mic-form,#mic-social-form,#keyword-editor-form')&&forbidden(event.target)){
      event.preventDefault();event.stopImmediatePropagation();
    }
  },true);
  document.addEventListener('click', event => {
    const control = event.target.closest(mutations);
    if (control && forbidden(control)) {event.preventDefault(); event.stopImmediatePropagation();}
  }, true);
})();
