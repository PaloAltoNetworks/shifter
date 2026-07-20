// Living style guide — theme toggle only.
// Kept in an external file (no inline scripts) to model the CSP posture the
// SPA cutover targets. DOM-only; no network, no storage of user data.
(function () {
  "use strict";

  var root = document.documentElement;
  var button = document.getElementById("sg-theme-toggle");
  if (!button) {
    return;
  }

  function currentTheme() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) {
      return explicit;
    }
    // No explicit theme: fall back to the OS preference (matches tokens.css).
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    button.setAttribute("aria-pressed", String(theme === "light"));
    button.textContent = theme === "light" ? "Dark theme" : "Light theme";
  }

  apply(currentTheme());

  button.addEventListener("click", function () {
    apply(currentTheme() === "light" ? "dark" : "light");
  });
})();
