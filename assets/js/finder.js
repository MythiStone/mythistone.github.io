// Generic client-side finder shared by the Route Finder and VOD Finder pages.
//
// A page calls MythiFinder.create(config): it owns the search Worker, the filter
// form <-> URL sync, infinite scroll, the loading overlay, and rendering. The
// page only supplies its filter list, a renderItem(item) function (KEEP IN SYNC
// with the matching Jinja macro), and the sort/index fields. Per-page filters
// (e.g. VOD-only video type / POV spec) are just extra entries in `filters`, so
// adding a filter is a one-line change on whichever page(s) want it.
//
// Results update live as filters change (no Search button). Each query is
// tagged with a sequence id so only the latest answer renders, and rendering is
// paged (PAGE_SIZE + infinite scroll), so a change never draws the full set.
// Filter entry options beyond id/param/field/mode:
//   advanced: true  lives in the folded "More filters" section (badge count)
//   scopedBy: id    a picker whose <optgroup data-dungeon> are limited to the
//                   values picked in filter `id`
(function () {
  "use strict";

  const PAGE_SIZE = 50;
  // The worker inherits this script's ?v= so a rebuild never pairs new page code
  // with a cached worker (an old worker drops the seq id and every result).
  const VERSION = document.currentScript ? new URL(document.currentScript.src).search : "";

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
    // An NPC id can sit under several dungeons, so the picker may hold it twice.
    return Array.isArray(v) ? Array.from(new Set(v)) : v ? [v] : [];
  }

  function setVal(id, values) {
    const el = document.getElementById(id);
    const $el = window.jQuery ? window.jQuery("#" + id) : null;
    if (!$el || !$el.selectpicker) return;
    $el.selectpicker("val", el && !el.multiple ? values[0] || "" : values);
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
      // Pages with no server-rendered skeleton run an empty query on load.
      autoQueryOnLoad = false,
      // With no active filter and the default sort, show the server-rendered
      // skeleton (one row per dungeon) instead of querying everything.
      skeletonWhenEmpty = false,
      // { selectId, param, options: { value: sortSpec[] } }, first key is the default.
      sortControl = null,
      advancedCollapseId = null,
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
    let querySeq = 0;
    let lastQueryKey = null;
    let skeletonNodes = null;
    let showingSkeleton = false;

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

    // ---- sort --------------------------------------------------------------
    const sortKeys = sortControl ? Object.keys(sortControl.options) : [];
    function currentSortKey() {
      if (!sortControl) return null;
      const v = valOf(sortControl.selectId)[0];
      return v && sortControl.options[v] ? v : sortKeys[0];
    }
    function currentSort() {
      return sortControl ? sortControl.options[currentSortKey()] : sort;
    }

    // ---- form <-> params ---------------------------------------------------
    function paramsFromForm() {
      const p = {};
      for (const f of filters) {
        p[f.param] = f.multiset ? multisetValues() : valOf(f.id);
      }
      if (sortControl) {
        const k = currentSortKey();
        p[sortControl.param] = k === sortKeys[0] ? [] : [k];
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
      if (sortControl) {
        const v = sp.get(sortControl.param) || "";
        p[sortControl.param] = sortControl.options[v] ? [v] : [];
      }
      return p;
    }
    function updateUrl(p, { replace = true } = {}) {
      const sp = new URLSearchParams();
      for (const f of filters) {
        if ((p[f.param] || []).length) sp.set(f.param, p[f.param].join(","));
      }
      if (sortControl && (p[sortControl.param] || []).length) {
        sp.set(sortControl.param, p[sortControl.param][0]);
      }
      // Keep the hash: deep-link.js owns it (e.g. #vods-streamers), and this runs at
      // boot, possibly before deep-link has read it.
      const url = window.location.pathname + (sp.toString() ? "?" + sp.toString() : "") + window.location.hash;
      if (replace) history.replaceState(p, "", url);
      else history.pushState(p, "", url);
    }
    // Sets every filter, clearing those absent from p, so back/forward lands
    // on exactly the state described.
    function applyParamsToForm(p) {
      for (const f of filters) {
        const vals = p[f.param] || [];
        if (f.multiset) applyMultisetFromValues(vals);
        else setVal(f.id, vals);
      }
      if (sortControl) setVal(sortControl.selectId, [(p[sortControl.param] || [])[0] || sortKeys[0]]);
      applyScopes();
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
      worker = new Worker("/assets/js/finder-worker.js" + VERSION);
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
          // A newer query (or the skeleton) superseded this one.
          if (msg.seq !== querySeq) return;
          setSummaryBusy(false);
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
      if (!append) {
        querySeq++;
        // A fresh query supersedes an in-flight page load, so release the scroller.
        if (appendResolve) {
          const resolve = appendResolve;
          appendResolve = null;
          resolve(false);
        }
      }
      pendingAppend = append;
      worker.postMessage({
        cmd: "query",
        payload: { clauses: buildClauses(), sort: currentSort(), page, pageSize, seq: querySeq },
      });
    }

    // Query now if the index is built, otherwise as soon as the build completes.
    function queryWhenReady() {
      if (!worker) initWorker();
      if (workerReady) doQuery({ page: 1 });
      else pendingInitialQuery = true;
    }

    // Query for the current form state, or show the skeleton when the page wants
    // one and nothing is filtered. A state that is already shown is skipped.
    function refresh({ overlay = false } = {}) {
      const p = paramsFromForm();
      const key = JSON.stringify(p);
      if (key === lastQueryKey) return;
      lastQueryKey = key;
      const sorted = sortControl && p[sortControl.param].length > 0;
      if (skeletonWhenEmpty && !hasAnyParams(p) && !sorted) {
        restoreSkeleton();
        return;
      }
      if (overlay) showOverlayUntilMutates(10000);
      else setSummaryBusy(true);
      currentPage = 1;
      queryWhenReady();
    }

    function restoreSkeleton() {
      querySeq++; // drop any answer still in flight
      pendingInitialQuery = false;
      setSummaryBusy(false);
      const accordion = document.getElementById(accordionId);
      if (accordion && skeletonNodes && !showingSkeleton) {
        accordion.replaceChildren(...skeletonNodes);
        showingSkeleton = true;
      }
      loadedCount = 0;
      lastResults = { total: 0, relaxHint: null };
      updateSummary(0, 0);
      if (infinite) infinite.finish();
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
        afterFormChange({ push: true });
      });
    }

    function wirePanelConsent(item) {
      const collapse = item.querySelector(".accordion-collapse");
      if (!collapse || collapse.getAttribute("data-consent-wired")) return;
      collapse.setAttribute("data-consent-wired", "1");
      collapse.addEventListener("shown.bs.collapse", function () {
        if (!window.MythiConsent) return;
        collapse.querySelectorAll("iframe[data-src]").forEach((el) => window.MythiConsent.loadEmbed(el));
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
      if (!append) {
        // Detaches the skeleton nodes too; restoreSkeleton re-attaches them.
        accordion.innerHTML = "";
        showingSkeleton = false;
      }
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
    // comp requires (1..remaining, total capped at MULTISET_MAX).
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
      afterFormChange();
    }

    // ---- pickers scoped to another filter (NPCs to the picked dungeons) ------
    // Out-of-scope groups are detached rather than disabled: the same NPC id can
    // sit in several dungeons, and bootstrap-select would keep selecting (and
    // counting) every copy of a value that is still in the DOM.
    const scopeGroups = new Map(); // filter id -> original <optgroup>s in order
    function applyScopes() {
      for (const f of filters) {
        if (!f.scopedBy) continue;
        const el = document.getElementById(f.id);
        if (!el) continue;
        if (!scopeGroups.has(f.id)) {
          scopeGroups.set(f.id, Array.from(el.querySelectorAll("optgroup[data-dungeon]")));
        }
        const groups = scopeGroups.get(f.id);
        const scope = valOf(f.scopedBy).map(String);
        const visible = groups.filter(
          (g) => !scope.length || scope.includes(g.getAttribute("data-dungeon"))
        );
        const current = Array.from(el.querySelectorAll("optgroup[data-dungeon]"));
        if (current.length === visible.length && current.every((g, i) => g === visible[i])) continue;
        const kept = valOf(f.id).map(String);
        el.replaceChildren();
        visible.forEach((g, i) => {
          if (i) {
            const divider = document.createElement("option");
            divider.setAttribute("data-divider", "true");
            el.appendChild(divider);
          }
          el.appendChild(g);
        });
        groups.forEach((g) => g.querySelectorAll("option").forEach((o) => (o.selected = false)));
        // refresh() keeps stale per-option state for swapped groups (wrong
        // "N items selected"), so rebuild the picker instead.
        kept.forEach((v) => {
          const opt = el.querySelector('option[value="' + v + '"]');
          if (opt) opt.selected = true;
        });
        if (window.jQuery) window.jQuery(el).selectpicker("destroy").selectpicker();
      }
    }

    // ---- "More filters" badge ------------------------------------------------
    function advancedActiveCount() {
      return filters.filter((f) => f.advanced && valOf(f.id).length).length;
    }

    function updateAdvancedBadge() {
      const badge = advancedCollapseId && document.getElementById(advancedCollapseId + "Count");
      if (!badge) return;
      const n = advancedActiveCount();
      badge.textContent = n ? String(n) : "";
      badge.classList.toggle("d-none", !n);
    }

    function openAdvancedIfActive() {
      const panel = advancedCollapseId && document.getElementById(advancedCollapseId);
      if (!panel || !advancedActiveCount() || !window.bootstrap) return;
      window.bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false }).show();
    }

    // Every filter edit lands here: badge, URL, then the live query.
    function afterFormChange({ push = false } = {}) {
      if (multisetFilter) renderMultisetChips();
      applyScopes();
      updateAdvancedBadge();
      updateUrl(paramsFromForm(), { replace: !push });
      refresh();
    }

    // ---- summary + overlay -------------------------------------------------
    function setSummaryBusy(on) {
      const summary = document.querySelector(summarySelector);
      if (summary) summary.classList.toggle("finder-busy", on);
    }

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
      const sorted = sortControl && (initial[sortControl.param] || []).length;
      initWorker();
      if (hasAnyParams(initial) || sorted) {
        applyParamsToForm(initial);
        openAdvancedIfActive();
      }
      if (multisetFilter) renderMultisetChips();
      updateAdvancedBadge();
      updateUrl(paramsFromForm(), { replace: true });
      if (hasAnyParams(initial) || sorted || autoQueryOnLoad) refresh({ overlay: true });
      else lastQueryKey = JSON.stringify(paramsFromForm());
    }

    function init() {
      const form = document.getElementById(formId);
      if (form) form.addEventListener("submit", (e) => e.preventDefault());

      const accordion = document.getElementById(accordionId);
      if (skeletonWhenEmpty && accordion) {
        skeletonNodes = Array.from(accordion.children);
        showingSkeleton = true;
      }

      runFromUrlOrForm();

      const onChange = debounce(() => afterFormChange(), 300);
      const ids = filters.map((f) => f.id);
      if (sortControl) ids.push(sortControl.selectId);
      const selector = ids.map((id) => "#" + id).join(", ");
      if (window.jQuery) window.jQuery(selector).on("changed.bs.select change", onChange);

      window.addEventListener("popstate", function (ev) {
        const state = ev.state || parseUrlParams();
        if (!state) return;
        applyParamsToForm(state);
        updateAdvancedBadge();
        refresh({ overlay: true });
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
