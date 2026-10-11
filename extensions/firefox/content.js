/* KazaA v2. revival Helper - content script (Chrome MV3 / Firefox MV2 compatible).
   Shows a "Download" button on video hover; sends the page URL to KazaA v2. revival. */
(function () {
  "use strict";
  const BRIDGE = "http://127.0.0.1:8765/add?url=";

  function sendToKazaA() {
    fetch(BRIDGE + encodeURIComponent(location.href), { mode: "cors" })
      .then(() => flash("Sent to KazaA v2. revival"))
      .catch(() => flash("KazaA v2. revival is not running"));
  }

  function flash(msg) {
    const el = document.createElement("div");
    el.textContent = msg;
    el.style.cssText =
      "position:fixed;top:16px;right:16px;z-index:2147483647;background:#222;" +
      "color:#fff;padding:10px 16px;border-radius:6px;font:13px sans-serif;" +
      "box-shadow:0 2px 8px rgba(0,0,0,.4)";
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }

  function makeButton() {
    const btn = document.createElement("div");
    btn.textContent = "Download";
    btn.style.cssText =
      "position:absolute;z-index:2147483646;background:rgba(20,20,20,.85);" +
      "color:#fff;padding:4px 10px;border-radius:4px;font:12px sans-serif;" +
      "cursor:pointer;display:none";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      sendToKazaA();
    });
    document.documentElement.appendChild(btn);
    return btn;
  }

  const btn = makeButton();
  let current = null;

  document.addEventListener("mouseover", (e) => {
    const v = e.target.closest ? e.target.closest("video") : null;
    if (v) {
      current = v;
      const r = v.getBoundingClientRect();
      btn.style.top = window.scrollY + r.top + 6 + "px";
      btn.style.left = window.scrollX + r.left + r.width - 90 + "px";
      btn.style.display = "block";
    }
  }, true);

  document.addEventListener("mouseout", (e) => {
    if (current && e.target === current) {
      btn.style.display = "none";
      current = null;
    }
  }, true);

  document.addEventListener("scroll", () => { btn.style.display = "none"; }, true);
})();
