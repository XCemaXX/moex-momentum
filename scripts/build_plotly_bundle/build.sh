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

NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if (( NODE_MAJOR < 22 )); then
    echo "plotly.js 4 needs Node >= 22, found $(node --version)" >&2
    exit 1
fi

# `ci` rather than `install`: it installs the committed lock exactly, so the
# bundle stays reproducible. It refuses when the lock and package.json disagree
# — that means a dependency was bumped, and regenerating the lock is a
# deliberate act, not something a build script should do behind your back.
if [[ -f package-lock.json ]]; then
    echo "==> npm ci"
    if ! npm ci --no-audit --no-fund --loglevel=error; then
        echo "" >&2
        echo "package-lock.json does not match package.json." >&2
        echo "If you changed a dependency, refresh the lock and commit it:" >&2
        echo "    npm install --no-audit --no-fund" >&2
        exit 1
    fi
else
    echo "==> npm install (no lock yet)"
    npm install --no-audit --no-fund --loglevel=error
fi

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
echo "Paste this hash into src/viz/site_builder.py:PLOTLY_BUNDLE_SHA256"
