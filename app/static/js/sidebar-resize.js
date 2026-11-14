(() => {
  const resizer = document.getElementById("sidebar-resizer");
  const toggle = document.getElementById("sidebar-toggle");
  const root = document.documentElement;
  if (!resizer || !toggle) return;

  const MIN = 180, MAX = 320, DEFAULT_W = 208;
  const KEY_W = "tophoo-global-compact-nav-width";
  const KEY_C = "tophoo-global-secondary-nav-collapsed";

  // 安全存储：沙箱预览 iframe / 隐私模式下 localStorage 可能抛异常，静默降级为内存态
  const memory = {};
  const store = {
    get(key, fallback) {
      try {
        const v = localStorage.getItem(key);
        return v == null ? fallback : v;
      } catch (e) {
        return key in memory ? memory[key] : fallback;
      }
    },
    set(key, value) {
      memory[key] = String(value);
      try { localStorage.setItem(key, String(value)); } catch (e) { /* 静默 */ }
    }
  };

  const isMobile = () => {
    try { return window.matchMedia("(max-width: 760px)").matches; }
    catch (e) { return false; }
  };
  const clamp = (n) => Math.max(MIN, Math.min(MAX, Math.round(n)));

  let width = clamp(parseInt(store.get(KEY_W, String(DEFAULT_W)), 10) || DEFAULT_W);
  let collapsed = store.get(KEY_C, "0") === "1";

  const apply = () => {
    root.style.setProperty("--secondary-nav-width", (collapsed ? 0 : width) + "px");
    root.style.setProperty("--sidebar-width", collapsed ? "var(--primary-rail-width)" : `calc(var(--primary-rail-width) + ${width}px)`);
    document.body.classList.toggle("secondary-nav-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
  };
  apply();

  // 拖拽缩放
  resizer.addEventListener("pointerdown", (event) => {
    if (isMobile() || collapsed) return;
    event.preventDefault();
    const startX = event.clientX, startW = width;
    document.body.classList.add("is-resizing");
    resizer.classList.add("is-active");
    if (resizer.setPointerCapture) { try { resizer.setPointerCapture(event.pointerId); } catch (e) { /* 忽略 */ } }
    let frame = 0;
    const flush = () => { frame = 0; apply(); };
    const move = (ev) => {
      const next = clamp(startW + (ev.clientX - startX));
      if (next === width) return;
      width = next;
      // 鼠标事件可能快于屏幕刷新；每帧仅更新一次布局。
      if (!frame) frame = requestAnimationFrame(flush);
    };
    const up = () => {
      resizer.removeEventListener("pointermove", move);
      resizer.removeEventListener("pointerup", up);
      resizer.removeEventListener("pointercancel", up);
      resizer.removeEventListener("lostpointercapture", up);
      if (frame) { cancelAnimationFrame(frame); flush(); }
      document.body.classList.remove("is-resizing");
      resizer.classList.remove("is-active");
      store.set(KEY_W, String(width));
    };
    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", up);
    resizer.addEventListener("pointercancel", up);
    resizer.addEventListener("lostpointercapture", up);
  });

  // 双击恢复默认宽度
  resizer.addEventListener("dblclick", () => {
    if (isMobile() || collapsed) return;
    width = DEFAULT_W;
    root.style.setProperty("--secondary-nav-width", width + "px");
    root.style.setProperty("--sidebar-width", `calc(var(--primary-rail-width) + ${width}px)`);
    store.set(KEY_W, String(width));
  });

  // 折叠 / 展开
  toggle.addEventListener("click", () => {
    if (isMobile()) return;
    collapsed = !collapsed;
    apply();
    store.set(KEY_C, collapsed ? "1" : "0");
  });
})();
