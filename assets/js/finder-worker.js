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

function addToIndex(indexMap, key, id) {
  if (!indexMap.has(key)) indexMap.set(key, new Set());
  indexMap.get(key).add(id);
}

function asValues(v) {
  if (v === null || v === undefined || v === "") return [];
  return Array.isArray(v) ? v : [v];
}

function buildIndexes(items, indexFields) {
  meta.clear();
  allIds.clear();
  indexes.clear();
  for (const field of indexFields) indexes.set(field, new Map());

  for (const [id, item] of Object.entries(items)) {
    if (!item) continue;
    meta.set(id, item);
    allIds.add(id);
    for (const field of indexFields) {
      const idx = indexes.get(field);
      for (const val of asValues(item[field])) addToIndex(idx, String(val), id);
    }
  }
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
  // over-specific comp can be relaxed to its largest matching subset.
  const relaxValues = relaxClause ? relaxClause.values.map(String) : [];
  let relaxSets = [];
  let relaxMissing = false;
  for (const v of relaxValues) {
    const idx = indexes.get(relaxClause.field);
    if (idx && idx.has(v)) relaxSets.push(idx.get(v));
    else {
      relaxMissing = true;
      break;
    }
  }

  let matchesSet = relaxMissing
    ? new Set()
    : matchesFor(
        candidateSets.concat(
          relaxSets.length ? [intersectSets(relaxSets.slice())] : []
        )
      );

  let relaxHint = null;
  if (relaxClause && matchesSet.size === 0 && relaxValues.length > 1) {
    const idx = indexes.get(relaxClause.field);
    const known = new Set(relaxValues.filter((v) => idx.has(v)));
    const priority = (relaxClause.priority || []).map(String);
    const ordered = priority.length
      ? priority.filter((v) => known.has(v))
      : relaxValues.filter((v) => known.has(v));
    const maxK =
      ordered.length < relaxValues.length ? ordered.length : ordered.length - 1;
    for (let k = maxK; k >= 1 && !relaxHint; --k) {
      const subset = ordered.slice(0, k);
      const sets = subset.map((v) => idx.get(v));
      const hits = matchesFor(candidateSets.concat([intersectSets(sets)]));
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
