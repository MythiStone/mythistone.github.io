(function () {
  "use strict";

  // Shared site search client: one index fetch and one Fuse instance, used by the
  // navbar dropdown below and by search-page.js. Defined before the navbar checks
  // so the search page works even if the navbar markup is missing.
  const INDEX_URL = "/assets/json/search_index.json";
  const MIN_QUERY_LENGTH = 2;
  const FALLBACK_ICON = "/assets/img/favicon/favicon-96x96.png";
  // Larger is worse: hundreds of items must not crowd out the spec or dungeon.
  const TYPE_FACTOR = { Streamer: 1.15, Item: 1.3, Consumable: 1.3 };

  let fuse = null;
  let readyPromise = null;

  function ready() {
    if (!readyPromise) {
      // The index only changes on a site rebuild, so the normal HTTP cache with
      // revalidation is enough (a 304 when unchanged).
      readyPromise = fetch(INDEX_URL, { cache: "default" })
        .then((res) => {
          if (!res.ok) throw new Error("search index status " + res.status);
          return res.json();
        })
        .then((data) => {
          fuse = new Fuse(data, {
            includeScore: true,
            ignoreLocation: true,
            threshold: 0.35,
            keys: [
              { name: "name", weight: 0.7 },
              { name: "keywords", weight: 0.3 },
            ],
          });
          return fuse;
        });
      readyPromise.catch((err) => {
        console.warn("[site-search] index load failed", err);
        readyPromise = null;
      });
    }
    return readyPromise;
  }

  function search(q, limit) {
    q = (q || "").trim();
    if (!fuse || q.length < MIN_QUERY_LENGTH) return [];
    const ql = q.toLowerCase();
    const wordStart = (s) => s.toLowerCase().split(/[\s'-]+/).some((w) => w.startsWith(ql));
    const ranked = fuse.search(q).map((r, i) => {
      const e = r.item;
      // A small floor keeps near-exact hits comparable, so the type factor and the
      // boosts order them. The word-start boost lets an alias or boss name keyword
      // ("BM", "Rav'i") beat a mid-word hit in an item name ("Grave").
      let rank = ((r.score || 0) + 0.01) * (TYPE_FACTOR[e.type] || 1);
      if (e.name.toLowerCase().startsWith(ql)) rank *= 0.5;
      else if (wordStart(e.name) || (e.keywords || []).some(wordStart)) rank *= 0.6;
      return { entry: e, rank: rank, i: i };
    });
    ranked.sort((a, b) => a.rank - b.rank || a.i - b.i);
    const out = ranked.map((r) => r.entry);
    return limit ? out.slice(0, limit) : out;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderRow(entry) {
    const a = el("a", "list-group-item list-group-item-action search-row");
    a.href = entry.url;

    const iconWrap = el("span", "search-row-icon");
    if (entry.icon) {
      const img = el("img");
      img.src = entry.icon;
      img.alt = "";
      img.loading = "lazy";
      // Streamer avatars (yt3.ggpht.com) refuse hotlinks with a foreign referrer.
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", () => { img.src = FALLBACK_ICON; }, { once: true });
      iconWrap.appendChild(img);
    } else {
      iconWrap.appendChild(el("i", "material-symbols-rounded", entry.symbol || "description"));
    }

    const body = el("span", "search-row-body");
    const head = el("span", "search-row-head");
    head.appendChild(el("span", "search-row-name", entry.name));
    head.appendChild(el("span", "badge search-row-type", entry.type));
    body.appendChild(head);
    if (entry.subtitle) body.appendChild(el("span", "search-row-subtitle", entry.subtitle));

    a.appendChild(iconWrap);
    a.appendChild(body);
    return a;
  }

  window.MythiSearch = {
    MIN_QUERY_LENGTH: MIN_QUERY_LENGTH,
    ready: ready,
    isReady: () => !!fuse,
    search: search,
    renderRow: renderRow,
  };

  const input = document.getElementById("site-search-input");
  const resultsMenu = document.getElementById("site-search-results");
  const resultsInner = document.getElementById("site-search-results-inner");
  const noResults = document.getElementById("site-search-noresults");
  const clearBtn = document.getElementById("site-search-clear");
  const allResultsLink = document.getElementById("site-search-all-results");

  if (!input || !resultsMenu || !resultsInner) {
    console.warn("[site-search] required elements not found — aborting init");
    return;
  }

  resultsMenu.setAttribute("data-open", "false");
  resultsMenu.classList.remove("show");
  resultsMenu.style.display = "none";

  const PAGE_ROOT =
    // Direct child only: the sticky header's navbar has its own .container-fluid.
    document.querySelector("main > .container-fluid, main > .container") ||
    document.querySelector("main") ||
    document.querySelector("article") ||
    document.querySelector(".ms-404-content") ||
    document.body;

  const DEBOUNCE_MS = 180;
  let debounceTimer = null;
  let focusedIndex = -1;
  const MAX_RESULTS = 8;
  // In-page highlight only; the index search uses MythiSearch.MIN_QUERY_LENGTH.
  const HIGHLIGHT_MIN_LENGTH = 3;

  // Fetch the index on first interaction instead of on every page load.
  input.addEventListener("focus", () => { ready(); }, { once: true });

  function showResultsMenu() {
    resultsMenu.setAttribute("data-open", "true");
    resultsMenu.classList.add("show");
    resultsMenu.style.display = "block";
    if (typeof window.__siteSearchPositionResults === "function")
      window.__siteSearchPositionResults();
  }
  function hideResultsMenu() {
    resultsMenu.setAttribute("data-open", "false");
    resultsMenu.classList.remove("show");
    resultsMenu.style.display = "none";
  }

  (function setupResultsPositioningAnchorRight() {
    if (!resultsMenu || !input) return;

    if (resultsMenu.parentElement !== document.body)
      document.body.appendChild(resultsMenu);

    const DROPDOWN_MAX_W = 520;
    const DROPDOWN_MIN_W = 320;
    const PAGE_MARGIN = 12;

    function positionResultsMenuAnchorRight() {
      const rect = input.getBoundingClientRect();

      const rightSidebar = document.getElementById("sidenav-right");
      let rightLimit = window.innerWidth - PAGE_MARGIN;
      // A hidden sidebar (display:none on small screens) reports a zero rect.
      if (rightSidebar && rightSidebar.getBoundingClientRect().width > 0) {
        const rs = rightSidebar.getBoundingClientRect();
        rightLimit = Math.min(
          rightLimit,
          Math.max(PAGE_MARGIN, rs.left - PAGE_MARGIN)
        );
      }

      // Grows left from the input's right edge, but never narrower than
      // DROPDOWN_MIN_W (spilling right on a phone, where the input sits on the left).
      const width = Math.min(
        DROPDOWN_MAX_W,
        rightLimit - PAGE_MARGIN,
        Math.max(DROPDOWN_MIN_W, rect.right - PAGE_MARGIN)
      );

      let left = rect.right - width;
      if (left < PAGE_MARGIN) left = PAGE_MARGIN;
      if (left + width > rightLimit)
        left = Math.max(PAGE_MARGIN, rightLimit - width);

      const top = rect.bottom + window.scrollY + 6;

      Object.assign(resultsMenu.style, {
        position: "absolute",
        left: `${Math.round(left)}px`,
        top: `${Math.round(top)}px`,
        width: `${Math.round(width)}px`,
      });
    }

    let scheduled = false;
    function schedule() {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        positionResultsMenuAnchorRight();
        scheduled = false;
      });
    }

    window.__siteSearchPositionResults = positionResultsMenuAnchorRight;
    window.addEventListener("resize", schedule);
    window.addEventListener("orientationchange", schedule);
    window.addEventListener("scroll", schedule, { passive: true });

    positionResultsMenuAnchorRight();
  })();

  function clearInPageHighlights() {
    try {
      const spans = PAGE_ROOT.querySelectorAll("span.search-highlight");
      spans.forEach((sp) => {
        const txt = document.createTextNode(sp.textContent);
        sp.parentNode.replaceChild(txt, sp);
      });
      PAGE_ROOT.normalize();
    } catch (e) {
      console.warn("[site-search] clearInPageHighlights error", e);
    }
  }

  function findFirstMatchRange(root, query) {
    if (!query || query.length < HIGHLIGHT_MIN_LENGTH) return null;
    const q = query.toLowerCase();

    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          if (!node.nodeValue || !node.nodeValue.trim())
            return NodeFilter.FILTER_REJECT;
          let el = node.parentElement;
          while (el && el !== root) {
            const tag = el.tagName && el.tagName.toLowerCase();
            if (
              tag === "nav" ||
              tag === "footer" ||
              el.classList.contains("breadcrumb") ||
              el.classList.contains("toc") ||
              el.classList.contains("sidebar")
            ) {
              return NodeFilter.FILTER_REJECT;
            }
            el = el.parentElement;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      },
      false
    );

    const nodes = [];
    let n;
    while ((n = walker.nextNode())) nodes.push(n);

    for (let i = 0; i < nodes.length; i++) {
      let combined = nodes[i].nodeValue;
      let j = i;
      while (combined.length < q.length && j + 1 < nodes.length && j - i < 6) {
        j++;
        combined += nodes[j].nodeValue || "";
      }

      for (let end = i; end <= j; end++) {
        const part = nodes
          .slice(i, end + 1)
          .map((x) => x.nodeValue || "")
          .join("");
        const partLower = part.toLowerCase();
        const idx = partLower.indexOf(q);
        if (idx !== -1) {
          let acc = 0;
          let startNode = null,
            startOffset = 0;
          for (let k = i; k <= end; k++) {
            const len = (nodes[k].nodeValue || "").length;
            if (acc + len > idx) {
              startNode = nodes[k];
              startOffset = idx - acc;
              break;
            }
            acc += len;
          }
          let matchLen = q.length;
          let endNode = startNode,
            endOffset = startOffset;
          let remaining = matchLen;
          for (
            let k = startNode ? nodes.indexOf(startNode) : i;
            k <= end;
            k++
          ) {
            const seg = nodes[k].nodeValue || "";
            const avail =
              k === (startNode ? nodes.indexOf(startNode) : i)
                ? seg.length - startOffset
                : seg.length;
            if (remaining <= avail) {
              endNode = nodes[k];
              endOffset =
                (k === (startNode ? nodes.indexOf(startNode) : i)
                  ? startOffset
                  : 0) + remaining;
              break;
            } else {
              remaining -= avail;
            }
          }

          try {
            const range = document.createRange();
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);
            return range;
          } catch (e) {
            console.warn("[site-search] error creating range for match", e);
            return null;
          }
        }
      }
    }
    return null;
  }

  function highlightRange(range) {
    if (!range) return null;
    try {
      const frag = range.extractContents();
      const wrap = document.createElement("span");
      wrap.className = "search-highlight";
      wrap.setAttribute("data-site-search-highlight", "1");
      wrap.appendChild(frag);
      range.insertNode(wrap);
      try {
        wrap.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (e) {}
      return wrap;
    } catch (e) {
      console.warn("[site-search] highlightRange failed", e);
      return null;
    }
  }

  function renderResults(results) {
    resultsInner.innerHTML = "";
    focusedIndex = -1;
    noResults.classList.toggle("d-none", results.length > 0);
    results.forEach((entry, i) => {
      const row = renderRow(entry);
      row.setAttribute("role", "option");
      row.setAttribute("data-index", i);
      resultsInner.appendChild(row);
    });
    showResultsMenu();
  }

  function doSearch(q) {
    q = (q || "").trim();
    if (allResultsLink)
      allResultsLink.href = "/pages/search?q=" + encodeURIComponent(q);

    if (!q) {
      hideResultsMenu();
      clearBtn.classList.add("d-none");
      clearInPageHighlights();
      return;
    }
    clearBtn.classList.remove("d-none");

    clearInPageHighlights();
    const pageRange = findFirstMatchRange(PAGE_ROOT, q);
    if (pageRange) {
      highlightRange(pageRange);
    }

    if (q.length < MIN_QUERY_LENGTH) {
      hideResultsMenu();
      return;
    }
    if (!fuse) {
      // Typed before the index arrived: search once it has, if still current.
      ready().then(() => {
        if (input.value.trim() === q) renderResults(search(q, MAX_RESULTS));
      }, () => renderResults([]));
      return;
    }
    renderResults(search(q, MAX_RESULTS));
  }

  input.addEventListener("input", (e) => {
    const q = e.target.value;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => doSearch(q), DEBOUNCE_MS);
  });

  clearBtn.addEventListener("click", () => {
    input.value = "";
    clearBtn.classList.add("d-none");
    hideResultsMenu();
    input.focus();
    clearInPageHighlights();
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideResultsMenu();
      input.blur();
      return;
    }
    const items = resultsInner.querySelectorAll("[data-index]");
    if (items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusedIndex = Math.min(items.length - 1, focusedIndex + 1);
      updateFocus(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      focusedIndex = Math.max(0, focusedIndex - 1);
      updateFocus(items);
    } else if (e.key === "Enter") {
      if (focusedIndex >= 0 && items[focusedIndex]) {
        window.location = items[focusedIndex].href;
      } else if (items.length > 0) {
        window.location = items[0].href;
      }
    }
  });

  function updateFocus(items) {
    items.forEach((el, i) => {
      if (i === focusedIndex) {
        el.classList.add("active");
        el.focus();
      } else {
        el.classList.remove("active");
      }
    });
  }

  document.addEventListener("click", (ev) => {
    const isOpen = resultsMenu.getAttribute("data-open") === "true";
    if (!isOpen) return;
    if (!resultsMenu.contains(ev.target) && ev.target !== input) {
      hideResultsMenu();
    }
  });

  window.__siteSearchPositionResults && window.__siteSearchPositionResults();
  window.__siteSearch_doSearch = doSearch;
})();
