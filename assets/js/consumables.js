/* Consumables browse page (consumables.html), served at /pages/consumables.
 *
 * Browse grid of all tracked consumables, filterable by category and used-by
 * spec/class, searchable by name. Each card links to the consumable's dedicated
 * static page at /consumables/<slug>.
 *
 * Data: /assets/json/consumables_index.json (compact manifest, includes a `slug`).
 * Spec names/icons are injected by the template as window.specs_map.
 *
 * Modeled on items.js but with a smaller filter set (no slot/armor/source/stat).
 */
(function () {
  "use strict";

  // Opt out of Wowhead's power.js recolour/rename/iconize before it can load, so
  // the card markup stays as authored (same reasoning as items.js).
  window.whTooltips = { colorLinks: false, iconizeLinks: false, renameLinks: false };

  var SPECS = window.specs_map || {};

  // Category display order, mirroring CONSUMABLE_CATEGORY_LABELS in the backend.
  var CATEGORY_LABELS = {
    flask: "Flask", potion: "Potion", food: "Food",
    weapon: "Weapon Enchant", augment: "Augment Rune",
  };
  var CATEGORY_ORDER = ["flask", "potion", "food", "weapon", "augment"];

  function classSlug(name) { return String(name).toLowerCase().replace(/\s+/g, "-"); }
  var CLASS_TOKEN_BY_SLUG = {}; // "retribution-paladin" -> "s:70", "paladin" -> "c:paladin"
  var CLASS_SLUG_BY_TOKEN = {}; // "s:70" -> "retribution-paladin"

  function el(id) { return document.getElementById(id); }
  function iconUrl(icon) { return "/data/icons/" + icon + ".png"; }
  function fmt(n) { return (n || 0).toLocaleString(); }
  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); };
  }

  var PAGE_SIZE = 60;
  var all = [];
  var filtered = [];
  var shown = 0;
  var infinite = null;

  function refreshPicker(id) {
    if (window.jQuery && window.jQuery.fn.selectpicker) {
      window.jQuery("#" + id).selectpicker("refresh");
    }
  }

  function getClassTokens() {
    if (window.jQuery && window.jQuery.fn.selectpicker) {
      var v = window.jQuery("#class-filter").selectpicker("val");
      return v == null ? [] : (Array.isArray(v) ? v : [v]);
    }
    var out = [], opts = el("class-filter").options;
    for (var i = 0; i < opts.length; i++) if (opts[i].selected) out.push(opts[i].value);
    return out;
  }

  function buildCategoryOptions() {
    var present = {};
    all.forEach(function (c) { if (c.category) present[c.category] = true; });
    var sel = el("category-filter");
    var allOpt = document.createElement("option");
    allOpt.value = ""; allOpt.textContent = "All categories";
    sel.appendChild(allOpt);
    CATEGORY_ORDER.forEach(function (cat) {
      if (!present[cat]) return;
      var o = document.createElement("option");
      o.value = cat; o.textContent = CATEGORY_LABELS[cat] || cat;
      sel.appendChild(o);
    });
    refreshPicker("category-filter");
  }

  function specIconContent(iconFileId, label) {
    if (!iconFileId) return null;
    return "<span class='dropdown-icon-item'><img src='/data/icons/" + iconFileId +
      ".jpg' class='dropdown-icon' alt='' style='width:20px;height:20px;border-radius:4px;" +
      "object-fit:cover;flex:0 0 20px;margin-right:8px;'>" +
      "<span class='dropdown-icon-label'>" + label + "</span></span>";
  }

  function addClassOption(parent, token, label, slug, content) {
    var o = document.createElement("option");
    o.value = token; o.textContent = label;
    o.setAttribute("data-tokens", label);
    if (content) o.setAttribute("data-content", content);
    parent.appendChild(o);
    CLASS_TOKEN_BY_SLUG[slug] = token;
    CLASS_SLUG_BY_TOKEN[token] = slug;
  }

  // Class filter: one optgroup per class present in the data, each with "All
  // <Class>" plus one option per spec that actually ran a consumable. Membership
  // comes from window.specs_map, never a who-can-use table.
  function buildClassOptions() {
    var specsPresent = {};
    all.forEach(function (c) {
      (c.specs || []).forEach(function (sid) { specsPresent[String(sid)] = true; });
    });
    var classes = {};
    Object.keys(specsPresent).forEach(function (sid) {
      var sp = SPECS[sid];
      if (!sp) return;
      var cslug = classSlug(sp.className);
      var cl = classes[cslug] || (classes[cslug] = { name: sp.className, specs: [] });
      cl.specs.push({ id: sid, name: sp.name, icon: sp.icon });
    });
    var sel = el("class-filter");
    sel.innerHTML = ""; // multi-select: empty selection means "all"
    Object.keys(classes).map(function (cslug) {
      return { slug: cslug, name: classes[cslug].name, specs: classes[cslug].specs };
    }).sort(function (a, b) {
      return String(a.name).localeCompare(String(b.name));
    }).forEach(function (c) {
      var og = document.createElement("optgroup");
      og.label = c.name;
      addClassOption(og, "c:" + c.slug, "All " + c.name, c.slug, null);
      c.specs.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); })
        .forEach(function (s) {
          addClassOption(og, "s:" + s.id, s.name, classSlug(s.name) + "-" + c.slug,
            specIconContent(s.icon, s.name));
        });
      sel.appendChild(og);
    });
    refreshPicker("class-filter");
  }

  function parseClassParam(raw) {
    if (!raw) return [];
    return raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
      .map(function (s) {
        if (CLASS_TOKEN_BY_SLUG[s]) return CLASS_TOKEN_BY_SLUG[s];
        if (CLASS_SLUG_BY_TOKEN[s]) return s;
        return null;
      }).filter(Boolean);
  }

  function readParams() {
    var sp = new URLSearchParams(window.location.search);
    var category = (sp.get("category") || "").toLowerCase();
    var sort = sp.get("sort") || "";
    return {
      q: sp.get("q") || "",
      category: CATEGORY_LABELS[category] ? category : "",
      "class": parseClassParam(sp.get("class") || ""),
      sort: sort === "name" || sort === "runs" ? sort : "runs",
    };
  }

  function setSelect(id, value) {
    if (window.jQuery && window.jQuery.fn.selectpicker) {
      window.jQuery("#" + id).selectpicker("val", value);
    } else {
      el(id).value = value;
    }
  }

  function applyParamsToControls(p) {
    el("consumable-search").value = p.q;
    setSelect("category-filter", p.category);
    setSelect("class-filter", p["class"]);
    setSelect("sort-by", p.sort);
  }

  function updateUrl() {
    var sp = new URLSearchParams();
    var q = el("consumable-search").value.trim();
    var category = el("category-filter").value;
    var classTokens = getClassTokens();
    var sort = el("sort-by").value;
    if (category) sp.set("category", category);
    if (classTokens.length) {
      sp.set("class", classTokens.map(function (t) { return CLASS_SLUG_BY_TOKEN[t] || t; }).join(","));
    }
    if (sort && sort !== "runs") sp.set("sort", sort);
    if (q) sp.set("q", q);
    var qs = sp.toString();
    window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
  }

  function matchesClass(item, classTokens) {
    var specsList = item.specs || [];
    if (!specsList.length) return false;
    return classTokens.some(function (t) {
      if (t.charAt(0) === "s") {
        var id = parseInt(t.slice(2), 10);
        return specsList.indexOf(id) !== -1;
      }
      var cslug = t.slice(2);
      return specsList.some(function (sid) {
        var sp = SPECS[String(sid)];
        return sp && classSlug(sp.className) === cslug;
      });
    });
  }

  function applyFilters() {
    var q = el("consumable-search").value.trim().toLowerCase();
    var category = el("category-filter").value;
    var classTokens = getClassTokens();
    var sort = el("sort-by").value;

    filtered = all.filter(function (c) {
      if (q && c.name.toLowerCase().indexOf(q) === -1) return false;
      if (category && c.category !== category) return false;
      if (classTokens.length && !matchesClass(c, classTokens)) return false;
      return true;
    });
    if (sort === "name") filtered.sort(function (a, b) { return a.name.localeCompare(b.name); });
    else filtered.sort(function (a, b) { return b.runs - a.runs; });

    shown = 0;
    el("consumables-grid").innerHTML = "";
    el("consumables-empty").classList.toggle("d-none", filtered.length > 0);
    var done = renderMore();
    if (infinite) done ? infinite.finish() : infinite.reset();
    updateUrl();
  }

  function consumableCard(item) {
    var col = document.createElement("div");
    col.className = "col-12 col-md-6 col-xl-4";
    var a = document.createElement("a");
    a.className = "consumable-card";
    a.href = "/consumables/" + item.slug;
    a.dataset.wowhead = "item=" + item.id;
    var img = document.createElement("img");
    img.src = iconUrl(item.icon);
    img.alt = item.name;
    img.loading = "lazy";
    img.className = "border border-grey-100";
    var meta = document.createElement("div");
    meta.className = "meta flex-grow-1";
    var name = document.createElement("div");
    name.className = "name";
    name.textContent = item.name;
    var sub = document.createElement("div");
    sub.className = "sub";
    var spec = item.top_spec != null ? SPECS[String(item.top_spec)] : null;
    sub.textContent = (item.category_label || item.category) + " · " + fmt(item.runs) + " runs" +
      (spec ? " · mostly " + spec.name + " " + spec.className : "");
    meta.appendChild(name); meta.appendChild(sub);
    a.appendChild(img); a.appendChild(meta);
    col.appendChild(a);
    return col;
  }

  function renderMore() {
    var grid = el("consumables-grid");
    var slice = filtered.slice(shown, shown + PAGE_SIZE);
    var frag = document.createDocumentFragment();
    slice.forEach(function (i) { frag.appendChild(consumableCard(i)); });
    grid.appendChild(frag);
    if (window.$WowheadPower && typeof window.$WowheadPower.refreshLinks === "function") {
      try { window.$WowheadPower.refreshLinks(); } catch (e) { /* tooltips optional */ }
    }
    shown += slice.length;
    return shown >= filtered.length;
  }

  function init() {
    fetch("/assets/json/consumables_index.json")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        all = data || [];
        buildCategoryOptions();
        buildClassOptions();
        infinite = window.MythiInfinite.create({
          sentinel: el("consumables-sentinel"),
          onLoadMore: renderMore,
        });
        applyParamsToControls(readParams());
        var grid = el("consumables-grid");
        if (!window.location.search && grid.children.length) {
          // Server already rendered page 1 in the default (unfiltered, runs-desc)
          // order; reuse it instead of wiping and re-rendering identical cards.
          filtered = all.slice().sort(function (a, b) { return b.runs - a.runs; });
          shown = Math.min(PAGE_SIZE, filtered.length, grid.children.length);
          el("consumables-empty").classList.add("d-none");
          if (shown >= filtered.length) infinite.finish(); else infinite.reset();
        } else {
          applyFilters();
        }
        el("consumable-search").addEventListener("input", debounce(applyFilters, 200));
        el("category-filter").addEventListener("change", applyFilters);
        el("class-filter").addEventListener("change", applyFilters);
        el("sort-by").addEventListener("change", applyFilters);
        window.addEventListener("popstate", function () {
          applyParamsToControls(readParams());
          applyFilters();
        });
      })
      .catch(function () {
        el("consumables-empty").textContent = "Could not load consumable list.";
        el("consumables-empty").classList.remove("d-none");
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
