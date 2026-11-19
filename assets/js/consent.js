/* Klaro consent helpers for every third-party embed (keystone.guru, Twitch, YouTube).
 *
 * Embeds name their Klaro service in data-embed-service, NOT data-name, so Klaro never
 * manages them: Klaro swaps data-src -> src on every data-name element at init, which
 * loaded every hidden embed on the page at once (332 on a busy streamer page, enough
 * to crash the tab). Instead each embed loads through loadEmbed when its panel opens,
 * which also checks consent, so nothing loads against the visitor's choice.
 */
(function () {
  "use strict";

  var POLL_MS = 500;
  var POLL_ATTEMPTS = 20;

  function manager() {
    try {
      if (!window.klaro || typeof klaro.getManager !== "function") return null;
      return klaro.getManager();
    } catch (e) {
      // Klaro is loaded with defer and initialises asynchronously, so this is
      // "not ready yet" rather than an error.
      return null;
    }
  }

  function granted(name) {
    try {
      var mgr = manager();
      if (mgr && typeof mgr.getConsent === "function") return !!mgr.getConsent(name);
      if (window.klaro && klaro.consents &&
        Object.prototype.hasOwnProperty.call(klaro.consents, name)) {
        return !!klaro.consents[name];
      }
    } catch (e) { /* treat an unreadable manager as "no consent" */ }
    return false;
  }

  // Runs cb() once consent for `name` is granted — immediately if it already is,
  // exactly once otherwise.
  //
  // The watcher and the poll both run, deliberately. Klaro's watcher payload
  // shape varies between versions, so a watcher that silently never matches is a
  // real possibility (it was: granting consent with a route panel already open
  // left the embed unloaded until a reload). And the poll alone isn't enough
  // either — a deep link can open a panel before Klaro has initialised, so there
  // is no manager to watch yet. Whichever notices first wins.
  function whenGranted(name, cb) {
    if (granted(name)) {
      cb();
      return;
    }

    var done = false;
    function fire() {
      if (done) return;
      done = true;
      cb();
    }

    var mgr = manager();
    if (mgr && typeof mgr.watch === "function") {
      try {
        mgr.watch({
          update: function (obj) {
            var states = obj && (obj.states || obj);
            if ((states && states[name]) || granted(name)) fire();
          }
        });
      } catch (e) { /* the poll below still covers us */ }
    }

    var attempts = 0;
    var id = setInterval(function () {
      attempts++;
      if (done || attempts > POLL_ATTEMPTS) {
        clearInterval(id);
        return;
      }
      if (granted(name)) {
        clearInterval(id);
        fire();
      }
    }, POLL_MS);
  }

  function serviceTitle(name) {
    try {
      var services = manager().config.services || [];
      for (var i = 0; i < services.length; i++) {
        if (services[i].name === name) return services[i].title || name;
      }
    } catch (e) { /* fall back to the raw name */ }
    return name;
  }

  // Klaro doesn't manage these embeds, so it renders no "load external content"
  // notice for them, and an embed that silently stays blank just reads as broken.
  // Stand in with an equivalent notice.
  //
  // Positioned with the same utilities as .iframe-spinner so it centres in the
  // container without needing its own stylesheet.
  function ensureNotice(container, service) {
    if (!container) return;
    if (container.querySelector(".klaro, .context-notice, .mythi-embed-notice")) return;

    var box = document.createElement("div");
    box.className = "mythi-embed-notice position-absolute top-50 start-50 translate-middle text-center px-3";

    var text = document.createElement("p");
    text.className = "text-sm mb-2";
    text.textContent = "External content from " + serviceTitle(service) +
      " is blocked until you allow it.";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-primary mb-0";
    btn.textContent = "Cookie settings";
    btn.addEventListener("click", function () {
      if (window.klaro && typeof klaro.show === "function") klaro.show();
    });

    box.appendChild(text);
    box.appendChild(btn);
    container.appendChild(box);
  }

  function clearNotice(container) {
    if (!container) return;
    var own = container.querySelector(".mythi-embed-notice");
    if (own) own.remove();
  }

  // Set an embed's src from its data-src, but only with consent, and own the
  // loading spinner while doing it.
  //
  // The spinner sits in the same .iframe-container as the embed on every page
  // that uses one. It has to stay hidden until a load is actually in flight:
  // without consent nothing loads, ensureNotice puts the "blocked until you allow
  // it" notice where the embed would be, and a spinner left running sits on top of
  // that notice.
  //
  // Reads the src ATTRIBUTE, never the property — the property resolves src=""
  // to the document's own URL, so a property check never sees an unloaded embed.
  function loadEmbed(el, onLoad) {
    if (!el || !el.getAttribute("data-src")) return;

    var container = (el.closest && el.closest(".iframe-container")) || el.parentElement;
    var spinner = container && container.querySelector(".iframe-spinner");
    function spin(on) {
      if (spinner) spinner.classList.toggle("d-none", !on);
    }

    function finish() {
      spin(false);
      if (typeof onLoad === "function") onLoad();
    }

    // Already loading or loaded (e.g. the panel was reopened).
    if (el.getAttribute("src")) {
      el.addEventListener("load", finish, { once: true });
      return;
    }

    spin(false);
    var service = el.getAttribute("data-embed-service") || "";
    function apply() {
      clearNotice(container);
      if (el.getAttribute("src")) return;
      spin(true);
      el.addEventListener("load", finish, { once: true });
      el.addEventListener("error", finish, { once: true });
      el.setAttribute("src", el.getAttribute("data-src"));
    }
    if (!service) { apply(); return; }
    if (!granted(service)) ensureNotice(container, service);
    whenGranted(service, apply);
  }

  // Wire the standard "load the route embed the first time its accordion panel is
  // opened" behaviour, shared verbatim by the spec, dungeon and streamer pages.
  // loadEmbed owns the consent check, deferral, src and spinner, so the pages can
  // never drift apart on it.
  function wireAccordionEmbeds(accordionSelector) {
    document.querySelectorAll(accordionSelector + " .accordion-collapse").forEach(function (panel) {
      panel.addEventListener("shown.bs.collapse", function () {
        panel.querySelectorAll("iframe[data-src]").forEach(function (el) { loadEmbed(el); });
      });
    });
  }

  window.MythiConsent = {
    granted: granted,
    whenGranted: whenGranted,
    loadEmbed: loadEmbed,
    wireAccordionEmbeds: wireAccordionEmbeds
  };
})();
