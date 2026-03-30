#!/usr/bin/env bash
set -euo pipefail

# git-isolate.sh — Branch/worktree isolation helper for AgenTeam.
# Called by assign and run skills. Never called by the runtime.
#
# Usage:
#   git-isolate.sh preflight
#   git-isolate.sh create-branch <branch> [<base>]
#   git-isolate.sh create-worktree <path> <branch> [<base>]
#   git-isolate.sh return <branch>
#   git-isolate.sh cleanup-worktree <path>

cmd="${1:-}"
shift || true

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

json_kv() {
  # Print a JSON object from key=value pairs. Values are strings.
  local out="{"
  local first=true
  for pair in "$@"; do
    local key="${pair%%=*}"
    local val="${pair#*=}"
    if [ "$first" = true ]; then first=false; else out="$out, "; fi
    # Escape quotes in value
    val="${val//\\/\\\\}"
    val="${val//\"/\\\"}"
    out="$out\"$key\": \"$val\""
  done
  echo "$out}"
}

json_bool() {
  if "$@" >/dev/null 2>&1; then echo "true"; else echo "false"; fi
}

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

cmd_preflight() {
  local is_git_repo="false"
  local is_clean="false"
  local is_detached="false"
  local current_branch=""
  local issues="[]"
  local issue_list=""

  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    is_git_repo="true"
    current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"

    if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
      is_clean="true"
    else
      issue_list="${issue_list:+$issue_list, }\"dirty-worktree\""
    fi

    if [ "$current_branch" = "HEAD" ]; then
      is_detached="true"
      issue_list="${issue_list:+$issue_list, }\"detached-head\""
    fi
  else
    issue_list="\"not-a-git-repo\""
  fi

  if [ -n "$issue_list" ]; then
    issues="[$issue_list]"
  fi

  cat <<EOF
{"is_git_repo": $is_git_repo, "is_clean": $is_clean, "is_detached": $is_detached, "current_branch": "$current_branch", "issues": $issues}
EOF
}

# ---------------------------------------------------------------------------
# create-branch
# ---------------------------------------------------------------------------

cmd_create_branch() {
  local branch="${1:?Usage: git-isolate.sh create-branch <branch> [<base>]}"
  local base="${2:-HEAD}"

  # Check if branch exists
  if git rev-parse --verify "$branch" >/dev/null 2>&1; then
    local branch_head
    branch_head="$(git rev-parse "$branch")"
    local current_head
    current_head="$(git rev-parse HEAD)"

    if [ "$branch_head" = "$current_head" ]; then
      # Same HEAD — just switch
      git checkout "$branch" >/dev/null 2>&1
      json_kv action=switched branch="$branch"
      return
    fi

    # Different HEAD — find a free suffix
    local suffix=2
    while git rev-parse --verify "${branch}-${suffix}" >/dev/null 2>&1; do
      suffix=$((suffix + 1))
    done
    branch="${branch}-${suffix}"
  fi

  # Create and switch
  git checkout -b "$branch" "$base" >/dev/null 2>&1
  json_kv action=created branch="$branch"
}

# ---------------------------------------------------------------------------
# create-worktree
# ---------------------------------------------------------------------------

cmd_create_worktree() {
  local wt_path="${1:?Usage: git-isolate.sh create-worktree <path> <branch> [<base>]}"
  local branch="${2:?Usage: git-isolate.sh create-worktree <path> <branch> [<base>]}"
  local base="${3:-HEAD}"

  if [ -d "$wt_path" ]; then
    # Check if it's a worktree (look for .git file that worktrees have)
    if [ -f "$wt_path/.git" ] && grep -q "gitdir:" "$wt_path/.git" 2>/dev/null; then
      json_kv action=reused worktree_path="$wt_path" branch="$branch"
      return
    fi
    echo "{\"error\": \"Path $wt_path exists but is not a git worktree\"}" >&2
    exit 1
  fi

  # Create worktree with new branch
  git worktree add -b "$branch" "$wt_path" "$base" >/dev/null 2>&1
  json_kv action=created worktree_path="$wt_path" branch="$branch"
}

# ---------------------------------------------------------------------------
# return
# ---------------------------------------------------------------------------

cmd_return() {
  local branch="${1:?Usage: git-isolate.sh return <branch>}"
  git checkout "$branch" >/dev/null 2>&1
  json_kv action=returned branch="$branch"
}

# ---------------------------------------------------------------------------
# cleanup-worktree
# ---------------------------------------------------------------------------

cmd_cleanup_worktree() {
  local wt_path="${1:?Usage: git-isolate.sh cleanup-worktree <path>}"

  # Check if path is a worktree
  if [ ! -d "$wt_path" ]; then
    json_kv action=no-op reason="path does not exist"
    return
  fi

  # Check if it's a worktree (look for .git file, not .git directory)
  if ! [ -f "$wt_path/.git" ] || ! grep -q "gitdir:" "$wt_path/.git" 2>/dev/null; then
    json_kv action=no-op reason="not a worktree"
    return
  fi

  # Check if clean
  if [ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null)" ]; then
    echo "Warning: Worktree at $wt_path has uncommitted changes. Inspect or commit before cleanup." >&2
    json_kv action=preserved reason="dirty" worktree_path="$wt_path"
    return
  fi

  git worktree remove "$wt_path" >/dev/null 2>&1
  json_kv action=removed worktree_path="$wt_path"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$cmd" in
  preflight)         cmd_preflight ;;
  create-branch)     cmd_create_branch "$@" ;;
  create-worktree)   cmd_create_worktree "$@" ;;
  return)            cmd_return "$@" ;;
  cleanup-worktree)  cmd_cleanup_worktree "$@" ;;
  *)
    echo "Usage: git-isolate.sh {preflight|create-branch|create-worktree|return|cleanup-worktree}" >&2
    exit 1
    ;;
esac
