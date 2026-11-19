// Dungeon page behaviour, extracted from templates/dungeon_page.html.
// Per-dungeon data (level_stats) comes from the inline
// <script type="application/json" id="dungeon-page-data"> block.
const DUNGEON = JSON.parse(document.getElementById('dungeon-page-data').textContent);

// --- Closest/Shortest/Longest run toggle + deep-link revealer ---
                (function () {
                    function activate(btn) {
                        var card = btn.closest('.run-toggle-card');
                        if (!card) return null;
                        card.querySelectorAll('.run-panel').forEach(function (p) { p.classList.add('d-none'); });
                        card.querySelectorAll('.run-toggle-btn').forEach(function (b) { b.classList.remove('active'); });
                        var target = document.getElementById(btn.dataset.target);
                        if (target) target.classList.remove('d-none');
                        btn.classList.add('active');
                        return target;
                    }

                    document.querySelectorAll('.run-toggle-btn').forEach(function (btn) {
                        btn.addEventListener('click', function () {
                            var target = activate(btn);
                            // #panel-closest-call / -shortest / -longest are stable names,
                            // so they make good permalinks even though this is a plain
                            // d-none toggle rather than a Bootstrap collapse.
                            if (target && window.MythiLink) MythiLink.notifyShown(target);
                        });
                    });

                    // This block sits mid-body, above javascript_imports.html, so
                    // MythiLink doesn't exist yet — register on DOMContentLoaded,
                    // which still lands before deep-link.js resolves the hash.
                    document.addEventListener('DOMContentLoaded', function () {
                        if (!window.MythiLink) return;
                        MythiLink.registerRevealer({
                            match: function (el) { return el.classList.contains('run-panel'); },
                            isOpen: function (el) { return !el.classList.contains('d-none'); },
                            show: function (el) {
                                var btn = document.querySelector('.run-toggle-btn[data-target="' + el.id + '"]');
                                if (btn) activate(btn);
                            }
                        });
                    });
                })();

// --- Boss Pacing: fight labels drop to a second row only when they would overlap ---
function layoutPacingLabels() {
    document.querySelectorAll('#dungeon-boss-pacing .pacing-panel:not(.d-none) .pacing-labels').forEach(function (lane) {
        if (!lane.offsetWidth) return;
        var upperEnd = -Infinity, stacked = false;
        lane.querySelectorAll('.pacing-label').forEach(function (label) {
            label.classList.remove('pacing-label-low');
            var textWidth = Math.max.apply(null, Array.prototype.map.call(label.children, function (c) { return c.offsetWidth; }));
            if (label.offsetLeft < upperEnd) {
                label.classList.add('pacing-label-low');
                stacked = true;
            } else {
                upperEnd = label.offsetLeft + textWidth + 4;
            }
        });
        lane.classList.toggle('pacing-labels-stacked', stacked);
    });
}
document.addEventListener('DOMContentLoaded', layoutPacingLabels);
window.addEventListener('load', layoutPacingLabels);
window.addEventListener('resize', layoutPacingLabels);

// --- Keystone scaling: damage and health numbers carry their Mythic 0 value ---
// Mirrors commonUtils.humanize_number, the humanize filter that renders them.
function humanizeNumber(value) {
    var n = Math.trunc(value);
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + ' M';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + ' K';
    return String(n);
}

// Below the affix level only one affix is active, depending on the week, so none is applied.
function keyMultiplier(stat, enemyKind, level) {
    var scaling = DUNGEON.keyScaling;
    var multiplier = scaling.level_bands.reduce(function (total, band) {
        var last = band.to === null ? level : Math.min(level, band.to);
        return total * Math.pow(band[stat], Math.max(0, last - band.from + 1));
    }, 1);
    return level >= scaling.affix_from_level ? multiplier * scaling.affixes[enemyKind][stat] : multiplier;
}

function damageNote(level) {
    if (!level) return 'Damage at Mythic 0, before keystone scaling.';
    return level >= DUNGEON.keyScaling.affix_from_level
        ? 'Damage at +' + level + '.'
        : 'Damage at +' + level + ', before the weekly affix.';
}

function applyKeyScaling(level) {
    document.querySelectorAll('[data-scale]').forEach(function (node) {
        var factor = level ? keyMultiplier(node.dataset.scale, node.dataset.scaleEnemy, level) : 1;
        node.textContent = humanizeNumber(Number(node.dataset.scaleBase) * factor);
    });
    document.querySelectorAll('[data-damage-note]').forEach(function (note) {
        note.textContent = damageNote(level);
    });
}

// --- Boss Pacing minimum-key filter (bootstrap-select fires change via jQuery) ---
// The boss detail modals carry their own pacing panels, so they follow it too.
$('#dungeon-boss-pacing #minKeySelect').on('change', function () {
    var key = this.value;
    document.querySelectorAll('.pacing-panel').forEach(function (p) {
        p.classList.toggle('d-none', p.dataset.pacing !== key);
    });
    layoutPacingLabels();
    applyKeyScaling(Number(key));
});

// --- A spell name in a fold-out row opens the row. Its icon, or a modified click, goes to Wowhead ---
document.addEventListener('click', function (e) {
    var link = e.target.closest('summary .detail-spell-link');
    if (!link || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var row = link.closest('details');
    row.open = !row.open;
});

// --- Boss Pacing bars open their boss modal (a bar's tooltip rules out data-bs-toggle="modal") ---
// Route Breakdown portraits are Wowhead links: a plain click opens the pull modal at that enemy instead.
document.addEventListener('click', function (e) {
    var bar = e.target.closest('[data-modal]');
    if (!bar) return;
    if (bar.tagName === 'A') {
        if (e.ctrlKey || e.metaKey || e.shiftKey) return;
        e.preventDefault();
    }
    var tip = bootstrap.Tooltip.getInstance(bar);
    if (tip) tip.hide();
    var modal = document.getElementById(bar.dataset.modal);
    if (bar.dataset.npc) modal.dataset.focusNpc = bar.dataset.npc;
    bootstrap.Modal.getOrCreateInstance(modal).show();
});

// A pull modal opened from a portrait scrolls to and highlights that enemy, one at a time.
function focusNpcCard(modal) {
    modal.querySelectorAll('.detail-card-flash').forEach(function (c) { c.classList.remove('detail-card-flash'); });
    var npc = modal.dataset.focusNpc;
    var card = npc && modal.querySelector('.detail-card[data-npc="' + npc + '"]');
    if (!card) return;
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    card.classList.add('detail-card-flash');
}
document.addEventListener('shown.bs.modal', function (e) { focusNpcCard(e.target); });
document.addEventListener('hidden.bs.modal', function (e) {
    delete e.target.dataset.focusNpc;
    focusNpcCard(e.target);
});
// The highlighted enemy rides in the share link as "&npc=<id>" (deep-link.js).
if (window.MythiLink) {
    MythiLink.registerState('npc', {
        read: function () {
            var modal = document.querySelector('.modal.show[data-focus-npc]');
            return modal ? modal.dataset.focusNpc : null;
        },
        apply: function (npc) {
            var modal = document.querySelector('.modal.show');
            if (!modal || !npc) return;
            modal.dataset.focusNpc = npc;
            focusNpcCard(modal);
        }
    });
}

// The boss rows of the Route Breakdown card open the same modal from the keyboard.
document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.route-row[data-modal]')) {
        e.preventDefault();
        e.target.click();
    }
});

// --- Route embeds (Klaro-gated) ---
    // Route embeds load on first open, gated on Klaro consent (see consent.js).
    MythiConsent.wireAccordionEmbeds('#routeDungeonAccordion');

// --- Runs-by-keylevel bar chart ---
        document.addEventListener("DOMContentLoaded", function () {
            // Disable chart pan/zoom on small screens so it doesn't hijack page scrolling.
            var enableZoom = window.matchMedia('(min-width: 992px)').matches;
            var levelData = DUNGEON.levelStats;
        if (!levelData || !levelData.length) return;
        // sort by key level
        levelData.sort((a, b) => a.keystone_level - b.keystone_level);

        var labels = levelData.map(d => '+' + d.keystone_level);
        var up3 = levelData.map(d => d.upgrade_3);
        var up2 = levelData.map(d => d.upgrade_2);
        var up1 = levelData.map(d => d.upgrade_1);
        var depleted = levelData.map(d => d.depleted);

        var ctxBar = document.getElementById("keyLevelChart").getContext("2d");
        var keyLevelChart = new Chart(ctxBar, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    { label: "Depleted", data: depleted, backgroundColor: "#FF0000" },
                    { label: "+1", data: up1, backgroundColor: "#1eff00" },
                    { label: "+2", data: up2, backgroundColor: "#a335ee" },
                    { label: "+3", data: up3, backgroundColor: "#ff8000" }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { stacked: true, ticks: { color: MythiChart.colors.tickText }, grid: { display: false } },
                    y: { stacked: true, ticks: { color: MythiChart.colors.tickText }, grid: { color: MythiChart.colors.grid } }
                },
                plugins: {
                    legend: { labels: { color: MythiChart.colors.tickText } },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    },
                    zoom: {
                        pan: {
                            enabled: enableZoom,
                            mode: 'x',
                            onPan: function ({ chart }) {
                                document.getElementById('resetZoomBtn').classList.remove('d-none');
                            }
                        },
                        zoom: {
                            wheel: { enabled: enableZoom },
                            pinch: { enabled: enableZoom },
                            mode: 'x',
                            onZoom: function ({ chart }) {
                                document.getElementById('resetZoomBtn').classList.remove('d-none');
                            }
                        }
                    }
                }
            }
        });

        document.getElementById('resetZoomBtn').addEventListener('click', function () {
            keyLevelChart.resetZoom();
            this.classList.add('d-none');
        });
        });

