(() => {
  const tokenKey = "tophoo-global-access-token";
  const userKey = "tophoo-global-current-user";

  function token() { return localStorage.getItem(tokenKey); }
  function headers() {
    const result = token() ? { Authorization: `Bearer ${token()}` } : {};
    const projectId = Number(localStorage.getItem('tophoo-global-selected-project'));
    if (projectId > 0) result['X-Project-ID'] = String(projectId);
    return result;
  }
  function currentUser() {
    try { return JSON.parse(localStorage.getItem(userKey) || "null"); } catch (_) { return null; }
  }
  function clearSession() {
    localStorage.removeItem(tokenKey);
    localStorage.removeItem(userKey);
  }
  function safeNextPath() {
    const next = new URLSearchParams(window.location.search).get("next");
    return next?.startsWith("/") && !next.startsWith("//") ? next : "/";
  }

  window.tophooAuth = { token, headers, currentUser, show: () => { window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`; } };

  const loginForm = document.querySelector("#login-form");
  if (loginForm) {
    document.querySelector(".login-password-toggle")?.addEventListener("click", (event) => {
      const input = document.querySelector("#auth-password");
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      event.currentTarget.setAttribute("aria-pressed", String(visible));
      event.currentTarget.setAttribute("aria-label", visible ? "隐藏密码" : "显示密码");
    });
    async function restoreLoginPageSession() {
      if (!token() || !currentUser()) return;
      try {
        const response = await fetch("/api/auth/me", { headers: headers() });
        if (!response.ok) throw new Error("stale session");
        localStorage.setItem(userKey, JSON.stringify(await response.json()));
        window.location.replace(safeNextPath());
      } catch (_) {
        clearSession();
      }
    }
    restoreLoginPageSession();
    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = document.querySelector("#auth-message");
      const submit = document.querySelector("#auth-submit");
      message.textContent = "";
      submit.disabled = true;
      submit.textContent = "正在登录…";
      try {
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: document.querySelector("#auth-email").value.trim(),
            password: document.querySelector("#auth-password").value,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "登录失败，请稍后重试。 ");
        localStorage.setItem(tokenKey, data.access_token);
        localStorage.setItem(userKey, JSON.stringify(data.user));
        window.location.replace(safeNextPath());
      } catch (error) {
        message.textContent = error.message;
      } finally {
        submit.disabled = false;
        submit.textContent = "登录并进入工作台";
      }
    });
    return;
  }

  const nativeFetch = window.fetch.bind(window);
  let redirecting = false, validation = null, sessionRendered = false;

  function expireSession() {
    if (redirecting) return;
    redirecting = true;
    clearSession();
    document.body.hidden = true;
    document.dispatchEvent(new CustomEvent("tophoo-auth-changed", { detail: { user: null } }));
    window.location.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }

  async function validateSession() {
    if (redirecting) return null;
    if (validation) return validation;
    const checkedToken = token();
    validation = (async () => {
      const response = await nativeFetch("/api/auth/me", { headers: headers(), cache: "no-store" });
      if (checkedToken !== token() || redirecting) return null;
      if (response.status === 401) {
        expireSession();
        return null;
      }
      if (!response.ok) return null;
      return response.json();
    })();
    try { return await validation; }
    finally { validation = null; }
  }

  window.fetch = async (input, options) => {
    const checkedToken = token();
    const response = await nativeFetch(input, options);
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, window.location.href);
    if (response.status === 401 && url.origin === window.location.origin &&
        url.pathname.startsWith("/api/") && url.pathname !== "/api/auth/logout" &&
        checkedToken === token() && !redirecting) {
      if (url.pathname === "/api/auth/me") expireSession();
      else await validateSession().catch(() => null);
    }
    return response;
  };

  const loginLink = document.querySelector("#sidebar-login");
  const userPanel = document.querySelector("#sidebar-user");
  const profileLink = document.querySelector("#sidebar-profile");
  const adminUsersLink = document.querySelector("#sidebar-admin-users");
  const adminPlansLink = document.querySelector("#sidebar-admin-plans");
  const logoutButton = document.querySelector("#auth-logout");
  const name = document.querySelector("#sidebar-user-name");
  const role = document.querySelector("#sidebar-user-role");
  const avatar = document.querySelector("#sidebar-user-avatar");

  function renderUser(user) {
    loginLink.hidden = Boolean(user);
    userPanel.hidden = !user;
    profileLink.hidden = !user;
    adminUsersLink.hidden = !user?.is_admin;
    adminPlansLink.hidden = !user?.is_admin;
    logoutButton.hidden = !user;
    name.textContent = user?.display_name || "";
    if (avatar) avatar.textContent = (user?.display_name || "U").trim().slice(0, 1).toUpperCase() || "U";
    role.hidden = !user?.is_admin;
    document.dispatchEvent(new CustomEvent("tophoo-auth-changed", { detail: { user } }));
  }

  async function restoreSession() {
    // Validate with the server even when a cached user is available.
    const freshUser = await validateSession();
    if (!freshUser || redirecting) return;
    const changed = JSON.stringify(currentUser()) !== JSON.stringify(freshUser);
    localStorage.setItem(userKey, JSON.stringify(freshUser));
    if (changed || !sessionRendered) { sessionRendered = true; renderUser(freshUser); }
  }

  function recheckSession() {
    if (!document.hidden && !redirecting) restoreSession().catch(() => {});
  }
  window.addEventListener("pageshow", recheckSession);
  window.addEventListener("focus", recheckSession);
  document.addEventListener("visibilitychange", recheckSession);
  window.addEventListener("storage", event => {
    if (event.key === tokenKey || event.key === userKey || event.key === null) recheckSession();
  });
  window.setInterval(recheckSession, 60000);

  logoutButton.addEventListener("click", async () => {
    logoutButton.disabled = true;
    try {
      await fetch("/api/auth/logout", { method: "POST", headers: headers() });
    } finally {
      clearSession();
      renderUser(null);
      logoutButton.disabled = false;
      window.location.assign("/login");
    }
  });

  restoreSession().catch(() => { if (!redirecting) renderUser(null); });
})();

