(() => {
  const addButton = document.querySelector('[data-workflow-add]');
  const form = document.querySelector('[data-workflow-form]');
  if (!addButton || !form) return;

  addButton.addEventListener('click', () => window.setTimeout(() => {
    const owner = form.elements.owner_user_id;
    if (!owner || form.dataset.mode === 'edit') return;
    if (!owner.querySelector('option[value=""]')) {
      owner.insertAdjacentHTML('afterbegin', '<option value="">当前用户（默认）</option>');
    }
    owner.value = '';
  }, 0));
})();
