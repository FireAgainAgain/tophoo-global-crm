(() => {
  const form = document.querySelector("#profile-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#profile-message");
    const submit = form.querySelector("button[type=submit]");
    const newPassword = document.querySelector("#profile-new-password").value;
    const payload = {
      display_name: document.querySelector("#profile-name").value.trim(),
      phone: document.querySelector("#profile-phone").value.trim() || null,
      wechat_id: document.querySelector("#profile-wechat").value.trim() || null,
    };
    if (newPassword) {
      payload.current_password = document.querySelector("#profile-current-password").value;
      payload.new_password = newPassword;
    }
    message.textContent = "";
    submit.disabled = true;
    try {
      const response = await fetch("/api/auth/me", { method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "保存失败，请稍后重试。 ");
      const {access_token, ...profile} = data;
      if (access_token) localStorage.setItem("tophoo-global-access-token", access_token);
      const existing = JSON.parse(localStorage.getItem("tophoo-global-current-user") || "{}");
      localStorage.setItem("tophoo-global-current-user", JSON.stringify({ ...existing, ...profile }));
      document.querySelector("#profile-current-password").value = "";
      document.querySelector("#profile-new-password").value = "";
      message.style.color = "#16754f";
      message.textContent = "个人信息已保存。";
    } catch (error) {
      message.style.color = "";
      message.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
})();

