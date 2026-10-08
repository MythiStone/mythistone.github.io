/*
 * Sticky page header (templates/top_chrome.html, styled by assets/css/top-chrome.css).
 *
 * - Publishes the header's live height as --top-chrome-h on <html> (scroll-padding-top
 *   and other sticky elements offset by it).
 * - Condenses the header once the page is scrolled past its full height and expands
 *   it again only back near the top, so the two states cannot flicker.
 * - While condensed, notifications fold into the navbar bell, which opens them as a
 *   panel below the header.
 *
 * The header sits in normal flow, so every change of its height moves the page.
 * Each state change below the top is therefore compensated by scrolling the same
 * amount, keeping what the visitor is reading in place (browser scroll anchoring
 * may already have done it, in which case the measured shift is zero).
 */
(function () {
  "use strict";

  var chrome = document.getElementById("page-top-chrome");
  if (!chrome) {
    return;
  }
  var root = document.documentElement;
  var notes = document.getElementById("top-chrome-notes");
  var bell = document.getElementById("top-chrome-bell");
  var bellCount = bell ? bell.querySelector(".top-chrome-bell-count") : null;
  var content = chrome.nextElementSibling;
  var EXPAND_AT = 8; // px from the top where the header expands again

  function publishHeight() {
    root.style.setProperty("--top-chrome-h", chrome.offsetHeight + "px");
  }

  // Run fn (which toggles header classes) without moving the visible page.
  function keepInPlace(fn) {
    if (!content) {
      fn();
      return;
    }
    var before = content.getBoundingClientRect().top;
    fn();
    var shift = content.getBoundingClientRect().top - before;
    if (shift) {
      window.scrollBy({ top: shift, behavior: "instant" });
    }
    publishHeight();
  }

  function update() {
    var y = window.scrollY;
    if (!chrome.classList.contains("is-condensed")) {
      var expandedHeight = chrome.offsetHeight;
      // Skip pages too short to scroll past the height the header would lose,
      // which would otherwise bounce between the two states at the bottom.
      var room = root.scrollHeight - window.innerHeight;
      if (y > expandedHeight && room > expandedHeight * 2) {
        keepInPlace(function () { chrome.classList.add("is-condensed"); });
      }
    } else if (y < EXPAND_AT) {
      // Not compensated: at the top the visitor wants the page's real start,
      // which the full header now pushes down into place.
      chrome.classList.remove("is-condensed", "notes-open");
      publishHeight();
      setBellExpanded(false);
    }
  }

  var pending = false;
  function onScroll() {
    if (pending) {
      return;
    }
    pending = true;
    window.requestAnimationFrame(function () {
      pending = false;
      update();
    });
  }

  // ---- notifications bell ----
  function setBellExpanded(open) {
    if (bell) {
      bell.setAttribute("aria-expanded", open ? "true" : "false");
    }
  }

  function countNotes() {
    var n = notes ? notes.querySelectorAll(".page-notification").length : 0;
    chrome.classList.toggle("has-notes", n > 0);
    if (bellCount) {
      bellCount.textContent = n > 0 ? String(n) : "";
    }
    if (n === 0) {
      chrome.classList.remove("notes-open");
      setBellExpanded(false);
    }
  }

  if (bell) {
    bell.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = chrome.classList.toggle("notes-open");
      setBellExpanded(open);
    });
    document.addEventListener("click", function (e) {
      // composedPath, not notes.contains(target): a dismissed alert is already
      // detached by the time the click reaches the document.
      if (chrome.classList.contains("notes-open") && notes && e.composedPath().indexOf(notes) === -1) {
        chrome.classList.remove("notes-open");
        setBellExpanded(false);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && chrome.classList.contains("notes-open")) {
        chrome.classList.remove("notes-open");
        setBellExpanded(false);
        bell.focus();
      }
    });
  }

  if (notes) {
    // notifications.js injects dismissible alerts after a fetch, and Bootstrap
    // removes dismissed ones, so watch the slot instead of hooking either.
    new MutationObserver(countNotes).observe(notes, { childList: true, subtree: true });
    countNotes();
  }

  if (window.ResizeObserver) {
    new ResizeObserver(publishHeight).observe(chrome);
  }
  publishHeight();

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  // A restored scroll position (back/forward, reload) needs the condensed state too.
  window.addEventListener("load", update);
  update();
})();
