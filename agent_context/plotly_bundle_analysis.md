# Plotly.js bundle choice — analysis

Phase 10 must decide which plotly.js bundle ships next to our HTMLs.
`docs/pages/plotly.min.js` is the shared library file referenced by every
chart in the directory (via `include_plotlyjs="directory"`).

## What plotly Python ships out of the box

`pip install plotly==6.7.0` bundles **plotly.js v3.5.0 full**:

| file | size on disk | size gzip |
|---|---:|---:|
| `plotly.min.js` (full, 40+ trace types) | 4.7 MB | 1.4 MB |

This is the kitchen-sink build: scatter, bar, pie, scatter3d, surface,
mesh3d, choropleth, choroplethmap, scattergeo, scattermap, sankey,
candlestick, ohlc, sunburst, treemap, icicle, parcoords, parcats,
indicator, waterfall, funnel, funnelarea, density, contour, heatmap,
heatmapgl, histogram, histogram2d, histogram2dcontour, box, violin,
image, table, polar, ternary, smith, carpet, scatterpolar,
scattersmith, scatterternary, scattermapbox, and so on.

For a momentum-strategy dashboard most of that is dead weight.

## Available partial bundles (plotly.js v3.5.0)

All from `https://cdn.plot.ly/plotly-<variant>-3.5.0.min.js`.

| variant | size | gzip | scatter | bar | pie | sankey | heatmap | candlestick | 3D |
|---|---:|---:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| basic | 1.1 MB | 363 KB | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| cartesian | ~1.6 MB | ~480 KB | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ |
| finance | ~1.5 MB | ~440 KB | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ (OHLC, waterfall, funnel) | ✗ |
| geo / mapbox | ~1.5 MB | ~440 KB | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ (geo traces instead) |
| gl3d / 3d | ~2.5 MB | ~700 KB | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| full | 4.7 MB | 1.4 MB | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Verified live: HEAD 200 OK for `plotly-basic-3.5.0.min.js`,
`plotly-cartesian-3.5.0.min.js`, `plotly-finance-3.5.0.min.js`.

Verified trace-module presence in `plotly-basic-3.5.0.min.js` by grep for
`moduleType:"trace",name:"<type>"`:
- registered: `scatter`, `bar`, `pie`
- absent: `sankey`, `heatmap`, `candlestick`, `ohlc`, `contour`,
  `choropleth`, `mesh3d`, `surface`, `histogram`, `box`, `violin`

## What our current code actually uses

`src/momentum/viz/plotly_charts.py` produces three charts:

1. `plot_q1_q4_dynamics` — 5 `go.Scatter` traces (mode=lines), log y,
   rangeselector + rangeslider in layout.
2. `plot_q1_minus_q4_premium` — 1 `go.Scatter` trace.
3. `plot_q1_minus_mcftrr` — 1 `go.Scatter` trace.

Extracted from generated HTML via the `Plotly.newPlot(...)` JSON dump:
all 7 traces have `type == "scatter"`. Nothing else.

**All current Phase-10 output is covered by plotly-basic.**

## Future tasks — what they need

Survey of `tasks/todo/`:

| task | charts planned | trace types | bundle needed |
|---|---|---|---|
| Phase 11 (GitHub Pages) | none (only HTML/jinja stitching) | — | inherits Phase 10 |
| Phase 12 (regression) | none (tests + diff reports) | — | inherits Phase 10 |
| Phase 13 (Claude skills) | none | — | inherits Phase 10 |
| 003_chart_modes (monthly bars) | adds `go.Bar` with `barmode='group'` | scatter, bar | **basic** ✓ |
| 002_mages_index (overlay charts) | "3-4 plotly functions" — comparison equity curves | scatter (lines) | **basic** ✓ |
| 001_quartile_transitions | **Sankey** flows + topN list | scatter, **sankey** | **full** required |

**Only `001_quartile_transitions` breaks `plotly-basic`** — its design
explicitly names `plotly.graph_objects.Sankey` for the flow diagram. No
other future task in our backlog uses anything outside `basic`.

## Options

### Option A — `basic` now, swap to `full` later on the transitions page

- Each HTML can reference a different `<script src>`. When Task 001 lands,
  `transitions.html` would link `plotly.min.js` (full) while the other
  pages stay on `plotly-basic.min.js` (or rename to keep things tidy).
- Pro: minimum bytes today (~363 KB gzip first-load instead of ~1.4 MB).
- Con: two bundles in the repo when Task 001 ships, slightly fiddlier
  build step. Browser caches both separately — first visit to the
  transitions page costs the extra megabyte.

### Option B — `full` always

- One bundle, no per-page logic, future-proof for any chart type we add.
- Pro: zero conditional code in the build.
- Con: ~4 MB on disk, ~1.4 MB gzip wire on first load even when only
  scatter is used.

### Option C — `basic` now, accept Task 001 will require a sitewide swap

- Simpler than A, but when Task 001 ships every page would re-download a
  bigger bundle. Realistically the same as Option A but worse — we'd
  lose the cache benefit on scatter pages.

## Smallest concrete change

I propose Option A:

1. Switch render to write `plotly-basic.min.js` (download once on first
   build, cached in repo). All charts on `docs/pages/` reference it.
2. When Task 001 lands, add a second download for `plotly.min.js` (full)
   used by `transitions.html` only. Other pages stay on basic.

The download step lives in the build (CLI), not at runtime; we ship the
vendored JS in the repo so first build after `git clone` works without
internet (the download is a one-off and the file is committed).

## Implementation outline (Option A)

`src/momentum/viz/render.py`:
- Add `_BUNDLE_URL = "https://cdn.plot.ly/plotly-basic-3.5.0.min.js"` and
  `_BUNDLE_SHA256 = "<hash>"`.
- After `fig.write_html(..., include_plotlyjs="directory")` (which writes
  the full bundle), overwrite `<out_dir>/plotly.min.js` with the basic
  bundle. Cache the download under `.iss_cache/plotly-basic-3.5.0.min.js`
  to avoid re-fetching across builds.
- Pin the version to plotly.js's embedded version (`3.5.0`). When we
  upgrade plotly Python in `pyproject.toml`, bump the partial-bundle URL
  in lockstep. Mismatch is fine as long as the basic bundle's version
  ≥ what plotly Python expects on the wire format — but pin-matching is
  safer.

`pyproject.toml`:
- No new runtime deps (urllib only).

Tests:
- The existing `test_render_html_writes_shared_plotly_js` keeps asserting
  `plotly.min.js` exists next to the HTML. Add an assertion that the
  file is the basic bundle (size < 1.5 MB), not the full one
  (size > 4 MB).
- Add an assertion that the SHA256 of the written file matches the
  expected hash, so partial-bundle integrity is verified after each
  build.

## Decision — Option C: custom bundle (scatter + bar + sankey)

User picked a fourth path: build a custom bundle from `plotly.js` source
that registers exactly the trace types we need. Result:

| metric | full (default) | basic (prebuilt) | **custom (chosen)** |
|---|---:|---:|---:|
| size on disk | 4.7 MB | 1.1 MB | **1.2 MB** |
| size gzip | 1.4 MB | 363 KB | **406 KB** |
| includes sankey | ✓ | ✗ | **✓** |
| includes 3D / geo / heatmap / candlestick | ✓ | ✗ | ✗ |

The custom bundle is **3.5× smaller** than the full prebuilt and only
~50 KB larger than basic — but unlike basic it covers every chart type
in the roadmap (scatter / bar / sankey).

### How it lands

- Source under `scripts/build_plotly_bundle/`:
  - `index.js` — `Plotly.register([scatter, bar, sankey])`.
  - `package.json` — pins `plotly.js@3.5.0` + `esbuild@0.24.0`.
  - `build.sh` — installs, bundles, copies result to
    `docs/pages/plotly.min.js`, prints SHA256.
  - `smoke.js` — JSDOM-driven smoke test that registers the bundle and
    calls `Plotly.newPlot` for each trace type.
  - `README.md` — full recipe, when to re-run.
- Output `docs/pages/plotly.min.js` is **committed to the repo** so
  first build after `git clone` works without Node. Re-run only when
  `plotly` Python is bumped.
- `src/momentum/viz/render.py` pins the bundle SHA256; `tests/
  test_plotly_charts.py` verifies the committed file matches the pin
  and is within the expected size range (guards against accidentally
  committing the full bundle).

### Verification done

- `scripts/build_plotly_bundle/smoke.js` (JSDOM + vm) loads the bundle
  and exercises scatter+log+rangeslider+rangeselector, sankey, bar —
  all pass.
- `Plotly.PlotSchema.get().traces` after load returns exactly
  `{bar, sankey, scatter}` — no kitchen-sink leakage.
- `momentum plot --signal curve_fit --out docs/pages/` renders all
  three charts; HTML 15–46 KB each, links to sibling `plotly.min.js`.
- `pytest`: 184/184 pass. `mypy`: clean. `ruff`: clean.

### Open verification step (needs human eyes)

Open each HTML in a real browser:
- Q1–Q4 dynamics: zoom, pan, hover unified, rangeslider drags,
  rangeselector buttons (1y/5y/all) work, log-y rendered.
- Q1/Q4 spread + Q1/MCFTRR alpha: hover works, log-y rendered.
- Open offline (DevTools → Network → Offline) — still works (no CDN
  dependency).
