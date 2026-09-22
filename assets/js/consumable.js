/* Per-consumable page (consumable.html), served at /consumables/<slug>.
 *
 * The page is fully server-rendered (no client-side scope switching), so this
 * script only opts out of Wowhead's power.js recolour/rename/iconize before it
 * loads, keeping the SSR markup as authored (same reasoning as items.js).
 */
(function () {
  "use strict";
  window.whTooltips = { colorLinks: false, iconizeLinks: false, renameLinks: false };
})();
