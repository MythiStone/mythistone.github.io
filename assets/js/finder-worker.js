// Generic search worker shared by the Route Finder and VOD Finder pages.
//
// It builds inverted indexes over whatever fields a page declares, then answers
// queries as set operations. Each query is a list of filter CLAUSES, one per
// active filter, each with a mode:
//   anyOf   - item matches if it has ANY of the selected values (union), and the
//             clause as a whole is AND-ed with the other clauses (intersect).
//             Used by dungeon / spells / npcInclude / video type / POV spec.
//   allRelax- item must have ALL selected values (intersect), with the spec-style
//             "largest matching subset" relaxation + relaxHint. Used by team comp.
//   noneOf  - item must have NONE of the selected values (subtract). Used by NPC
//             exclude.
// Item ids are opaque strings (route_key for routes, route_key+video for vods).
//
// This replaces the old comp-routes-worker.js; the route semantics are preserved
// exactly (dungeon/spells/npcInclude are unions AND-ed together, comp specs relax,
// npcExclude subtracts).

let meta = new Map(); // id -> item object
let allIds = new Set(); // every item id
let indexes = new Map(); // field -> Map(value(string) -> Set(id))
// Per-item occurrence counts, so allRelax can require a value more than once
// (a group can run the same spec twice). anyOf/noneOf stay Set-based on `indexes`.
let countIndexes = new Map(); // field -> Map(value(string) -> Map(id -> count))

function addToIndex(indexMap, key, id) {
  if (!indexMap.has(key)) indexMap.set(key, new Set());
  indexMap.get(key).add(id);
}

function addToCount(countMap, key, id) {
  let m = countMap.get(key);
  if (!m) {
    m = new Map();
    countMap.set(key, m);
  }
  m.set(id, (m.get(id) || 0) + 1);
}

function asValues(v) {
  if (v === null || v === undefined || v === "") return [];
  return Array.isArray(v) ? v : [v];
}

function buildIndexes(items, indexFields) {
  meta.clear();
  allIds.clear();
  indexes.clear();
  countIndexes.clear();
  for (const field of indexFields) {
    indexes.set(field, new Map());
    countIndexes.set(field, new Map());
  }

  for (const [id, item] of Object.entries(items)) {
    if (!item) continue;
    meta.set(id, item);
    allIds.add(id);
    for (const field of indexFields) {
      const idx = indexes.get(field);
      const cidx = countIndexes.get(field);
      for (const val of asValues(item[field])) {
        const key = String(val);
        addToIndex(idx, key, id);
        addToCount(cidx, key, id);
      }
    }
  }
}

// Set of ids whose count for (field, value) is >= n. For n <= 1 this is plain
// membership, so reuse the Set index directly.
function idsWithAtLeast(field, value, n) {
  const key = String(value);
  if (n <= 1) {
    const idx = indexes.get(field);
    return idx ? idx.get(key) || null : null;
  }
  const cidx = countIndexes.get(field);
  const m = cidx ? cidx.get(key) : null;
  if (!m) return null;
  const out = new Set();
  for (const [id, c] of m) if (c >= n) out.add(id);
  return out.size ? out : null;
}

// Candidate Sets for a multiset of relax values (duplicates = required count).
// Returns null if any (value, count) has no items, marking the comp unmatchable
// so the caller can relax it.
function relaxCandidateSets(field, values) {
  const required = new Map();
  for (const v of values) {
    const k = String(v);
    required.set(k, (required.get(k) || 0) + 1);
  }
  const sets = [];
  for (const [v, n] of required) {
    const s = idsWithAtLeast(field, v, n);
    if (!s || s.size === 0) return null;
    sets.push(s);
  }
  return sets;
}

function intersectSets(sets) {
  if (!sets || sets.length === 0) return new Set(allIds);
  sets.sort((a, b) => a.size - b.size);
  let out = new Set(sets[0]);
  for (let i = 1; i < sets.length; ++i) {
    const s = sets[i];
    for (const v of out) if (!s.has(v)) out.delete(v);
    if (out.size === 0) break;
  }
  return out;
}

function unionSets(sets) {
  const out = new Set();
  for (const s of sets) for (const v of s) out.add(v);
  return out;
}

// Sets for each selected value of a field (skips values with no index entry).
function setsForValues(field, values) {
  const idx = indexes.get(field);
  const out = [];
  if (!idx) return out;
  for (const v of values) {
    if (idx.has(String(v))) out.push(idx.get(String(v)));
  }
  return out;
}

function compareBy(sort) {
  return (a, b) => {
    for (const { key, dir = "desc" } of sort) {
      const av = a[key] || 0;
      const bv = b[key] || 0;
      if (av !== bv) return dir === "asc" ? av - bv : bv - av;
    }
    return 0;
  };
}

self.onmessage = (ev) => {
  const msg = ev.data;
  if (!msg || !msg.cmd) return;

  if (msg.cmd === "build") {
    try {
      const { items = {}, indexFields = [] } = msg.payload || {};
      buildIndexes(items, indexFields);
      self.postMessage({ cmd: "built", total: allIds.size });
    } catch (e) {
      self.postMessage({ cmd: "error", payload: String(e) });
    }
    return;
  }

  if (msg.cmd !== "query") return;

  const {
    clauses = [],
    sort = [],
    page = 1,
    pageSize = 50,
  } = msg.payload || {};

  const empty = () =>
    self.postMessage({ cmd: "result", total: 0, page, pageSize, results: [] });

  // anyOf clauses become the AND-ed candidate sets. An anyOf clause whose values
  // are all unknown to the index matches nothing (same early-out as before).
  const candidateSets = [];
  const excludeClauses = [];
  let relaxClause = null;

  for (const c of clauses) {
    const values = (c.values || []).map(String);
    if (!values.length) continue;
    if (c.mode === "noneOf") {
      excludeClauses.push(c);
    } else if (c.mode === "allRelax") {
      relaxClause = c;
    } else {
      // anyOf
      const sets = setsForValues(c.field, values);
      if (sets.length === 0) return empty();
      candidateSets.push(unionSets(sets));
    }
  }

  function applyExcludes(out) {
    for (const c of excludeClauses) {
      const idx = indexes.get(c.field);
      if (!idx) continue;
      for (const ex of c.values) {
        const s = idx.get(String(ex));
        if (!s) continue;
        for (const id of s) out.delete(id);
      }
    }
    return out;
  }

  function matchesFor(sets) {
    const out =
      sets.length > 0 ? intersectSets(sets.slice()) : new Set(allIds);
    return applyExcludes(out);
  }

  // The relax (team-comp) filter is intersected in, but kept separate so an
  // over-specific comp can be relaxed to its largest matching subset. Its values
  // are a multiset: a repeated spec requires that many copies on the run.
  const relaxValues = relaxClause ? relaxClause.values.map(String) : [];
  const relaxSets = relaxValues.length
    ? relaxCandidateSets(relaxClause.field, relaxValues)
    : [];

  let matchesSet =
    relaxSets === null
      ? new Set()
      : matchesFor(candidateSets.concat(relaxSets));

  let relaxHint = null;
  if (relaxClause && matchesSet.size === 0 && relaxValues.length > 1) {
    const cidx = countIndexes.get(relaxClause.field);
    const known = (v) => cidx && cidx.has(v);
    const priority = (relaxClause.priority || []).map(String);
    const ordered = (priority.length ? priority : relaxValues).filter(known);
    const maxK =
      ordered.length < relaxValues.length ? ordered.length : ordered.length - 1;
    for (let k = maxK; k >= 1 && !relaxHint; --k) {
      const subset = ordered.slice(0, k);
      const sets = relaxCandidateSets(relaxClause.field, subset);
      if (sets === null) continue;
      const hits = matchesFor(candidateSets.concat(sets));
      if (hits.size > 0) relaxHint = { values: subset, total: hits.size };
    }
  }

  const matched = Array.from(matchesSet)
    .map((id) => meta.get(id))
    .filter(Boolean);
  if (sort.length) matched.sort(compareBy(sort));

  const total = matched.length;
  const start = (page - 1) * pageSize;
  const results = matched.slice(start, start + pageSize);
  self.postMessage({ cmd: "result", total, page, pageSize, results, relaxHint });
};
