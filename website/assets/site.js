// Shared page behaviour: theme toggle, mobile menu, and filling in values from config.js.
(function () {
  const S = window.SITE || {};
  const root = document.documentElement;

  // ---- theme (remembered per browser; works without storage too)
  try {
    const saved = localStorage.getItem("theme");
    if (saved) root.dataset.theme = saved;
  } catch (e) { /* storage blocked - fine */ }
  function currentTheme() {
    return root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function paintThemeButton() {
    document.querySelectorAll(".theme-btn:not(.menu-btn)").forEach((b) => {
      const dark = currentTheme() === "dark";
      b.textContent = dark ? "☀" : "☾";
      b.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    paintThemeButton();
    document.querySelectorAll(".theme-btn:not(.menu-btn)").forEach((b) => b.addEventListener("click", () => {
      root.dataset.theme = currentTheme() === "dark" ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch (e) { /* ignore */ }
      paintThemeButton();
    }));

    // ---- mobile menu
    const menuBtn = document.querySelector(".menu-btn");
    const nav = document.querySelector(".nav");
    if (menuBtn && nav) {
      menuBtn.addEventListener("click", () => {
        const open = nav.classList.toggle("open");
        menuBtn.setAttribute("aria-expanded", String(open));
      });
      nav.addEventListener("click", (e) => { if (e.target.closest("a")) nav.classList.remove("open"); });
    }

    // ---- values from config.js
    const set = (sel, fn) => document.querySelectorAll(sel).forEach(fn);
    set("[data-site]", (el) => { const v = S[el.dataset.site]; if (v !== undefined && v !== "") el.textContent = v; });
    set("[data-download]", (a) => {
      if (S.downloadUrl) {
        a.href = S.downloadUrl;
        a.setAttribute("download", "");
      } else {
        a.href = "#download";
        a.title = "The download link is added when the site is published";
      }
    });
    set("[data-donate]", (a) => {
      if (S.donateUrl) {
        a.href = S.donateUrl;
        a.target = "_blank";
        a.rel = "noopener";
      } else {
        a.href = "#support";
        a.classList.add("disabled");
        a.title = "Support link coming soon";
        const sub = a.querySelector(".btn-sub");
        if (sub) sub.textContent = "coming soon";
      }
    });
    set("[data-source]", (a) => { if (S.sourceUrl) a.href = S.sourceUrl; else a.closest("[data-hide-empty]")?.remove(); });
    set("[data-studio]", (el) => {
      if (!S.studioName) { el.closest("[data-hide-empty]")?.remove(); return; }
      if (S.studioUrl) {
        const a = document.createElement("a");
        a.href = S.studioUrl; a.textContent = S.studioName; a.rel = "noopener";
        el.replaceChildren(a);
      } else el.textContent = S.studioName;
    });
    set("[data-email]", (el) => {
      if (!S.contactEmail) { el.closest("[data-hide-empty]")?.remove(); return; }
      el.textContent = S.contactEmail;
      if (el.tagName === "A") el.href = "mailto:" + S.contactEmail;
    });
    set("[data-year]", (el) => { el.textContent = new Date().getFullYear(); });
  });
})();
