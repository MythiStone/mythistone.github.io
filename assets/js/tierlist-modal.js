/*
 * tierlist-modal.js — the Sim DPS Tierlist "what was this simmed with?" modal.
 *
 * Each DPS bar on the tierlist (Popular / SimC BIS) is a button carrying its
 * spec id + gear set. A click opens one shared Bootstrap modal that shows the
 * exact gear and talents SimulationCraft used for that (spec, gear set): the
 * gear in the spec page's double-column armory layout, the talents as the same
 * positioned tree the spec page and analyzer draw.
 *
 * Data source: /assets/json/tierlist_gear.json, emitted by
 * generateSimcProfiles.py (the DB-having sim-profiles job) as
 *   { "<specId>": { "popular": {talents, slots}, "simcbis": {talents, slots} } }
 * where each slot is { id, name, icon, quality, bonus[], enchant?, gems?[] } and
 * `talents` is the Blizzard loadout export string. Item icon/name/rarity are
 * pre-resolved server-side. The gear layout and talent tree are drawn by the
 * shared loadout-view.js (window.MythiLoadout), which must load first.
 */
(function () {
  "use strict";

  var esc = window.MythiLoadout.esc;

  var modalEl = document.getElementById("gearModal");
  if (!modalEl) return;
  var titleEl = document.getElementById("gearModalTitle");
  var iconEl = document.getElementById("gearModalIcon");
  var bodyEl = document.getElementById("gearModalBody");

  // ---- shipped-catalog loaders (each fetched once, tolerant) ---------------
  var gearData = null, gearPromise = null;
  function loadGearData() {
    if (gearPromise) return gearPromise;
    gearPromise = fetch("/assets/json/tierlist_gear.json")
      .then(function (r) {
        // A 404 means the file isn't present (a template-only --debug preview,
        // which never emits it) — degrade to the per-spec "no gear recorded"
        // notice rather than a hard error. Any other failure is a real problem.
        if (r.status === 404) return {};
        if (!r.ok) { var e = new Error("gear data HTTP " + r.status); e.dataError = true; throw e; }
        return r.json();
      })
      .then(function (o) { gearData = o || {}; return gearData; });
    return gearPromise;
  }

  // ---- open + populate -----------------------------------------------------

  function populate(btn) {
    var specId = btn.getAttribute("data-spec-id");
    var gearset = btn.getAttribute("data-gearset");
    var label = btn.getAttribute("data-label") || "";
    var specName = btn.getAttribute("data-spec-name") || "";
    var className = btn.getAttribute("data-class-name") || "";
    var cleanClass = btn.getAttribute("data-clean-class") || "";
    var icon = btn.getAttribute("data-icon");

    if (iconEl) {
      if (icon) { iconEl.src = "/data/icons/" + icon + ".jpg"; iconEl.hidden = false; }
      else { iconEl.hidden = true; }
    }
    if (titleEl) {
      titleEl.innerHTML = '<span class="class-' + esc(cleanClass) + '-text">' +
        esc(specName) + " " + esc(className) + '</span> ' +
        '<span class="text-secondary">&middot; ' + esc(label) + '</span>';
    }
    bodyEl.innerHTML = '<p class="text-sm text-secondary mb-0">Loading gear and talents…</p>';

    loadGearData()
      .then(function () {
        var set = ((gearData && gearData[specId]) || {})[gearset];
        if (!set) {
          bodyEl.innerHTML = '<div class="alert alert-warning text-dark text-sm mb-0">' +
            '<i class="material-symbols-rounded align-middle me-1">warning</i>' +
            'No ' + esc(label) + ' gear was recorded for this spec.</div>';
          return;
        }
        return window.MythiLoadout.render(bodyEl, {
          specId: specId, talents: set.talents, slots: set.slots,
        });
      })
      .catch(function () {
        bodyEl.innerHTML = '<div class="alert alert-warning text-dark text-sm mb-0">' +
          '<i class="material-symbols-rounded align-middle me-1">warning</i>' +
          "Couldn't load the gear data. Reload the page and try again.</div>";
      });
  }

  var modal = window.bootstrap && window.bootstrap.Modal
    ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;

  // ---- deep link (#gearModal&gear=<specId>-<gearset>) -----------------------
  //
  // The modal is built in JS from a spec id + gear set, so its contents can't be
  // reached by an element id alone: they ride in the hash as gear=<specId>-<gearset>,
  // mirroring the comps page Details modal (comp=<specIds>). deep-link.js keeps the
  // #gearModal target + this state in the address bar (copy-link button in the modal
  // header) and, on a fresh load, opens the right spec+gearset modal — independent of
  // which target-count tab is active, because the same button exists in every tab.
  var openGear = null;

  function openFor(btn) {
    var specId = btn.getAttribute("data-spec-id");
    var gearset = btn.getAttribute("data-gearset");
    openGear = { specId: specId, gearset: gearset };
    populate(btn);
    if (modal) modal.show();
    if (window.MythiLink) window.MythiLink.sync();
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("[data-gear-open]");
    if (!btn) return;
    ev.preventDefault();
    openFor(btn);
  });

  modalEl.addEventListener("hidden.bs.modal", function () {
    openGear = null;
    if (window.MythiLink) window.MythiLink.sync();
  });

  if (window.MythiLink) {
    window.MythiLink.registerState("gear", {
      read: function () {
        return openGear ? openGear.specId + "-" + openGear.gearset : null;
      },
      apply: function (value) {
        var i = String(value).indexOf("-");
        if (i < 1) return;
        var specId = String(value).slice(0, i);
        var gearset = String(value).slice(i + 1);
        if (!specId || !gearset) return;
        var btn = document.querySelector(
          '[data-gear-open][data-spec-id="' + specId + '"][data-gearset="' + gearset + '"]'
        );
        if (btn) openFor(btn);
      }
    });
  }
})();
