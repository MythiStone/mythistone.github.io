// VOD page Streamers view: filter the server-rendered streamer cards by class/spec
// and reorder them by the chosen sort. All data rides on each card's data-* attributes.
(function () {
  "use strict";

  var grid = document.getElementById("streamerGrid");
  if (!grid) return;
  var empty = document.getElementById("streamerEmpty");
  var classSel = document.getElementById("streamerClassSelect");
  var specSel = document.getElementById("streamerSpecSelect");
  var sortSel = document.getElementById("streamerSortSelect");

  var items = Array.prototype.map.call(grid.querySelectorAll(".streamer-grid-item"), function (el) {
    var d = el.dataset;
    return {
      el: el,
      name: d.name,
      vods: Number(d.vods),
      key: Number(d.key),
      latest: Number(d.latest),
      classes: d.classes ? d.classes.split(" ") : [],
      specs: d.specs ? d.specs.split(" ") : [],
      overall: Number(d.rankOverall) || Infinity,
      classRank: Number(d.rankClass) || Infinity,
      specRanks: JSON.parse(d.rankSpecs || "{}"),
    };
  });

  function selected(sel) {
    return Array.prototype.filter.call(sel.options, function (o) { return o.selected; })
      .map(function (o) { return o.value; });
  }

  function anyOf(have, wanted) {
    return !wanted.length || wanted.some(function (v) { return have.indexOf(v) !== -1; });
  }

  // Spec rank for sorting: best rank among the filtered specs, else the best of any spec.
  function specRank(item, specs) {
    var ids = specs.length ? specs : Object.keys(item.specRanks);
    return ids.reduce(function (best, id) {
      var r = item.specRanks[id];
      return r && r < best ? r : best;
    }, Infinity);
  }

  var COMPARE = {
    vods: function (a, b) { return b.vods - a.vods || b.key - a.key; },
    overall: function (a, b) { return a.overall - b.overall; },
    "class": function (a, b) { return a.classRank - b.classRank; },
    spec: function (a, b, specs) { return specRank(a, specs) - specRank(b, specs); },
    key: function (a, b) { return b.key - a.key || b.vods - a.vods; },
    latest: function (a, b) { return b.latest - a.latest; },
    name: function (a, b) { return a.name.localeCompare(b.name); },
  };

  function apply() {
    var classes = selected(classSel);
    var specs = selected(specSel);
    var compare = COMPARE[sortSel.value] || COMPARE.vods;
    var shown = 0;
    items.slice()
      .sort(function (a, b) {
        // Infinity - Infinity is NaN: unranked pairs keep the default order.
        return compare(a, b, specs) || COMPARE.vods(a, b);
      })
      .forEach(function (item) {
        var match = anyOf(item.classes, classes) && anyOf(item.specs, specs);
        item.el.classList.toggle("d-none", !match);
        if (match) shown++;
        grid.appendChild(item.el);
      });
    empty.classList.toggle("d-none", shown > 0);
  }

  // bootstrap-select reports changes as jQuery events (same binding as finder.js).
  var selector = "#streamerClassSelect, #streamerSpecSelect, #streamerSortSelect";
  if (window.jQuery) window.jQuery(selector).on("changed.bs.select change", apply);
})();
