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

// --- Route embeds (Klaro-gated) ---
    // Route embeds load on first open, gated on Klaro consent (see consent.js).
    MythiConsent.wireAccordionEmbeds('#routeDungeonAccordion');

// --- Curated tables: DataTables responsive column collapsing ---
        // Curated, pre-ranked tables: enable Responsive column collapsing on small
        // screens while keeping their server-side order (ordering disabled).
        $(function () {
            var common = { responsive: true, ordering: false, paging: false, searching: false, info: false };
            var tables = {
                'lust-table': [{ targets: 0, responsivePriority: 1 }, { targets: 1, responsivePriority: 2 }, { targets: 3, responsivePriority: 4 }, { targets: 2, responsivePriority: 5 }],
                'popular-comps-table': [{ targets: 0, responsivePriority: 1 }, { targets: 1, responsivePriority: 2 }, { targets: 3, responsivePriority: 3 }, { targets: 2, responsivePriority: 4 }],
                'best-loot-table': [{ targets: 0, responsivePriority: 1 }, { targets: 2, responsivePriority: 2 }, { targets: 3, responsivePriority: 3 }, { targets: 1, responsivePriority: 5 }],
                'skip-npcs-table': [{ targets: 0, responsivePriority: 1 }, { targets: 1, responsivePriority: 2 }, { targets: 3, responsivePriority: 4 }, { targets: 2, responsivePriority: 5 }]
            };
            Object.keys(tables).forEach(function (id) {
                var el = document.getElementById(id);
                if (el) $(el).DataTable(Object.assign({ columnDefs: tables[id] }, common));
            });
        });

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

