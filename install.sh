#!/usr/bin/env bash
set -euo pipefail

# AgenTeam (codex-agenteam) installer
# Usage:
#   bash install.sh                    # Clone to ~/.codex/plugins/ateam-source + register
#   bash install.sh --codex-plugin     # Same as above (explicit)
#   bash install.sh --local            # Use current directory as plugin source (for contributors)

PLUGIN_NAME="ateam"
REPO_URL="https://github.com/yimwoo/codex-agenteam"
SOURCE_DIR="$HOME/.codex/plugins/ateam-source"
MARKETPLACE_FILE="$HOME/.agents/plugins/marketplace.json"
CODEX_PLUGIN_CACHE_ROOT="$HOME/.codex/plugins/cache/codex-plugins/ateam"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
      mkdir -p "${cache_dir}"
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

with open(dest_path, "w") as f:
    json.dump(dest, f, indent=2)
    f.write("\n")

ver = entry["version"]
print(action + " AgenTeam plugin entry (version " + ver + ")")
' "$manifest_path" "$dest_path" "$plugin_source_path"
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------

LOCAL_MODE=false
for arg in "$@"; do
  case "$arg" in
    --local) LOCAL_MODE=true ;;
    --codex-plugin) ;; # default behavior
    --help|-h)
      echo "AgenTeam (codex-agenteam) Installer"
      echo ""
      echo "Usage:"
      echo "  bash install.sh                  Install as Codex plugin (clone to ~/.codex/plugins/)"
      echo "  bash install.sh --local          Use current directory as plugin source (contributors)"
      echo ""
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Determine plugin path
# ---------------------------------------------------------------------------

if [ "$LOCAL_MODE" = true ]; then
  PLUGIN_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  MARKETPLACE_FILE="${PLUGIN_PATH}/.agents/plugins/marketplace.json"
  MARKETPLACE_PLUGIN_PATH="${PLUGIN_PATH}"
  echo "Local mode: using $PLUGIN_PATH as plugin source"
else
  PLUGIN_PATH="$SOURCE_DIR"
  MARKETPLACE_PLUGIN_PATH="$SOURCE_DIR"

  if [ -d "$SOURCE_DIR/.git" ]; then
    echo "Updating existing source checkout at $SOURCE_DIR..."
    fast_forward_source_checkout "$SOURCE_DIR"
  else
    echo "Cloning AgenTeam to $SOURCE_DIR..."
    mkdir -p "$(dirname "$SOURCE_DIR")"
    git clone "$REPO_URL" "$SOURCE_DIR"
  fi
fi

# ---------------------------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------------------------

cd "$PLUGIN_PATH"
ensure_python_dependencies
cd - > /dev/null

# ---------------------------------------------------------------------------
# Register in marketplace
# ---------------------------------------------------------------------------

MARKETPLACE_DIR="$(dirname "$MARKETPLACE_FILE")"
mkdir -p "$MARKETPLACE_DIR"

PLUGIN_MANIFEST="${PLUGIN_PATH}/.codex-plugin/plugin.json"
if [ ! -f "$PLUGIN_MANIFEST" ]; then
  echo "Error: ${PLUGIN_MANIFEST} not found." >&2
  exit 1
fi

register_marketplace "$PLUGIN_MANIFEST" "$MARKETPLACE_FILE" "$MARKETPLACE_PLUGIN_PATH"

# ---------------------------------------------------------------------------
# Refresh Codex plugin cache
# ---------------------------------------------------------------------------

refresh_codex_plugin_cache "$PLUGIN_PATH"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "AgenTeam installed successfully."
echo ""
echo "Next steps:"
echo "  1. Restart Codex"
echo "  2. Open the plugin directory, switch to Local Plugins, and install AgenTeam"
echo "  3. Initialize a team in your project:"
echo ""
echo "     cd <your-project>"
echo "     \$ateam:init"
echo ""
echo "  4. Run a task with the full pipeline:"
echo ""
echo "     \$ateam:run \"Add user authentication\""
echo ""
echo "Plugin source: $PLUGIN_PATH"
echo "Marketplace:   $MARKETPLACE_FILE"
