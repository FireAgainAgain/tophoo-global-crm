(() => {
  const trigger = document.querySelector("#sidebar-user");
  const popover = document.querySelector("#crm-user-menu-popover");
  if (!trigger || !popover) return;
  const close = () => { popover.hidden = true; trigger.setAttribute("aria-expanded", "false"); };
  trigger.addEventListener("click", event => {
    event.stopPropagation();
    const opening = popover.hidden;
    popover.hidden = !opening;
    trigger.setAttribute("aria-expanded", String(opening));
  });
  document.addEventListener("click", event => { if (!popover.contains(event.target) && !trigger.contains(event.target)) close(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
  document.addEventListener("tophoo-auth-changed", event => { if (!event.detail?.user) close(); });
})();
