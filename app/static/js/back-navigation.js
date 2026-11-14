(() => {
  document.querySelectorAll("[data-back-navigation]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const previous = document.referrer ? new URL(document.referrer) : null;
      if (previous?.origin === window.location.origin && window.history.length > 1) {
        event.preventDefault();
        window.history.back();
      }
    });
  });
})();
