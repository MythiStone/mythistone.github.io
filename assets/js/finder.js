// Generic client-side finder shared by the Route Finder and VOD Finder pages.
//
// A page calls MythiFinder.create(config): it owns the search Worker, the filter
// form <-> URL sync, infinite scroll, the loading overlay, and rendering. The
// page only supplies its filter list, a renderItem(item) function (KEEP IN SYNC
// with the matching Jinja macro), and the sort/index fields. Per-page filters
// (e.g. VOD-only video type / POV spec) are just extra entries in `filters`, so
// adding a filter is a one-line change on whichever page(s) want it.
(function () {
  "use strict";

  const PAGE_SIZE = 50;

  function debounce(fn, ms) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  // Frequency map of a value list (used for multiset filters).
  function countMap(list) {
    const m = new Map();
    for (const v of list) {
      const k = String(v);
      m.set(k, (m.get(k) || 0) + 1);
    }
    return m;
  }

  function valOf(id) {
    const $el = window.jQuery ? window.jQuery("#" + id) : null;
    let v;
    if ($el && $el.selectpicker) v = $el.selectpicker("val");
    else if ($el) v = $el.val();
    if (v === undefined || v === null) return [];
    return Array.isArray(v) ? v : v ? [v] : [];
  }

  function setVal(id, values) {
    const $el = window.jQuery ? window.jQuery("#" + id) : null;
    if ($el && $el.selectpicker) $el.selectpicker("val", values);
  }

  function create(config) {
    const {
      formId,
      accordionId,
      sentinelId,
      overlayId,
      summarySelector = ".pagination-summary",
      jsonUrl,
      indexFields,
      sort = [],
      noun = "result",
      filters = [],
      renderItem,
      relaxFilterId = null,
      // Pages with no server-rendered skeleton (VOD finder) run an empty query on
      // load to show everything; the routes page keeps its skeleton and stays idle
      // until the visitor searches.
      autoQueryOnLoad = false,
    } = config;

    let worker = null;
    let workerReady = false;
    let pendingInitialQuery = false;
    let currentPage = 1;
    let loadedCount = 0;
    let pendingAppend = false;
    let appendResolve = null;
    let infinite = null;
    let lastResults = { total: 0, relaxHint: null };

    const relaxFilter = filters.find((f) => f.id === relaxFilterId) || null;

    // ---- multiset state ----------------------------------------------------
    // A `multiset: true` filter (the team-comp spec picker) can require the same
    // spec more than once. The selectpicker only holds DISTINCT values, so the
    // multiplicity lives here as specId -> count and is expressed in a chip row.
    const multisetFilter = filters.find((f) => f.multiset) || null;
    const multisetCounts = new Map(); // specId(string) -> count (>=1)
    const MULTISET_MAX = multisetFilter ? multisetFilter.max || 5 : 5;

    function multisetTotal() {
      let t = 0;
      for (const c of multisetCounts.values()) t += c;
      return t;
    }
    // Trim trailing counts until the total fits MULTISET_MAX (defensive: the
    // stepper already refuses to overflow).
    function clampMultiset(order) {
      let over = multisetTotal() - MULTISET_MAX;
      for (let i = order.length - 1; i >= 0 && over > 0; --i) {
        const s = String(order[i]);
        const c = multisetCounts.get(s) || 1;
        const take = Math.min(c - 1, over);
        multisetCounts.set(s, c - take);
        over -= take;
      }
    }
    // Keep counts in step with the picker: new specs default to 1, removed specs
    // drop out. Returns the current distinct selection (picker order).
    function reconcileMultiset() {
      const chosen = valOf(multisetFilter.id).map(String);
      for (const k of Array.from(multisetCounts.keys())) {
        if (!chosen.includes(k)) multisetCounts.delete(k);
      }
      for (const s of chosen) if (!multisetCounts.has(s)) multisetCounts.set(s, 1);
      clampMultiset(chosen);
      return chosen;
    }
    // Selected specs expanded by their count, in picker order (the clause/URL value).
    function multisetValues() {
      const chosen = reconcileMultiset();
      const out = [];
      for (const s of chosen) {
        const c = multisetCounts.get(s) || 1;
        for (let i = 0; i < c; i++) out.push(s);
      }
      return out;
    }
    // Load a multiset value list (from URL or a relax hint) into picker + counts.
    function applyMultisetFromValues(values) {
      const counts = countMap(values);
      multisetCounts.clear();
      const distinct = [];
      for (const s of values.map(String)) {
        if (!distinct.includes(s)) distinct.push(s);
      }
      for (const [s, c] of counts) multisetCounts.set(s, c);
      setVal(multisetFilter.id, distinct);
      clampMultiset(distinct);
      renderMultisetChips();
    }

    // ---- form <-> params ---------------------------------------------------
    function paramsFromForm() {
      const p = {};
      for (const f of filters) {
        p[f.param] = f.multiset ? multisetValues() : valOf(f.id);
      }
      return p;
    }
    function hasAnyParams(p) {
      return filters.some((f) => (p[f.param] || []).length);
    }
    function parseUrlParams() {
      const sp = new URLSearchParams(window.location.search);
      const p = {};
      for (const f of filters) {
        const v = sp.get(f.param) || "";
        p[f.param] = v ? v.split(",").map((s) => s.trim()).filter(Boolean) : [];
      }
      return p;
    }
    function updateUrl(p, { replace = true } = {}) {
      const sp = new URLSearchParams();
      for (const f of filters) {
        if ((p[f.param] || []).length) sp.set(f.param, p[f.param].join(","));
      }
      // Keep the hash: deep-link.js owns it (e.g. #vods-streamers), and this runs at
      // boot, possibly before deep-link has read it.
      const url = window.location.pathname + (sp.toString() ? "?" + sp.toString() : "") + window.location.hash;
      if (replace) history.replaceState(p, "", url);
      else history.pushState(p, "", url);
    }
    function applyParamsToForm(p) {
      for (const f of filters) {
        const vals = p[f.param] || [];
        if (!vals.length) continue;
        if (f.multiset) applyMultisetFromValues(vals);
        else setVal(f.id, vals);
      }
    }

    // ---- clause building ---------------------------------------------------
    function buildClauses() {
      const clauses = [];
      for (const f of filters) {
        let values = f.multiset ? multisetValues() : valOf(f.id);
        if (f.expand) values = f.expand(values);
        if (!values.length) continue;
        const clause = { field: f.field, mode: f.mode || "anyOf", values };
        if (f.mode === "allRelax" && f.priorityByRole) {
          const roleOf = (id) =>
            Number(((window.spec_data || {})[id] || {}).role ?? 2);
          if (f.multiset) {
            // Relaxation trims the priority tail, so a distinct spec (one copy)
            // per role comes first and the EXTRA copies of a duplicate sort to
            // the end -- the worker drops a duplicate before dropping a spec.
            const counts = countMap(values);
            const distinct = Array.from(counts.keys()).sort(
              (a, b) => roleOf(a) - roleOf(b)
            );
            const extras = [];
            for (const s of distinct) {
              for (let i = 1; i < counts.get(s); i++) extras.push(s);
            }
            extras.sort((a, b) => roleOf(a) - roleOf(b));
            clause.priority = distinct.concat(extras);
          } else {
            clause.priority = values.slice().sort((a, b) => roleOf(a) - roleOf(b));
          }
        }
        clauses.push(clause);
      }
      return clauses;
    }

    // ---- worker ------------------------------------------------------------
    function initWorker() {
      if (worker) return;
      worker = new Worker("/assets/js/finder-worker.js");
      worker.onmessage = function (ev) {
        const msg = ev.data;
        if (!msg || !msg.cmd) return;
        if (msg.cmd === "built") {
          workerReady = true;
          // Run the query that was requested before the index finished building.
          if (pendingInitialQuery) {
            pendingInitialQuery = false;
            doQuery({ page: 1 });
          }
        } else if (msg.cmd === "result") {
          lastResults.total = msg.total;
          lastResults.relaxHint = msg.relaxHint || null;
          const isAppend = pendingAppend;
          pendingAppend = false;
          if (isAppend) {
            currentPage = msg.page;
            loadedCount += msg.results.length;
            renderMatches(msg.results, true);
          } else {
            currentPage = 1;
            loadedCount = msg.results.length;
            renderMatches(msg.results, false);
          }
          updateSummary(loadedCount, msg.total);
          const done = loadedCount >= msg.total;
          if (appendResolve) {
            const resolve = appendResolve;
            appendResolve = null;
            resolve(done);
          }
          if (!isAppend && infinite) {
            if (done) infinite.finish();
            else infinite.reset();
          }
        } else if (msg.cmd === "error") {
          console.error("Finder worker error:", msg.payload);
        }
      };
      fetch(jsonUrl)
        .then((r) => {
          if (!r.ok) throw new Error("Failed to load " + jsonUrl + ": " + r.status);
          return r.json();
        })
        .then((json) => {
          worker.postMessage({
            cmd: "build",
            payload: { items: json, indexFields },
          });
        })
        .catch((err) => console.error("Failed to load finder data:", err));
    }

    function doQuery({ page = 1, pageSize = PAGE_SIZE, append = false } = {}) {
      if (!worker) initWorker();
      pendingAppend = append;
      worker.postMessage({
        cmd: "query",
        payload: { clauses: buildClauses(), sort, page, pageSize },
      });
    }

    // Query now if the index is built, otherwise as soon as the build completes.
    function queryWhenReady() {
      if (!worker) initWorker();
      if (workerReady) doQuery({ page: 1 });
      else pendingInitialQuery = true;
    }

    // ---- rendering ---------------------------------------------------------
    function relaxLabel(value) {
      if (relaxFilter && relaxFilter.label) return relaxFilter.label(value);
      return String(value);
    }

    function renderNoResults(accordion) {
      const hint = lastResults.relaxHint;
      const chosen = relaxFilter
        ? relaxFilter.multiset
          ? multisetValues()
          : valOf(relaxFilter.id).map(String)
        : [];
      if (!hint || !hint.values || !hint.values.length || !relaxFilter) {
        accordion.innerHTML =
          '<p class="text-sm mb-0">No ' + noun + "s found for these filters.</p>";
        return;
      }
      const kept = hint.values.map(String);
      // Multiset difference: a spec whose REQUIRED count drops (e.g. 2x -> 1x)
      // counts as dropped once, so the message names it once.
      const keptCounts = countMap(kept);
      const dropped = [];
      for (const [v, c] of countMap(chosen)) {
        if (c - (keptCounts.get(v) || 0) > 0 && !dropped.includes(v)) dropped.push(v);
      }
      const wrap = document.createElement("div");
      wrap.className = "route-relax-notice text-sm";
      wrap.innerHTML =
        '<p class="mb-2">No ' + noun + " has been recorded with all " +
        chosen.length + " of these.</p>" +
        '<p class="mb-2">Searching without <strong>' +
        dropped.map(relaxLabel).join(", ") + "</strong> finds <strong>" +
        hint.total + "</strong> " + noun + (hint.total === 1 ? "" : "s") + ".</p>" +
        '<button type="button" class="btn btn-sm btn-primary mb-0" data-relax-btn>' +
        "Search with " + kept.length + " instead</button>";
      accordion.innerHTML = "";
      accordion.appendChild(wrap);
      wrap.querySelector("[data-relax-btn]").addEventListener("click", function () {
        if (relaxFilter.multiset) applyMultisetFromValues(kept);
        else setVal(relaxFilter.id, kept);
        currentPage = 1;
        const params = paramsFromForm();
        updateUrl(params, { replace: false });
        doQuery({ page: 1 });
      });
    }

    function wirePanelConsent(item) {
      const collapse = item.querySelector(".accordion-collapse");
      if (!collapse || collapse.getAttribute("data-consent-wired")) return;
      collapse.setAttribute("data-consent-wired", "1");
      collapse.addEventListener("shown.bs.collapse", function () {
        const iframe = collapse.querySelector("iframe[data-src]");
        if (iframe && window.MythiConsent) window.MythiConsent.loadEmbed(iframe);
      });
    }

    function fillTimestamps(item) {
      item.querySelectorAll(".timestamp").forEach(function (el) {
        const t = el.getAttribute("data-timestamp");
        if (!t) return;
        el.textContent = (el.textContent + " " + window.timeAgo(Number(t))).trim();
        el.setAttribute("title", new Date(Number(t) * 1000).toLocaleString());
      });
    }

    function renderMatches(items, append) {
      const accordion = document.getElementById(accordionId);
      if (!append) accordion.innerHTML = "";
      if (!items || items.length === 0) {
        if (!append) renderNoResults(accordion);
        return;
      }
      items.forEach((it) => {
        const el = renderItem(it);
        if (!el) return;
        fillTimestamps(el);
        accordion.appendChild(el);
        wirePanelConsent(el);
      });
      if (window.MythiLink) window.MythiLink.refresh();
    }

    // ---- multiset count chips ----------------------------------------------
    // One chip per selected spec with a stepper that sets how many copies the
    // comp requires (1..remaining, total capped at MULTISET_MAX). Mirrors the
    // filter-change path: update the URL, then the visitor clicks Search.
    function renderMultisetChips() {
      if (!multisetFilter) return;
      const box = document.getElementById(multisetFilter.id + "Counts");
      if (!box) return;
      const chosen = reconcileMultiset();
      if (!chosen.length) {
        box.innerHTML = "";
        return;
      }
      const total = multisetTotal();
      const frag = document.createDocumentFragment();
      chosen.forEach((s) => {
        const count = multisetCounts.get(s) || 1;
        const spec = (window.spec_data || {})[s] || {};
        const chip = document.createElement("div");
        chip.className = "spec-count-chip";
        const iconUrl = spec.SpellIconFileId
          ? "/data/icons/" + spec.SpellIconFileId + ".jpg"
          : "";
        chip.innerHTML =
          (iconUrl ? '<img src="' + iconUrl + '" alt="" class="spec-count-icon">' : "") +
          '<span class="spec-count-name">' + (spec.name || s) + "</span>" +
          '<span class="spec-count-steps">' +
          '<button type="button" class="spec-count-step" data-dir="-1"' +
          (count <= 1 ? " disabled" : "") + ' aria-label="One fewer">&minus;</button>' +
          '<span class="spec-count-badge">&times;' + count + "</span>" +
          '<button type="button" class="spec-count-step" data-dir="1"' +
          (total >= MULTISET_MAX ? " disabled" : "") + ' aria-label="One more">+</button>' +
          "</span>";
        chip.querySelectorAll(".spec-count-step").forEach((btn) => {
          btn.addEventListener("click", () =>
            stepMultiset(s, Number(btn.getAttribute("data-dir")))
          );
        });
        frag.appendChild(chip);
      });
      box.innerHTML = "";
      box.appendChild(frag);
    }

    function stepMultiset(spec, dir) {
      const s = String(spec);
      const cur = multisetCounts.get(s) || 1;
      if (dir > 0) {
        if (multisetTotal() >= MULTISET_MAX) return;
        multisetCounts.set(s, cur + 1);
      } else {
        if (cur <= 1) return;
        multisetCounts.set(s, cur - 1);
      }
      renderMultisetChips();
      currentPage = 1;
      updateUrl(paramsFromForm(), { replace: true });
    }

    // ---- summary + overlay -------------------------------------------------
    function updateSummary(loaded, total) {
      const summary = document.querySelector(summarySelector);
      if (!summary) return;
      if (!total || total <= 0) {
        summary.style.display = "none";
        return;
      }
      summary.style.display = "inline-block";
      summary.textContent =
        "Showing " + loaded + " of " + total + " " + noun + (total === 1 ? "" : "s");
    }

    function showOverlayUntilMutates(timeoutMs = 10000) {
      const overlay = document.getElementById(overlayId);
      if (overlay) {
        overlay.style.display = "flex";
        overlay.setAttribute("aria-hidden", "false");
      }
      const hide = () => {
        if (!overlay) return;
        overlay.style.display = "none";
        overlay.setAttribute("aria-hidden", "true");
      };
      const accordion = document.getElementById(accordionId);
      if (!accordion) {
        setTimeout(hide, 200);
        return;
      }
      const mo = new MutationObserver((mut, obs) => {
        if (mut && mut.length) {
          obs.disconnect();
          hide();
        }
      });
      mo.observe(accordion, { childList: true, subtree: true });
      setTimeout(() => {
        try { mo.disconnect(); } catch (e) {}
        hide();
      }, timeoutMs);
    }

    // ---- infinite scroll ---------------------------------------------------
    function loadMore() {
      if (loadedCount >= lastResults.total) return true;
      return new Promise((resolve) => {
        appendResolve = resolve;
        doQuery({ page: currentPage + 1, append: true });
      });
    }

    // ---- wiring ------------------------------------------------------------
    function runFromUrlOrForm() {
      const initial = parseUrlParams();
      if (hasAnyParams(initial)) {
        showOverlayUntilMutates(10000);
        applyParamsToForm(initial);
        currentPage = 1;
        queryWhenReady();
      } else {
        initWorker();
        updateUrl(paramsFromForm(), { replace: true });
        if (autoQueryOnLoad) {
          showOverlayUntilMutates(10000);
          queryWhenReady();
        }
      }
    }

    function init() {
      const form = document.getElementById(formId);
      if (form) {
        form.addEventListener("submit", function (e) {
          e.preventDefault();
          currentPage = 1;
          updateUrl(paramsFromForm(), { replace: false });
          showOverlayUntilMutates(10000);
          doQuery({ page: 1 });
        });
      }

      runFromUrlOrForm();

      const onChange = debounce(() => {
        if (multisetFilter) renderMultisetChips();
        updateUrl(paramsFromForm(), { replace: true });
      }, 220);
      const selector = filters.map((f) => "#" + f.id).join(", ");
      if (window.jQuery) window.jQuery(selector).on("changed.bs.select change", onChange);
      if (multisetFilter) renderMultisetChips();

      window.addEventListener("popstate", function (ev) {
        const state = ev.state || parseUrlParams();
        if (!state) return;
        applyParamsToForm(state);
        currentPage = 1;
        if (hasAnyParams(state)) {
          showOverlayUntilMutates(10000);
          queryWhenReady();
        }
      });

      const sentinel = document.getElementById(sentinelId);
      if (sentinel && window.MythiInfinite) {
        infinite = window.MythiInfinite.create({ sentinel, onLoadMore: loadMore });
      }
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }

    return { doQuery };
  }

  window.MythiFinder = { create };
})();
