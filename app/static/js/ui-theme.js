(() => {
  const key = 'tophoo-global-ui-theme';
  const normalize = value => ['green', 'blue', 'purple'].includes(value) ? value : 'green';
  function apply(value) {
    const theme = normalize(value);
    document.documentElement.dataset.uiTheme = theme;
    document.querySelectorAll('[data-appearance] [data-ui-theme]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.uiTheme === theme));
    });
  }
  let saved;
  try { saved = localStorage.getItem(key); } catch {}
  apply(saved);
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.uiTheme);
    const root = document.querySelector('[data-appearance]');
    if (!root) return;
    const trigger = root.querySelector('[data-appearance-trigger]');
    const panel = root.querySelector('[data-appearance-panel]');
    function close(restoreFocus = false) {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus();
    }
    trigger.addEventListener('click', () => {
      if (!panel.hidden) return close();
      document.querySelector('#crm-user-menu-popover')?.setAttribute('hidden', '');
      document.querySelector('#sidebar-user')?.setAttribute('aria-expanded', 'false');
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      panel.querySelector('[aria-pressed="true"]')?.focus();
    });
    root.querySelector('[data-appearance-close]').addEventListener('click', () => close(true));
    panel.querySelectorAll('[data-ui-theme]').forEach(button => {
      button.addEventListener('click', () => {
        apply(button.dataset.uiTheme);
        try { localStorage.setItem(key, normalize(button.dataset.uiTheme)); } catch {}
      });
    });
    document.addEventListener('click', event => { if (!root.contains(event.target)) close(); });
    root.addEventListener('keydown', event => {
      if (panel.hidden) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
      const options = [...panel.querySelectorAll('[data-ui-theme]')];
      const index = options.indexOf(document.activeElement);
      if (index >= 0 && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + options.length) % options.length;
        options[next].focus();
      }
    });
    document.addEventListener('focusin', event => { if (!root.contains(event.target)) close(); });
    document.addEventListener('tophoo-auth-changed', () => close());
  });
  window.addEventListener('storage', event => { if (event.key === key) apply(event.newValue); });
})();
