#!/usr/bin/env bash
# Build the custom plotly.js bundle for the MOEX momentum project.
# See README.md for background. Run from this directory:
#   cd scripts/build_plotly_bundle && ./build.sh
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
OUT="$REPO_ROOT/docs/pages/plotly.min.js"

# npm on some systems (notably WSL with corporate-CA setups) misses the system
# CA bundle. Point Node at it explicitly so install works without disabling SSL.
if [[ -f /etc/ssl/certs/ca-certificates.crt && -z "${NODE_EXTRA_CA_CERTS:-}" ]]; then
    export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
fi

echo "==> npm install"
npm install --no-audit --no-fund --loglevel=error

echo "==> esbuild bundle"
./node_modules/.bin/esbuild index.js \
    --bundle \
    --minify \
    --global-name=Plotly \
    --platform=browser \
    --define:global=globalThis \
    --loader:.css=empty \
    --outfile=plotly.min.js

mkdir -p "$(dirname "$OUT")"
cp plotly.min.js "$OUT"

SIZE=$(stat -c '%s' "$OUT")
HASH=$(sha256sum "$OUT" | cut -d' ' -f1)
GZIP_SIZE=$(gzip -c "$OUT" | wc -c)
echo ""
echo "Built $OUT"
echo "  size:        $SIZE bytes ($(numfmt --to=iec "$SIZE"))"
echo "  gzip size:   $GZIP_SIZE bytes ($(numfmt --to=iec "$GZIP_SIZE"))"
echo "  sha256:      $HASH"
echo ""
echo "Paste this hash into src/momentum/viz/render.py:_BUNDLE_SHA256"
