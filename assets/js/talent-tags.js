/* Talent tags page (pages/talent-tags, generateTalentTagsPage.py).
 *
 * Public mode: players see the tags behind build names per spec and suggest
 * other tags/impact, then Save shows a JSON to send via GitHub or Discord.
 * Admin mode (localDev/buildTalentTagAdmin.py, never deployed): the same page
 * plus imported suggestions, override review (valid only while the talent's
 * version matches) and gold labels for tagTalents.py --eval, exported as files.
 */
(function () {
  'use strict';

  const ADMIN = window.TALENT_TAGS_ADMIN === true;
  const STORE_KEY = ADMIN ? 'talentTagsAdmin:v1' : 'talentTagSuggestions:v1';
  const KIND = 'mythistone-talent-tag-suggestions';
  const MAX_TAGS = 2;
  const GITHUB_URL_LIMIT = 7000;

  let DATA = null;
  let TAGS = [];
  let state = { edits: {}, decisions: {}, imports: {}, gold: {} };
  let spec = null;

  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, kids = []) => {
    const n = Object.assign(document.createElement(tag), props);
    for (const k of [].concat(kids)) if (k !== null && k !== undefined && k !== false) n.append(k);
    return n;
  };

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (saved) state = Object.assign(state, saved);
    } catch (e) { /* no storage: start fresh */ }
  }

  function persist() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* the draft is a convenience */ }
  }

  // ---------- values ----------

  function goldEntry(sid, specId) {
    const doc = goldDoc(specId);
    const hit = doc && doc.tags.find(([id]) => id === sid);
    return hit ? hit[1] : null;
  }

  function goldDoc(specId) {
    if (!ADMIN) return null;
    for (const f of DATA.gold.files) {
      const doc = f.specs.find((d) => d.spec === specId);
      if (doc) return doc;
    }
    return null;
  }

  function isGold(sid, specId) {
    const g = (state.gold[specId] || {})[sid];
    return g === undefined ? !!goldEntry(sid, specId) : g;
  }

  /** What the spec pages use now: a valid override, else the model's tags. */
  function current(sid) {
    const t = DATA.talents[sid];
    if (t.override) return { tags: t.override.tags, impact: t.override.impact, source: 'override' };
    if (t.model) return { tags: t.model.tags, impact: t.model.impact, source: 'model' };
    return { tags: [], impact: 'minor', source: 'untagged' };
  }

  /** The row's editable value: my edit, else (admin) an override awaiting re-check,
   * else this spec's gold label, else current. */
  function value(sid, specId) {
    if (state.edits[sid]) return state.edits[sid];
    const o = ADMIN && DATA.overrides[sid];
    if (o && o.status === 'stale') return { tags: o.tags, impact: o.impact };
    const g = goldEntry(sid, specId);
    if (g) return { tags: g.tags, impact: g.impact || current(sid).impact };
    const c = current(sid);
    return { tags: c.tags, impact: c.impact };
  }

  const sameTags = (a, b) => a.length === b.length && a.every((t) => b.includes(t));

  function setEdit(sid, v) {
    const c = current(sid);
    if (!ADMIN && sameTags(v.tags, c.tags) && v.impact === c.impact) delete state.edits[sid];
    else state.edits[sid] = { tags: TAGS.filter((t) => v.tags.includes(t)), impact: v.impact };
    persist();
  }

  // ---------- rendering ----------

  function chips(tags, cls) {
    if (!tags.length) return [el('span', { className: 'tg-chip is-empty', textContent: 'no tags' })];
    return tags.map((t) => el('span', { className: 'tg-chip ' + (cls || ''), textContent: DATA.tags[t] ? DATA.tags[t].label : t, title: DATA.tags[t] ? DATA.tags[t].help : '' }));
  }

  function wordDiff(oldText, newText) {
    const a = oldText.split(/\s+/), b = newText.split(/\s+/);
    const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
    for (let i = a.length - 1; i >= 0; i--)
      for (let j = b.length - 1; j >= 0; j--)
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = el('div', { className: 'tg-diff' });
    let i = 0, j = 0;
    const push = (w, cls) => out.append(cls ? el('span', { className: cls, textContent: w }) : w, ' ');
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { push(a[i]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) push(a[i++], 'is-del');
      else push(b[j++], 'is-ins');
    }
    while (i < a.length) push(a[i++], 'is-del');
    while (j < b.length) push(b[j++], 'is-ins');
    return out;
  }

  /** One labelled row of the .tg-facts grid. */
  function fact(label, value) {
    return [el('span', { className: 'tg-fact-label', textContent: label }), el('div', { className: 'tg-fact-value' }, value)];
  }

  /** The tag and impact toggles: filled is the row's value (my pick), ringed is what
   * the spec pages use now, so a change shows as the fill moving off the ring. */
  function editor(sid, specId) {
    const v = value(sid, specId);
    const c = current(sid);
    const isCurrent = (on) => (c.source !== 'untagged' && on ? ' is-current' : '');
    const tagRow = [];
    for (const t of TAGS) {
      const b = el('button', { type: 'button', className: 'tg-tag' + isCurrent(c.tags.includes(t)), textContent: DATA.tags[t].label, title: DATA.tags[t].help });
      b.setAttribute('aria-pressed', v.tags.includes(t));
      b.addEventListener('click', () => {
        const tags = v.tags.includes(t) ? v.tags.filter((x) => x !== t) : v.tags.concat(t);
        setEdit(sid, { tags, impact: v.impact });
        rerender(sid);
      });
      tagRow.push(b);
    }
    if (v.tags.length > MAX_TAGS) tagRow.push(el('span', { className: 'tg-warn', textContent: `Pick at most ${MAX_TAGS} tags.` }));
    const impactRow = [];
    for (const imp of ['major', 'minor']) {
      const b = el('button', { type: 'button', className: 'tg-tag' + isCurrent(c.impact === imp), textContent: imp });
      b.setAttribute('aria-pressed', v.impact === imp);
      b.addEventListener('click', () => { setEdit(sid, { tags: v.tags, impact: imp }); rerender(sid); });
      impactRow.push(b);
    }
    const note = c.source === 'override' ? ' (reviewed)' : c.source === 'untagged' ? ' (not tagged yet)' : '';
    return [...fact(`Tags${note}`, tagRow), ...fact('Impact', impactRow)];
  }

  function mentionList(mentions) {
    return el('details', { className: 'tg-mentions', open: true }, [
      el('summary', { textContent: `Abilities it mentions (${mentions.length})` }),
      ...mentions.map((m) => {
        const img = el('img', { src: m.icon || '/data/icons/inv_misc_questionmark.png', alt: '', width: 20, height: 20, loading: 'lazy' });
        img.onerror = () => { img.onerror = null; img.src = '/data/icons/inv_misc_questionmark.png'; };
        return el('div', { className: 'tg-mention' }, [
          img,
          el('div', {}, [
            el('a', { href: `https://www.wowhead.com/spell=${m.id}`, target: '_blank', rel: 'noopener', className: 'tg-mention-name', textContent: m.name }),
            ' ', el('span', { className: 'tg-mention-desc', textContent: m.desc }),
          ]),
        ]);
      }),
    ]);
  }

  function adminBlocks(sid, specId) {
    const t = DATA.talents[sid];
    const out = [];
    const o = DATA.overrides[sid];
    if (o && o.status === 'stale') {
      out.push(el('div', { className: 'tg-box is-warn' }, [
        el('strong', { textContent: 'Override needs a re-check: ' }), ...chips(o.tags), ` ${o.impact}, reviewed ${o.reviewed_at || '?'} (${o.source || '?'}). Text then vs now:`,
        wordDiff(o.desc || '', t.desc || ''),
      ]));
    } else if (o) {
      out.push(el('div', { className: 'tg-box' }, [el('strong', { textContent: 'Override: ' }), ...chips(o.tags), ` ${o.impact}, ${o.source || ''} ${o.reviewed_at || ''}`]));
    }
    if (t.model && t.override) out.push(el('div', { className: 'tg-sub' }, ['Model said: ', ...chips(t.model.tags), ` ${t.model.impact}`]));
    for (const s of state.imports[sid] || []) {
      const use = el('button', { type: 'button', className: 'btn btn-sm btn-outline-primary mb-0 tg-use', textContent: 'Use' });
      use.addEventListener('click', () => { setEdit(sid, s); rerender(sid); });
      out.push(el('div', { className: 'tg-box is-info' }, [
        el('strong', { textContent: `Suggested (${s.source}): ` }), ...chips(s.tags), ` ${s.impact} `,
        s.version && t.version && s.version !== t.version ? el('span', { className: 'tg-warn', textContent: 'made for older talent text ' }) : null,
        s.note ? el('em', { textContent: `"${s.note}" ` }) : null, use,
      ]));
    }
    const d = state.decisions[sid];
    const actions = el('div', { className: 'tg-admin-actions' });
    const accept = el('button', { type: 'button', className: 'btn btn-sm btn-success mb-0', textContent: o && o.status === 'stale' ? 'Confirm for current text' : 'Accept as override' });
    accept.addEventListener('click', () => {
      const src = ((state.imports[sid] || []).map((s) => s.source).join(', ')) || 'admin';
      state.decisions[sid] = { action: 'accept', source: src };
      if (!state.edits[sid]) state.edits[sid] = value(sid, specId);
      persist(); rerender(sid);
    });
    actions.append(accept);
    if (o) {
      const remove = el('button', { type: 'button', className: 'btn btn-sm btn-outline-danger mb-0', textContent: 'Remove override' });
      remove.addEventListener('click', () => { state.decisions[sid] = { action: 'remove' }; persist(); rerender(sid); });
      actions.append(remove);
    }
    if (state.imports[sid]) {
      const reject = el('button', { type: 'button', className: 'btn btn-sm btn-outline-secondary mb-0', textContent: 'Dismiss suggestions' });
      reject.addEventListener('click', () => { delete state.imports[sid]; persist(); rerender(sid); });
      actions.append(reject);
    }
    if (d) {
      const undo = el('button', { type: 'button', className: 'btn btn-sm btn-link mb-0', textContent: 'Undo' });
      undo.addEventListener('click', () => { delete state.decisions[sid]; persist(); rerender(sid); });
      actions.append(el('span', { className: 'tg-decision', textContent: d.action === 'accept' ? 'Will be saved as override' : 'Override will be removed' }), undo);
    }
    const gold = el('input', { type: 'checkbox', checked: isGold(sid, specId) });
    gold.addEventListener('change', () => {
      (state.gold[specId] = state.gold[specId] || {})[sid] = gold.checked;
      persist(); rerender(sid);
    });
    actions.append(el('label', { className: 'tg-gold' }, [gold, ` gold (${specName(specId)})`]));
    out.push(actions);
    return out;
  }

  function row(sid, specId) {
    const t = DATA.talents[sid];
    const edited = !!state.edits[sid];
    const card = el('article', { className: 'card tg-row' + (edited ? ' is-edited' : '') + (ADMIN && state.decisions[sid] ? ' is-decided' : '') });
    card.dataset.sid = sid;
    card.dataset.spec = specId;
    const img = el('img', { src: `/data/icons/${t.icon}.png`, alt: '', width: 28, height: 28, loading: 'lazy' });
    img.onerror = () => { img.onerror = null; img.src = '/data/icons/inv_misc_questionmark.png'; };
    const head = el('div', { className: 'tg-head' }, [
      img,
      el('a', { href: `https://www.wowhead.com/spell=${sid}`, target: '_blank', rel: 'noopener', className: 'tg-name', textContent: t.name }),
    ]);
    if (ADMIN) head.append(el('span', { className: 'tg-sid', textContent: sid + (t.versionSource === 'computed' ? ' (unversioned)' : '') }));
    if (edited) {
      const reset = el('button', { type: 'button', className: 'btn btn-sm btn-outline-secondary mb-0 tg-reset', textContent: 'Reset' });
      reset.title = ADMIN ? 'Drop my edit of this talent' : 'Drop my suggestion for this talent';
      reset.addEventListener('click', () => { delete state.edits[sid]; persist(); rerender(sid); });
      head.append(reset);
    }
    const desc = (ADMIN && DATA.specDesc[specId] && DATA.specDesc[specId][sid]) || t.desc;
    card.append(head, el('p', { className: 'tg-desc', textContent: desc || 'Description not available yet.' }));
    if (t.mentions && t.mentions.length) card.append(mentionList(t.mentions));
    if (ADMIN) card.append(...adminBlocks(sid, specId));
    card.append(el('div', { className: 'tg-facts' }, editor(sid, specId)));
    return card;
  }

  function rerender(sid) {
    for (const old of document.querySelectorAll(`.tg-row[data-sid="${sid}"]`)) old.replaceWith(row(sid, Number(old.dataset.spec)));
    updateCount();
    refreshTooltips();
  }

  function specName(id) {
    for (const c of DATA.classes) for (const s of c.specs) if (s.id === id) return `${s.name} ${c.name}`;
    return String(id);
  }

  function specOf(sid) {
    for (const [id, ids] of Object.entries(DATA.specs)) if (ids.includes(sid)) return Number(id);
    return spec;
  }

  function visible() {
    const view = $('tg-view').value;
    const global = { changed: () => Object.keys(state.edits).concat(Object.keys(state.decisions)),
      suggested: () => Object.keys(state.imports),
      stale: () => Object.keys(DATA.overrides || {}).filter((sid) => DATA.overrides[sid].status === 'stale'),
      overrides: () => Object.keys(DATA.overrides || {}) }[view];
    let pairs;
    if (global) {
      const ids = [...new Set(global())].filter((sid) => DATA.talents[sid]);
      pairs = ids.map((sid) => [sid, (DATA.specs[spec] || []).includes(sid) ? spec : specOf(sid)]);
    } else {
      pairs = (DATA.specs[spec] || []).map((sid) => [sid, spec]);
      if (view === 'gold') pairs = pairs.filter(([sid]) => isGold(sid, spec));
    }
    const q = $('tg-filter').value.trim().toLowerCase();
    if (q) pairs = pairs.filter(([sid]) => (DATA.talents[sid].name + ' ' + DATA.talents[sid].desc).toLowerCase().includes(q));
    return pairs;
  }

  function render() {
    const list = $('tg-list');
    list.replaceChildren();
    const pairs = visible();
    if (!pairs.length) list.append(el('p', { className: 'text-sm tg-muted', textContent: 'Nothing to show here.' }));
    for (const [sid, specId] of pairs) list.append(row(sid, specId));
    updateCount();
    refreshTooltips();
  }

  function refreshTooltips() {
    try { if (window.$WowheadPower && window.$WowheadPower.refreshLinks) window.$WowheadPower.refreshLinks(); } catch (e) { /* tooltips are optional */ }
  }

  function updateCount() {
    const n = Object.keys(state.edits).length;
    $('tg-count').textContent = ADMIN
      ? `${Object.keys(state.decisions).length} override decisions, ${Object.keys(state.imports).length} talents with suggestions`
      : n ? `${n} suggestion${n === 1 ? '' : 's'}` : '';
  }

  // ---------- spec picker ----------

  function refreshPicker(sel) {
    if (window.jQuery && window.jQuery.fn.selectpicker) window.jQuery(sel).selectpicker('refresh');
  }

  function initSpecPicker() {
    const sel = $('tg-spec');
    for (const c of DATA.classes) {
      const group = el('optgroup', { label: c.name });
      for (const s of c.specs) group.append(el('option', { value: s.id, textContent: `${s.name} ${c.name}` }));
      sel.append(group);
    }
    const wanted = Number(new URLSearchParams(location.search).get('spec'));
    spec = DATA.specs[wanted] ? wanted : Number(sel.options[0].value);
    sel.value = spec;
    refreshPicker(sel);
    sel.addEventListener('change', () => {
      spec = Number(sel.value);
      const url = new URL(location.href);
      url.searchParams.set('spec', spec);
      history.replaceState(null, '', url);
      render();
    });
  }

  // ---------- public save ----------

  function suggestionJson() {
    const suggestions = {};
    for (const [sid, v] of Object.entries(state.edits)) {
      const t = DATA.talents[sid];
      if (!t) continue;
      const c = current(sid);
      suggestions[sid] = { name: t.name, version: t.version || null, tags: v.tags, impact: v.impact, was: { tags: c.tags, impact: c.impact } };
    }
    const note = $('tg-note') ? $('tg-note').value.trim() : '';
    // one suggestion per line: readable, and short enough to fit a prefilled GitHub link
    const lines = Object.entries(suggestions).map(([sid, s]) => `  ${q(sid)}: ${q(s)}`);
    return `{"kind": ${q(KIND)}, "v": 1,${note ? ` "note": ${q(note)},` : ''}\n "suggestions": {\n${lines.join(',\n')}\n }}`;
  }

  function showModal(title, help, json) {
    $('tg-modal-title').textContent = title;
    $('tg-modal-help').textContent = help;
    $('tg-modal-json').value = json;
    $('tg-copied').textContent = '';
    window.bootstrap.Modal.getOrCreateInstance($('tg-modal')).show();
  }

  async function copy() {
    const ta = $('tg-modal-json');
    try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand('copy'); }
    $('tg-copied').textContent = 'Copied';
  }

  function githubUrl(json) {
    const title = `Talent tag suggestions (${Object.keys(JSON.parse(json).suggestions).length})`;
    const intro = 'Suggested from the MythiStone talent tags page.\n\n';
    const full = `${DATA.github}?title=${encodeURIComponent(title)}&body=${encodeURIComponent(intro + '```json\n' + json + '\n```')}`;
    if (full.length <= GITHUB_URL_LIMIT) return { url: full, needsPaste: false };
    const body = intro + 'The suggestions were too long for the link. They are on your clipboard: paste them between the lines below.\n\n```json\n\n```';
    return { url: `${DATA.github}?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`, needsPaste: true };
  }

  function initPublicSave() {
    const refresh = () => {
      const json = suggestionJson();
      $('tg-modal-json').value = json;
      $('tg-github').href = githubUrl(json).url;
    };
    $('tg-save').addEventListener('click', () => {
      if (!Object.keys(state.edits).length) {
        $('tg-count').textContent = 'Change some tags first, then Save.';
        return;
      }
      showModal('Send your suggestions', 'Thanks! Copy this and send it to us, either as a GitHub issue (opens prefilled) or in our Discord. We review every suggestion before it changes a build name.', '');
      refresh();
    });
    $('tg-note').addEventListener('input', refresh);
    $('tg-discord').href = DATA.discord;
    $('tg-discord').addEventListener('click', copy);
    $('tg-github').addEventListener('click', () => { if (githubUrl($('tg-modal-json').value).needsPaste) copy(); });
  }

  // ---------- admin import and export ----------

  /** Every top-level {...} in pasted text, so several suggestion files can be pasted at once. */
  function jsonObjects(text) {
    const out = [];
    let depth = 0, start = -1, inStr = false, esc = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inStr) {
        if (esc) esc = false;
        else if (ch === '\\') esc = true;
        else if (ch === '"') inStr = false;
        continue;
      }
      if (ch === '"') inStr = true;
      else if (ch === '{') { if (depth++ === 0) start = i; }
      else if (ch === '}' && depth > 0 && --depth === 0) out.push(text.slice(start, i + 1));
    }
    return out;
  }

  function importSuggestions() {
    const source = $('tg-import-source').value.trim() || 'import';
    let added = 0, skipped = 0, files = 0;
    for (const raw of jsonObjects($('tg-import-json').value)) {
      let doc;
      try { doc = JSON.parse(raw); } catch (e) { continue; }
      if (!doc || doc.kind !== KIND || !doc.suggestions) continue;
      files++;
      for (const [sid, s] of Object.entries(doc.suggestions)) {
        if (!DATA.talents[sid] || !Array.isArray(s.tags)) { skipped++; continue; }
        const tags = TAGS.filter((t) => s.tags.includes(t));
        const impact = s.impact === 'minor' ? 'minor' : 'major';
        (state.imports[sid] = state.imports[sid] || []).push({ tags, impact, version: s.version || null, was: s.was || null, source, note: doc.note || '' });
        added++;
      }
    }
    persist();
    $('tg-import-msg').textContent = files ? `${added} suggestions from ${files} file(s) imported${skipped ? `, ${skipped} unknown talents skipped` : ''}.` : 'No suggestion JSON found.';
    if (files) { $('tg-import-json').value = ''; $('tg-view').value = 'suggested'; refreshPicker($('tg-view')); render(); }
    updateImportCount();
  }

  function updateImportCount() {
    const n = Object.keys(state.imports).length;
    $('tg-import-count').textContent = n ? `(${n} talents with suggestions)` : '';
  }

  const q = JSON.stringify;

  function overridesJson() {
    const today = new Date().toISOString().slice(0, 10);
    const out = {};
    for (const [sid, o] of Object.entries(DATA.overrides)) {
      const { status, ...kept } = o;
      out[sid] = kept;
    }
    for (const [sid, d] of Object.entries(state.decisions)) {
      const t = DATA.talents[sid];
      if (d.action === 'remove') { delete out[sid]; continue; }
      const v = value(sid, specOf(sid));
      out[sid] = { name: t.name, tags: v.tags, impact: v.impact, version: t.version, desc: t.desc, source: d.source, reviewed_at: today };
    }
    // numeric keys keep ascending order in a JS object, the order the file uses
    const lines = Object.entries(out).map(([sid, o]) => ` ${q(sid)}: {"name": ${q(o.name)}, "tags": [${o.tags.map((t) => q(t)).join(', ')}], "impact": ${q(o.impact)}, "version": ${q(o.version)}, "source": ${q(o.source || '')}, "reviewed_at": ${q(o.reviewed_at || '')},\n  "desc": ${q(o.desc || '')}}`);
    return lines.length ? `{\n${lines.join(',\n')}\n}\n` : '{}\n';
  }

  // same layout as the checked-in gold files: one talent per line; doc.tags is [id, entry] pairs
  function specJson(doc) {
    const lines = doc.tags.map(([id, g]) =>
      `  ${q(id)}: {"name": ${q(g.name)}, "tags": [${g.tags.map((t) => q(t)).join(', ')}]${g.impact ? `, "impact": ${q(g.impact)}` : ''}}`);
    return `{\n "_about": ${q(doc._about)},\n "spec": ${doc.spec},\n "tags": {\n${lines.join(',\n')}\n }\n}`;
  }

  /** A spec's gold doc with this session's checks and edits applied, file order kept. */
  function goldSpecDoc(specId, existing) {
    const ids = (existing ? existing.tags.map(([id]) => id) : []);
    for (const sid of DATA.specs[specId] || []) if (isGold(sid, specId) && !ids.includes(sid)) ids.push(sid);
    const tags = [];
    for (const sid of ids) {
      if (!isGold(sid, specId)) continue;
      const old = goldEntry(sid, specId);
      const e = state.edits[sid];
      const entry = { name: (old && old.name) || DATA.talents[sid].name, tags: e ? e.tags : old ? old.tags : value(sid, specId).tags };
      const impact = e ? e.impact : old ? old.impact : value(sid, specId).impact;
      if (impact) entry.impact = impact;
      tags.push([sid, entry]);
    }
    return { _about: existing ? existing._about : DATA.gold.about.replace('{spec}', specName(specId)).replace('{id}', specId), spec: specId, tags };
  }

  function goldJson() {
    const touched = Object.keys(state.gold).map(Number).filter((s) => Object.values(state.gold[s]).some(Boolean));
    let file = DATA.gold.files.find((f) => f.specs.some((d) => d.spec === spec)) || DATA.gold.files.find((f) => f.isList);
    if (!file) {
      return { path: DATA.gold.newPath.replace('{id}', spec), json: specJson(goldSpecDoc(spec, null)) + '\n' };
    }
    const specs = file.specs.map((d) => goldSpecDoc(d.spec, d));
    if (file.isList) {
      for (const s of touched.concat(spec)) {
        if (!specs.some((d) => d.spec === s) && !DATA.gold.files.some((f) => f !== file && f.specs.some((d) => d.spec === s))) {
          const doc = goldSpecDoc(s, null);
          if (doc.tags.length) specs.push(doc);
        }
      }
      return { path: file.path, json: '[' + specs.map(specJson).join(',\n') + ']\n' };
    }
    return { path: file.path, json: specJson(specs[0]) + '\n' };
  }

  function initAdmin() {
    $('tg-import').addEventListener('click', importSuggestions);
    $('tg-export-overrides').addEventListener('click', () =>
      showModal('talent_tag_overrides.json', `Paste over ${DATA.overridesPath}. Accepted rows carry the current talent version and text, removed ones are gone, stale ones stay until confirmed or removed.`, overridesJson()));
    $('tg-export-gold').addEventListener('click', () => {
      const g = goldJson();
      showModal('Gold labels', `Paste over ${g.path}.`, g.json);
    });
    updateImportCount();
  }

  // ---------- boot ----------

  async function boot() {
    load();
    try {
      const resp = await fetch(window.TALENT_TAGS_DATA_URL);
      if (!resp.ok) throw new Error(resp.status);
      DATA = await resp.json();
    } catch (e) {
      $('tg-list').replaceChildren(el('p', { className: 'text-sm tg-warn', textContent: 'Could not load the talent tags. Please reload the page.' }));
      throw e;
    }
    TAGS = Object.keys(DATA.tags);
    DATA.specDesc = DATA.specDesc || {};
    initSpecPicker();
    $('tg-filter').addEventListener('input', render);
    $('tg-view').addEventListener('change', render);
    $('tg-copy').addEventListener('click', copy);
    $('tg-clear').addEventListener('click', () => {
      if (!confirm(ADMIN ? 'Forget all edits, decisions, imports and gold changes in this browser?' : 'Remove all your suggestions?')) return;
      state = { edits: {}, decisions: {}, imports: {}, gold: {} };
      persist();
      if (ADMIN) updateImportCount();
      render();
    });
    if (ADMIN) initAdmin(); else initPublicSave();
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
