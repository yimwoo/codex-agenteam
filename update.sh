#!/usr/bin/env bash
set -euo pipefail

# AgenTeam (ateam) updater
# Usage:
#   bash update.sh              # Update from remote (default)
#   bash update.sh --local      # Refresh cache from local source (for contributors)

PLUGIN_NAME="ateam"
SOURCE_DIR="$HOME/.codex/plugins/ateam-source"
MARKETPLACE_FILE="$HOME/.agents/plugins/marketplace.json"
CODEX_PLUGIN_CACHE_ROOT="$HOME/.codex/plugins/cache/codex-plugins/ateam"

ensure_python_dependencies() {
  if python3 -c "import yaml, toml" >/dev/null 2>&1; then
    echo "Python dependencies already available."
    return 0
  fi

  echo "Installing Python dependencies..."
  python3 -m pip install -r runtime/requirements.txt --quiet
}

ensure_clean_checkout() {
  local source_dir="$1"

  if [ -n "$(git -C "${source_dir}" status --porcelain)" ]; then
    echo "Error: ${source_dir} has local changes." >&2
    echo "Commit or stash them first, or use --local from the repo you want Codex to load." >&2
    exit 1
  fi
}

fast_forward_source_checkout() {
  local source_dir="$1"
  local current_branch

  ensure_clean_checkout "${source_dir}"
  current_branch="$(git -C "${source_dir}" branch --show-current)"
  if [ "${current_branch}" != "main" ]; then
    echo "Error: expected ${source_dir} to be on branch main, found ${current_branch}." >&2
    echo "Switch that checkout back to main, or use --local from your working tree." >&2
    exit 1
  fi

  git -C "${source_dir}" fetch origin
  git -C "${source_dir}" pull --ff-only origin main
}

register_marketplace() {
  local manifest_path="$1"
  local dest_path="$2"
  local plugin_source_path="$3"

  python3 -c '
import json, os, sys

manifest_path = sys.argv[1]
dest_path = sys.argv[2]
plugin_source_path = sys.argv[3]
owner_name = os.environ.get("USER", "unknown")
marketplace_root = os.path.abspath(os.path.join(os.path.dirname(dest_path), "..", ".."))
plugin_source_abs = os.path.abspath(plugin_source_path)

with open(manifest_path) as f:
    manifest = json.load(f)

relative_plugin_path = os.path.relpath(plugin_source_abs, marketplace_root)
if relative_plugin_path == ".":
    marketplace_path = "./"
elif relative_plugin_path.startswith(".."):
    raise SystemExit(
        "Error: plugin source must live inside the marketplace root: " + marketplace_root
    )
else:
    marketplace_path = "./" + relative_plugin_path.replace(os.sep, "/")

entry = {
    "name": manifest["name"],
    "description": manifest["description"],
    "version": manifest["version"],
    "author": manifest.get("author", {"name": owner_name}),
    "source": {
        "source": "local",
        "path": marketplace_path,
    },
    "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    },
    "category": "Productivity",
}

if "interface" in manifest:
    entry["interface"] = manifest["interface"]

if os.path.exists(dest_path):
    with open(dest_path) as f:
        dest = json.load(f)
else:
    dest = {
        "name": "codex-plugins",
        "description": "Codex plugin marketplace",
        "owner": {"name": owner_name},
        "interface": {"displayName": "Local Plugins"},
        "plugins": [],
    }

dest.setdefault("name", "codex-plugins")
dest.setdefault("description", "Codex plugin marketplace")
dest.setdefault("owner", {"name": owner_name})
dest.setdefault("interface", {"displayName": "Local Plugins"})
dest.setdefault("plugins", [])

existing_index = None
for i, p in enumerate(dest["plugins"]):
    if p and p.get("name") == manifest["name"]:
        existing_index = i
        break

if existing_index is not None:
    dest["plugins"][existing_index] = entry
    action = "Updated"
else:
    dest["plugins"].append(entry)
    action = "Added"

os.makedirs(os.path.dirname(dest_path), exist_ok=True)
with open(dest_path, "w") as f:
    json.dump(dest, f, indent=2)
    f.write("\n")

ver = entry["version"]
print(action + " AgenTeam plugin entry (version " + ver + ")")
' "$manifest_path" "$dest_path" "$plugin_source_path"
}

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
  MARKETPLACE_FILE="${PLUGIN_PATH}/.agents/plugins/marketplace.json"
  echo "Local mode: refreshing from $PLUGIN_PATH"
else
  PLUGIN_PATH="$SOURCE_DIR"

  if [ ! -d "$SOURCE_DIR/.git" ]; then
    echo "Error: AgenTeam source not found at $SOURCE_DIR" >&2
    echo "Run install.sh first, or use --local from the repo directory." >&2
    exit 1
  fi

  echo "Pulling latest changes..."
  OLD_VERSION=$(python3 -c "import json; print(json.load(open('${SOURCE_DIR}/.codex-plugin/plugin.json'))['version'])" 2>/dev/null || echo "unknown")
  fast_forward_source_checkout "$SOURCE_DIR"
  NEW_VERSION=$(python3 -c "import json; print(json.load(open('${SOURCE_DIR}/.codex-plugin/plugin.json'))['version'])" 2>/dev/null || echo "unknown")

  if [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
    echo "Already up to date (v${NEW_VERSION})."
  else
    echo "Updated: v${OLD_VERSION} -> v${NEW_VERSION}"
  fi
fi

# Install or refresh Python dependencies only when needed.
cd "$PLUGIN_PATH"
ensure_python_dependencies
cd - > /dev/null

# Refresh marketplace metadata so Codex sees the current version and doc-compliant path.
PLUGIN_MANIFEST="${PLUGIN_PATH}/.codex-plugin/plugin.json"
if [ ! -f "$PLUGIN_MANIFEST" ]; then
  echo "Error: ${PLUGIN_MANIFEST} not found." >&2
  exit 1
fi

register_marketplace "$PLUGIN_MANIFEST" "$MARKETPLACE_FILE" "$PLUGIN_PATH"

# Refresh the Codex plugin cache
refresh_codex_plugin_cache "$PLUGIN_PATH"

echo ""
echo "AgenTeam updated successfully. Restart Codex to pick up changes."
