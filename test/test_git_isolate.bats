#!/usr/bin/env bats
# Tests for scripts/git-isolate.sh

SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
GIT_ISOLATE="$SCRIPT_DIR/scripts/git-isolate.sh"

setup() {
  WORK_DIR="$(mktemp -d "${BATS_TEST_TMPDIR}/git-isolate-XXXXXX")"
}

teardown() {
  # Clean up any worktrees before removing dirs
  if [ -d "$WORK_DIR" ] && [ -d "$WORK_DIR/.git" ]; then
    cd "$WORK_DIR"
    git worktree list --porcelain 2>/dev/null | grep "^worktree " | grep -v "^worktree $WORK_DIR$" | sed 's/^worktree //' | while read -r wt; do
      git worktree remove --force "$wt" 2>/dev/null || true
    done
    cd /
  fi
  rm -rf "$WORK_DIR"
}

init_repo() {
  cd "$WORK_DIR"
  git init -b main .
  git commit --allow-empty -m "init"
}

# -----------------------------------------------------------------------
# preflight
# -----------------------------------------------------------------------

@test "preflight: clean git repo returns no issues" {
  init_repo
  run bash "$GIT_ISOLATE" preflight
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['is_git_repo'] == True
assert d['is_clean'] == True
assert d['is_detached'] == False
assert d['issues'] == []
assert d['current_branch'] != ''
"
}

@test "preflight: non-git directory reports not-a-git-repo" {
  cd "$WORK_DIR"
  run bash "$GIT_ISOLATE" preflight
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['is_git_repo'] == False
assert 'not-a-git-repo' in d['issues']
"
}

@test "preflight: dirty worktree reports issue" {
  init_repo
  echo "dirty" > file.txt
  run bash "$GIT_ISOLATE" preflight
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['is_clean'] == False
assert 'dirty-worktree' in d['issues']
"
}

@test "preflight: detached HEAD reports issue" {
  init_repo
  git checkout --detach HEAD
  run bash "$GIT_ISOLATE" preflight
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['is_detached'] == True
assert 'detached-head' in d['issues']
"
}

# -----------------------------------------------------------------------
# create-branch
# -----------------------------------------------------------------------

@test "create-branch: new branch is created and checked out" {
  init_repo
  run bash "$GIT_ISOLATE" create-branch test/new-feature
  [ "$status" -eq 0 ]
  [ "$(git rev-parse --abbrev-ref HEAD)" = "test/new-feature" ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'created'
assert d['branch'] == 'test/new-feature'
"
}

@test "create-branch: existing branch at same HEAD switches to it" {
  init_repo
  git checkout -b existing-branch
  git checkout main
  run bash "$GIT_ISOLATE" create-branch existing-branch
  [ "$status" -eq 0 ]
  [ "$(git rev-parse --abbrev-ref HEAD)" = "existing-branch" ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'switched'
"
}

@test "create-branch: existing branch at different HEAD gets suffix" {
  init_repo
  git checkout -b diverged
  git commit --allow-empty -m "diverge"
  git checkout main
  run bash "$GIT_ISOLATE" create-branch diverged
  [ "$status" -eq 0 ]
  [ "$(git rev-parse --abbrev-ref HEAD)" = "diverged-2" ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'created'
assert d['branch'] == 'diverged-2'
"
}

@test "create-branch: with explicit base" {
  init_repo
  git commit --allow-empty -m "second"
  run bash "$GIT_ISOLATE" create-branch from-base main~1
  [ "$status" -eq 0 ]
  [ "$(git rev-parse --abbrev-ref HEAD)" = "from-base" ]
}

# -----------------------------------------------------------------------
# create-worktree
# -----------------------------------------------------------------------

@test "create-worktree: new worktree is created" {
  init_repo
  run bash "$GIT_ISOLATE" create-worktree "$WORK_DIR/.wt" test/wt-branch
  [ "$status" -eq 0 ]
  [ -d "$WORK_DIR/.wt" ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'created'
"
}

@test "create-worktree: existing worktree is reused" {
  init_repo
  git worktree add -b reuse-branch "$WORK_DIR/.wt-reuse" HEAD
  run bash "$GIT_ISOLATE" create-worktree "$WORK_DIR/.wt-reuse" reuse-branch
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'reused'
"
}

@test "create-worktree: occupied non-worktree path errors" {
  init_repo
  mkdir -p "$WORK_DIR/.occupied"
  run bash "$GIT_ISOLATE" create-worktree "$WORK_DIR/.occupied" test/occ
  [ "$status" -ne 0 ]
}

# -----------------------------------------------------------------------
# return
# -----------------------------------------------------------------------

@test "return: switches back to specified branch" {
  init_repo
  git checkout -b feature
  run bash "$GIT_ISOLATE" return main
  [ "$status" -eq 0 ]
  [ "$(git rev-parse --abbrev-ref HEAD)" = "main" ]
}

# -----------------------------------------------------------------------
# cleanup-worktree
# -----------------------------------------------------------------------

@test "cleanup-worktree: clean worktree is removed" {
  init_repo
  git worktree add -b clean-wt "$WORK_DIR/.wt-clean" HEAD
  run bash "$GIT_ISOLATE" cleanup-worktree "$WORK_DIR/.wt-clean"
  [ "$status" -eq 0 ]
  [ ! -d "$WORK_DIR/.wt-clean" ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'removed'
"
}

@test "cleanup-worktree: dirty worktree is preserved" {
  init_repo
  git worktree add -b dirty-wt "$WORK_DIR/.wt-dirty" HEAD
  echo "dirty" > "$WORK_DIR/.wt-dirty/file.txt"
  run bash "$GIT_ISOLATE" cleanup-worktree "$WORK_DIR/.wt-dirty"
  [ "$status" -eq 0 ]
  [ -d "$WORK_DIR/.wt-dirty" ]
  # Output contains both stderr warning and stdout JSON; extract JSON line
  echo "$output" | grep '^{' | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'preserved'
"
}

@test "cleanup-worktree: nonexistent path is no-op" {
  init_repo
  run bash "$GIT_ISOLATE" cleanup-worktree "$WORK_DIR/.nonexistent"
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['action'] == 'no-op'
"
}
