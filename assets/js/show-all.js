/* "Show all" for long in-card lists (MythiShowAll).
 *
 * Mark the element whose direct children are the items (a list div or a <tbody>) with
 * data-show-all="<noun>" and a breakpoint class, show-all-lg or show-all-xxl. Below that
 * breakpoint, where the card is stacked, custom-scrollbars.css drops the card's inner scroll
 * box, hides items 6+ and shows the button this script adds. Side by side, nothing changes.
 *
 * A MutationObserver re-counts when a page re-renders the list (comps.js on a dungeon
 * filter change), so callers need no hook.
 */
(function () {
  "use strict";

  var VISIBLE = 5;

  function setup(list) {
    var bp = list.classList.contains("show-all-xxl") ? "xxl" : "lg";
    var noun = list.getAttribute("data-show-all") || "items";
    var anchor = list.closest(".card-scroll") || list.closest("table") || list;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-outline-secondary mx-3 my-2 show-all-btn show-all-btn-" + bp;
    btn.setAttribute("aria-expanded", "false");
    anchor.insertAdjacentElement("afterend", btn);

    function label() {
      return "Show all " + list.children.length + " " + noun;
    }

    function refresh() {
      var items = list.children;
      for (var i = 0; i < items.length; i++) {
        items[i].classList.toggle("show-all-extra", i >= VISIBLE);
      }
      list.classList.remove("is-expanded");
      btn.hidden = items.length <= VISIBLE;
      btn.textContent = label();
      btn.setAttribute("aria-expanded", "false");
    }

    btn.addEventListener("click", function () {
      var open = list.classList.toggle("is-expanded");
      btn.textContent = open ? "Show fewer" : label();
      btn.setAttribute("aria-expanded", String(open));
    });

    refresh();
    new MutationObserver(refresh).observe(list, { childList: true });
  }

  function init() {
    document.querySelectorAll("[data-show-all]").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
