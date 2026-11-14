(() => {
  const root = document.querySelector(".checkout-layout");
  const message = document.querySelector("#checkout-message");
  const submit = document.querySelector("#test-payment-submit");
  let method = "stripe";

  document.querySelectorAll(".checkout-method").forEach((button) => {
    button.addEventListener("click", () => {
      method = button.dataset.method;
      document.querySelectorAll(".checkout-method").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-checked", String(selected));
      });
    });
  });

  submit.addEventListener("click", async () => {
    submit.disabled = true;
    message.textContent = "正在完成模拟支付…";
    try {
      const response = await fetch("/api/billing/test-checkout/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_code: root.dataset.planCode, payment_method: method }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "模拟支付失败。");
      message.textContent = data.message;
      submit.textContent = "已开通，正在进入工作台…";
      window.setTimeout(() => window.location.assign("/"), 900);
    } catch (error) {
      message.style.color = "#b64035";
      message.textContent = error.message;
      submit.disabled = false;
    }
  });
})();
