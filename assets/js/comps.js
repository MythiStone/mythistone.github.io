// Comps page: Perfect Fit widget, synergy, best-spec pairs, archetype cards.
// Extracted from templates/comps.html. Page-config lookups (dungeon/spec
// lookups, synergy matrix, best-spec pairs, group buffs, meta key) come from the
// inline <script type="application/json" id="comps-page-data"> block, read
// synchronously because buffProviders / META_COMP_SPECS are derived at load.
// The large comp datasets are still fetched from /assets/json/comps_index.json
// and comp_archetypes.json inside this script.
const PAGE = JSON.parse(document.getElementById('comps-page-data').textContent);

    // Prefetch comps JSON
    let compsData = [];
    const compsLoaded = fetch('/assets/json/comps_index.json')
      .then(response => response.json())
      .then(data => {
        compsData = data;
      })
      .catch(err => console.error("Error loading comp data", err));

    // Ordered multiset of selected spec ids (numbers), capped at 5, duplicates
    // allowed so a comp can include the same spec twice (e.g. two Blood DKs).
    let selected = [];
    function selCount(s) {
      const n = Number(s);
      let c = 0;
      for (const x of selected) if (x === n) c++;
      return c;
    }
    function countMapOf(list) {
      const m = new Map();
      for (const x of list) m.set(Number(x), (m.get(Number(x)) || 0) + 1);
      return m;
    }
    // Sorted-ascending multiset key, matching the DB `comp` string (so it lines up
    // with isMetaComp / comp keys, which keep duplicates).
    function selSortedKey() {
      return selected.slice().sort((a, b) => a - b);
    }
    const specIcons = document.querySelectorAll('.spec-icon');
    const suggestionsContainer = document.getElementById('suggestions-container');
    const selectedCompRow = document.getElementById('selected-comp');

    // A broken game icon (e.g. an unresolved spec falling back to a missing
    // placeholder file) should quietly hide rather than show a broken box.
    document.addEventListener('error', (e) => {
      const t = e.target;
      if (t && t.tagName === 'IMG' && typeof t.src === 'string' && t.src.indexOf('/data/icons/') !== -1) {
        t.style.visibility = 'hidden';
      }
    }, true);

    const roleMap = { 0: 'Tank', 1: 'Healer', 2: 'Dps' };
    const dungeonLookup = PAGE.dungeonLookup;
    const specLookup = PAGE.specLookup;

    const TOP_KEY_LEVELS = PAGE.topKeyLevels;
    const synergyMatrix = PAGE.synergyMatrix;

    // Best Spec Combinations, precomputed per dungeon context ('all' + each dungeon id
    // as a string key). Small enough (~18 rows x ~9 contexts) to embed inline; the card
    // is server-rendered for 'all' first paint and re-ranked client-side on dungeon
    // change from this map.
    const BEST_SPEC_PAIRS = PAGE.bestSpecPairs;

    // --- Group buff / utility coverage (Perfect Fit) ---
    // Each entry: {id, icon, name, specIDs:[...]}. Bloodlust (2825) and
    // Battlerez (20484) are group-critical utility and are flagged so a missing
    // one is called out more prominently than a missing class raid buff.
    const GROUP_BUFFS = PAGE.groupBuffs;
    const CRITICAL_BUFF_IDS = new Set([2825, 20484]);
    // buff id -> Set of specIDs that provide it (for fast covered/missing checks)
    const buffProviders = new Map(
      GROUP_BUFFS.map(b => [b.id, new Set((b.specIDs || []).map(Number))])
    );

    // Which buffs the given set of specIDs covers vs. still misses.
    function computeBuffCoverage(specSet) {
      const ids = Array.from(specSet).map(Number);
      const covered = [], missing = [];
      GROUP_BUFFS.forEach(b => {
        const providers = buffProviders.get(b.id);
        (ids.some(s => providers.has(s)) ? covered : missing).push(b);
      });
      return { covered, missing };
    }

    // Buffs a candidate spec would newly add on top of the current selection.
    function buffGainForSpec(specId, specSet) {
      const sid = Number(specId);
      const gains = [];
      GROUP_BUFFS.forEach(b => {
        const providers = buffProviders.get(b.id);
        if (!providers.has(sid)) return;
        const alreadyCovered = Array.from(specSet).some(s => providers.has(Number(s)));
        if (!alreadyCovered) gains.push(b);
      });
      return gains;
    }

    function buffChip(b, covered) {
      const critical = CRITICAL_BUFF_IDS.has(b.id);
      const cls = covered ? 'buff-chip buff-chip--on' : `buff-chip buff-chip--off${critical ? ' buff-chip--critical' : ''}`;
      const status = covered ? 'covered' : 'missing';
      return `<span class="${cls}" title="${b.name}: ${status}">
        <img src="/data/icons/${b.icon.replace(/\.(jpg|png)$/i, '')}.${/\.png$/i.test(b.icon) ? 'png' : 'jpg'}" alt="${b.name}" loading="lazy">
      </span>`;
    }

    function renderBuffCoverage() {
      const el = document.getElementById('buff-coverage');
      if (!el) return;
      if (selected.length === 0) {
        el.innerHTML = '<p class="text-sm text-secondary mb-0">Select specs to see which raid buffs, Bloodlust and Battle Rez your group covers.</p>';
        return;
      }
      const { covered, missing } = computeBuffCoverage(selected);
      const criticalMissing = missing.filter(b => CRITICAL_BUFF_IDS.has(b.id));
      const chips = GROUP_BUFFS
        .map(b => buffChip(b, covered.includes(b)))
        .join('');
      let summary;
      if (missing.length === 0) {
        summary = '<span class="text-success"><i class="material-symbols-rounded align-middle text-sm me-1">check_circle</i>Full buff coverage</span>';
      } else {
        const parts = [];
        if (criticalMissing.length) {
          parts.push(`<span class="text-danger font-weight-bold">Missing ${criticalMissing.map(b => b.name).join(' &amp; ')}</span>`);
        }
        const otherMissing = missing.filter(b => !CRITICAL_BUFF_IDS.has(b.id));
        if (otherMissing.length) {
          parts.push(`<span class="text-warning">${otherMissing.length} raid buff${otherMissing.length > 1 ? 's' : ''} missing</span>`);
        }
        summary = parts.join(' &middot; ');
      }
      el.innerHTML = `
        <div class="buff-chip-row">${chips}</div>
        <div class="text-xs mt-2">${summary}</div>
      `;
    }

    // The "meta" comp (strongest in the highest keys) is highlighted everywhere.
    const META_COMP_KEY = PAGE.metaCompKey;
    const META_COMP_SPECS = META_COMP_KEY ? META_COMP_KEY.split(',').map(Number) : [];
    const META_BADGE = '<span class="badge meta-badge ms-2" title="Current meta comp: the strongest composition in the highest keys"><i class="material-symbols-rounded align-middle">workspace_premium</i> META</span>';
    function isMetaComp(cArr) {
      return Array.isArray(cArr) && META_COMP_KEY && cArr.join(',') === META_COMP_KEY;
    }
    // True when every selected spec is part of the meta comp, so adding more of
    // its specs keeps the user on the path toward building the meta comp.
    function onMetaPath(specList) {
      return META_COMP_SPECS.length > 0 && Array.from(specList).every(s => META_COMP_SPECS.includes(Number(s)));
    }

    // Deep-link into the routes page. Both pages use the same spec ids, so the
    // comp key can be handed over verbatim. The dungeon filter is read live so
    // every link reflects whatever the user currently has selected.
    function compRoutesUrl(specIds) {
      const dFilter = document.getElementById('dungeonFilter');
      const d = dFilter ? dFilter.value : 'all';
      let qs = 'specs=' + Array.from(specIds).join(',');
      if (d && d !== 'all') qs += '&dungeons=' + d;
      return '/pages/routes?' + qs;
    }

    const ROUTES_LINK_TITLE = 'Find keystone.guru routes played by this comp';
    function routesLinkHtml(specIds, compact = true) {
      const cls = compact
        ? 'btn btn-sm btn-outline-primary mb-0 ms-2 comp-routes-btn'
        : 'btn btn-primary w-100 mb-2';
      // The icon only earns its space on the full-width variant.
      const label = compact
        ? 'Routes'
        : '<i class="material-symbols-rounded align-middle me-1">route</i>Find routes for this comp';
      return `<a href="${compRoutesUrl(specIds)}" target="_blank" rel="noopener" class="${cls}" title="${ROUTES_LINK_TITLE}">${label}</a>`;
    }

    function readUrlParams() {
      const sp = new URLSearchParams(window.location.search);
      let changed = false;
      const d = sp.get('dungeons');
      const dOld = sp.get('dungeon'); // Support old param if any
      const usedD = d || dOld;
      if (usedD) {
        const dFilter = document.getElementById('dungeonFilter');
        if (dFilter.querySelector(`option[value="${usedD}"]`)) {
          dFilter.value = usedD;
          changed = true;
        }
      }

      const sParams = sp.get('specs') || sp.get('spec');
      if (sParams) {
        sParams.split(',').forEach(sid => {
          const id = parseInt(sid);
          if (!isNaN(id) && selected.length < 5) {
            const icon = document.querySelector(`.spec-icon[data-spec="${id}"]`);
            if (icon) {
              selected.push(id);
              changed = true;
            }
          }
        });
        renderSelectedComp();
      }
      return changed;
    }

    function writeUrlParams() {
      const sp = new URLSearchParams(window.location.search);
      if (selected.length > 0) {
        sp.set('specs', selSortedKey().join(','));
        sp.delete('spec');
      } else {
        sp.delete('specs');
        sp.delete('spec');
      }

      const dFilter = document.getElementById('dungeonFilter');
      if (dFilter.value && dFilter.value !== 'all') {
        sp.set('dungeons', dFilter.value);
        sp.delete('dungeon'); // clear old param if present
      } else {
        sp.delete('dungeons');
        sp.delete('dungeon');
      }

      const newQs = sp.toString();
      // Keep the deep-link fragment: the filters and the open comp modal are
      // independent bits of state and either can change without the other.
      const base = newQs ? '?' + newQs : window.location.pathname;
      window.history.replaceState({}, '', base + window.location.hash);
    }

    compsLoaded.then(() => {
      if (readUrlParams()) {
        updateSuggestions();
      }
    });

    // Clicking a grid icon TOGGLES the spec (adds it, or removes all its copies).
    // A second copy for a duplicate-spec comp is added with the chip stepper below.
    specIcons.forEach(icon => {
      icon.addEventListener('click', (e) => {
        const specId = parseInt(e.currentTarget.dataset.spec);
        if (selCount(specId) > 0) {
          selected = selected.filter(s => s !== specId);
        } else {
          if (selected.length >= 5) return;
          selected.push(specId);
        }
        renderSelectedComp();
        writeUrlParams();
        updateSuggestions();
      });
    });

    // Render the picked comp as one stepper chip per distinct spec (same -/xN/+
    // control as the routes/VOD finders); the icon grid handles select/unselect.
    function renderSelectedComp() {
      specIcons.forEach(icon => {
        icon.classList.toggle('selected', selCount(icon.dataset.spec) > 0);
      });
      if (!selectedCompRow) return;
      const distinct = [];
      selected.forEach(s => { if (!distinct.includes(s)) distinct.push(s); });
      if (distinct.length === 0) {
        selectedCompRow.innerHTML = '';
        return;
      }
      const total = selected.length;
      const frag = document.createDocumentFragment();
      distinct.forEach(sid => {
        const count = selCount(sid);
        const info = specLookup[sid] || { icon: 'inv_misc_questionmark', name: 'Unknown' };
        const chip = document.createElement('div');
        chip.className = 'spec-count-chip';
        chip.innerHTML =
          `<img src="/data/icons/${info.icon}.jpg" alt="" class="spec-count-icon">` +
          `<span class="spec-count-name">${info.name}</span>` +
          `<span class="spec-count-steps">` +
          `<button type="button" class="spec-count-step" data-dir="-1"${count <= 1 ? ' disabled' : ''} aria-label="One fewer">&minus;</button>` +
          `<span class="spec-count-badge">&times;${count}</span>` +
          `<button type="button" class="spec-count-step" data-dir="1"${total >= 5 ? ' disabled' : ''} aria-label="One more">+</button>` +
          `</span>`;
        chip.querySelectorAll('.spec-count-step').forEach(btn => {
          btn.addEventListener('click', () => stepSelected(sid, Number(btn.getAttribute('data-dir'))));
        });
        frag.appendChild(chip);
      });
      selectedCompRow.innerHTML = '';
      selectedCompRow.appendChild(frag);
    }

    // Stepper only adjusts multiplicity (1..5). Dropping the last copy is done by
    // clicking the grid icon, so the minus button stops at 1.
    function stepSelected(specId, dir) {
      const s = Number(specId);
      if (dir > 0) {
        if (selected.length >= 5) return;
        selected.push(s);
      } else {
        if (selCount(s) <= 1) return;
        const idx = selected.lastIndexOf(s);
        if (idx !== -1) selected.splice(idx, 1);
      }
      renderSelectedComp();
      writeUrlParams();
      updateSuggestions();
    }

    const dungeonFilter = document.getElementById('dungeonFilter');
    dungeonFilter.addEventListener('change', () => {
      writeUrlParams();
      updateSuggestions();
    });

    function updateSuggestions() {
      renderBuffCoverage();
      const headerTitle = document.querySelector('.card-header h6');
      if (selected.length === 0) {
        suggestionsContainer.innerHTML = '<p class="text-sm text-secondary">Select 1 to 5 specs to see suggestions.</p>';
        if (headerTitle) headerTitle.innerText = 'The Perfect Fit';
        return;
      }

      const selectedDungeonId = dungeonFilter.value; // 'all' or dungeon ID as string

      // Keep comps that contain the selection as a SUB-MULTISET (a spec picked
      // twice needs two copies in the comp), and drop comps with 0 runs in the
      // selected dungeon when a specific dungeon is chosen.
      const selCounts = countMapOf(selected);
      const possibleComps = compsData.filter(comp => {
        const compCounts = countMapOf(comp.c);
        for (const [s, c] of selCounts) if ((compCounts.get(s) || 0) < c) return false;

        if (selectedDungeonId !== 'all') {
          const did = parseInt(selectedDungeonId);
          if (!comp.dungeons || !comp.dungeons[did] || (comp.dungeons[did].t + comp.dungeons[did].d) === 0) {
            return false;
          }
        }
        return true;
      });

      // We need to re-sort them based on the weight for the selected dungeon if 'all' is not selected
      if (selectedDungeonId !== 'all') {
        const did = parseInt(selectedDungeonId);
        possibleComps.sort((a, b) => b.dungeons[did].w - a.dungeons[did].w);
      } else {
        // Fall back to total weight
        possibleComps.sort((a, b) => b.w - a.w);
      }

      if (selected.length === 5) {
        if (headerTitle) headerTitle.innerText = 'Composition Analysis';
        if (possibleComps.length === 0) {
          // No aggregate stats for this exact team, but routes may still exist.
          suggestionsContainer.innerHTML = '<div class="alert alert-secondary text-sm"><i class="material-symbols-rounded align-middle me-2">info</i>We don\'t have enough top-tier data matching this exact 5-man team.</div>'
            + routesLinkHtml(selSortedKey(), false);
        } else {
          const comp = possibleComps[0];

          let cTimed = comp.t;
          let cDepleted = comp.d;
          let cMaxKey = comp.mk;

          if (selectedDungeonId !== 'all') {
            const did = parseInt(selectedDungeonId);
            if (comp.dungeons && comp.dungeons[did]) {
              cTimed = comp.dungeons[did].t || 0;
              cDepleted = comp.dungeons[did].d || 0;
              cMaxKey = comp.dungeons[did].mk || 0;
            } else {
              cTimed = 0;
              cDepleted = 0;
              cMaxKey = 0;
            }
          }

          const totalRuns = cTimed + cDepleted;
          const winRate = totalRuns > 0 ? Math.round((cTimed / totalRuns) * 100) : 0;

          let dungeonStat = "";
          if (selectedDungeonId === 'all') {
            if (comp.bd && comp.bdr > 0 && dungeonLookup[comp.bd]) {
              const usagePercent = Math.round((comp.bdr / totalRuns) * 100);
              dungeonStat = `
                  <div class="d-flex justify-content-between mb-2">
                    <span class="text-sm text-secondary" title="Dungeon where this comp is played the most">Top Dungeon:</span>
                    <span class="text-sm text-body-emphasis font-weight-bold text-end">${dungeonLookup[comp.bd]} <span class="badge bg-secondary font-weight-normal ms-1 p-1" title="${usagePercent}% of this comp's total runs were played here">${usagePercent}% of runs</span></span>
                  </div>
              `;
            }
          }

          suggestionsContainer.innerHTML = `
            <div class="card border border-secondary mb-3 mt-2${isMetaComp(comp.c) ? ' meta-comp' : ''}">
              <div class="card-body p-3">
                <h6 class="text-body-emphasis mb-3">Stats for Selected Comp${isMetaComp(comp.c) ? META_BADGE : ''}</h6>
                <div class="d-flex justify-content-between mb-2">
                  <span class="text-sm text-secondary">Max Key Timed:</span>
                  <span class="text-sm text-body-emphasis font-weight-bold">${cMaxKey}</span>
                </div>
                <div class="d-flex justify-content-between mb-2">
                  <span class="text-sm text-secondary">Total Runs:</span>
                  <span class="text-sm text-body-emphasis font-weight-bold">${totalRuns}</span>
                </div>
                <div class="d-flex justify-content-between mb-2">
                  <span class="text-sm text-secondary">Success Rate:</span>
                  <span class="text-sm ${winRate >= 70 ? 'text-success' : 'text-warning'} font-weight-bold">${winRate}%</span>
                </div>
                ${dungeonStat}
              </div>
            </div>
            ${routesLinkHtml(comp.c, false)}
            <button class="btn btn-outline-primary w-100" onclick="clearSelection()">Start Over</button>
          `;
        }
        return;
      }

      if (headerTitle) headerTitle.innerText = 'Suggested Additions';

      if (possibleComps.length === 0) {
        suggestionsContainer.innerHTML = '<p class="text-sm text-warning">No viable top-tier data for this combo.</p>';
        return;
      }

      // Aggregate stats of remaining potential specs
      const specStats = {};
      possibleComps.forEach(comp => {
        let compWt = comp.w;
        let compT = comp.t;
        let compD = comp.d;
        let compMK = comp.mk;

        if (selectedDungeonId !== 'all') {
          const did = parseInt(selectedDungeonId);
          if (comp.dungeons && comp.dungeons[did]) {
            compWt = comp.dungeons[did].w || 0;
            compT = comp.dungeons[did].t || 0;
            compD = comp.dungeons[did].d || 0;
            compMK = comp.dungeons[did].mk || 0;
          } else {
            compWt = 0; compT = 0; compD = 0; compMK = 0;
          }
        }

        if (compWt > 0) {
          // Suggest each distinct spec the comp still has headroom for: a spec
          // already picked once is still suggestable if the comp uses it twice.
          const compCounts = countMapOf(comp.c);
          for (const [s, cCount] of compCounts) {
            if (selCount(s) >= cCount) continue;
            if (!specStats[s]) {
              specStats[s] = { t: 0, d: 0, mk: 0, w: 0 };
            }
            specStats[s].t += compT;
            specStats[s].d += compD;
            specStats[s].w += compWt;
            if (compMK > specStats[s].mk) {
              specStats[s].mk = compMK;
            }
          }
        }
      });

      const sortedSuggestions = Object.entries(specStats)
        .sort((a, b) => b[1].w - a[1].w)
        .slice(0, 10);

      // Suggestions that complete the meta comp (only when still on its path)
      const metaPath = onMetaPath(selected);

      let html = '<div class="w-100"><ul class="list-group mb-0">';
      sortedSuggestions.forEach(([specId, stats]) => {
        const specInfo = specLookup[specId] || { name: "Unknown", icon: "inv_misc_questionmark", specName: "Unknown", className: "Unknown", cleanClass: "Unknown", roleName: "Dps" };
        const total = stats.t + stats.d;
        const winRate = total > 0 ? Math.round((stats.t / total) * 100) : 0;
        const isMetaSpec = metaPath && META_COMP_SPECS.includes(Number(specId));

        // Buffs this suggestion would newly bring to the current group.
        const buffGains = buffGainForSpec(specId, selected);
        const buffGainBadges = buffGains.map(b => {
          const critical = CRITICAL_BUFF_IDS.has(b.id);
          return `<span class="buff-gain-badge${critical ? ' buff-gain-badge--critical' : ''}" title="Adds ${b.name}">+${b.name}</span>`;
        }).join('');

        html += `
          <li class="list-group-item border-0 d-flex justify-content-between px-3 mb-2 border-radius-lg cursor-pointer flex-column flex-md-row${isMetaSpec ? ' meta-comp' : ''}" onclick="addSuggestedSpec(${specId})">
            <div class="d-flex align-items-center">
              <img src="/data/icons/${specInfo.icon}.jpg" class="avatar avatar-sm me-3 border-radius-sm">
              <div class="d-flex flex-column">
                <a href="/classes/${specInfo.roleName}/${specInfo.specName}_${specInfo.className}" onclick="event.stopPropagation();" class="mb-1 text-sm font-weight-bolder class-${specInfo.cleanClass}-text">${specInfo.name}${isMetaSpec ? META_BADGE : ''}</a>
                <span class="text-xs text-secondary mt-1">
                  Runs: <span class="text-body-emphasis pe-2">${total}</span>
                  Success %: <span class="${winRate >= 70 ? 'text-success' : 'text-warning'} pe-2">${winRate}%</span>
                  Max Key: <span class="text-body-emphasis">${stats.mk}</span>
                </span>
                ${buffGainBadges ? `<span class="buff-gain-row mt-1">${buffGainBadges}</span>` : ''}
              </div>
            </div>
            <div class="mt-3 mt-md-0 w-100 w-md-auto d-flex">
               <button class="btn btn-sm btn-outline-primary mb-0 d-flex align-items-center px-3 py-2 add-spec-btn" onclick="event.stopPropagation(); addSuggestedSpec(${specId})">
                 <i class="material-symbols-rounded text-sm me-1">add</i> 
                 <span>Add Spec</span>
               </button>
            </div>
          </li>
        `;
      });
      html += '</ul></div>';
      suggestionsContainer.innerHTML = html;
    }

    function addSuggestedSpec(specId) {
      if (selected.length >= 5) return;
      selected.push(Number(specId));
      renderSelectedComp();
      writeUrlParams();
      updateSuggestions();
    }

    function clearSelection() {
      selected = [];
      renderSelectedComp();
      writeUrlParams();
      updateSuggestions();
    }

    // --- Top lists rendering (Most Popular & Best High-Key) ---
    const MIN_RUNS_DEFAULT = 20;
    const TOP_N_DEFAULT = 6;

    function getCompRuns(comp, dungeonId) {
      if (dungeonId && dungeonId !== 'all') {
        const d = comp.dungeons && comp.dungeons[dungeonId];
        return d ? (d.runs || (d.t || 0) + (d.d || 0)) : 0;
      }
      return comp.runs || (comp.t || 0) + (comp.d || 0);
    }

    function getCompWeight(comp, dungeonId) {
      if (dungeonId && dungeonId !== 'all') {
        const d = comp.dungeons && comp.dungeons[dungeonId];
        return d ? (d.w || 0) : 0;
      }
      return comp.w || 0;
    }

    function renderCompRow(comp, dungeonId, useTopKey = false) {
      const specImgs = comp.c.map(sid => {
        const si = specLookup[sid] || { icon: 'inv_misc_questionmark', name: 'Unknown' };
        return `<img src="/data/icons/${si.icon}.jpg" class="avatar avatar-sm me-1" title="${si.name}">`;
      }).join('');

      let runs = 0;
      let timed = 0;
      if (useTopKey) {
        if (dungeonId && dungeonId !== 'all' && comp.dungeons && comp.dungeons[dungeonId]) {
          runs = comp.dungeons[dungeonId].top_key_runs || 0;
          timed = comp.dungeons[dungeonId].top_key_timed || 0;
        } else {
          runs = comp.top_key_runs || 0;
          timed = comp.top_key_timed || 0;
        }
      } else {
        runs = getCompRuns(comp, dungeonId);
        if (dungeonId && dungeonId !== 'all' && comp.dungeons && comp.dungeons[dungeonId]) {
          timed = comp.dungeons[dungeonId].t || 0;
        } else {
          timed = comp.t || 0;
        }
      }
      const winRate = runs > 0 ? Math.round((timed || 0) / runs * 100) : 0;
      const mk = comp.mk || 0;
      const meta = isMetaComp(comp.c);

      return `
        <div class="list-group-item border-0 d-flex justify-content-between px-3 mb-2 border-radius-lg align-items-center${meta ? ' meta-comp' : ''}">
          <div class="d-flex align-items-center">
            ${specImgs}
            <div class="ms-3">
              <div class="text-sm font-weight-bolder">${runs} runs${meta ? META_BADGE : ''}</div>
              <div class="text-xs text-secondary">Max: ${mk} &nbsp; Success %: ${winRate}%</div>
            </div>
          </div>
          <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-outline-primary mb-0" onclick='showCompDetails(${JSON.stringify(comp)}, ${useTopKey}, ${JSON.stringify(dungeonId)})'>Details</button>
            ${routesLinkHtml(comp.c)}
          </div>
        </div>
      `;
    }

    // Note: 'Use this comp' functionality removed per UX feedback.

    function showCompDetails(comp, useTopKey = false, contextDungeonId = 'all') {
      const body = document.getElementById('compDetailsBody');
      const titleEl = document.querySelector('#compDetailsModal .modal-title');
      if (!body) { alert('Comp details not available'); return; }

      // Always show the comp's full (overall) picture, with high-key performance
      // called out separately, so numbers are never mislabeled by how it was opened.
      const runs = comp.runs || ((comp.t || 0) + (comp.d || 0));
      const timed = comp.t || 0;
      const successPct = runs > 0 ? Math.round(timed / runs * 100) : 0;
      const mk = comp.mk || 0;
      const avgKey = comp.avg_key != null ? Math.round(comp.avg_key * 10) / 10 : 0;
      const isMeta = isMetaComp(comp.c);
      const successClass = pct => pct >= 80 ? 'text-success' : (pct >= 60 ? 'text-warning' : 'text-danger');

      if (titleEl) titleEl.innerHTML = `Composition Details${isMeta ? META_BADGE : ''}`;

      // header: spec icon + class-coloured name + class
      let specsHtml = '';
      comp.c.forEach(sid => {
        const si = specLookup[sid] || { icon: 'inv_misc_questionmark', name: sid, cleanClass: '', className: '' };
        specsHtml += `
          <div class="d-flex align-items-center me-4 mb-2">
            <img src="/data/icons/${si.icon}.jpg" class="avatar avatar-sm border border-secondary me-2" title="${si.name}">
            <div class="lh-sm">
              <div class="text-sm font-weight-bold class-${si.cleanClass}-text">${si.name}</div>
              <div class="text-xs text-secondary">${si.className || ''}</div>
            </div>
          </div>`;
      });

      // Team-comp table: one column per slot. The header is the main spec (icon left, then
      // name / class / usage% stacked right); the body lists the alternate specs that swap
      // into that slot, with usage %. Attached as comp.__slots by showCompDetailsByC. When
      // present this replaces the separate spec bar above (same info).
      let flexHtml = '';
      if (comp.__slots && comp.__slots.length) {
        const slots = comp.__slots;
        const ALT_CAP = 6;
        const maxRows = Math.max(0, ...slots.map(s => (s.alts || []).length));
        const head = slots.map(s =>
          `<th class="pt-2 pb-2 pe-3" style="min-width:150px">
             <div class="d-flex align-items-center">
               <img src="/data/icons/${s.icon}.jpg" class="me-2" style="width:34px;height:34px;border-radius:6px;box-shadow:0 0 0 2px ${s.color}">
               <div class="lh-sm text-start">
                 <div class="text-xs font-weight-bold" style="color:${s.color}">${s.name}</div>
                 <div class="text-xs text-secondary">${s.class || ''}</div>
                 <div class="text-xs text-secondary">${s.primary_pct}%</div>
               </div>
             </div>
           </th>`).join('');
        const rowN = Math.min(maxRows, ALT_CAP);
        let rows = '';
        for (let r = 0; r < rowN; r++) {
          rows += '<tr>' + slots.map(s => {
            const a = (s.alts || [])[r];
            if (!a) return '<td class="py-1"></td>';
            return `<td class="py-1 pe-3">
              <span class="d-inline-flex align-items-center">
                <img src="/data/icons/${a.icon}.jpg" class="me-1" style="width:20px;height:20px;border-radius:4px;border-bottom:2px solid ${a.color}">
                <span class="text-xs" style="color:${a.color}">${a.name}</span>
                <span class="text-xs text-secondary ms-1">${a.pct}%</span>
              </span></td>`;
          }).join('') + '</tr>';
        }
        if (slots.some(s => (s.alts || []).length > ALT_CAP || s.hidden)) {
          rows += '<tr>' + slots.map(s => {
            const extra = Math.max(0, (s.alts || []).length - ALT_CAP) + (s.hidden || 0);
            return `<td class="text-xs text-secondary py-1">${extra ? '+' + extra + ' more' : ''}</td>`;
          }).join('') + '</tr>';
        }
        flexHtml = `<div class="table-responsive mb-3"><table class="table align-items-center mb-0">
            <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
      }

      const tile = (label, value, valueClass = 'text-body-emphasis') => `
        <div class="col">
          <div class="border border-secondary border-radius-lg p-2 text-center h-100">
            <div class="text-xs text-secondary text-uppercase">${label}</div>
            <div class="h6 mb-0 ${valueClass}">${value}</div>
          </div>
        </div>`;

      let html = '';
      // The team-comp table already shows the specs as its column headers, so only fall
      // back to the standalone spec bar when there's no slot data.
      if (flexHtml) html += flexHtml;
      else html += `<div class="d-flex flex-wrap align-items-center mb-3">${specsHtml}</div>`;

      html += `<div class="row g-2 row-cols-2 row-cols-md-4 mb-3">`;
      html += tile('Total Runs', runs.toLocaleString());
      html += tile('Success', `${successPct}%`, successClass(successPct));
      html += tile('Highest Key', mk ? ('+' + mk) : '–');
      html += tile('Avg Key', avgKey || '–');
      html += `</div>`;

      // most-played dungeon
      const bestDungeonName = comp.bd && dungeonLookup[comp.bd] ? dungeonLookup[comp.bd] : '';
      if (bestDungeonName) {
        const share = runs > 0 ? Math.round((comp.bdr || 0) / runs * 100) : 0;
        html += `<p class="text-sm mb-3"><span class="text-secondary">Most played in</span>
          <strong>${bestDungeonName}</strong>
          <span class="text-secondary">(${comp.bdr || 0} runs, ${share}% of this comp)</span></p>`;
      }

      // per-dungeon breakdown (overall numbers, resolved names, busiest first)
      const dungeonRows = [];
      if (comp.dungeons) {
        Object.entries(comp.dungeons).forEach(([did, dstats]) => {
          const dRuns = dstats.runs || ((dstats.t || 0) + (dstats.d || 0));
          if (dRuns <= 0) return;
          const dTimed = dstats.t || 0;
          dungeonRows.push({
            name: dungeonLookup[did] || ('Dungeon ' + did),
            runs: dRuns,
            success: Math.round(dTimed / dRuns * 100),
            mk: dstats.mk || 0
          });
        });
      }
      dungeonRows.sort((a, b) => b.runs - a.runs);
      if (dungeonRows.length) {
        html += `<h6 class="mb-2">Per-dungeon breakdown</h6>`;
        html += `<div class="table-responsive mb-3"><table class="table table-sm align-items-center mb-0">
          <thead><tr>
            <th class="text-xxs text-uppercase text-secondary">Dungeon</th>
            <th class="text-xxs text-uppercase text-secondary text-end">Runs</th>
            <th class="text-xxs text-uppercase text-secondary text-end">Success</th>
            <th class="text-xxs text-uppercase text-secondary text-end">Highest Key</th>
          </tr></thead><tbody>`;
        dungeonRows.forEach(r => {
          html += `<tr>
            <td class="text-sm">${r.name}</td>
            <td class="text-sm text-end">${r.runs}</td>
            <td class="text-sm text-end ${successClass(r.success)}">${r.success}%</td>
            <td class="text-sm text-end">${r.mk ? '+' + r.mk : '–'}</td>
          </tr>`;
        });
        html += `</tbody></table></div>`;
      }

      // strongest synergies as compact chips
      try {
        if (typeof synergyMatrix !== 'undefined') {
          const pairs = [];
          for (let i = 0; i < comp.c.length; i++) {
            for (let j = i + 1; j < comp.c.length; j++) {
              const a = comp.c[i], b = comp.c[j];
              const val = (synergyMatrix[a] && synergyMatrix[a][b]) ? synergyMatrix[a][b] : 0;
              if (val) pairs.push({ val, a, b });
            }
          }
          pairs.sort((x, y) => y.val - x.val);
          if (pairs.length) {
            html += `<h6 class="mb-1">Strongest synergies</h6>`;
            html += `<p class="text-xs text-secondary mb-2">How much more often a pair is played together than expected (1.0 = as expected).</p>`;
            html += `<div class="d-flex flex-wrap">`;
            pairs.slice(0, 3).forEach(p => {
              const a = specLookup[p.a] || { name: p.a, icon: 'inv_misc_questionmark' };
              const b = specLookup[p.b] || { name: p.b, icon: 'inv_misc_questionmark' };
              const vc = p.val >= 1.1 ? 'text-success' : (p.val >= 0.9 ? 'text-body-emphasis' : 'text-secondary');
              html += `<div class="d-flex align-items-center border border-secondary border-radius-lg px-2 py-1 me-2 mb-2">
                <img src="/data/icons/${a.icon}.jpg" title="${a.name}" style="width:22px;height:22px;border-radius:4px;" class="me-1">
                <img src="/data/icons/${b.icon}.jpg" title="${b.name}" style="width:22px;height:22px;border-radius:4px;" class="me-2">
                <span class="text-sm font-weight-bold ${vc}">${p.val.toFixed(2)}</span>
              </div>`;
            });
            html += `</div>`;
          }
        }
      } catch (e) { /* ignore */ }

      body.innerHTML = html;
      const routesLink = document.getElementById('compRoutesLink');
      if (routesLink) {
        routesLink.href = compRoutesUrl(comp.c);
        // Reset the label in case the shared modal was last used for a spec pair.
        routesLink.innerHTML = '<i class="material-symbols-rounded align-middle me-1">route</i>Find routes for this comp';
      }
      const modalEl = document.getElementById('compDetailsModal');
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      openComp = { specs: comp.c.join(','), topKey: !!useTopKey, dungeon: contextDungeonId };
      modal.show();
      if (window.MythiLink) MythiLink.sync();
    }

    // The comp modal is built in JS from three inputs, so its contents can't be
    // reached by an element id alone, so they ride in the hash as
    // &comp=<specIds>[|top][|<dungeonId>] instead.
    let openComp = null;

    document.getElementById('compDetailsModal').addEventListener('hidden.bs.modal', function () {
      openComp = null;
      if (window.MythiLink) MythiLink.sync();
    });

    if (window.MythiLink) {
      MythiLink.registerState('comp', {
        read: function () {
          if (!openComp) return null;
          const parts = [openComp.specs];
          if (openComp.topKey) parts.push('top');
          if (openComp.dungeon && openComp.dungeon !== 'all') parts.push(openComp.dungeon);
          return parts.join('|');
        },
        apply: function (value) {
          const parts = String(value).split('|');
          const specs = parts[0];
          if (!specs) return;
          const topKey = parts.indexOf('top') > 0;
          const dungeon = parts.slice(1).filter(p => p && p !== 'top')[0] || 'all';
          // Handles compsData not being loaded yet by fetching, then retrying.
          showCompDetailsByC(specs, topKey, dungeon);
        }
      });
    }

    function showCompDetailsByC(cKey, useTopKey = false, contextDungeonId = 'all') {
      const findComp = () => {
        if (Array.isArray(compsData) && compsData.length) {
          return compsData.find(c => Array.isArray(c.c) && c.c.join(',') === cKey);
        }
        return null;
      };

      // If this comp heads a visible archetype family, show the WHOLE family's merged numbers
      // (runs, success, per-dungeon breakdown, …) — the card advertises the family total, so
      // the details must match it, not just the core comp's own runs. The per-slot alternates
      // ride along as __slots. Falls back to the raw comp when it heads no family (e.g. a
      // deep-linked comp, or archetypes not loaded yet).
      const attachSlots = (c) => {
        const arch = (typeof findArchetypeByKey === 'function') ? findArchetypeByKey(cKey) : null;
        if (!arch) { if (c) c.__slots = null; return c; }
        // Everything comes from the family so the modal is internally consistent with the card.
        // In a single-dungeon context arch.dungeons is empty, so the per-dungeon table is simply
        // omitted (the scoped run total already tells the whole story).
        return {
          c: arch.c,
          runs: arch.runs, t: arch.t, d: arch.d,
          mk: arch.mk, avg_key: arch.avg_key,
          dungeons: arch.dungeons || null,
          bd: arch.bd, bdr: arch.bdr,
          members: arch.members,
          __slots: arch.slots,
        };
      };

      const comp = findComp();
      if (comp || findArchetypeByKey(cKey)) {
        showCompDetails(attachSlots(comp), useTopKey, contextDungeonId);
        return;
      }

      // If compsData not yet loaded, fetch and try again
      fetch('/assets/json/comps_index.json')
        .then(r => r.json())
        .then(data => {
          compsData = data;
          const c2 = compsData.find(x => Array.isArray(x.c) && x.c.join(',') === cKey);
          if (c2) showCompDetails(attachSlots(c2), useTopKey, contextDungeonId);
          else alert('Comp details not available');
        })
        .catch(err => {
          console.error(err);
          alert('Comp details not available');
        });
    }

    // --- Best Spec Combinations card ---
    // Server-rendered for the 'all' context on first paint; re-ranked client-side per
    // dungeon from the inline BEST_SPEC_PAIRS map (keyed 'all' / dungeon-id string), the
    // way the archetype cards swap from comp_archetypes.json. Row markup is kept in sync
    // with the Jinja first paint above.
    const UNKNOWN_SPEC = { icon: 'inv_misc_questionmark', name: 'Unknown', specName: 'Unknown', className: 'Unknown', cleanClass: 'Unknown', roleName: 'Dps' };

    function renderBestPairRow(pair) {
      const a = specLookup[pair.spec_a] || UNKNOWN_SPEC;
      const b = specLookup[pair.spec_b] || UNKNOWN_SPEC;
      const successClass = pair.hk_success >= 70 ? 'text-success' : 'text-warning';
      return `
        <div class="list-group-item border-0 d-flex justify-content-between align-items-center px-3 mb-2 border-radius-lg">
          <div class="d-flex align-items-center">
            <img src="/data/icons/${a.icon}.jpg" class="avatar avatar-sm border-radius-sm me-1" title="${a.name} ${a.className}">
            <img src="/data/icons/${b.icon}.jpg" class="avatar avatar-sm border-radius-sm me-3" title="${b.name} ${b.className}">
            <div class="d-flex flex-column">
              <span class="text-sm font-weight-bolder">
                <a href="/classes/${a.roleName}/${a.specName}_${a.className}" class="class-${a.cleanClass}-text">${a.name}</a>
                <span class="text-secondary font-weight-normal mx-1">+</span>
                <a href="/classes/${b.roleName}/${b.specName}_${b.className}" class="class-${b.cleanClass}-text">${b.name}</a>
              </span>
              <span class="text-xs text-secondary mt-1">
                Success: <span class="${successClass} pe-2">${pair.hk_success}%</span>
                Runs: <span class="text-body-emphasis pe-2">${pair.total_runs}</span>
                Max: <span class="text-body-emphasis pe-2">+${pair.max_key}</span>
              </span>
            </div>
          </div>
          <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-outline-primary mb-0" onclick="showPairDetails(${pair.spec_a}, ${pair.spec_b})">Details</button>
            ${routesLinkHtml([pair.spec_a, pair.spec_b])}
          </div>
        </div>`;
    }

    function renderBestPairs() {
      const listEl = document.getElementById('best-pairs-list');
      if (!listEl) return;
      const dungeonId = document.getElementById('dungeonFilter').value || 'all';
      const pairs = BEST_SPEC_PAIRS[dungeonId] || BEST_SPEC_PAIRS['all'] || [];
      const label = dungeonContextLabel();
      const subEl = document.getElementById('best-pairs-sub');
      if (subEl) {
        subEl.textContent = `The strongest pairs of specs to bring together ${label}, ranked by how well they perform in the highest keys.`;
      }
      if (!pairs.length) {
        listEl.innerHTML = `<p class="text-sm text-secondary px-2">Not enough high-key data yet to rank spec combinations ${label}.</p>`;
        return;
      }
      listEl.innerHTML = pairs.map(renderBestPairRow).join('');
    }

    // Pair-focused modal. A pair is not a full 5-man comp, so it can't reuse
    // showCompDetailsByC; it borrows the shared #compDetailsModal, swapping the body for
    // the two specs, the pair's context stats and the top full comps that feature both.
    function showPairDetails(specA, specB) {
      const body = document.getElementById('compDetailsBody');
      const titleEl = document.querySelector('#compDetailsModal .modal-title');
      if (!body) { alert('Pair details not available'); return; }
      const dungeonId = document.getElementById('dungeonFilter').value || 'all';
      const a = specLookup[specA] || { icon: 'inv_misc_questionmark', name: specA, cleanClass: '', className: '' };
      const b = specLookup[specB] || { icon: 'inv_misc_questionmark', name: specB, cleanClass: '', className: '' };
      const successClass = pct => pct >= 80 ? 'text-success' : (pct >= 60 ? 'text-warning' : 'text-danger');

      if (titleEl) titleEl.innerHTML = 'Spec Pair Details';

      // Context stats: reuse the exact numbers this pair shows on the card in the current
      // context, so the modal and the card never disagree.
      const ctxPairs = BEST_SPEC_PAIRS[dungeonId] || BEST_SPEC_PAIRS['all'] || [];
      const lo = Math.min(specA, specB), hi = Math.max(specA, specB);
      const row = ctxPairs.find(p => p.spec_a === lo && p.spec_b === hi) || { hk_success: 0, total_runs: 0, max_key: 0 };

      const tile = (label, value, valueClass = 'text-body-emphasis') => `
        <div class="col">
          <div class="border border-secondary border-radius-lg p-2 text-center h-100">
            <div class="text-xs text-secondary text-uppercase">${label}</div>
            <div class="h6 mb-0 ${valueClass}">${value}</div>
          </div>
        </div>`;

      const specCard = (s) => `
        <div class="d-flex align-items-center me-4 mb-2">
          <img src="/data/icons/${s.icon}.jpg" class="avatar avatar-sm border border-secondary me-2" title="${s.name}">
          <div class="lh-sm">
            <div class="text-sm font-weight-bold class-${s.cleanClass}-text">${s.name}</div>
            <div class="text-xs text-secondary">${s.className || ''}</div>
          </div>
        </div>`;

      const ctxLabel = dungeonContextLabel();
      let html = `<div class="d-flex flex-wrap align-items-center mb-2">${specCard(a)}${specCard(b)}</div>`;
      html += `<p class="text-xs text-secondary mb-2">High-key performance ${ctxLabel}.</p>`;
      html += `<div class="row g-2 row-cols-3 mb-3">`;
      html += tile('Success', `${row.hk_success}%`, successClass(row.hk_success));
      html += tile('Runs', (row.total_runs || 0).toLocaleString());
      html += tile('Highest Key', row.max_key ? ('+' + row.max_key) : '–');
      html += `</div>`;

      // Top full comps featuring this pair, from the loaded compsData, scoped to context.
      const withPair = compsData.filter(c => Array.isArray(c.c) && c.c.includes(specA) && c.c.includes(specB));
      const scoped = (dungeonId !== 'all') ? withPair.filter(c => getCompRuns(c, dungeonId) > 0) : withPair;
      scoped.sort((x, y) => getCompWeight(y, dungeonId) - getCompWeight(x, dungeonId));
      const topComps = scoped.slice(0, 8);

      if (topComps.length) {
        html += `<h6 class="mb-2">Top comps featuring this pair</h6>`;
        html += `<div class="list-group list-group-flush">`;
        topComps.forEach(c => {
          const icons = c.c.map(sid => {
            const si = specLookup[sid] || { icon: 'inv_misc_questionmark', name: 'Unknown' };
            return `<img src="/data/icons/${si.icon}.jpg" class="avatar avatar-sm me-1" title="${si.name}">`;
          }).join('');
          const cRuns = getCompRuns(c, dungeonId);
          let cTimed;
          if (dungeonId !== 'all' && c.dungeons && c.dungeons[dungeonId]) {
            cTimed = c.dungeons[dungeonId].t || 0;
          } else {
            cTimed = c.t || 0;
          }
          const cSuccess = cRuns > 0 ? Math.round(cTimed / cRuns * 100) : 0;
          html += `
            <div class="list-group-item border-0 d-flex justify-content-between align-items-center px-2 mb-1 border-radius-lg">
              <div class="d-flex align-items-center">
                ${icons}
                <div class="ms-2 text-xs text-secondary">${cRuns} runs &middot; ${cSuccess}%</div>
              </div>
              <div class="d-flex align-items-center">
                <button class="btn btn-sm btn-outline-primary mb-0" onclick='showCompDetailsByC(${JSON.stringify(c.c.join(','))}, false, ${JSON.stringify(dungeonId)})'>Details</button>
                ${routesLinkHtml(c.c)}
              </div>
            </div>`;
        });
        html += `</div>`;
      } else {
        html += `<p class="text-sm text-secondary">No individual comps with this pair in the top data ${ctxLabel}.</p>`;
      }

      body.innerHTML = html;
      const routesLink = document.getElementById('compRoutesLink');
      if (routesLink) {
        routesLink.href = compRoutesUrl([specA, specB]);
        routesLink.innerHTML = '<i class="material-symbols-rounded align-middle me-1">route</i>Find routes for this pair';
      }
      // The pair modal is not registered as a MythiLink deep-link state, so make sure the
      // shared comp state does not resurrect a stale comp when the modal is synced.
      openComp = null;
      const modalEl = document.getElementById('compDetailsModal');
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
      if (window.MythiLink) MythiLink.sync();
    }

    // --- Archetype cards (Most Popular / Best High Keys / Hidden Gems) ---
    // Grouping is precomputed per dungeon in comp_archetypes.json (leader radius-1);
    // the client renders the selected dungeon's lists and swaps on change. renderArchetypeRow
    // is kept structurally in sync with the arch_row() Jinja macro used for first paint.
    let archetypesByDungeon = null;
    let currentArchetypes = { popular: [], highkey: [], gems: [] };
    const archetypesLoaded = fetch('/assets/json/comp_archetypes.json')
      .then(r => r.json())
      .then(data => { archetypesByDungeon = data; })
      .catch(err => { console.error('archetypes load failed', err); });

    function archAltPopover(slot) {
      if (!slot.alts || !slot.alts.length) return '';
      let rows = slot.alts.map(a =>
        `<div class="arch-pr"><img src="/data/icons/${a.icon}.jpg" title="${a.name}">` +
        `<span style="color:${a.color}">${a.name}</span><b>${a.pct}%</b></div>`).join('');
      if (slot.hidden) rows += `<div class="arch-pr arch-more-row">+${slot.hidden} rarer (&lt;1%)</div>`;
      return `<div class="arch-pop"><div class="arch-pop-h">Alternatives</div>${rows}</div>`;
    }

    function renderArchetypeRow(arch, mode) {
      const isMeta = isMetaComp(arch.c);
      let statRuns, statLabel, sub, useTop;
      if (mode === 'highkey') {
        statRuns = arch.hk_runs; statLabel = 'high-key runs'; useTop = true;
        sub = `Max: +${arch.hk_max} &nbsp; Success %: ${arch.hk_success}%`;
      } else if (mode === 'gems') {
        statRuns = arch.gem_runs; statLabel = 'high-key runs'; useTop = false;
        sub = `Max: +${arch.gem_max} &nbsp; Success %: ${arch.gem_success}%`;
      } else {
        statRuns = arch.runs; statLabel = 'runs'; useTop = false;
        sub = `Max: +${arch.mk} &nbsp; Success %: ${arch.success}%`;
      }
      const slots = arch.slots.map(slot => {
        const under = slot.top_alt
          ? `<img src="/data/icons/${slot.top_alt.icon}.jpg" class="arch-alt-icon" ` +
            `style="border-bottom:2px solid ${slot.top_alt.color}" title="${slot.top_alt.name} (${slot.top_alt.pct}%)">` +
            (slot.more ? `<span class="arch-more">+${slot.more}</span>` : '')
          : '';
        return `<div class="arch-slot">` +
          `<img src="/data/icons/${slot.icon}.jpg" class="avatar avatar-sm arch-main" style="--arch-ring:${slot.color}" alt="${slot.name}">` +
          `<div class="arch-under">${under}</div>${archAltPopover(slot)}</div>`;
      }).join('');
      const cKey = arch.c.join(',');
      return `
        <div class="list-group-item border-0 d-flex justify-content-between px-3 mb-2 border-radius-lg align-items-center${isMeta ? ' meta-comp' : ''}">
          <div class="d-flex align-items-center">
            <div class="archetype-slots d-flex">${slots}</div>
            <div class="ms-3">
              <div class="text-sm font-weight-bolder">${statRuns} ${statLabel}${isMeta ? META_BADGE : ''}</div>
              <div class="text-xs text-secondary">${sub} &nbsp; &middot; ${arch.members} comps</div>
            </div>
          </div>
          <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-outline-primary mb-0" onclick='showCompDetailsByC(${JSON.stringify(cKey)}, ${useTop}, "all")'>Details</button>
            ${routesLinkHtml(arch.c)}
          </div>
        </div>`;
    }

    function fillArchList(id, list, mode) {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = (list && list.length)
        ? list.map(a => renderArchetypeRow(a, mode)).join('')
        : '<p class="text-sm text-secondary px-2">Nothing to show for this dungeon.</p>';
    }

    // Phrase describing the current dungeon dropdown selection, for card descriptions.
    function dungeonContextLabel() {
      const sel = document.getElementById('dungeonFilter');
      if (!sel || !sel.value || sel.value === 'all') return 'across all dungeons';
      const opt = sel.options[sel.selectedIndex];
      const name = opt ? opt.textContent.trim() : '';
      return name ? `in ${name}` : 'across all dungeons';
    }

    function renderArchetypeLists() {
      if (!archetypesByDungeon) return;
      const dungeonId = document.getElementById('dungeonFilter').value || 'all';
      currentArchetypes = archetypesByDungeon[dungeonId] || archetypesByDungeon['all'] || { popular: [], highkey: [], gems: [] };
      fillArchList('most-popular-list', currentArchetypes.popular, 'popular');
      fillArchList('best-highkey-list', currentArchetypes.highkey, 'highkey');
      fillArchList('hidden-gems-list', currentArchetypes.gems, 'gems');
      // Card descriptions name the key-level band and the current dungeon context.
      const label = dungeonContextLabel();
      const popSub = document.getElementById('most-popular-sub');
      if (popSub) {
        popSub.textContent = `Most-played team comps ${label}.`;
      }
      const hkSub = document.getElementById('best-highkey-sub');
      if (hkSub && currentArchetypes.hk_label) {
        hkSub.textContent = `Team comps performing best in ${currentArchetypes.hk_label} ${label}.`;
      }
      const gemSub = document.getElementById('hidden-gems-sub');
      if (gemSub && currentArchetypes.gem_label) {
        gemSub.textContent = `Niche team comps with strong success in ${currentArchetypes.gem_label} ${label}.`;
      }
    }

    // Find the archetype (in the current dungeon context) whose meta comp matches a
    // spec-id key, so the details modal can show its per-slot alternates.
    function findArchetypeByKey(cKey) {
      for (const bucket of ['popular', 'highkey', 'gems']) {
        const hit = (currentArchetypes[bucket] || []).find(a => a.c.join(',') === cKey);
        if (hit) return hit;
      }
      return null;
    }

    // Apply a dungeon from the URL (?dungeons=<id>) to the selectpicker + native select,
    // since bootstrap-select needs an explicit val() to update its button and menu.
    function applyDungeonFromUrl() {
      const sp = new URLSearchParams(window.location.search);
      const d = sp.get('dungeons') || sp.get('dungeon');
      if (d && dungeonFilter.querySelector(`option[value="${d}"]`)) {
        dungeonFilter.value = d;
        if (window.jQuery && jQuery.fn.selectpicker) jQuery(dungeonFilter).selectpicker('val', d);
      }
    }

    // Render the selected dungeon's archetypes once loaded, and on dungeon change. The
    // best-pairs card rides the same flow (its data is inline, so it does not wait on a
    // fetch, but sharing the URL-applied dungeon keeps the two cards in sync).
    archetypesLoaded.then(() => { applyDungeonFromUrl(); renderArchetypeLists(); renderBestPairs(); });
    dungeonFilter.addEventListener('change', renderArchetypeLists);
    dungeonFilter.addEventListener('change', renderBestPairs);
