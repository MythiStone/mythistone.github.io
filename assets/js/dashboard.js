// Dashboard charts. Data is fetched from /assets/json/dashboard_data.json
// (written by backend_scripts/generateDashboardPage.py) rather than inlined into
// the page. Chart theming goes through the shared MythiChart helper
// (assets/js/chart-theme.js), which re-themes every live chart on
// mythistone:themechange, so nothing here needs a theme listener.

(function () {
  function initDashboardCharts(data) {
    // Patch release lines shared by the two weekly charts. Delegates to the
    // shared MythiChart helper so the styling matches every other chart.
    const buildPatchAnnotations = () =>
      MythiChart.buildPatchAnnotations(data.patchAnnotations || []);

    function renderOverall(d) {
      const el = document.getElementById("chart-overall");
      if (!el) return;
      const overall_ctx = el.getContext("2d");
      const { labels, counts, barColors, iconUrls } = d.overall;

      // load images once
      const iconPromises = iconUrls.map(src => new Promise(res => {
        const img = new Image();
        img.src = src;
        img.onload = () => res(img);
        img.onerror = () => res(null); // fail-safe
      }));

      const iconPlugin = {
        id: "iconLabels",
        afterDraw(chart, args, opts) {
          if (!opts.enabled) return;
          const { ctx, chartArea: { bottom }, scales: { x } } = chart;
          opts.icons.forEach((img, i) => {
            if (!img) return; // skip failed loads
            const xPos = x.getPixelForTick(i);
            ctx.drawImage(img, xPos - opts.size / 2, bottom + opts.offsetY, opts.size, opts.size);
          });
        }
      };

      Promise.all(iconPromises).then(icons => {
        new Chart(overall_ctx, {
          type: "bar",
          data: {
            labels: labels,
            datasets: [{
              label: "Keys by spec",
              tension: 0.4,
              borderColor: "darkgrey",
              borderWidth: 1,
              borderRadius: 4,
              borderSkipped: false,
              backgroundColor: barColors,
              data: counts,
              barThickness: 'flex'
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              iconLabels: {
                enabled: true,
                size: 32,
                offsetY: 4,
                icons: icons
              }
            },
            layout: { padding: { bottom: (32 + 8 + 4) } },
            interaction: { intersect: false, mode: 'index' },
            scales: {
              y: { grid: { drawBorder: false, display: true, drawOnChartArea: true, drawTicks: false, borderDash: [5, 5], color: MythiChart.colors.grid }, ticks: { display: false } },
              x: { grid: { drawBorder: false, display: false, drawOnChartArea: false, drawTicks: false, borderDash: [5, 5] }, ticks: { display: false, color: MythiChart.colors.tickText, padding: 10, font: { size: 14, lineHeight: 2 } } }
            }
          },
          plugins: [iconPlugin]
        });
      });
    }

    function renderKeyLevel(d) {
      const el = document.getElementById("chart-keylevel");
      if (!el) return;
      const keylevel_ctx = el.getContext("2d");
      const keyLevels = d.keyLevel.keyLevels;
      const datasets = d.keyLevel.datasets;

      new Chart(keylevel_ctx, {
        type: "bar",
        data: {
          labels: keyLevels.map(lvl => `M + Level ${lvl}`),
          datasets
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              stacked: true,
              max: 100,
              ticks: {
                callback: val => val + '%'   // show "%"
              },
              grid: {
                display: false,
                drawBorder: false,
                color: MythiChart.colors.grid,
                borderDash: [5, 5]
              }
            },
            y: {
              stacked: true,
              grid: { display: false },
              barPercentage: 0.1,
              ticks: {
                color: MythiChart.colors.tickText,
                padding: 6,
                font: { size: 12, lineHeight: 2 }
              }
            }
          },
          plugins: {
            tooltip: {
              mode: 'nearest',
              intersect: true,
              callbacks: {
                label: ctx => {
                  const pct = ctx.parsed.x;
                  const rawCount = (ctx.dataset.rawCounts?.[ctx.dataIndex]) || 0;
                  // return percentage + raw count
                  return `${ctx.dataset.label}: ${pct}% (${rawCount.toLocaleString()} ${rawCount > 1 ? "runs" : "run"})`;
                }
              }
            },
            legend: {
              display: false,
            }
          }
        }
      });
    }

    function renderKeysPerWeek(d) {
      const el = document.getElementById("chart-keys-per-week");
      if (!el) return;
      const ctx_keys_per_week = el.getContext("2d");
      const periodLabels = d.keysPerWeek.labels;
      const periodDatasets = d.keysPerWeek.datasets;
      const grain = d.keysPerWeek.grain;

      new Chart(ctx_keys_per_week, {
        type: "line",
        data: {
          labels: periodLabels,
          datasets: periodDatasets
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              display: true,
              title: {
                display: true,
                text: (grain === 'day' ? 'Day' : 'Week'),
                font: { size: 14 }
              },
              ticks: {
                autoSkip: false,
                maxRotation: 0,
                minRotation: 0
              }
            },
            y: {
              display: true,
              title: {
                display: true,
                text: "Total Keys",
                font: { size: 14 }
              },
              beginAtZero: true,
              grid: {
                color: MythiChart.colors.grid,
                borderDash: [5, 5]
              }
            }
          },
          plugins: {
            tooltip: {
              callbacks: {
                label: ctx => ` ${ctx.parsed.y.toLocaleString()} keys`
              }
            },
            legend: {
              display: true
            },
            annotation: {
              // patch lines sit on week-index boundaries, so only draw them on
              // the weekly axis (never on the week-1 per-day breakdown).
              annotations: (grain === 'week') ? buildPatchAnnotations() : {}
            }
          }
        }
      });
    }

    function renderDungeonPopularity(d) {
      const el = document.getElementById("chart-dungeon-popularity");
      if (!el) return;
      const ctx = el.getContext("2d");

      const dungeonLabels = d.dungeonPopularity.labels;
      const dungeonFullNames = d.dungeonPopularity.fullNames;
      const iconUrls = d.dungeonPopularity.iconUrls;
      const totalCounts = d.dungeonPopularity.totalCounts;
      const dungeonDatasets = d.dungeonPopularity.datasets;

      // Kick off loading each icon
      const iconPromises = iconUrls.map(src =>
        new Promise(resolve => {
          const img = new Image();
          img.src = src;
          img.onload = () => resolve(img);
          img.onerror = () => resolve(null);
        })
      );

      // Plugin that draws the icons + short-names on the Y axis
      const iconPlugin = {
        id: "iconLabels",
        afterDraw(chart, args, opts) {
          if (!opts.enabled) return;
          const { ctx, chartArea, scales: { y } } = chart;
          const { size, iconOffset, textGap, fontSize, fontFace, color, icons } = opts;

          ctx.textBaseline = "middle";
          ctx.font = `${fontSize}px ${fontFace}`;
          ctx.fillStyle = color;

          icons.forEach((img, i) => {
            const yPos = y.getPixelForTick(i);
            const iconX = chartArea.left - iconOffset - size;
            if (img) {
              ctx.drawImage(img, iconX, yPos - size / 2, size, size);
            }

            const shortName = dungeonLabels[i];
            const textX = iconX - textGap;
            ctx.textAlign = "right";
            ctx.fillText(shortName, textX, yPos);
          });
        }
      };

      // Once all icons are loaded, build the chart
      Promise.all(iconPromises).then(icons => {
        new Chart(ctx, {
          type: "bar",
          data: {
            labels: dungeonLabels,
            datasets: dungeonDatasets
          },
          options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            layout: {
              padding: { left: 120 }
            },
            scales: {
              x: {
                stacked: true,
                grid: { display: false },
                ticks: {
                  callback: v => v.toLocaleString(),
                  font: { size: 12 }
                }
              },
              y: {
                stacked: true,
                grid: { color: MythiChart.colors.grid, borderDash: [5, 5] },
                ticks: { display: false, padding: 6, font: { size: 12 } }
              }
            },
            plugins: {
              legend: { position: "top" },
              tooltip: {
                callbacks: {
                  title: items => dungeonFullNames[items[0].dataIndex],
                  label: item => {
                    const count = item.parsed.x;
                    const total = totalCounts[item.dataIndex];
                    const pct = total
                      ? ((count / total) * 100).toFixed(1)
                      : "0.0";
                    return `${count.toLocaleString()} runs (${pct}%)`;
                  }
                }
              },
              // pass the pre-loaded icons into the plugin via its options
              iconLabels: {
                enabled: true,
                icons: icons,        // the loaded Image objects
                size: 28,
                iconOffset: 8,
                textGap: 4,
                fontSize: 12,
                fontFace: "Arial",
                color: MythiChart.colors.legendText
              }
            }
          },
          plugins: [iconPlugin]
        });
      });
    }

    function renderScatter(d) {
      const el = document.getElementById("chart-popularity-vs-tier");
      if (!el) return;
      const ctx = el.getContext("2d");

      const rawPoints = d.scatter;
      const ICON_SIZE = 20;
      // preload each icon
      const iconPromises = rawPoints.map(p =>
        new Promise(res => {
          const img = new Image();
          img.width = ICON_SIZE;
          img.height = ICON_SIZE;
          img.src = p.iconUrl;
          img.onload = () => res(img);
          img.onerror = () => res(null);
        })
      );

      const avgPerf = rawPoints.length
        ? rawPoints.reduce((s, p) => s + p.x, 0) / rawPoints.length
        : 0;

      // Compressive X scale: GAMMA < 1 spreads specs close to the average and
      // squeezes the extreme performers toward the edges. Tune here.
      const X_GAMMA = 0.5;
      const xForward = x => {
        const dv = x - avgPerf;
        return avgPerf + Math.sign(dv) * Math.pow(Math.abs(dv), X_GAMMA);
      };
      const xInverse = p => {
        const dv = p - avgPerf;
        return avgPerf + Math.sign(dv) * Math.pow(Math.abs(dv), 1 / X_GAMMA);
      };

      // Keep 0% (the average) dead center: symmetric limits in transformed space.
      // The signed-power transform is odd, so avgPerf maps to the exact center.
      let maxDev = rawPoints.reduce((m, p) => Math.max(m, Math.abs(p.x - avgPerf)), 0);
      if (maxDev <= 0) maxDev = Math.abs(avgPerf) || 1;
      const xMin = xForward(avgPerf - maxDev * 1.05);
      const xMax = xForward(avgPerf + maxDev * 1.05);

      // Explicit ticks at readable percentages of avg, mapped through the
      // transform. The callback inverse-transforms back to the true percent.
      const nicePcts = [-100, -50, -25, -10, -5, 0, 5, 10, 25, 50, 100];
      const xTickValues = nicePcts
        .map(pct => xForward(avgPerf * (1 + pct / 100)))
        .filter(v => v >= xMin && v <= xMax);

      // Compressive Y (run count) scale: logarithmic spreads the crowded
      // low/mid-run band so icons overlap less. Runs are strictly positive.
      const runVals = rawPoints.map(p => p.y).filter(y => y > 0);
      const minRun = runVals.length ? Math.min(...runVals) : 1;
      const maxRun = runVals.length ? Math.max(...runVals) : 1;
      const yMin = minRun / 1.2;
      const yMax = maxRun * 1.2;
      const niceRuns = [1e2, 2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6];
      const yTickValues = niceRuns.filter(r => r >= yMin && r <= yMax);

      const formatRuns = value => {
        if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
        if (value >= 1e6) return (value / 1e6).toFixed(1) + 'M';
        if (value >= 1e3) return (value / 1e3).toFixed(1) + 'k';
        return value.toFixed(0);
      };

      // once loaded, build the chart
      Promise.all(iconPromises).then(images => {
        // attach the loaded Image to each data point
        const chartData = rawPoints.map((p, i) => ({
          ...p,
          xPos: xForward(p.x),   // plotted position (compressed); raw x kept for tooltip
          pointStyle: images[i]
        }));

        new Chart(ctx, {
          type: 'scatter',
          data: {
            datasets: [{
              label: 'Spec Popularity vs Performance',
              data: chartData,
              // plot the compressed xPos; y unchanged. raw x stays on the datum.
              parsing: { xAxisKey: 'xPos', yAxisKey: 'y' },
              pointRadius: 12,
              pointHoverRadius: 16,
              // these two read from the raw datum
              pointStyle: ctx => ctx.raw.pointStyle,
              borderColor: ctx => ctx.raw.borderColor,
              backgroundColor: ctx => ctx.raw.backgroundColor,
              borderWidth: 2,
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: {
                min: xMin,
                max: xMax,
                afterBuildTicks: scale => {
                  scale.ticks = xTickValues.map(v => ({ value: v }));
                },
                title: { display: true, text: 'Performance vs Average' },
                ticks: {
                  display: true,
                  // value is the transformed position; recover the true percent.
                  callback: value => {
                    const realX = xInverse(value);
                    const pct = avgPerf ? (realX - avgPerf) / avgPerf * 100 : 0;
                    const sign = pct > 0 ? '+' : '';
                    return sign + pct.toFixed(0) + '%';
                  }
                }
              },
              y: {
                type: 'logarithmic',
                min: yMin,
                max: yMax,
                afterBuildTicks: scale => {
                  scale.ticks = yTickValues.map(v => ({ value: v }));
                },
                title: { display: true, text: 'Runs' },
                ticks: {
                  display: true,
                  callback: value => formatRuns(value)
                }
              }
            },
            plugins: {
              tooltip: {
                callbacks: {
                  label: ctx => {
                    const { label, x, y } = ctx.raw;
                    return `${label}: TierScore=${x.toFixed(2)}, Runs=${y}`;
                  }
                }
              },
              legend: { display: false }
            }
          }
        });
      });
    }

    function renderScoreScatters(d) {
      const ICON_SIZE = 20;

      const formatRuns = value => {
        if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
        if (value >= 1e6) return (value / 1e6).toFixed(1) + 'M';
        if (value >= 1e3) return (value / 1e3).toFixed(1) + 'k';
        return value.toFixed(0);
      };

      // Shared renderer: score on a linear X axis, run count on a logarithmic Y
      // axis (matching the tier-score chart's Y), spec icons as points.
      const renderScoreScatter = (canvasId, rawPoints, xTitle) => {
        const el = document.getElementById(canvasId);
        if (!el || !rawPoints.length) return;
        const ctx = el.getContext("2d");

        const iconPromises = rawPoints.map(p =>
          new Promise(res => {
            const img = new Image();
            img.width = ICON_SIZE;
            img.height = ICON_SIZE;
            img.src = p.iconUrl;
            img.onload = () => res(img);
            img.onerror = () => res(null);
          })
        );

        const xVals = rawPoints.map(p => p.x);
        const minX = Math.min(...xVals);
        const maxX = Math.max(...xVals);
        const pad = (maxX - minX) * 0.08 || Math.abs(maxX) * 0.05 || 1;
        const xMin = minX - pad;
        const xMax = maxX + pad;

        const runVals = rawPoints.map(p => p.y).filter(y => y > 0);
        const minRun = runVals.length ? Math.min(...runVals) : 1;
        const maxRun = runVals.length ? Math.max(...runVals) : 1;
        const yMin = minRun / 1.2;
        const yMax = maxRun * 1.2;
        const niceRuns = [1e2, 2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6];
        const yTickValues = niceRuns.filter(r => r >= yMin && r <= yMax);

        Promise.all(iconPromises).then(images => {
          const chartData = rawPoints.map((p, i) => ({ ...p, pointStyle: images[i] }));

          new Chart(ctx, {
            type: 'scatter',
            data: {
              datasets: [{
                label: xTitle,
                data: chartData,
                parsing: { xAxisKey: 'x', yAxisKey: 'y' },
                pointRadius: 12,
                pointHoverRadius: 16,
                pointStyle: c => c.raw.pointStyle,
                borderColor: c => c.raw.borderColor,
                backgroundColor: c => c.raw.backgroundColor,
                borderWidth: 2,
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              scales: {
                x: {
                  min: xMin,
                  max: xMax,
                  title: { display: true, text: xTitle },
                  ticks: { display: true, callback: value => formatRuns(value) }
                },
                y: {
                  type: 'logarithmic',
                  min: yMin,
                  max: yMax,
                  afterBuildTicks: scale => {
                    scale.ticks = yTickValues.map(v => ({ value: v }));
                  },
                  title: { display: true, text: 'Runs' },
                  ticks: { display: true, callback: value => formatRuns(value) }
                }
              },
              plugins: {
                tooltip: {
                  callbacks: {
                    label: c => {
                      const { label, x, y } = c.raw;
                      return `${label}: Score=${Math.round(x).toLocaleString()}, Runs=${y}`;
                    }
                  }
                },
                legend: { display: false }
              }
            }
          });
        });
      };

      renderScoreScatter("chart-popularity-vs-top50-score", d.top50Scatter, "Avg Top 50 Score");
      renderScoreScatter("chart-popularity-vs-char-score", d.charScatter, "Avg Character Score");
    }

    function renderDungeonEase(d) {
      const el = document.getElementById("chart-dungeon-popularity-vs-ease");
      if (!el) return;
      const ctx = el.getContext("2d");

      const keyLevels = d.dungeonEase.keyLevels;
      const datasets = d.dungeonEase.datasets;

      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: keyLevels.map(l => `M + Level ${l}`),
          datasets: datasets
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              stacked: true,
              max: 100,
              ticks: { callback: v => v + '%' },
              grid: {
                display: false,
                drawBorder: false,
                color: MythiChart.colors.grid,
                borderDash: [5, 5]
              }
            },
            y: {
              stacked: true,
              grid: { display: false },
              barPercentage: 0.1,
              ticks: {
                color: MythiChart.colors.tickText,
                padding: 6,
                font: { size: 12, lineHeight: 2 }
              }
            }
          },
          plugins: {
            tooltip: {
              mode: 'nearest',
              intersect: true,
              callbacks: {
                label: ctx => {
                  const ds = ctx.dataset;
                  const pct = ctx.parsed.x.toFixed(1);
                  const raw = ds.rawCounts[ctx.dataIndex] || 0;
                  return `${ds.label}: ${pct}% (${raw.toLocaleString()} runs)`;
                }
              }
            },
            legend: { display: false }
          }
        }
      });
    }

    function renderKeyThroughput(d) {
      const el = document.getElementById("chart-key-throughput");
      if (!el) return;
      const ctx = el.getContext("2d");

      const labels = d.keyThroughput.labels;
      const series = d.keyThroughput.series;

      const datasets = series.map(s => ({
        label: s.region,
        data: s.data,
        borderColor: s.color,
        backgroundColor: s.color,
        pointBackgroundColor: s.color,
        // emphasise the combined "Overall" line; regions are thinner/dashed
        borderWidth: s.overall ? 3 : 1.5,
        borderDash: s.overall ? [] : [4, 3],
        tension: 0.35,
        pointRadius: s.overall ? 0 : 2,
        pointHoverRadius: 5,
        order: s.overall ? 0 : 1,
        spanGaps: true
      }));

      const resetBtn = document.getElementById("resetThroughputZoom");
      // Disable chart pan/zoom on small screens so it doesn't hijack page scrolling.
      const enableZoom = window.matchMedia('(min-width: 992px)').matches;

      const chart = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { intersect: false, mode: "index" },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: MythiChart.colors.tickText, maxRotation: 0, autoSkip: true, font: { size: 10 } }
            },
            y: {
              beginAtZero: true,
              grid: { color: MythiChart.colors.grid },
              ticks: { color: MythiChart.colors.tickText, maxTicksLimit: 4, font: { size: 10 } }
            }
          },
          plugins: {
            legend: {
              position: "top",
              labels: {
                color: MythiChart.colors.legendText, usePointStyle: true, pointStyle: "circle",
                boxWidth: 8, padding: 8, font: { size: 10 }
              }
            },
            tooltip: {
              callbacks: {
                label: c => ` ${c.dataset.label}: ${c.parsed.y == null ? "—" : c.parsed.y.toLocaleString() + " keys/min"}`
              }
            },
            annotation: {
              // patch lines sit on week-index boundaries; hide them on the
              // week-1 per-day breakdown (matches the Keys per Day chart).
              annotations: (d.periodGrain === 'week') ? buildPatchAnnotations() : {}
            },
            zoom: {
              // weeks are the finest grain in the data, so cap how far you can
              // zoom in (minRange keeps at least ~2 weeks in view).
              limits: { x: { min: "original", max: "original", minRange: 1 } },
              pan: {
                enabled: enableZoom,
                mode: "x",
                onPan: () => { if (resetBtn) resetBtn.style.display = "inline-block"; }
              },
              zoom: {
                wheel: { enabled: enableZoom },
                pinch: { enabled: enableZoom },
                mode: "x",
                onZoom: () => { if (resetBtn) resetBtn.style.display = "inline-block"; }
              }
            }
          }
        }
      });

      if (resetBtn) {
        resetBtn.addEventListener("click", () => {
          chart.resetZoom();
          resetBtn.style.display = "none";
        });
      }
    }

    function renderCompletionHeatmap(d) {
      const el = document.getElementById("chart-completion-heatmap");
      if (!el || typeof Chart === "undefined") return;

      // grids are UTC, flat 168-cell arrays indexed day * 24 + hour, day 0=Sun..6=Sat
      const HEAT = d.completionHeatmap;

      // getTimezoneOffset() is minutes *behind* UTC (UTC+2 => -120), so the local
      // shift in hours is its negation. Math.round approximates half-hour zones
      // (e.g. India +5:30 -> +6) — acceptable at hour granularity.
      const shift = Math.round(-new Date().getTimezoneOffset() / 60);
      // The week is cyclic, so rotating the flat array by shift (mod 168) handles
      // day wraparound automatically (Sun 23:00 UTC + 2h -> Mon 01:00 local).
      const rotate = (grid) => {
        const out = new Array(168);
        for (let i = 0; i < 168; i++) out[(i + shift + 336) % 168] = grid[i];
        return out;
      };

      const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      const DAY_ORDER = [1, 2, 3, 4, 5, 6, 0]; // display Monday-first

      const toCells = (grid) => {
        const local = rotate(grid);
        const cells = [];
        for (const dd of DAY_ORDER)
          for (let h = 0; h < 24; h++)
            cells.push({ x: h, y: DAYS[dd], v: local[dd * 24 + h] });
        return cells;
      };

      // WoW item-rarity color scale: underplayed hours read as Common, the most
      // played hours as Legendary. Tiers are percentile-based — each rarity
      // covers an equal fifth of the non-zero cells — so the spread stays
      // visible no matter how skewed the distribution is, and re-normalises
      // when the toggle switches region.
      // Colors live in /assets/css/dashboard.css so the legend swatches and
      // the chart can never drift apart.
      const rootStyle = getComputedStyle(document.documentElement);
      const heat = (name) => rootStyle.getPropertyValue(`--dash-heat-${name}`).trim();
      const RARITY_SCALE = ["common", "uncommon", "rare", "epic", "legendary"].map(heat);
      const ZERO_COLOR = heat("zero");
      let tierThresholds = []; // 20/40/60/80th percentile values of non-zero cells
      const setThresholds = (cells) => {
        const vals = cells.map(c => c.v).filter(v => v > 0).sort((a, b) => a - b);
        tierThresholds = vals.length
          ? [0.2, 0.4, 0.6, 0.8].map(q => vals[Math.min(vals.length - 1, Math.floor(q * vals.length))])
          : [];
      };
      const rarityColor = (v) => {
        if (v <= 0) return ZERO_COLOR;
        let tier = 0;
        for (const t of tierThresholds) if (v >= t) tier++;
        return RARITY_SCALE[Math.min(tier, RARITY_SCALE.length - 1)];
      };

      const initial = toCells(HEAT.grids["all"]);
      setThresholds(initial);

      const chart = new Chart(el.getContext("2d"), {
        type: "matrix",
        data: {
          datasets: [{
            label: "Keys completed",
            data: initial,
            backgroundColor: (c) => rarityColor(c.raw ? c.raw.v : 0),
            borderColor: "rgba(255,255,255,0.06)",
            borderWidth: 1,
            width: (c) => ((c.chart.chartArea || {}).width || 0) / 24 - 2,
            height: (c) => ((c.chart.chartArea || {}).height || 0) / 7 - 2,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              type: "linear", position: "top", min: -0.5, max: 23.5, offset: false,
              ticks: {
                stepSize: 3, color: MythiChart.colors.tickText, font: { size: 10 },
                callback: v => (v >= 0 && v % 3 === 0) ? `${v}:00` : ""
              },
              grid: { display: false }
            },
            y: {
              type: "category", labels: DAY_ORDER.map(dd => DAYS[dd]),
              ticks: { color: MythiChart.colors.tickText, font: { size: 10 } },
              grid: { display: false }
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: (items) => {
                  const r = items[0].raw;
                  const hh = String(r.x).padStart(2, "0");
                  return `${r.y} ${hh}:00–${hh}:59 (your time)`;
                },
                label: (c) => ` ${c.raw.v.toLocaleString()} keys completed`
              }
            }
          }
        }
      });

      const toggle = document.getElementById("heatmap-region-toggle");
      if (toggle) {
        toggle.addEventListener("click", (ev) => {
          const btn = ev.target.closest("button[data-region]");
          if (!btn) return;
          toggle.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === btn));
          const cells = toCells(HEAT.grids[btn.dataset.region] || HEAT.grids["all"]);
          setThresholds(cells);
          chart.data.datasets[0].data = cells;
          chart.update();
        });
      }

      const note = document.getElementById("heatmap-tz-note");
      if (note) {
        try {
          note.textContent = `Shown in your local time (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;
        } catch (e) { /* keep the generic label */ }
      }
    }

    // Each chart is isolated so one failing render never aborts the others
    // (matching the old separate inline <script> blocks).
    [
      renderKeyThroughput,
      renderOverall,
      renderKeyLevel,
      renderKeysPerWeek,
      renderDungeonPopularity,
      renderScatter,
      renderScoreScatters,
      renderDungeonEase,
      renderCompletionHeatmap,
    ].forEach(fn => {
      try { fn(data); } catch (e) { console.error(`dashboard chart ${fn.name} failed`, e); }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    fetch("/assets/json/dashboard_data.json")
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(initDashboardCharts)
      .catch(err => console.error("Failed to load dashboard data", err));
  });
})();
