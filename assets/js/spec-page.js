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
    // Filled in by the talent builds block below: the export string of the build
    // painted on a hero tree, and a hook for when the visible tree or list changes.
    const talentBuilds = { codeFor: () => '', onViewChange: () => {} };

    // Export Talent String copies the build painted on the visible tree, else
    // that tree's most-used loadout.
    function syncExport() {
      const btnText = document.getElementById('btnText');
      const copyBtn = document.getElementById('copyBtn');
      const active = Array.from(document.querySelectorAll('.tt-variant')).find((el) => el.style.display !== 'none');
      if (!btnText || !copyBtn || !active) return;
      const loadout = talentBuilds.codeFor(active.getAttribute('data-hero-tree-id')) ||
        active.getAttribute('data-loadout') || '';
      btnText.setAttribute('data-loadout', loadout);
      copyBtn.style.display = loadout ? '' : 'none';
    }

    // View switcher: the hero tree (cycled by clicking the hero icon) and the Top
    // Players toggle together pick which server-rendered blocks are visible. Every
    // switchable block carries data-hero-tree-id; blocks that differ per data
    // source also carry data-cohort ("all" | "top", see section_variants in
    // generateSpecPages.py). Blocks without data-cohort (per-dungeon talent diffs)
    // follow the hero tree only.
    (function () {
      const variants = Array.from(document.querySelectorAll('.tt-variant'));
      if (!variants.length) return;
      const switchable = Array.from(
        document.querySelectorAll('.tt-variant, .talent-dif-variant, .hero-section-variant')
      );
      const treeIds = [...new Set(variants.map((el) => el.getAttribute('data-hero-tree-id')))];
      const cohortSwitch = document.getElementById('cohort-toggle');

      // The server-rendered default: the visible overall-data tree.
      const initial = variants.find((el) => el.style.display !== 'none') || variants[0];
      const defaultTreeId = initial.getAttribute('data-hero-tree-id');
      let treeId = defaultTreeId;
      let cohort = 'all';

      function show() {
        switchable.forEach((el) => {
          const elCohort = el.getAttribute('data-cohort');
          const match = el.getAttribute('data-hero-tree-id') === treeId && (!elCohort || elCohort === cohort);
          el.style.display = match ? '' : 'none';
        });
        syncExport();
        const isTop = cohort === 'top';
        document.body.classList.toggle('spec-cohort-top', isTop);
        if (cohortSwitch) cohortSwitch.checked = isTop;
        talentBuilds.onViewChange();
      }
      show();

      function advance() {
        treeId = treeIds[(treeIds.indexOf(treeId) + 1) % treeIds.length];
        show();
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

      if (cohortSwitch) {
        cohortSwitch.addEventListener('change', () => {
          cohort = cohortSwitch.checked ? 'top' : 'all';
          show();
          if (window.MythiLink) MythiLink.sync();
        });
      }

      // Both bits of view state change what a visitor walks away with (the talent
      // tree, the gear lists *and* the Export Talent String), so a shared link
      // carries them as &cohort=top / &hero=<treeId> whenever they aren't the default.
      if (window.MythiLink) {
        MythiLink.registerState('cohort', {
          read: function () {
            return cohort === 'top' ? 'top' : null;
          },
          apply: function (value) {
            if (value !== 'top' || !cohortSwitch) return;  // no Top Players view on this page
            cohort = 'top';
            show();
          }
        });
        MythiLink.registerState('hero', {
          read: function () {
            return treeId === defaultTreeId ? null : treeId;
          },
          apply: function (value) {
            if (!treeIds.includes(String(value))) return;  // unknown tree id in a hand-edited link
            treeId = String(value);
            show();
          }
        });
      }
    })();

    // Strips a painted build (paintTree below) from a talent tree.
    function clearTree(root) {
      root.querySelectorAll('.tt-build-rank, .tt-build-flex-badge, .tt-build-change, .tt-build-choice-pct').forEach((el) => el.remove());
      root.querySelectorAll('.is-picked, .is-flex').forEach((el) => el.classList.remove('is-picked', 'is-flex'));
      root.querySelectorAll('img[data-orig-src]').forEach((img) => {
        img.setAttribute('src', img.getAttribute('data-orig-src'));
        img.removeAttribute('data-orig-src');
      });
    }

    // A copy of one hero tree's page talent tree for a modal to repaint, with the
    // season-wide badges and the page-only hero switcher stripped.
    function cloneTalentTree(treeId) {
      const source = document.querySelector(
        '#static-talent-tree .tt-variant[data-cohort="all"][data-hero-tree-id="' + treeId + '"] .talent-tree-wrapper'
      );
      if (!source) return null;
      const clone = source.cloneNode(true);
      clearTree(clone);  // the page tree may be showing a build
      clone.querySelectorAll(
        '.tt-top-badge, .tt-choice-pct, .tt-choice-badge, .tt-hero-top-hint, .tt-hero-switch-label, .tt-hero-switch-hint, .tt-hero-detail-btn'
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

    // Talent build list: a build card paints that exact build onto its hero
    // tree's page talent tree and points Export Talent String at its (real,
    // collected) string; the "Overview" card (empty id) restores the pick rates.
    // The paint is class-driven (.tt-build-view, see spec-page.css), so it needs
    // no saved node state. Lists exist per (cohort, hero tree), the selection per
    // hero tree.
    (function () {
      const root = document.getElementById('static-talent-tree');
      const paths = SPEC.buildPaths || {};
      const choiceSpells = paths.choiceSpells || {};
      const buildsByTree = paths.builds || {};
      const panels = root ? Array.from(root.querySelectorAll('.tt-builds')) : [];
      if (!panels.length) return;
      const viewTitle = root.querySelector('.tt-panel-view-title');
      const viewSub = root.querySelector('.tt-panel-view-sub');
      const selected = {};  // hero tree id -> build id, unset on Overview

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
        syncVariants(panel);
      }

      // Class tree variants show for the selected build. When the list is as
      // tall as the tree (absolutely positioned in the wide layout, see
      // spec-page.css), the other builds' variants open too while they fit, so
      // a short list fills the rail. `refill` redoes that fill, as does going
      // back to the Overview; picking a build keeps it, so the rows above the
      // clicked build do not move.
      function syncVariants(panel, refill) {
        const list = panel.querySelector('.tt-build-list');
        const core = (selected[treeIdOf(panel)] || '').split('.')[0];
        const rows = Array.from(panel.querySelectorAll('.tt-build-variants'));
        refill = refill || !core;
        if (refill) rows.forEach((row) => row.removeAttribute('data-fill'));
        rows.forEach((row) => {
          row.hidden = row.getAttribute('data-core') !== core && !row.hasAttribute('data-fill');
        });
        if (refill && list.clientHeight && getComputedStyle(list).position === 'absolute') {
          for (const row of rows) {
            if (!row.hidden) continue;
            row.hidden = false;
            if (list.scrollHeight > list.clientHeight) {
              row.hidden = true;
              break;
            }
            row.setAttribute('data-fill', '');
          }
        }
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

      function treeIdOf(panel) {
        return panel.getAttribute('data-hero-tree-id');
      }

      function visiblePanel() {
        return panels.find((p) => p.style.display !== 'none');
      }

      // The id a card selects. A Top 50 list's core card leads with the class
      // tree variant those players favour instead of the most-run one.
      function cardTarget(card) {
        return card.getAttribute('data-lead') || card.getAttribute('data-build');
      }

      // The title over the tree names the visible tree's selection (the class
      // tree variant only when it is not the standard one), the Overview adds
      // its caption, and the export follows.
      function syncView() {
        const panel = visiblePanel();
        const onBuild = !!(panel && selected[treeIdOf(panel)]);
        const active = panel ? Array.from(panel.querySelectorAll('.tt-build-card.is-active')) : [];
        const caption = panel && panel.querySelector('[data-build=""] .tt-build-sub');
        viewTitle.textContent = active
          .filter((card) => !card.getAttribute('data-build').endsWith('.v1'))
          .map((card) => card.querySelector('.tt-build-label').textContent)
          .join(', ') || 'Overview';
        if (caption) viewSub.textContent = caption.textContent;
        viewSub.hidden = onBuild;
        syncExport();
      }

      // An empty id is the Overview. Returns false for an id this hero tree does not have.
      function select(treeId, id) {
        const build = id ? (buildsByTree[treeId] || {})[id] : null;
        if (id && !build) return false;
        root.querySelectorAll('.tt-variant[data-hero-tree-id="' + treeId + '"]').forEach((variant) => {
          variant.classList.toggle('tt-build-view', !!build);
          if (build) paintTree(variant, build, id.indexOf('.') >= 0 ? 'the standard class tree' : 'the Standard build');
          else clearTree(variant);
        });
        if (build) selected[treeId] = id;
        else delete selected[treeId];
        panels.forEach((panel) => {
          if (treeIdOf(panel) === treeId) syncCards(panel, id || '');
        });
        syncView();
        return true;
      }

      talentBuilds.codeFor = function (treeId) {
        const build = (buildsByTree[treeId] || {})[selected[treeId]];
        return build ? build.code : '';
      };

      // The Top 50 list drops builds none of those players run, so a selection the
      // visible list cannot show moves to its build card, else back to the Overview.
      talentBuilds.onViewChange = function () {
        const panel = visiblePanel();
        const id = panel && selected[treeIdOf(panel)];
        if (id) {
          const card = panel.querySelector('[data-build="' + id + '"]');
          if (!card || card.hasAttribute('data-lead')) {
            const core = card || panel.querySelector('[data-build="' + id.split('.')[0] + '"]');
            select(treeIdOf(panel), core ? cardTarget(core) : '');
            return;
          }
        }
        if (panel) syncVariants(panel, true);
        syncView();
      };

      panels.forEach((panel) => {
        panel.addEventListener('click', (e) => {
          const btn = e.target.closest('[data-build]');
          if (!btn) return;
          // Chips are Wowhead links for the hover tooltip; a plain click picks the
          // row instead, while Ctrl/Cmd/Shift-click still opens Wowhead.
          if (e.target.closest('.tt-diff-chip') && !(e.ctrlKey || e.metaKey || e.shiftKey)) e.preventDefault();
          select(treeIdOf(panel), cardTarget(btn));
          if (window.MythiLink) MythiLink.sync();
        });
        panel.addEventListener('keydown', (e) => {
          const btn = e.target.closest('.tt-build-card');
          if (!btn || e.target !== btn || (e.key !== 'Enter' && e.key !== ' ')) return;
          e.preventDefault();
          btn.click();
        });
      });

      // A list is refitted whenever its size changes, which includes becoming
      // visible on a hero tree or Top 50 switch.
      let resizeTimer;
      const observer = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => panels.forEach((panel) => syncVariants(panel, true)), 150);
      });
      panels.forEach((panel) => observer.observe(panel.querySelector('.tt-build-list')));
      panels.forEach((panel) => syncVariants(panel, true));

      // Registered after 'cohort' and 'hero', so a link's tree and list are shown
      // before its build applies.
      if (window.MythiLink) {
        MythiLink.registerState('build', {
          read: function () {
            const panel = visiblePanel();
            return (panel && selected[treeIdOf(panel)]) || null;
          },
          apply: function (id) {
            const panel = visiblePanel();
            if (panel && select(treeIdOf(panel), id)) talentBuilds.onViewChange();
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

