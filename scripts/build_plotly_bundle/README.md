# Custom plotly.js bundle

Why we need this: the prebuilt `plotly.min.js` that ships with `pip
install plotly` is 4.7 MB (1.4 MB gzipped) — it contains every trace
type plotly supports (3D, choropleth, sankey, candlestick, contour, …).
Our dashboard uses only `scatter` (lines), `bar` (planned for monthly
mode, task 003), and `sankey` (planned for quartile transitions, task
001). Plotly raises no prebuilt partial bundle that includes sankey
without also pulling in the rest of the kitchen sink, so we cut our own.

Result: `docs/pages/plotly.min.js` is **1.2 MB / 406 KB gzip** — ~3.5×
smaller on the wire than the full bundle, while still covering every
chart type in our plan.

This is a one-time build per plotly Python upgrade. The output is
checked into the repo at `docs/pages/plotly.min.js`. You only need to
re-run this when you bump `plotly` in `pyproject.toml`.

## When to re-run

Every time `plotly` in `pyproject.toml` changes. The embedded plotly.js
version is locked to the matching wheel:

| plotly Python | plotly.js | notes |
|---|---|---|
| 6.7.0 | 3.5.0 | current |

If you upgrade `plotly` past 6.7.0:

1. Check the new plotly.js version: `.venv/bin/python -c "import plotly; print(plotly.__version__)"` and grep `plotly.js v` in the wheel's `plotly.min.js`.
2. Bump `plotly.js` in `package.json` to that exact version (no caret).
3. Re-run `./build.sh`.
4. Commit the regenerated `docs/pages/plotly.min.js` + updated SHA256
   in `src/momentum/viz/render.py`.

## Prerequisites

- Node ≥ 18 and npm.
- Network access to `registry.npmjs.org`.
- System CA bundle reachable. On Debian/Ubuntu/WSL this lives at
  `/etc/ssl/certs/ca-certificates.crt`. If npm errors with
  `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`, set
  `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt` for the
  install step (the build script does this automatically).

## Build

```bash
cd scripts/build_plotly_bundle
./build.sh
```

This:
1. Installs `plotly.js@3.5.0` + `esbuild@0.24.0` into a local
   `node_modules/` (not committed).
2. Bundles `index.js` into `plotly.min.js` (minified, IIFE, with the
   `Plotly` global).
3. Copies the result to `docs/pages/plotly.min.js`.
4. Prints the new SHA256 — paste it into `src/momentum/viz/render.py`'s
   `_BUNDLE_SHA256` constant.

## What's in the bundle

`index.js` registers exactly three traces:

```js
const Plotly = require('plotly.js/lib/core');
Plotly.register([
    require('plotly.js/lib/scatter'),
    require('plotly.js/lib/bar'),
    require('plotly.js/lib/sankey'),
]);
module.exports = Plotly;
```

Core (axes, layout, hover, rangeselector/rangeslider, modebar, legend,
log-scale) comes for free with `plotly.js/lib/core`. CSS imports from
maplibre/mapbox are dropped via `--loader:.css=empty` (we don't render
maps).

If a future task needs a trace type not on this list, add the
corresponding `require()` line and re-run the build. Available modules
live under `node_modules/plotly.js/lib/` after install. Common ones:
- `heatmap`, `contour` — adds heatmap-family
- `histogram`, `histogram2d` — adds histograms
- `pie`, `sunburst`, `treemap` — adds pie-family
- `box`, `violin` — adds distribution plots
- `candlestick`, `ohlc` — adds finance
- `scatter3d`, `surface`, `mesh3d` — adds 3D (large; pulls WebGL)
- `choropleth`, `scattergeo` — adds geo (pulls topojson)

## Smoke test

`smoke.js` loads the produced bundle inside JSDOM and exercises a
scatter+log+rangeslider+rangeselector plot, a sankey plot, and a bar
plot. Run after building:

```bash
node smoke.js plotly.min.js
```

Expected output (last line): `ALL PASSED`.

## What is NOT here

- No bundler-config file (webpack.config, vite.config). esbuild's CLI
  flags are sufficient.
- No watch mode. This is a one-shot build.
- No source maps. Production-only.
- No alternate bundles. One file, one purpose.
