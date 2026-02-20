#!/usr/bin/env bash
set -euo pipefail

REPO="ai-janitor/minion-tasks"
PKG_URL="git+https://github.com/${REPO}.git"

echo "=== minion-tasks installer ==="
echo ""

# Phase 1: Install package
echo "Phase 1: Installing minion-tasks..."
if command -v pipx &>/dev/null; then
    echo "  Using pipx..."
    pipx install "$PKG_URL" || pipx upgrade "$PKG_URL" 2>/dev/null || true
elif command -v uv &>/dev/null; then
    echo "  Using uv..."
    uv tool install "$PKG_URL" 2>/dev/null || uv pip install "$PKG_URL"
elif command -v pip &>/dev/null; then
    echo "  Using pip (consider installing pipx or uv for isolated installs)..."
    pip install "$PKG_URL"
else
    echo "ERROR: No Python package manager found. Install pipx, uv, or pip first."
    exit 1
fi

echo "  Done."
echo ""

# Phase 2: Seed task-flows to ~/.minion-tasks/task-flows/
echo "Phase 2: Seeding task flow definitions..."
FLOWS_DIR="$HOME/.minion-tasks/task-flows"
mkdir -p "$FLOWS_DIR"

# Locate bundled flows via Python introspection
FLOWS_SRC=$(python3 -c "
from pathlib import Path
import minion_tasks
pkg = Path(minion_tasks.__file__).resolve().parent.parent / 'task-flows'
if not pkg.exists():
    # fallback: check shared-data location
    import sysconfig
    shared = Path(sysconfig.get_path('data')) / 'share' / 'minion-tasks' / 'task-flows'
    pkg = shared if shared.exists() else None
print(pkg or '')
" 2>/dev/null || echo "")

if [ -n "$FLOWS_SRC" ] && [ -d "$FLOWS_SRC" ]; then
    cp -n "$FLOWS_SRC"/*.yaml "$FLOWS_DIR/" 2>/dev/null || true
    echo "  Seeded flows to $FLOWS_DIR"
else
    echo "  WARN: Could not locate bundled task-flows. Copy manually from the repo."
fi

echo ""
echo "=== Installation complete ==="
echo "  Flows: $FLOWS_DIR"
echo "  Usage: from minion_tasks import load_flow"
