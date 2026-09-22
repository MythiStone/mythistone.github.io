// Route Finder page: filter config + client-side row renderer for the shared
// MythiFinder engine (assets/js/finder.js + finder-worker.js). Replaces the old
// bespoke route-search.js; behavior (filters, relaxation, infinite scroll) is
// unchanged, it just runs on the shared engine now.
(function () {
  "use strict";

  function safeId(str) {
    return String(str).replace(/[^A-Za-z0-9_-]/g, "_");
  }

  function specLabel(id) {
    const opt = document.querySelector(`#specSelect option[value="${id}"]`);
    const text = opt ? opt.textContent.trim() : "";
    return text || String(id);
  }

  // KEEP IN SYNC with rt.route_accordion_item in templates/_route_macros.html.
  function renderRouteItem(r) {
    const dungeon = (window.dungeons || {})[r.dungeon] || {};
    const slug = dungeon.slug || r.dungeon;
    const runKey = safeId(`${slug}-${r.route_key}-${r.run_id}`);
    const englishName = (dungeon.name && dungeon.name.en_US) || slug;
    const bgIcon = dungeon.icon || slug + ".jpg";
    const runUrl = `https://raider.io/mythic-plus-runs/${window.current_season}/${r.run_id}`;
    const embedSrc = `https://keystone.guru/route/${slug}/${r.route_key}/${slug}/embed`;

    // One modern pill style shared by every header badge (mirror of `badge_cls` in the macro).
    const BADGE = "rt-pill";

    let specIcons = "";
    ["0", "1", "2"].forEach((role) => {
      (r.specs || []).forEach((sid) => {
        const spec = (window.spec_data || {})[sid];
        if (spec && String(spec.role) === role) {
          specIcons += `<img src="/data/icons/${spec.SpellIconFileId}.jpg" alt="${spec.name || ""}" title="${spec.name || ""}" class="img-fluid" style="width:24px;height:24px;object-fit:cover;border-radius:4px;">`;
        }
      });
    });

    const keyBadge = r.upgrade_text
      ? `<span class="${BADGE} ${r.upgrade_css || "text-success"}">${r.upgrade_text}</span>`
      : `<span class="${BADGE} text-success">+${r.level}</span>`;

    const usageBadge =
      r.usage_count && r.usage_count > 1
        ? `<span class="${BADGE} text-white" data-bs-toggle="tooltip" title="Route usage count">${r.usage_count} Uses</span>`
        : "";

    // "VOD available" header badge with unique POV spec icon(s).
    const videos = r.videos || [];
    let vodBadge = "";
    if (videos.length) {
      const seen = new Set();
      let icons = "";
      videos.forEach((v) => {
        const sp = (window.spec_data || {})[String(v.pov_spec)];
        if (sp && !seen.has(String(v.pov_spec))) {
          seen.add(String(v.pov_spec));
          icons += `<img src="/data/icons/${sp.SpellIconFileId}.jpg" alt="${sp.name || ""}" title="${sp.name || ""} POV" style="width:16px;height:16px;object-fit:cover;border-radius:3px;">`;
        }
      });
      vodBadge = `<span class="${BADGE} text-white" data-bs-toggle="tooltip" title="VOD available"><i class="material-symbols-rounded text-primary" style="font-size:16px;line-height:1;">smart_display</i>${icons}</span>`;
    }

    // "View VOD" buttons linking out to Twitch/YouTube (watch_url precomputed in compRoutes.json).
    let vodButtons = "";
    videos.forEach((v) => {
      if (!v.watch_url) return;
      const sp = (window.spec_data || {})[String(v.pov_spec)];
      const icon = sp
        ? `<img src="/data/icons/${sp.SpellIconFileId}.jpg" alt="${sp.name || ""}" style="width:18px;height:18px;object-fit:cover;border-radius:4px;">`
        : "";
      const plat = v.video_type === "twitch" ? " (Twitch)" : v.video_type === "youtube" ? " (YouTube)" : "";
      const title = (v.pov_character_name ? v.pov_character_name + " POV on " : "") + (v.video_type ? v.video_type.charAt(0).toUpperCase() + v.video_type.slice(1) : "");
      vodButtons += `<a href="${v.watch_url}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary mb-0 d-inline-flex align-items-center gap-2" title="${title}">${icon}<span>View VOD${plat}</span><i class="material-symbols-rounded text-sm">open_in_new</i></a>`;
    });

    const item = document.createElement("div");
    item.className = "accordion-item mb-2";
    item.innerHTML = `
  <h2 class="accordion-header" id="heading-${runKey}">
    <button class="accordion-button collapsed p-0" type="button" data-bs-toggle="collapse"
      data-bs-target="#collapse-${runKey}" aria-expanded="false" aria-controls="collapse-${runKey}"
      style="background-image: url('/data/icons/${bgIcon}'); background-size: cover; background-position: center; background-repeat: no-repeat; background-blend-mode: overlay;">
      <div class="w-100 row gx-2 gy-2 align-items-center py-3 px-4">
        <div class="col-12 col-lg-5">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start">
            <span class="${BADGE} text-white">${englishName}</span>
            ${keyBadge}
            ${usageBadge}
            ${vodBadge}
          </div>
        </div>
        <div class="col-12 col-lg-4">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start justify-content-lg-center">
            <span class="${BADGE} text-white">${formatDuration(r.duration)}</span>
            <span class="timestamp ${BADGE} text-white" data-bs-toggle="tooltip" data-bs-placement="top" data-timestamp="${r.timestamp}"></span>
          </div>
        </div>
        <div class="col-12 col-lg-3">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start justify-content-lg-end">${specIcons}</div>
        </div>
      </div>
    </button>
  </h2>
  <div id="collapse-${runKey}" data-share-id="${safeId(`route-${slug}-${r.route_key}`)}"
    class="accordion-collapse collapse" aria-labelledby="heading-${runKey}" data-bs-parent="#routeDungeonAccordion">
    <div class="accordion-body p-0">
      <div class="route-run-details">
        <div class="route-run-head px-3 pt-2 pb-2 d-flex flex-wrap align-items-center gap-2">
          <a href="${runUrl}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary mb-0 d-inline-flex align-items-center gap-2">
            <img src="/assets/img/logos/RaiderIOLogo.png" alt="" width="18" height="18" class="rounded">
            <span>View full run details on Raider.io</span>
            <i class="material-symbols-rounded text-sm">open_in_new</i>
          </a>
          ${vodButtons}
        </div>
        <div class="iframe-container position-relative">
          <div class="iframe-spinner position-absolute top-50 start-50 translate-middle d-none">
            <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
          </div>
          <iframe loading="lazy" data-name="keystoneGuru" data-src="${embedSrc}" class="w-100 route-embed" style="border:none;width:100%;height:calc(80vh - 3rem);display:block;"></iframe>
        </div>
      </div>
    </div>
  </div>`;
    return item;
  }

  const lustIds = (window.bloodlust_spell_ids || []).map(Number);
  function expandLust(values) {
    return values
      .flatMap((s) => (s === "lust" ? lustIds : Number(s)))
      .filter((n) => !Number.isNaN(n))
      .map(String);
  }

  window.MythiFinder.create({
    formId: "compForm",
    accordionId: "routeDungeonAccordion",
    sentinelId: "route-sentinel",
    overlayId: "route-search-overlay",
    jsonUrl: "/assets/json/compRoutes.json",
    indexFields: ["dungeon", "specs", "spells", "npcs"],
    sort: [
      { key: "usage_count", dir: "desc" },
      { key: "level", dir: "desc" },
      { key: "duration", dir: "asc" },
      { key: "timestamp", dir: "desc" },
    ],
    noun: "route",
    relaxFilterId: "specSelect",
    filters: [
      { id: "dungeonSelect", param: "dungeons", field: "dungeon", mode: "anyOf" },
      { id: "specSelect", param: "specs", field: "specs", mode: "allRelax", priorityByRole: true, multiset: true, max: 5, label: specLabel },
      { id: "spellSelect", param: "spells", field: "spells", mode: "anyOf", expand: expandLust },
      { id: "npcIncludeSelect", param: "npcInclude", field: "npcs", mode: "anyOf" },
      { id: "npcExcludeSelect", param: "npcExclude", field: "npcs", mode: "noneOf" },
    ],
    renderItem: renderRouteItem,
  });
})();
