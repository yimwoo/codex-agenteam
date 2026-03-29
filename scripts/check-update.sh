#!/usr/bin/env bash
# check-update.sh — Best-effort version check for codex-agenteam plugin.
# Outputs to stderr only. Never fails hard.

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_JSON="$PLUGIN_DIR/.codex-plugin/plugin.json"

# Read current version
if [ ! -f "$PLUGIN_JSON" ]; then
  echo "Warning: plugin.json not found" >&2
  exit 0
fi

CURRENT_VERSION=$(python3 -c "import json; print(json.load(open('$PLUGIN_JSON'))['version'])" 2>/dev/null || echo "unknown")

if [ "$CURRENT_VERSION" = "unknown" ]; then
  echo "Warning: could not read current version" >&2
  exit 0
fi

# Check GitHub for latest version (best-effort)
REPO="yimwoo/codex-agenteam"
LATEST=$(curl -sf --max-time 5 "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name','').lstrip('v'))" 2>/dev/null \
  || echo "")

if [ -z "$LATEST" ]; then
  # Could not reach GitHub — silent exit
  exit 0
fi

if [ "$CURRENT_VERSION" != "$LATEST" ]; then
  echo "codex-agenteam update available: $CURRENT_VERSION -> $LATEST" >&2
  echo "Update with: cd <plugin-dir> && git pull" >&2
fi

exit 0
