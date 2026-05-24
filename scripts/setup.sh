#!/usr/bin/env bash
# Bootstrap for a clean clone. Linux/WSL only.
# 1. Creates .venv via stdlib python -m venv (no pre-installed uv required).
# 2. Installs uv INSIDE .venv (isolation, see CLAUDE.md).
# 3. Runs uv sync --frozen.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=${PYTHON:-python3.12}
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: $PY not found. Install Python 3.12 first." >&2
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating .venv with $PY"
    "$PY" -m venv .venv
fi

# uv lives inside the venv, not system-wide.
if [ ! -x ".venv/bin/uv" ]; then
    echo "Installing uv into .venv"
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet uv
fi

echo "Syncing dependencies"
.venv/bin/uv sync --frozen 2>/dev/null || .venv/bin/uv sync

mkdir -p data/{prices_iss,dividends,splits,indices,momentum} docs/pages

echo "Done. Activate with: source .venv/bin/activate"
