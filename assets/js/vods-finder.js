// VOD Finder page: filter config + client-side row renderer for the shared
// MythiFinder engine (assets/js/finder.js + finder-worker.js).
(function () {
  "use strict";

  function safeId(str) {
    return String(str).replace(/[^A-Za-z0-9_-]/g, "_");
  }

  // Label a spec by its select option, falling back to the id. Works for both the
  // team-comp and POV spec pickers.
  function specLabel(id) {
    const opt =
      document.querySelector(`#specSelect option[value="${id}"]`) ||
      document.querySelector(`#povSpecSelect option[value="${id}"]`);
    const text = opt ? opt.textContent.trim() : "";
    return text || String(id);
  }

  // Mirror of commonUtils.build_vod_embed_src (KEEP IN SYNC). youtube -> privacy
  // embed; twitch -> player.twitch.tv with the required parent domains + XhYmZs time.
  const VOD_EMBED_PARENTS = ["mythistone.com", "localhost", "127.0.0.1"];
  function buildVodEmbedSrc(videoRef, videoType, startSeconds) {
    const ref = String(videoRef);
    const start = Number(startSeconds);
    if (videoType === "youtube") {
      let src = `https://www.youtube-nocookie.com/embed/${ref}?rel=0`;
      if (start) src += `&start=${start}`;
      return src;
    }
    if (videoType === "twitch") {
      const parents = VOD_EMBED_PARENTS.map((p) => `&parent=${p}`).join("");
      let src = `https://player.twitch.tv/?video=${ref}${parents}&autoplay=false`;
      if (start) {
        const h = Math.floor(start / 3600);
        const m = Math.floor((start % 3600) / 60);
        const s = start % 60;
        src += `&time=${h}h${m}m${s}s`;
      }
      return src;
    }
    return "";
  }

  // KEEP IN SYNC with vod_accordion_item in templates/_vod_macros.html. Same
  // markup, but the accordion parent is this page's #vodFinderAccordion.
  function renderVodItem(v) {
    const dungeon = (window.dungeons || {})[v.dungeon] || {};
    const slug = dungeon.slug || v.dungeon;
    const englishName = (dungeon.name && dungeon.name.en_US) || slug;
    const bgIcon = dungeon.icon || slug + ".jpg";
    const key = safeId(`${slug}-${v.video_ref}`);
    const runUrl = `https://raider.io/mythic-plus-runs/${window.current_season}/${v.run_id}`;
    const embedSrc = buildVodEmbedSrc(v.video_ref, v.video_type, v.start_seconds);
    const pov = (window.spec_data || {})[String(v.pov_spec)];

    // Same shared modern pill style as the route accordion badges (mirror of `badge_cls`).
    const BADGE = "rt-pill";

    // POV pill (streamer's spec icon + character name) kept in the left group.
    const povPill =
      pov || v.pov_character_name
        ? `<span class="${BADGE} text-white" data-bs-toggle="tooltip" title="POV: ${v.pov_character_name || (pov ? pov.name : "")}">${pov ? `<img src="/data/icons/${pov.SpellIconFileId}.jpg" alt="${pov.name || ""}" title="${(pov.name || "")} POV" style="width:16px;height:16px;object-fit:cover;border-radius:3px;">` : ""}${v.pov_character_name ? `<span class="rt-name">${v.pov_character_name}</span>` : ""}</span>`
        : "";

    // Team comp icons (role-sorted), same as the route accordion.
    let specIcons = "";
    ["0", "1", "2"].forEach((role) => {
      (v.specs || []).forEach((sid) => {
        const spec = (window.spec_data || {})[sid];
        if (spec && String(spec.role) === role) {
          specIcons += `<img src="/data/icons/${spec.SpellIconFileId}.jpg" alt="${spec.name || ""}" title="${spec.name || ""}" class="img-fluid" style="width:24px;height:24px;object-fit:cover;border-radius:4px;">`;
        }
      });
    });

    const item = document.createElement("div");
    item.className = "accordion-item mb-2";
    item.innerHTML = `
  <h2 class="accordion-header" id="vodheading-${key}">
    <button class="accordion-button collapsed p-0" type="button" data-bs-toggle="collapse"
      data-bs-target="#vodcollapse-${key}" aria-expanded="false" aria-controls="vodcollapse-${key}"
      style="background-image: url('/data/icons/${bgIcon}'); background-size: cover; background-position: center; background-repeat: no-repeat; background-blend-mode: overlay;">
      <div class="w-100 row gx-2 gy-2 align-items-center py-3 px-4">
        <div class="col-12 col-lg-5">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start">
            <span class="${BADGE} text-white">${englishName}</span>
            <span class="${BADGE} text-success">+${v.level}</span>
            ${povPill}
          </div>
        </div>
        <div class="col-12 col-lg-4">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start justify-content-lg-center">
            <span class="${BADGE} text-white">${formatDuration(v.duration)}</span>
            <span class="timestamp ${BADGE} text-white" data-bs-toggle="tooltip" data-bs-placement="top" data-timestamp="${v.timestamp}"></span>
          </div>
        </div>
        <div class="col-12 col-lg-3">
          <div class="d-flex align-items-center flex-wrap gap-1 justify-content-start justify-content-lg-end">${specIcons}</div>
        </div>
      </div>
    </button>
  </h2>
  <div id="vodcollapse-${key}" data-share-id="${safeId(`vod-${slug}-${v.video_ref}`)}"
    class="accordion-collapse collapse" aria-labelledby="vodheading-${key}" data-bs-parent="#vodFinderAccordion">
    <div class="accordion-body p-0">
      <div class="route-run-details">
        <div class="route-run-head px-3 pt-2 pb-2">
          <a href="${runUrl}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary mb-0 d-inline-flex align-items-center gap-2">
            <img src="/assets/img/logos/RaiderIOLogo.png" alt="" width="18" height="18" class="rounded">
            <span>View full run details on Raider.io</span>
            <i class="material-symbols-rounded text-sm">open_in_new</i>
          </a>
        </div>
        <div class="iframe-container position-relative">
          <div class="iframe-spinner position-absolute top-50 start-50 translate-middle d-none">
            <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
          </div>
          <iframe loading="lazy" allowfullscreen data-name="${v.video_type}" data-src="${embedSrc}" class="w-100 route-embed" style="border:none;width:100%;height:calc(80vh - 3rem);display:block;"></iframe>
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
    accordionId: "vodFinderAccordion",
    sentinelId: "route-sentinel",
    overlayId: "route-search-overlay",
    jsonUrl: "/assets/json/compVods.json",
    indexFields: ["dungeon", "specs", "spells", "npcs", "pov_spec", "video_type"],
    sort: [
      { key: "level", dir: "desc" },
      { key: "timestamp", dir: "desc" },
      { key: "duration", dir: "asc" },
    ],
    noun: "VOD",
    relaxFilterId: "specSelect",
    autoQueryOnLoad: true,
    filters: [
      { id: "dungeonSelect", param: "dungeons", field: "dungeon", mode: "anyOf" },
      { id: "specSelect", param: "specs", field: "specs", mode: "allRelax", priorityByRole: true, multiset: true, max: 5, label: specLabel },
      { id: "povSpecSelect", param: "povSpecs", field: "pov_spec", mode: "anyOf", label: specLabel },
      { id: "videoTypeSelect", param: "videoTypes", field: "video_type", mode: "anyOf" },
      { id: "spellSelect", param: "spells", field: "spells", mode: "anyOf", expand: expandLust },
      { id: "npcIncludeSelect", param: "npcInclude", field: "npcs", mode: "anyOf" },
      { id: "npcExcludeSelect", param: "npcExclude", field: "npcs", mode: "noneOf" },
    ],
    renderItem: renderVodItem,
  });
})();
