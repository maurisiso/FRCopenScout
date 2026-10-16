/* Small helpers used on every page. */
(function () {
  // Register the service worker (needs https or localhost).
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    });
    // Signed out? Drop cached pages so the next person on this device can't see them offline.
    if (document.body.dataset.auth === "0" && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage("clear-pages");
    }
  }

  // Theme toggle: automatic (follow device) -> dark -> light -> automatic. Saved per device.
  const THEMES = ["auto", "dark", "light"];
  const ICONS = { auto: "🖥️", dark: "🌙", light: "☀️" };
  function currentTheme() {
    try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; }
  }
  function applyTheme(theme) {
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((b) => {
      b.textContent = ICONS[theme];
      const label = b.dataset["label" + theme.charAt(0).toUpperCase() + theme.slice(1)];
      b.title = label; b.setAttribute("aria-label", label);
    });
  }
  applyTheme(currentTheme());
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-toggle]");
    if (!b) return;
    const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
    try { next === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", next); } catch (err) {}
    applyTheme(next);
  });

  // Online/offline indicator
  function updateNet() {
    document.body.classList.toggle("is-offline", !navigator.onLine);
  }
  window.addEventListener("online", updateNet);
  window.addEventListener("offline", updateNet);
  updateNet();

  // Close the team switcher when clicking elsewhere
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.team-menu[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // Mobile nav toggle
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-toggle-nav]");
    if (t) document.body.classList.toggle("nav-open");
  });

  // Click-to-sort tables: <table class="sortable">, cells may set data-sort="number"
  document.addEventListener("click", (e) => {
    const th = e.target.closest("table.sortable th");
    if (!th) return;
    const table = th.closest("table");
    const idx = Array.from(th.parentNode.children).indexOf(th);
    const body = table.tBodies[0];
    const asc = th.dataset.dir !== "asc";
    table.querySelectorAll("th").forEach((h) => delete h.dataset.dir);
    th.dataset.dir = asc ? "asc" : "desc";
    const val = (row) => {
      const cell = row.children[idx];
      const raw = cell ? (cell.dataset.sort ?? cell.textContent.trim()) : "";
      const num = parseFloat(raw.replace("%", ""));
      return isNaN(num) ? raw.toLowerCase() : num;
    };
    Array.from(body.rows)
      .sort((a, b) => {
        const x = val(a), y = val(b);
        if (x === "" || x === "?") return 1;
        if (y === "" || y === "?") return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1);
      })
      .forEach((r) => body.appendChild(r));
  });

  // Copy-to-clipboard buttons: <button data-copy="text">
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    navigator.clipboard?.writeText(b.dataset.copy).then(() => {
      const old = b.textContent;
      b.textContent = "✓";
      setTimeout(() => (b.textContent = old), 1200);
    });
  });

  // Send the CSRF token with every HTMX request.
  document.body.addEventListener("htmx:configRequest", (e) => {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    if (m) e.detail.headers["X-CSRFToken"] = m[1];
  });
})();
