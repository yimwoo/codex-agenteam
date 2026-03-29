#!/usr/bin/env bash
set -euo pipefail

# AgenTeam (ateam) updater
# Usage:
#   bash update.sh              # Update from remote (default)
#   bash update.sh --local      # Refresh cache from local source (for contributors)

PLUGIN_NAME="ateam"
SOURCE_DIR="$HOME/.codex/plugins/ateam-source"
CODEX_PLUGIN_CACHE_ROOT="$HOME/.codex/plugins/cache/codex-plugins/ateam"

refresh_codex_plugin_cache() {
  local source_dir="$1"
  local cache_root="${CODEX_PLUGIN_CACHE_ROOT}"
  local refreshed=0

  if [ ! -d "${source_dir}" ]; then
    return 0
  fi

  if [ -d "${cache_root}" ]; then
    for cache_dir in "${cache_root}"/*/; do
      [ -d "${cache_dir}" ] || continue
      echo "Refreshing Codex plugin cache at ${cache_dir}..."
      rsync -a --delete --exclude '.git' "${source_dir}/" "${cache_dir}"
      refreshed=1
    done
  fi

  if [ "${refreshed}" -eq 0 ]; then
    local seed_dir="${cache_root}/local"
    echo "Seeding Codex plugin cache at ${seed_dir}..."
    mkdir -p "${seed_dir}"
    rsync -a --delete --exclude '.git' "${source_dir}/" "${seed_dir}/"
    refreshed=1
  fi

  if [ "${refreshed}" -eq 1 ]; then
    echo "  Codex plugin cache refreshed."
  fi
}

LOCAL_MODE=false
for arg in "$@"; do
  case "$arg" in
    --local) LOCAL_MODE=true ;;
    --help|-h)
      echo "AgenTeam (ateam) Updater"
      echo ""
      echo "Usage:"
      echo "  bash update.sh                  Pull latest and refresh plugin cache"
      echo "  bash update.sh --local          Refresh cache from local source (contributors)"
      echo ""
      exit 0
      ;;
  esac
done

if [ "$LOCAL_MODE" = true ]; then
  PLUGIN_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  echo "Local mode: refreshing from $PLUGIN_PATH"
else
  PLUGIN_PATH="$SOURCE_DIR"

  if [ ! -d "$SOURCE_DIR/.git" ]; then
    echo "Error: AgenTeam source not found at $SOURCE_DIR" >&2
    echo "Run install.sh first, or use --local from the repo directory." >&2
    exit 1
  fi

  echo "Pulling latest changes..."
  cd "$SOURCE_DIR"
  OLD_VERSION=$(python3 -c "import json; print(json.load(open('.codex-plugin/plugin.json'))['version'])" 2>/dev/null || echo "unknown")
  git fetch origin
  git reset --hard origin/main
  NEW_VERSION=$(python3 -c "import json; print(json.load(open('.codex-plugin/plugin.json'))['version'])" 2>/dev/null || echo "unknown")
  cd - > /dev/null

  if [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
    echo "Already up to date (v${NEW_VERSION})."
  else
    echo "Updated: v${OLD_VERSION} -> v${NEW_VERSION}"
  fi
fi

# Reinstall Python dependencies (in case they changed)
echo "Updating Python dependencies..."
cd "$PLUGIN_PATH"
pip install -r runtime/requirements.txt --quiet
cd - > /dev/null

# Refresh the Codex plugin cache
refresh_codex_plugin_cache "$PLUGIN_PATH"

echo ""
echo "AgenTeam updated successfully. Restart Codex to pick up changes."
