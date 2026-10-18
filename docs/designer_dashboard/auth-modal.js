/*
 * murmurent dashboard — session login modal.
 *
 * When dashboard auth is enabled (a secret is configured server-side), any
 * mutating request without a valid session returns 401. This wraps
 * window.fetch so that the FIRST such 401 pops a small login modal, exchanges
 * the dashboard secret for a session cookie via POST /api/login/authenticate,
 * and transparently retries the original request. With auth OFF no 401 ever
 * fires, so this is inert.
 *
 * Self-contained, no framework. Injected before </body> on every page.
 */
(function () {
  "use strict";
  if (window.__wigamigAuthModal) return;
  window.__wigamigAuthModal = true;

  var _fetch = window.fetch.bind(window);
  var _pending = null; // shared Promise<boolean> so concurrent 401s share one prompt

  function currentHandle() {
    try {
      var u = new URLSearchParams(window.location.search).get("user");
      if (u) return u.replace(/^@/, "");
    } catch (e) {}
    return "";
  }

  function promptLogin() {
    if (_pending) return _pending;
    _pending = new Promise(function (resolve) {
      var done = function (ok) {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        _pending = null;
        resolve(ok);
      };
      var overlay = document.createElement("div");
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99999;display:flex;" +
        "align-items:center;justify-content:center;font-family:system-ui,-apple-system,sans-serif;";
      overlay.innerHTML =
        '<div role="dialog" aria-modal="true" style="background:#fff;border-radius:10px;padding:24px 26px;' +
        'max-width:380px;width:90%;box-shadow:0 10px 40px rgba(0,0,0,.3);">' +
        '<h2 style="margin:0 0 6px;font-size:18px;">Dashboard login</h2>' +
        '<p style="margin:0 0 16px;color:#555;font-size:13px;">This centre requires the ' +
        'dashboard secret to make changes.</p>' +
        '<label style="display:block;font-size:12px;color:#333;margin-bottom:4px;">Handle</label>' +
        '<input id="wgm-h" autocomplete="username" style="width:100%;box-sizing:border-box;padding:8px;' +
        'margin-bottom:12px;border:1px solid #ccc;border-radius:6px;">' +
        '<label style="display:block;font-size:12px;color:#333;margin-bottom:4px;">Dashboard secret</label>' +
        '<input id="wgm-s" type="password" autocomplete="current-password" style="width:100%;box-sizing:border-box;' +
        'padding:8px;margin-bottom:8px;border:1px solid #ccc;border-radius:6px;">' +
        '<div id="wgm-e" style="color:#b23a2b;font-size:12px;min-height:16px;margin-bottom:10px;"></div>' +
        '<button id="wgm-b" style="width:100%;padding:9px;background:#5b3fa0;color:#fff;border:none;' +
        'border-radius:6px;font-size:14px;cursor:pointer;">Log in</button>' +
        '<div style="text-align:center;margin-top:8px;"><a href="#" id="wgm-c" style="font-size:12px;' +
        'color:#888;">cancel</a></div>' +
        "</div>";
      document.body.appendChild(overlay);

      var hEl = overlay.querySelector("#wgm-h");
      var sEl = overlay.querySelector("#wgm-s");
      var eEl = overlay.querySelector("#wgm-e");
      var btn = overlay.querySelector("#wgm-b");
      hEl.value = currentHandle();
      (hEl.value ? sEl : hEl).focus();

      function submit() {
        eEl.textContent = "";
        btn.disabled = true;
        btn.textContent = "Logging in…";
        _fetch("/api/login/authenticate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ handle: hEl.value, secret: sEl.value }),
        })
          .then(function (r) {
            if (r.ok) {
              done(true);
              return;
            }
            return r.json().catch(function () { return {}; }).then(function (j) {
              eEl.textContent = j.detail || "Login failed (" + r.status + ")";
              btn.disabled = false;
              btn.textContent = "Log in";
            });
          })
          .catch(function (err) {
            eEl.textContent = String(err);
            btn.disabled = false;
            btn.textContent = "Log in";
          });
      }

      btn.addEventListener("click", submit);
      sEl.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
      overlay.querySelector("#wgm-c").addEventListener("click", function (e) {
        e.preventDefault();
        done(false);
      });
      overlay.addEventListener("keydown", function (e) { if (e.key === "Escape") done(false); });
    });
    return _pending;
  }

  window.fetch = function (input, init) {
    return _fetch(input, init).then(function (resp) {
      if (resp.status !== 401) return resp;
      var url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.indexOf("/api/login/authenticate") !== -1) return resp; // never loop on the login call
      return promptLogin().then(function (ok) {
        return ok ? _fetch(input, init) : resp; // retry once on success, else surface the 401
      });
    });
  };
})();
