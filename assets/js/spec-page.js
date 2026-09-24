// Spec page behaviour, extracted from templates/spec_page.html.
// Per-spec data (level_stats) comes from the inline
// <script type="application/json" id="spec-page-data"> block; the per-dungeon
// talent usage still rides in the <script class="js-dungeon-tree-usage"> blocks.
const SPEC = JSON.parse(document.getElementById('spec-page-data').textContent);

// --- Item-name link capture (accordion header rows) ---
    // Item-name links inside accordion header rows: Bootstrap's collapse
    // data-api listens on document in the CAPTURE phase (its EventHandler
    // passes the delegation flag as addEventListener's third argument), so it
    // toggles the accordion and preventDefault()s the click before the anchor
    // ever sees it an onclick="event.stopPropagation()" on the link can't
    // help. A window-capture listener runs before any document listener, so
    // stopping propagation here keeps Bootstrap out while the link's native
    // navigation (and ctrl/middle-click behavior) proceeds untouched.
    window.addEventListener('click', function (e) {
      var link = e.target.closest && e.target.closest('a.item-name-link');
      if (link && link.closest('button.accordion-button')) e.stopPropagation();
    }, true);

// --- Choice-node "TOP" badge tooltips ---
    // Choice-node "TOP" badges: attach the tooltip above and to the LEFT of the
    // badge so it clears the Wowhead spell tooltip that fires on the same choice
    // row. We use Popper's native `top-end` corner placement (tooltip sits above
    // the badge, right edges aligned, body extending left) via `popperConfig` —
    // Bootstrap's own `placement` only maps to top/bottom/left/right, but the
    // popperConfig override reaches Popper directly, and native placement means
    // Popper flips it (to bottom-end) cleanly near a viewport edge. `customClass`
    // forces a normal short/wide tooltip shape (see .tt-choice-tip in CSS) so it
    // doesn't collapse into a tall column that overflows near the tree edges.
    // These badges are excluded from the global [data-bs-toggle="tooltip"] init;
    // they carry `js-choice-top-tip` (+ data-bs-title) instead.
    (function () {
      if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;
      document.querySelectorAll('.js-choice-top-tip').forEach(function (el) {
        new bootstrap.Tooltip(el, {
          container: 'body',
          customClass: 'tt-choice-tip',
          popperConfig: { placement: 'top-end' }
        });
      });
    })();

// --- Runs-by-keylevel bar chart ---
    document.addEventListener('DOMContentLoaded', function () {
      const canvas = document.getElementById('runsBarChart');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');

      // Disable chart pan/zoom on small screens so it doesn't hijack page scrolling.
      const enableZoom = window.matchMedia('(min-width: 992px)').matches;

      // Use per-key-level stacked counts for this spec
      var levelData = SPEC.levelStats;
      levelData.sort((a,b) => a.keystone_level - b.keystone_level);
      var labels = levelData.map(d => '+' + d.keystone_level);
      var up3 = levelData.map(d => d.upgrade_3);
      var up2 = levelData.map(d => d.upgrade_2);
      var up1 = levelData.map(d => d.upgrade_1);
      var depleted = levelData.map(d => d.depleted);

      // Make canvas width proportional to number of labels so bars are readable in small card
      const container = canvas.parentElement;
      const perLabel = 36; // px per keystone label
      const desiredWidth = Math.max(container.clientWidth, labels.length * perLabel);
      canvas.width = desiredWidth;
      canvas.style.width = desiredWidth + 'px';

      var keyLevelChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: 'Depleted', data: depleted, backgroundColor: '#FF0000', maxBarThickness: 20, barPercentage: 0.85, categoryPercentage: 0.9 },
            { label: '+1', data: up1, backgroundColor: '#1eff00', maxBarThickness: 20, barPercentage: 0.85, categoryPercentage: 0.9 },
            { label: '+2', data: up2, backgroundColor: '#a335ee', maxBarThickness: 20, barPercentage: 0.85, categoryPercentage: 0.9 },
            { label: '+3', data: up3, backgroundColor: '#ff8000', maxBarThickness: 20, barPercentage: 0.85, categoryPercentage: 0.9 }            
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              stacked: true,
              ticks: { color: MythiChart.colors.tickText, autoSkip: true, maxRotation: 0, minRotation: 0, maxTicksLimit: 12, font: { size: 11 } },
              grid: { display: false }
            },
            y: {
              stacked: true,
              ticks: { color: MythiChart.colors.tickText, beginAtZero: true, font: { size: 11 } },
              grid: { color: MythiChart.colors.grid }
            }
          },
          plugins: {
            legend: { labels: { color: MythiChart.colors.tickText } },
            tooltip: { mode: 'index', intersect: false },
            datalabels: { display: false },
            zoom: {
              pan: { enabled: enableZoom, mode: 'x', onPan: function({chart}) { document.getElementById('resetZoomBtnSpec').style.display = 'inline-block'; } },
              zoom: { wheel: { enabled: enableZoom }, pinch: { enabled: enableZoom }, mode: 'x', onZoom: function({chart}) { document.getElementById('resetZoomBtnSpec').style.display = 'inline-block'; } }
            }
          }
        }
      });

      document.getElementById('resetZoomBtnSpec').addEventListener('click', function() {
        keyLevelChart.resetZoom();
        this.style.display = 'none';
      });
    });

// --- Route embeds, talent export copy, hero-tree switcher, talent-diff modal ---
    // Route embeds load on first open, gated on Klaro consent (see consent.js).
    MythiConsent.wireAccordionEmbeds('#routeDungeonAccordion');
    // VOD (Twitch/YouTube) embeds in the VODs modal, same consent gating.
    MythiConsent.wireAccordionEmbeds('#vodDungeonAccordion');
    (function () {
      const copyBtn = document.getElementById('copyBtn');
      const btnText = document.getElementById('btnText');
      if (!copyBtn || !btnText) return;
      const text = btnText.getAttribute('data-text');

      copyBtn.addEventListener('click', async () => {
        // Read the loadout at click time so it reflects the active hero tree.
        const toCopy = btnText.getAttribute('data-loadout') || '';
        try {
          await navigator.clipboard.writeText(toCopy);
          // Show success state
          btnText.textContent = 'Copied!';
          copyBtn.classList.replace('btn-primary', 'btn-success');
          setTimeout(() => {
            btnText.textContent = text;
            copyBtn.classList.replace('btn-success', 'btn-primary');
          }, 2000);
        } catch (err) {
          console.error('Copy failed', err);
          btnText.textContent = 'Error';
          copyBtn.classList.replace('btn-primary', 'btn-danger');
          setTimeout(() => {
            btnText.textContent = text;
            copyBtn.classList.replace('btn-danger', 'btn-primary');
          }, 2000);
        }
      });
    })();
    // Hero-tree switcher: cycles the talent overview (class/spec/hero trees),
    // the Talent Differences modal, and the Export Talent String between hero
    // trees. Clicking the hero icon advances to the next tree.
    (function () {
      const variants = Array.from(document.querySelectorAll('.tt-variant'));
      if (variants.length <= 1) return;
      const difVariants = Array.from(document.querySelectorAll('.talent-dif-variant'));

      function syncExport(variantEl) {
        const btnText = document.getElementById('btnText');
        const copyBtn = document.getElementById('copyBtn');
        if (!btnText || !copyBtn) return;
        const loadout = variantEl.getAttribute('data-loadout') || '';
        btnText.setAttribute('data-loadout', loadout);
        copyBtn.style.display = loadout ? '' : 'none';
      }

      // The gear / stats / enchant / gem / missive / embellishment / crafted /
      // set-combo sections each ship one .hero-section-variant per hero tree
      // (see sections_by_tree in generateSpecPages.py); switching the hero tree
      // shows the matching variant across every section at once.
      const sectionVariants = Array.from(document.querySelectorAll('.hero-section-variant'));

      function show(idx) {
        const treeId = variants[idx].getAttribute('data-hero-tree-id');
        variants.forEach((el, i) => { el.style.display = (i === idx) ? '' : 'none'; });
        difVariants.forEach((el) => {
          el.style.display = (el.getAttribute('data-hero-tree-id') === treeId) ? '' : 'none';
        });
        sectionVariants.forEach((el) => {
          el.style.display = (el.getAttribute('data-hero-tree-id') === treeId) ? '' : 'none';
        });
        syncExport(variants[idx]);
      }

      // Determine the initially visible variant (the server-rendered default).
      let current = variants.findIndex((el) => el.style.display !== 'none');
      if (current < 0) current = 0;
      const defaultTreeId = variants[current].getAttribute('data-hero-tree-id');
      show(current);

      function advance() {
        current = (current + 1) % variants.length;
        show(current);
        if (window.MythiLink) MythiLink.sync();
      }

      document.querySelectorAll('.tt-hero-switch-active').forEach((el) => {
        el.addEventListener('click', advance);
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            advance();
          }
        });
      });

      // The hero tree is the one bit of view state that changes what a visitor
      // walks away with: it drives the talent tree, the per-dungeon diffs *and*
      // the Export Talent String. A shared link that landed on the default tree
      // would hand the recipient the wrong import string, so it rides in the
      // hash as &hero=<treeId> whenever it isn't the default.
      if (window.MythiLink) {
        MythiLink.registerState('hero', {
          read: function () {
            const id = variants[current].getAttribute('data-hero-tree-id');
            return id === defaultTreeId ? null : id;
          },
          apply: function (treeId) {
            const idx = variants.findIndex((el) => el.getAttribute('data-hero-tree-id') === String(treeId));
            if (idx < 0) return;  // unknown tree id in a hand-edited link
            current = idx;
            show(current);
          }
        });
      }
    })();

    // A copy of one hero tree's page talent tree for a modal to repaint, with the
    // season-wide badges and the page-only hero switcher stripped.
    function cloneTalentTree(treeId) {
      const source = document.querySelector(
        '#static-talent-tree .tt-variant[data-hero-tree-id="' + treeId + '"] .talent-tree-wrapper'
      );
      if (!source) return null;
      const clone = source.cloneNode(true);
      clone.querySelectorAll(
        '.tt-top-badge, .tt-choice-pct, .tt-choice-badge, .tt-hero-top-hint, .tt-hero-switch-label, .tt-hero-switch-hint'
      ).forEach((el) => el.remove());
      clone.querySelectorAll('.tt-hero-switch').forEach((el) => {
        el.classList.remove('tt-hero-switch-active');
        el.removeAttribute('role');
        el.removeAttribute('tabindex');
        el.removeAttribute('title');
      });
      // Bootstrap moves initialised tooltips' text into data-bs-original-title
      // and the clone is not registered with it, so fall back to plain titles.
      clone.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
        const text = el.getAttribute('data-bs-original-title');
        if (text) el.setAttribute('title', text);
        el.removeAttribute('data-bs-toggle');
      });
      return clone;
    }

    // Talent Builds modal: a build card paints that exact build onto a clone of
    // its hero tree's talent tree and points "Copy this build" at its (real,
    // collected) string. The paint is class-driven (.tt-build-view, see
    // spec-page.css), so repainting another build needs no saved node state.
    (function () {
      const modal = document.getElementById('talentBuildsModal');
      const paths = SPEC.buildPaths || {};
      const choiceSpells = paths.choiceSpells || {};
      const buildsByTree = paths.builds || {};
      const panels = modal ? Array.from(modal.querySelectorAll('.tt-builds')) : [];
      if (!panels.length) return;
      const selected = {};  // hero tree id -> build id

      function clearTree(mount) {
        mount.querySelectorAll('.tt-build-rank, .tt-build-flex-badge, .tt-build-change, .tt-build-choice-pct').forEach((el) => el.remove());
        mount.querySelectorAll('.is-picked, .is-flex').forEach((el) => el.classList.remove('is-picked', 'is-flex'));
        mount.querySelectorAll('img[data-orig-src]').forEach((img) => {
          img.setAttribute('src', img.getAttribute('data-orig-src'));
          img.removeAttribute('data-orig-src');
        });
      }

      function addBadge(node, cls, text, title) {
        const el = document.createElement('span');
        el.className = cls;
        el.textContent = text;
        el.title = title;
        (node.querySelector('.tt-choice-wrapper') || node).appendChild(el);
      }

      function paintTree(mount, build, lead) {
        clearTree(mount);
        const picked = new Set();
        mount.querySelectorAll('[data-nodeid]').forEach((node) => {
          const id = node.getAttribute('data-nodeid');
          const pick = build.picks[id];
          if (pick || node.hasAttribute('data-free')) {
            picked.add(id);
            node.classList.add('is-picked');
          }
          if (pick && choiceSpells[id]) {
            // show the chosen entry's icon, not the most popular one
            const row = node.querySelector('.tt-choice-row[href$="spell=' + choiceSpells[id][pick[0]] + '"]');
            const icon = node.querySelector('img.tt-octagon');
            if (row) {
              row.classList.add('is-picked');
              const rowIcon = row.querySelector('img');
              if (icon && rowIcon) {
                icon.setAttribute('data-orig-src', icon.getAttribute('src'));
                icon.setAttribute('src', rowIcon.getAttribute('src'));
              }
            }
          }
          const maxRanks = Number(node.getAttribute('data-maxranks') || 1);
          if (pick && maxRanks > 1) {
            addBadge(node, 'tt-build-rank', pick[1] + '/' + maxRanks, 'Points spent: ' + pick[1] + '/' + maxRanks);
          }
          const flex = build.flex[id];
          if (flex !== undefined) {
            node.classList.add('is-flex');
            addBadge(node, 'tt-build-flex-badge', Math.round(flex) + '%',
              'Flexible: ' + flex + '% of this build\'s runs take this talent');
          }
          // a flexible choice node lists each option's share in its choice list
          const choiceFlex = (build.choiceFlex || {})[id];
          if (choiceFlex && choiceSpells[id]) {
            Object.keys(choiceFlex).forEach((entry) => {
              const row = node.querySelector('.tt-choice-row[href$="spell=' + choiceSpells[id][entry] + '"]');
              if (!row) return;
              const pct = document.createElement('span');
              pct.className = 'tt-build-choice-pct';
              pct.textContent = Math.round(choiceFlex[entry]) + '%';
              pct.title = choiceFlex[entry] + '% of this build\'s runs pick this option';
              row.appendChild(pct);
            });
          }
          const change = (build.changed || {})[id];
          if (change) {
            addBadge(node, 'tt-build-change ' + (change === '+' ? 'is-plus' : 'is-minus'),
              change === '+' ? '+' : '\u2212', (change === '+' ? 'Added or changed vs ' : 'Dropped vs ') + lead);
          }
        });
        mount.querySelectorAll('line[data-from]').forEach((line) => {
          line.classList.toggle('is-picked',
            picked.has(line.getAttribute('data-from')) && picked.has(line.getAttribute('data-to')));
        });
      }

      function syncCards(panel, id) {
        const core = id.split('.')[0];
        const variantId = id.indexOf('.') >= 0 ? id : id + '.v1';
        panel.querySelectorAll('[data-build]').forEach((btn) => {
          const b = btn.getAttribute('data-build');
          const on = b === core || b === variantId;
          btn.classList.toggle('is-active', on);
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        panel.querySelectorAll('.tt-build-variants').forEach((row) => {
          row.hidden = row.getAttribute('data-core') !== core;
        });
        fitChips(panel);
      }

      // Shows as many change chips as fit on one line and counts the rest in
      // "+N more", so wide screens show every change. Chips are hidden from the
      // ends of the dropped, added and swapped groups in turn, so a narrow row
      // still shows every side. Hidden rows measure 0 and are fitted when they appear.
      function fitChips(root) {
        root.querySelectorAll('.tt-build-chips').forEach((row) => {
          if (!row.offsetWidth) return;
          const chips = Array.from(row.querySelectorAll('.tt-diff-chip'));
          const groups = [
            chips.filter((c) => c.classList.contains('is-minus')),
            chips.filter((c) => c.classList.contains('is-plus') || c.classList.contains('is-rank')),
            chips.filter((c) => c.classList.contains('is-swap')),
          ];
          const dividers = Array.from(row.querySelectorAll('.tt-diff-divider'));
          const more = row.querySelector('.tt-build-more');
          chips.forEach((c) => { c.hidden = false; });
          dividers.forEach((d) => { d.hidden = false; });
          more.hidden = true;
          let hiddenCount = 0;
          let turn = 0;
          while (row.scrollWidth > row.clientWidth && groups.some((g) => g.length)) {
            while (!groups[turn % groups.length].length) turn += 1;
            groups[turn % groups.length].pop().hidden = true;
            turn += 1;
            hiddenCount += 1;
            more.textContent = '+' + hiddenCount + ' more';
            more.hidden = false;
            syncDividers(row);
          }
        });
      }

      // A divider shows only between two groups that still have a visible chip,
      // so an emptied middle group leaves one divider, not two.
      function syncDividers(row) {
        let chipBefore = false;
        let lastDivider = null;
        Array.from(row.children).forEach((el) => {
          if (el.classList.contains('tt-diff-divider')) {
            el.hidden = true;
            if (chipBefore) lastDivider = el;
          } else if (el.classList.contains('tt-diff-chip') && !el.hidden) {
            if (lastDivider) lastDivider.hidden = false;
            lastDivider = null;
            chipBefore = true;
          }
        });
      }

      // Returns false for an id this hero tree does not have.
      function select(panel, id) {
        const treeId = panel.getAttribute('data-hero-tree-id');
        const build = (buildsByTree[treeId] || {})[id];
        const mount = panel.querySelector('.tt-build-tree-mount');
        if (!build || !mount) return false;
        if (!mount.firstChild) {
          const clone = cloneTalentTree(treeId);
          if (!clone) return false;
          mount.appendChild(clone);
        }
        paintTree(mount, build, id.indexOf('.') >= 0 ? 'Variant 1' : 'Build 1');
        panel.querySelector('.js-copy-build').setAttribute('data-loadout', build.code);
        selected[treeId] = id;
        syncCards(panel, id);
        return true;
      }

      function visiblePanel() {
        return panels.find((p) => p.closest('.hero-section-variant').style.display !== 'none');
      }

      panels.forEach((panel) => {
        panel.addEventListener('click', (e) => {
          const btn = e.target.closest('[data-build]');
          if (!btn) return;
          // Chips are Wowhead links for the hover tooltip; a plain click picks the
          // row instead, while Ctrl/Cmd/Shift-click still opens Wowhead.
          if (e.target.closest('.tt-diff-chip') && !(e.ctrlKey || e.metaKey || e.shiftKey)) e.preventDefault();
          select(panel, btn.getAttribute('data-build'));
          if (window.MythiLink) MythiLink.sync();
        });
        panel.addEventListener('keydown', (e) => {
          const btn = e.target.closest('.tt-build-card');
          if (!btn || e.target !== btn || (e.key !== 'Enter' && e.key !== ' ')) return;
          e.preventDefault();
          btn.click();
        });
      });

      modal.addEventListener('shown.bs.modal', () => fitChips(modal));
      // Observes the body, not the window, so any width change (scrollbar, zoom) refits.
      let resizeTimer;
      new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          if (modal.classList.contains('show')) fitChips(modal);
        }, 150);
      }).observe(modal.querySelector('.modal-body'));

      // Trees are cloned on first open, not at load, since most visitors never open the modal.
      modal.addEventListener('show.bs.modal', () => {
        panels.forEach((panel) => {
          if (!selected[panel.getAttribute('data-hero-tree-id')]) select(panel, 'b1');
        });
      });

      // Registered after 'hero', so a link's hero tree is shown before its build applies.
      if (window.MythiLink) {
        MythiLink.registerState('build', {
          read: function () {
            const panel = visiblePanel();
            const id = panel && selected[panel.getAttribute('data-hero-tree-id')];
            return modal.classList.contains('show') && id && id !== 'b1' ? id : null;
          },
          apply: function (id) {
            const panel = visiblePanel();
            if (panel) select(panel, id);
          }
        });
      }
    })();

    // Talent Differences modal: the per-dungeon tree views are clones of the
    // page's talent tree, repainted from the per-dungeon usage JSON. Rendering
    // a tree per dungeon server-side would add megabytes to every spec page, so
    // the page ships one tree plus a few KB of numbers. Every percentage in a
    // clone is repainted or removed, so nothing season-wide leaks into a
    // dungeon view.
    (function () {
      const usageByTree = {};
      document.querySelectorAll('script.js-dungeon-tree-usage').forEach((el) => {
        try {
          usageByTree[el.getAttribute('data-hero-tree-id')] = JSON.parse(el.textContent);
        } catch (err) {
          console.error('Unreadable per-dungeon talent usage payload', err);
        }
      });

      // mirrors the pct_color macro
      function pctColor(pct) {
        if (pct < 10) return '#9d9d9d';
        if (pct < 25) return 'var(--class-Priest)';
        if (pct < 50) return 'var(--class-Monk)';
        if (pct < 75) return '#0070dd';
        if (pct < 95) return '#a335ee';
        return '#ff8000';
      }

      function repaintNode(node, entry) {
        const pct = entry ? entry[0] : 0;
        const avgRank = entry ? entry[1] : 0;
        node.classList.toggle('inactive', pct === 0);
        const shaded = node.querySelector('.tt-octagon-border') || node.querySelector('img');
        if (shaded) shaded.style.filter = 'grayscale(' + (100 - pct) + '%)';
        const badge = node.querySelector('.tt-badge, .tt-hero-node-pct');
        if (badge) {
          badge.textContent = Math.round(pct) + '%';
          badge.title = pct.toFixed(1) + '%';
          badge.style.borderColor = pctColor(pct);
        }
        const maxRank = node.querySelector('.tt-maxrank');
        if (maxRank) {
          maxRank.textContent = Math.round(avgRank);
          maxRank.title = 'Average points spent: ' + avgRank.toFixed(2);
        }
      }

      function hydrate(mount) {
        if (mount.dataset.hydrated) return;
        const treeId = mount.getAttribute('data-hero-tree-id');
        const data = (usageByTree[treeId] || {})[mount.getAttribute('data-dungeon')];
        const clone = data && cloneTalentTree(treeId);
        if (!clone) return;
        mount.dataset.hydrated = '1';

        const share = clone.querySelector('.tt-hero-share');
        if (share) {
          share.textContent = Math.round(data.tree_pct || 0) + '%';
          share.title = (data.tree_pct || 0).toFixed(1) + '% of this dungeon\'s top-50 loadouts';
        }
        clone.querySelectorAll('[data-nodeid]').forEach((node) => {
          repaintNode(node, data.nodes[node.getAttribute('data-nodeid')]);
        });
        mount.appendChild(clone);
      }

      // Hydrate every variant in a dungeon panel, not just the visible one, so
      // switching hero trees with the panel open never leaves an empty mount.
      // Direct children only: the gains/losses lists are accordions too.
      document.querySelectorAll('#dungeonAccordion > .accordion-item > .accordion-collapse').forEach((panel) => {
        panel.addEventListener('show.bs.collapse', () => {
          panel.querySelectorAll('.dungeon-tree-mount').forEach(hydrate);
        });
      });

      document.querySelectorAll('.js-copy-build').forEach((btn) => {
        const label = btn.querySelector('.js-copy-build-text');
        if (!label) return;
        const text = label.getAttribute('data-text');
        btn.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(btn.getAttribute('data-loadout') || '');
            label.textContent = 'Copied!';
            btn.classList.replace('btn-primary', 'btn-success');
          } catch (err) {
            console.error('Copy failed', err);
            label.textContent = 'Error';
            btn.classList.replace('btn-primary', 'btn-danger');
          }
          setTimeout(() => {
            label.textContent = text;
            btn.classList.replace('btn-success', 'btn-primary');
            btn.classList.replace('btn-danger', 'btn-primary');
          }, 2000);
        });
      });
    })();

